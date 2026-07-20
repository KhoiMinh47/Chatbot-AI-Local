"""FastAPI application factory."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress
from typing import Any, cast

from fastapi import FastAPI

from app.api.admin import router as admin_router
from app.api.auth import router as auth_router
from app.api.conversations import router as conversations_router
from app.api.documents import router as documents_router
from app.api.health import router as health_router
from app.application.get_dependency_health import GetDependencyHealth
from app.application.get_liveness import GetLiveness
from app.core.settings import ApiSettings
from app.domain.health import ServiceIdentity
from app.infrastructure.auth import AuthBundle, build_auth_bundle
from app.infrastructure.auth_settings import AuthSettings as AuthConfig
from app.infrastructure.health_probes import build_dependency_probes
from app.infrastructure.ingestion import IngestionBundle, build_ingestion_bundle
from app.infrastructure.ingestion_settings import IngestionSettings
from app.infrastructure.nim_client_factory import NimClientBundle, build_nim_client_bundle
from app.infrastructure.rag_factory import build_rag_graph


def create_app(
    settings: ApiSettings | None = None,
    *,
    ingestion_settings: IngestionSettings | None = None,
    auth_config: AuthConfig | None = None,
    _override_auth_bundle: AuthBundle | None = None,
) -> FastAPI:
    """Build an API process without opening external connections."""

    resolved_settings = settings or ApiSettings()
    resolved_ingestion_settings = ingestion_settings or IngestionSettings()
    resolved_auth_config = auth_config or AuthConfig()
    identity = ServiceIdentity(
        name=resolved_settings.service_name,
        version=resolved_settings.version,
    )

    # Dynamic slowapi Limiter storage config
    from limits.storage import storage_from_string
    from limits.strategies import STRATEGIES
    from ntc_shared import RuntimeEnvironment
    from slowapi import _rate_limit_exceeded_handler
    from slowapi.errors import RateLimitExceeded

    from app.security.limiter import limiter

    if resolved_settings.redis_host:
        redis_pwd = ""
        if resolved_settings.redis_password:
            redis_pwd = f":{resolved_settings.redis_password.get_secret_value()}"
        storage_uri = (
            f"redis://{redis_pwd}@{resolved_settings.redis_host}:{resolved_settings.redis_port}"
        )
        limiter._storage = storage_from_string(storage_uri)
        strategy = limiter._strategy or "fixed-window"
        limiter._limiter = STRATEGIES[strategy](limiter._storage)

    import sys

    limiter.enabled = (
        resolved_settings.env != RuntimeEnvironment.TEST and "pytest" not in sys.modules
    )

    @asynccontextmanager
    async def lifespan(running_app: FastAPI) -> AsyncIterator[None]:
        import logging
        import sys

        logger = logging.getLogger(__name__)

        clients: NimClientBundle | None = None
        ingestion: IngestionBundle | None = None
        auth: AuthBundle | None = _override_auth_bundle
        rag_async_engine: Any | None = None
        conversation_memory_service: Any | None = None

        if resolved_settings.nim_clients_enabled:
            try:
                print("Building NIM client bundle...", file=sys.stderr, flush=True)
                clients = build_nim_client_bundle(resolved_settings)
                print("✓ NIM client bundle built successfully", file=sys.stderr, flush=True)
            except Exception as exc:
                print(f"✗ Failed to build NIM client bundle: {exc}", file=sys.stderr, flush=True)
                logger.exception("Failed to build NIM client bundle")
                clients = None

        if resolved_ingestion_settings.enabled:
            try:
                print("Building ingestion bundle...", file=sys.stderr, flush=True)
                ingestion = build_ingestion_bundle(resolved_ingestion_settings)
                print(
                    f"✓ Ingestion bundle built successfully: {ingestion.service}",
                    file=sys.stderr,
                    flush=True,
                )
            except Exception as exc:
                print(f"✗ Failed to build ingestion bundle: {exc}", file=sys.stderr, flush=True)
                logger.exception("Failed to build ingestion bundle")
                ingestion = None

        if auth is None and resolved_auth_config.enabled:
            try:
                print("Building auth bundle...", file=sys.stderr, flush=True)
                auth = build_auth_bundle(resolved_auth_config)
                print("✓ Auth bundle built successfully", file=sys.stderr, flush=True)
            except Exception as exc:
                print(f"✗ Failed to build auth bundle: {exc}", file=sys.stderr, flush=True)
                logger.exception("Failed to build auth bundle")
                auth = None

        # Wire up the RAG graph if NIM clients are available
        rag_graph = None
        redis_client = None
        if clients is not None:
            try:
                import asyncio
                import logging

                import redis.asyncio as aioredis
                from sqlalchemy import URL
                from sqlalchemy.ext.asyncio import create_async_engine

                # Final-answer caching is opt-in because keys must remain bound to ACL,
                # memory and model/index/prompt versions.
                if resolved_settings.enable_rag_cache and resolved_settings.redis_host:
                    redis_pwd = (
                        resolved_settings.redis_password.get_secret_value()
                        if resolved_settings.redis_password
                        else None
                    )
                    redis_client = aioredis.Redis(
                        host=resolved_settings.redis_host,
                        port=resolved_settings.redis_port,
                        password=redis_pwd,
                        decode_responses=True,
                    )
                    logging.getLogger(__name__).info("Redis cache client initialized for RAG graph")

                concurrency_semaphore = asyncio.Semaphore(resolved_settings.rag_max_concurrency)

                _db_url = URL.create(
                    "postgresql+psycopg",
                    username=resolved_settings.database_user,
                    password=(
                        resolved_settings.database_password.get_secret_value()
                        if resolved_settings.database_password
                        else None
                    ),
                    host=resolved_settings.database_host,
                    port=resolved_settings.database_port,
                    database=resolved_settings.database_name,
                )
                rag_async_engine = create_async_engine(
                    _db_url,
                    pool_pre_ping=True,
                    connect_args={"options": "-csearch_path=app,public"},
                )
                rag_graph = build_rag_graph(
                    resolved_settings,
                    clients,
                    rag_async_engine,
                    redis=redis_client,
                    semaphore=concurrency_semaphore,
                )
                logging.getLogger(__name__).info("RAG graph wired successfully")
            except Exception as exc:
                import logging

                logging.getLogger(__name__).warning("Failed to build RAG graph: %s", exc)
                rag_graph = None

        if clients is not None and auth is not None and resolved_settings.enable_new_memory:
            try:
                from app.application.conversation_memory import (
                    ConversationMemoryService,
                    LlmRollingSummarizer,
                )
                from app.infrastructure.conversation_memory import (
                    PostgresConversationMemoryRepository,
                )

                conversation_memory_service = ConversationMemoryService(
                    repository=PostgresConversationMemoryRepository(auth.engine),
                    summarizer=LlmRollingSummarizer(clients.llm),
                    embedding=clients.embedding,
                    embedding_model=resolved_settings.nim_embed_model or "unknown-embedding",
                    retrieval_limit=resolved_settings.memory_semantic_final_limit,
                    candidate_limit=resolved_settings.memory_semantic_candidate_limit,
                    rolling_summary_enabled=resolved_settings.enable_rolling_summary,
                    long_term_enabled=resolved_settings.enable_long_term_memory,
                )
                logger.info("Conversation summary and semantic memory service initialized")
            except Exception:
                logger.exception("Failed to initialize conversation memory service")
                conversation_memory_service = None

        running_app.state.ai_clients = clients
        running_app.state.ingestion_service = None if ingestion is None else ingestion.service
        running_app.state.auth_bundle = auth
        running_app.state.rag_graph = rag_graph
        running_app.state.conversation_memory_service = conversation_memory_service

        try:
            yield
        finally:
            if redis_client is not None:
                with suppress(Exception):
                    await redis_client.aclose()
            if rag_async_engine is not None:
                with suppress(Exception):
                    await rag_async_engine.dispose()
            try:
                if ingestion is not None:
                    ingestion.close()
            finally:
                running_app.state.ingestion_service = None
                try:
                    if auth is not None and auth is not _override_auth_bundle:
                        auth.close()
                finally:
                    running_app.state.auth_bundle = None
                    running_app.state.conversation_memory_service = None
                    if clients is not None:
                        try:
                            await clients.aclose()
                        finally:
                            running_app.state.ai_clients = None

    application = FastAPI(
        title="NTC Local RAG API",
        version=resolved_settings.version,
        lifespan=lifespan,
    )
    from fastapi.middleware.cors import CORSMiddleware

    application.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:3000", "http://127.0.0.1:3000", "http://localhost:8080"],
        allow_origin_regex="https?://(localhost|127\\.0\\.0\\.1)(:[0-9]+)?",
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    application.state.limiter = limiter
    application.add_exception_handler(
        RateLimitExceeded,
        cast(Any, _rate_limit_exceeded_handler),
    )
    application.state.settings = resolved_settings
    application.state.ingestion_settings = resolved_ingestion_settings
    application.state.ai_clients = None
    application.state.ingestion_service = None
    application.state.auth_bundle = None
    application.state.rag_graph = None
    application.state.conversation_memory_service = None
    application.state.get_liveness = GetLiveness(identity)
    application.state.get_dependency_health = GetDependencyHealth(
        build_dependency_probes(resolved_settings),
        timeout_seconds=resolved_settings.dependency_timeout_seconds,
    )
    application.include_router(health_router)
    application.include_router(documents_router)
    application.include_router(auth_router)
    application.include_router(conversations_router)
    application.include_router(admin_router)
    return application


app = create_app()

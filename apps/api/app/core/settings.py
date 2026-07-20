"""Typed API settings loaded from the process environment."""

from pathlib import Path
from typing import Self
from urllib.parse import urlsplit

from ntc_shared import LogLevel, RuntimeEnvironment
from pydantic import AnyHttpUrl, Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_RUNTIME_SECRETS_DIR = Path("/run/secrets")
SELECTED_NIM_LLM_MODEL = "nvidia/nemotron-nano-9b-v2"
SELECTED_NIM_LLM_MODEL_VERSION = "1.0.0"


class ApiSettings(BaseSettings):
    """Configuration read once while constructing the FastAPI application."""

    model_config = SettingsConfigDict(
        env_prefix="APP_",
        case_sensitive=False,
        extra="ignore",
        frozen=True,
        hide_input_in_errors=True,
        # Disable secrets_dir for now to avoid Pydantic errors with missing files
        # secrets_dir=_RUNTIME_SECRETS_DIR if _RUNTIME_SECRETS_DIR.is_dir() else None,
    )

    env: RuntimeEnvironment = RuntimeEnvironment.DEVELOPMENT
    host: str = Field(default="127.0.0.1", min_length=1)
    port: int = Field(default=8000, ge=1, le=65535)
    log_level: LogLevel = LogLevel.INFO
    service_name: str = Field(default="ntc-api", min_length=1)
    version: str = Field(default="0.1.0", min_length=1)
    dependency_timeout_seconds: float = Field(default=2.0, gt=0, le=10)

    database_host: str | None = None
    database_port: int = Field(default=5432, ge=1, le=65535)
    database_name: str = Field(default="ntc_rag", min_length=1)
    database_user: str = Field(default="ntc_app", min_length=1)
    database_password: SecretStr | None = None

    redis_host: str | None = None
    redis_port: int = Field(default=6379, ge=1, le=65535)
    redis_password: SecretStr | None = None

    qdrant_health_url: AnyHttpUrl | None = None
    rabbitmq_health_url: AnyHttpUrl | None = None
    rabbitmq_user: str = Field(default="ntc_worker", min_length=1)
    rabbitmq_password: SecretStr | None = None
    minio_health_url: AnyHttpUrl | None = None
    llm_health_url: AnyHttpUrl | None = None

    # Phase 3 application-side NIM contract. Container image/profile/cache
    # settings stay in Compose; these values configure only the API adapters.
    nim_clients_enabled: bool = False
    # Winner-bound by default; a deliberate local experiment must opt in to a
    # non-Nemotron OpenAI-compatible endpoint.
    nim_dev_mode: bool = False
    nim_inference_api_key: SecretStr | None = None
    nim_timeout_seconds: float = Field(default=120.0, gt=0, le=3600)
    nim_max_retries: int = Field(default=2, ge=0, le=5)
    nim_retry_delay_seconds: float = Field(default=0.1, ge=0, le=60)

    nim_llm_base_url: AnyHttpUrl | None = None
    nim_llm_model: str | None = Field(default=None, min_length=1)
    nim_llm_model_version: str | None = Field(default=None, min_length=1)

    nim_embed_base_url: AnyHttpUrl | None = None
    nim_embed_model: str | None = Field(default=None, min_length=1)
    nim_embed_model_version: str | None = Field(default=None, min_length=1)
    embedding_dimension: int | None = Field(default=None, gt=0)
    nim_embed_max_batch_size: int = Field(default=32, ge=1, le=2048)
    nim_embed_allow_batch_downshift: bool = True
    nim_embed_min_downshift_batch_size: int = Field(default=1, ge=1, le=2048)

    nim_rerank_base_url: AnyHttpUrl | None = None
    nim_rerank_model: str | None = Field(default=None, min_length=1)
    nim_rerank_model_version: str | None = Field(default=None, min_length=1)

    # RAG index settings (used to build IndexConfig and wire the graph)
    rag_collection_name: str = Field(default="ntc_chunks_local_v1", min_length=1)
    rag_index_version: str = Field(default="embed300m-v2-1.13.0", min_length=1)
    rag_chunk_size: int = Field(default=256, ge=1)
    rag_overlap_percent: int = Field(default=10, ge=0, le=50)
    qdrant_base_url: str = Field(default="http://qdrant:6333")
    rag_dense_candidate_limit: int = Field(default=20, ge=1)
    rag_final_limit: int = Field(default=10, ge=1)
    rag_dense_threshold: float = Field(default=0.2300481, ge=0.0)
    rag_hnsw_ef: int = Field(default=128, ge=1)
    rag_reranker_enabled: bool = Field(default=False)
    rag_rerank_threshold: float | None = None
    enable_hybrid_retrieval: bool = False
    rag_rrf_k: int = Field(default=60, ge=1, le=1000)
    rag_dense_weight: float = Field(default=1.0, gt=0)
    rag_lexical_weight: float = Field(default=1.0, gt=0)

    # Quality optimization flags. These keep the selected Nemotron stack while
    # providing a configuration-only rollback for the new memory/runtime wiring.
    enable_new_memory: bool = True
    memory_recent_max_turns: int = Field(default=16, ge=1, le=64)
    memory_recent_token_limit: int = Field(default=12_000, ge=256, le=24_000)
    enable_rolling_summary: bool = True
    enable_long_term_memory: bool = True
    memory_summary_source_limit: int = Field(default=128, ge=16, le=1_000)
    memory_semantic_candidate_limit: int = Field(default=200, ge=1, le=1_000)
    memory_semantic_final_limit: int = Field(default=6, ge=1, le=20)
    require_exact_tokenizer: bool = True
    rag_max_concurrency: int = Field(default=4, ge=1, le=64)
    enable_rag_cache: bool = False
    enable_adaptive_reasoning: bool = True

    @model_validator(mode="after")
    def validate_nim_client_contract(self) -> Self:
        """Fail closed when the selected LLM/embed pair or optional reranker is unsafe."""

        urls = (
            self.nim_llm_base_url,
            self.nim_embed_base_url,
            self.nim_rerank_base_url,
        )
        for url in (candidate for candidate in urls if candidate is not None):
            parsed = urlsplit(str(url).rstrip("/"))
            if (
                parsed.username is not None
                or parsed.password is not None
                or parsed.query
                or parsed.fragment
                or not parsed.path.endswith("/v1")
            ):
                raise ValueError(
                    "each configured NIM base URL must be credential-free and end in /v1"
                )

        if self.nim_embed_min_downshift_batch_size > self.nim_embed_max_batch_size:
            raise ValueError(
                "nim_embed_min_downshift_batch_size must not exceed nim_embed_max_batch_size"
            )
        if self.memory_semantic_final_limit > self.memory_semantic_candidate_limit:
            raise ValueError(
                "memory_semantic_final_limit must not exceed memory_semantic_candidate_limit"
            )

        reranker = (
            self.nim_rerank_base_url,
            self.nim_rerank_model,
            self.nim_rerank_model_version,
        )
        if any(value is not None for value in reranker) and not all(
            value is not None for value in reranker
        ):
            raise ValueError(
                "optional reranking requires nim_rerank_base_url, nim_rerank_model, "
                "and nim_rerank_model_version together"
            )
        if self.rag_reranker_enabled and not all(value is not None for value in reranker):
            raise ValueError(
                "rag_reranker_enabled requires a complete optional reranking NIM contract"
            )

        if not self.nim_clients_enabled:
            return self

        # In dev mode, skip the strict Nemotron model name check (allows Ollama etc.)
        if not self.nim_dev_mode:
            if self.nim_llm_model is None:
                object.__setattr__(self, "nim_llm_model", SELECTED_NIM_LLM_MODEL)
            if self.nim_llm_model_version is None:
                object.__setattr__(
                    self,
                    "nim_llm_model_version",
                    SELECTED_NIM_LLM_MODEL_VERSION,
                )
            if (
                self.nim_llm_model != SELECTED_NIM_LLM_MODEL
                or self.nim_llm_model_version != SELECTED_NIM_LLM_MODEL_VERSION
            ):
                raise ValueError(
                    "enabled NIM LLM must match the selected Nemotron model and runtime version"
                )

        required = {
            "nim_llm_base_url": self.nim_llm_base_url,
            "nim_llm_model": self.nim_llm_model,
            "nim_llm_model_version": self.nim_llm_model_version,
            "nim_embed_base_url": self.nim_embed_base_url,
            "nim_embed_model": self.nim_embed_model,
            "nim_embed_model_version": self.nim_embed_model_version,
            "embedding_dimension": self.embedding_dimension,
        }
        missing = sorted(name for name, value in required.items() if value is None)
        if missing:
            raise ValueError(
                "enabled NIM clients require complete LLM and embedding settings: "
                + ", ".join(missing)
            )

        for value in (
            self.nim_llm_model,
            self.nim_llm_model_version,
            self.nim_embed_model,
            self.nim_embed_model_version,
            self.nim_rerank_model,
            self.nim_rerank_model_version,
        ):
            if value is not None and not value.strip():
                raise ValueError("enabled NIM model names and versions must not be blank")
        return self

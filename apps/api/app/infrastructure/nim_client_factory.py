"""Construction and process-lifetime ownership for the active NIM client trio."""

from __future__ import annotations

from dataclasses import dataclass

import httpx2 as httpx
from pydantic import AnyHttpUrl

from app.application.ai_clients import (
    AiServiceUnavailableError,
    AsyncAiClient,
    EmbeddingClient,
    LlmClient,
    RerankClient,
)
from app.core.settings import ApiSettings
from app.infrastructure.nim_clients import NimEmbeddingClient, NimLlmClient, NimRerankClient


def _required[T](value: T | None, field_name: str) -> T:
    """Defend the factory if settings validation is bypassed by a test double."""

    if value is None:
        raise ValueError(f"{field_name} is required when NIM clients are enabled")
    return value


def _url(value: AnyHttpUrl | None, field_name: str) -> str:
    return str(_required(value, field_name)).rstrip("/")


@dataclass(frozen=True, slots=True)
class NimClientTransports:
    """Optional transport overrides for hermetic contract tests."""

    llm: httpx.AsyncBaseTransport | None = None
    embedding: httpx.AsyncBaseTransport | None = None
    reranking: httpx.AsyncBaseTransport | None = None


@dataclass(frozen=True, slots=True)
class NimClientBundle:
    """Application ports plus one deterministic async shutdown boundary."""

    llm: LlmClient
    embedding: EmbeddingClient
    reranking: RerankClient | None

    async def aclose(self) -> None:
        """Attempt every close and expose only a stable, credential-free failure."""

        close_failed = False
        clients: tuple[AsyncAiClient, ...] = tuple(
            client for client in (self.llm, self.embedding, self.reranking) if client is not None
        )
        for client in clients:
            try:
                await client.aclose()
            except Exception:  # Transport details may contain sensitive endpoint data.
                close_failed = True
        if close_failed:
            raise AiServiceUnavailableError("one or more NIM clients failed to close cleanly")


def build_nim_client_bundle(
    settings: ApiSettings,
    *,
    transports: NimClientTransports | None = None,
) -> NimClientBundle:
    """Build the configured local NIM trio without opening a network connection."""

    if not settings.nim_clients_enabled:
        raise ValueError("NIM clients are disabled")

    resolved_transports = transports or NimClientTransports()
    api_key = (
        settings.nim_inference_api_key.get_secret_value()
        if settings.nim_inference_api_key is not None
        else None
    )
    llm = NimLlmClient(
        api_base_url=_url(settings.nim_llm_base_url, "nim_llm_base_url"),
        model=_required(settings.nim_llm_model, "nim_llm_model"),
        model_version=_required(settings.nim_llm_model_version, "nim_llm_model_version"),
        api_key=api_key,
        timeout_seconds=settings.nim_timeout_seconds,
        max_retries=settings.nim_max_retries,
        retry_delay_seconds=settings.nim_retry_delay_seconds,
        transport=resolved_transports.llm,
    )
    embedding = NimEmbeddingClient(
        api_base_url=_url(settings.nim_embed_base_url, "nim_embed_base_url"),
        model=_required(settings.nim_embed_model, "nim_embed_model"),
        model_version=_required(settings.nim_embed_model_version, "nim_embed_model_version"),
        expected_dimension=_required(settings.embedding_dimension, "embedding_dimension"),
        max_batch_size=settings.nim_embed_max_batch_size,
        allow_batch_downshift=settings.nim_embed_allow_batch_downshift,
        minimum_downshift_batch_size=settings.nim_embed_min_downshift_batch_size,
        api_key=api_key,
        timeout_seconds=settings.nim_timeout_seconds,
        max_retries=settings.nim_max_retries,
        retry_delay_seconds=settings.nim_retry_delay_seconds,
        transport=resolved_transports.embedding,
    )
    reranking: RerankClient | None = None
    if settings.nim_rerank_base_url is not None:
        reranking = NimRerankClient(
            api_base_url=_url(settings.nim_rerank_base_url, "nim_rerank_base_url"),
            model=_required(settings.nim_rerank_model, "nim_rerank_model"),
            model_version=_required(
                settings.nim_rerank_model_version,
                "nim_rerank_model_version",
            ),
            api_key=api_key,
            timeout_seconds=settings.nim_timeout_seconds,
            max_retries=settings.nim_max_retries,
            retry_delay_seconds=settings.nim_retry_delay_seconds,
            transport=resolved_transports.reranking,
        )
    return NimClientBundle(llm=llm, embedding=embedding, reranking=reranking)

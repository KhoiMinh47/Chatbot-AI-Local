from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass

import httpx2 as httpx
import pytest
from app import main as main_module
from app.application.ai_clients import (
    AiServiceUnavailableError,
    ChatMessage,
    ChatRequest,
    EmbeddingRequest,
    RerankRequest,
)
from app.core.settings import (
    SELECTED_NIM_LLM_MODEL,
    SELECTED_NIM_LLM_MODEL_VERSION,
    ApiSettings,
)
from app.infrastructure.nim_client_factory import (
    NimClientBundle,
    NimClientTransports,
    build_nim_client_bundle,
)
from fastapi.testclient import TestClient
from pydantic import SecretStr


def active_nim_settings(*, api_key: SecretStr | None = None) -> ApiSettings:
    return ApiSettings(
        nim_clients_enabled=True,
        nim_inference_api_key=api_key,
        nim_timeout_seconds=5,
        nim_max_retries=0,
        nim_retry_delay_seconds=0,
        nim_llm_base_url="http://nim-llm.test/v1",
        nim_llm_model=SELECTED_NIM_LLM_MODEL,
        nim_llm_model_version=SELECTED_NIM_LLM_MODEL_VERSION,
        nim_embed_base_url="http://nim-embed.test/v1",
        nim_embed_model="embed-model",
        nim_embed_model_version="1.13.0",
        embedding_dimension=2,
        nim_embed_max_batch_size=4,
        nim_embed_min_downshift_batch_size=1,
        nim_rerank_base_url="http://nim-rerank.test/v1",
        nim_rerank_model="rerank-model",
        nim_rerank_model_version="1.10.0",
    )


def request_json(request: httpx.Request) -> dict[str, object]:
    payload: object = json.loads(request.content)
    assert isinstance(payload, dict)
    return payload


def test_factory_builds_typed_clients_from_settings_and_propagates_metadata() -> None:
    credential = "".join(("phase3-test-", "inference-credential"))

    async def llm_handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/chat/completions"
        assert request.headers["authorization"] == f"Bearer {credential}"
        return httpx.Response(
            200,
            json={
                "model": SELECTED_NIM_LLM_MODEL,
                "choices": [{"message": {"content": "OK"}, "finish_reason": "stop"}],
                "usage": {
                    "prompt_tokens": 4,
                    "completion_tokens": 1,
                    "total_tokens": 5,
                },
            },
        )

    async def embedding_handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/embeddings"
        payload = request_json(request)
        inputs = payload["input"]
        assert isinstance(inputs, list)
        return httpx.Response(
            200,
            json={
                "model": "embed-model",
                "data": [
                    {"index": index, "embedding": [float(index), 1.0]}
                    for index in range(len(inputs))
                ],
                "usage": {"prompt_tokens": len(inputs), "total_tokens": len(inputs)},
            },
        )

    async def reranking_handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/ranking"
        return httpx.Response(
            200,
            json={
                "model": "rerank-model",
                "rankings": [
                    {"index": 1, "logit": 2.0},
                    {"index": 0, "logit": 1.0},
                ],
                "usage": {"prompt_tokens": 7, "total_tokens": 7},
            },
        )

    async def scenario() -> None:
        settings = active_nim_settings(api_key=SecretStr(credential))
        bundle = build_nim_client_bundle(
            settings,
            transports=NimClientTransports(
                llm=httpx.MockTransport(llm_handler),
                embedding=httpx.MockTransport(embedding_handler),
                reranking=httpx.MockTransport(reranking_handler),
            ),
        )
        try:
            chat = await bundle.llm.chat(
                ChatRequest(
                    messages=(
                        ChatMessage(role="system", content="/no_think\n\nTest prompt"),
                        ChatMessage(role="user", content="test"),
                    ),
                    max_tokens=8,
                )
            )
            embedding = await bundle.embedding.embed(
                EmbeddingRequest(texts=("first", "second"), input_type="passage")
            )
            assert bundle.reranking is not None
            reranking = await bundle.reranking.rerank(
                RerankRequest(query="query", passages=("first", "second"))
            )
        finally:
            await bundle.aclose()

        assert chat.model_version == SELECTED_NIM_LLM_MODEL_VERSION
        assert chat.usage is not None and chat.usage.total_tokens == 5
        assert embedding.model_version == "1.13.0"
        assert embedding.dimension == 2
        assert reranking.model_version == "1.10.0"
        assert reranking.input_tokens == 7
        assert credential not in repr(settings)
        assert credential not in repr(bundle)

    asyncio.run(scenario())


def test_factory_builds_selected_llm_and_embedding_without_optional_reranker() -> None:
    settings = ApiSettings(
        nim_clients_enabled=True,
        nim_llm_base_url="http://nim-llm.test/v1",
        nim_embed_base_url="http://nim-embed.test/v1",
        nim_embed_model="embed-model",
        nim_embed_model_version="1.13.0",
        embedding_dimension=2,
    )

    bundle = build_nim_client_bundle(settings)
    try:
        assert bundle.reranking is None
        assert SELECTED_NIM_LLM_MODEL in repr(bundle.llm)
    finally:
        asyncio.run(bundle.aclose())


def test_factory_rejects_disabled_configuration() -> None:
    with pytest.raises(ValueError, match="disabled"):
        build_nim_client_bundle(ApiSettings())


@dataclass
class ClosingClient:
    should_fail: bool = False
    close_count: int = 0

    async def aclose(self) -> None:
        self.close_count += 1
        if self.should_fail:
            raise RuntimeError("transport detail must be suppressed")


def test_bundle_attempts_every_close_and_returns_only_a_safe_error() -> None:
    first = ClosingClient(should_fail=True)
    second = ClosingClient()
    third = ClosingClient()
    bundle = NimClientBundle(  # type: ignore[arg-type]
        llm=first,
        embedding=second,
        reranking=third,
    )

    async def scenario() -> None:
        with pytest.raises(AiServiceUnavailableError) as caught:
            await bundle.aclose()
        assert "transport detail" not in str(caught.value)

    asyncio.run(scenario())
    assert (first.close_count, second.close_count, third.close_count) == (1, 1, 1)


def test_fastapi_lifespan_owns_enabled_client_bundle(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    fake_bundle = ClosingClient()
    monkeypatch.setattr(main_module, "build_nim_client_bundle", lambda _settings: fake_bundle)
    application = main_module.create_app(active_nim_settings())

    assert application.state.ai_clients is None
    with TestClient(application):
        assert application.state.ai_clients is fake_bundle
        assert fake_bundle.close_count == 0

    assert application.state.ai_clients is None
    assert fake_bundle.close_count == 1

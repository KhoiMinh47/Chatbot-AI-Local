"""Version-neutral HTTP adapters for NVIDIA NIM OpenAI-compatible APIs."""

from __future__ import annotations

import asyncio
import json
import math
import random
import re
import time
from collections.abc import AsyncIterator, Mapping
from itertools import pairwise
from typing import cast
from urllib.parse import urlsplit

import httpx2 as httpx

from app.application.ai_clients import (
    AiClientError,
    AiProtocolError,
    AiServiceUnavailableError,
    ChatRequest,
    ChatResponse,
    ChatStreamChunk,
    EmbeddingRequest,
    EmbeddingResponse,
    RankedPassage,
    RerankRequest,
    RerankResponse,
    TokenUsage,
)
from app.core.settings import SELECTED_NIM_LLM_MODEL

_TRANSIENT_STATUS_CODES = frozenset({408, 429, 500, 502, 503, 504})
_OOM_STATUS_CODES = frozenset({413, 507})
_MAX_RETRY_SLEEP_SECONDS = 60.0
_NEMOTRON_REASONING_CONTROL = re.compile(r"/(?:no_)?think\b", re.IGNORECASE)
_NEMOTRON_REASONING_END = re.compile(r"<\s*/\s*think\s*>", re.IGNORECASE)
_NEMOTRON_REASONING_TAG = re.compile(r"<\s*/?\s*think\b", re.IGNORECASE)


class _NimOutOfMemoryError(AiServiceUnavailableError):
    """Internal signal used to downshift embedding batches without leaking bodies."""


def _validated_api_base_url(api_base_url: str) -> str:
    """Return a normalized API base whose path explicitly ends in ``/v1/``."""

    candidate = api_base_url.strip().rstrip("/")
    parsed = urlsplit(candidate)
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
        or not parsed.path.endswith("/v1")
    ):
        raise ValueError(
            "api_base_url must be an HTTP(S) URL without credentials, query, or fragment "
            "and its path must end in /v1"
        )
    return f"{candidate}/"


def _mapping(value: object, field_name: str) -> Mapping[str, object]:
    if not isinstance(value, dict):
        raise AiProtocolError(f"NIM response field {field_name} must be an object")
    return cast(dict[str, object], value)


def _list(value: object, field_name: str) -> list[object]:
    if not isinstance(value, list):
        raise AiProtocolError(f"NIM response field {field_name} must be an array")
    return cast(list[object], value)


def _string(value: object, field_name: str) -> str:
    if not isinstance(value, str):
        raise AiProtocolError(f"NIM response field {field_name} must be a string")
    return value


def _optional_string(value: object, field_name: str) -> str | None:
    if value is None:
        return None
    return _string(value, field_name)


def _integer(value: object, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise AiProtocolError(f"NIM response field {field_name} must be an integer")
    return value


def _non_negative_integer(value: object, field_name: str) -> int:
    result = _integer(value, field_name)
    if result < 0:
        raise AiProtocolError(f"NIM response field {field_name} must be non-negative")
    return result


def _finite_number(value: object, field_name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise AiProtocolError(f"NIM response field {field_name} must be numeric")
    result = float(value)
    if not math.isfinite(result):
        raise AiProtocolError(f"NIM response field {field_name} must be finite")
    return result


def _response_json(response: httpx.Response) -> Mapping[str, object]:
    try:
        payload: object = response.json()
    except (json.JSONDecodeError, UnicodeDecodeError):
        raise AiProtocolError("NIM returned a non-JSON response") from None
    return _mapping(payload, "root")


def _token_usage(payload: Mapping[str, object]) -> TokenUsage | None:
    raw_usage = payload.get("usage")
    if raw_usage is None:
        return None
    usage = _mapping(raw_usage, "usage")
    input_tokens = _non_negative_integer(usage.get("prompt_tokens"), "usage.prompt_tokens")
    output_tokens = _non_negative_integer(usage.get("completion_tokens"), "usage.completion_tokens")
    total_tokens = _non_negative_integer(usage.get("total_tokens"), "usage.total_tokens")
    if total_tokens != input_tokens + output_tokens:
        raise AiProtocolError("NIM response token totals are inconsistent")
    return TokenUsage(
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        total_tokens=total_tokens,
    )


def _validate_selected_nemotron_reasoning_control(request: ChatRequest) -> None:
    """Require one trusted leading control and reject controls in untrusted turns."""

    first = request.messages[0]
    valid_prefix = next(
        (
            prefix
            for prefix in ("/no_think\n\n", "/think\n\n")
            if first.role == "system" and first.content.startswith(prefix)
        ),
        None,
    )
    if valid_prefix is None:
        raise ValueError("selected Nemotron requests require one trusted reasoning control")
    if _NEMOTRON_REASONING_CONTROL.search(first.content[len(valid_prefix) :]):
        raise ValueError("selected Nemotron system prompt contains an extra reasoning control")
    if any(_NEMOTRON_REASONING_CONTROL.search(message.content) for message in request.messages[1:]):
        raise ValueError("untrusted chat content contains a Nemotron reasoning control")


def _selected_nemotron_reasoning_enabled(request: ChatRequest) -> bool:
    return request.messages[0].content.startswith("/think\n\n")


def _visible_nemotron_chat_content(
    content: str,
    *,
    reasoning_enabled: bool,
    structured_reasoning_present: bool,
) -> str:
    """Discard hidden reasoning even when this NIM puts it in ``content``.

    Nemotron may return private reasoning in a dedicated field, or it may place
    reasoning before a closing ``</think>`` boundary in the content field (with
    no opening tag).  Content-mode output is buffered through that explicit
    boundary.  With a dedicated reasoning field, only the separate ``content``
    value is visible; the reasoning-field value is never copied into a result.
    """

    boundary = _NEMOTRON_REASONING_END.search(content)
    if boundary is not None:
        visible = content[boundary.end() :].lstrip()
        if _NEMOTRON_REASONING_TAG.search(visible):
            raise AiProtocolError("NIM visible answer contains a reasoning tag")
        return visible
    if _NEMOTRON_REASONING_TAG.search(content):
        raise AiProtocolError("NIM reasoning content has no safe visible-answer boundary")
    if reasoning_enabled and not structured_reasoning_present:
        raise AiProtocolError("NIM reasoning response has no safe visible-answer boundary")
    return content


class _NimHttpAdapter:
    """Shared bounded request behavior; never exposes response bodies or credentials."""

    def __init__(
        self,
        *,
        api_base_url: str,
        model: str,
        model_version: str | None,
        api_key: str | None,
        timeout_seconds: float,
        max_retries: int,
        retry_delay_seconds: float,
        transport: httpx.AsyncBaseTransport | None,
    ) -> None:
        if not model.strip():
            raise ValueError("model must not be blank")
        if model_version is not None and not model_version.strip():
            raise ValueError("model_version must be non-empty when provided")
        if not math.isfinite(timeout_seconds) or not 0 < timeout_seconds <= 3600:
            raise ValueError("timeout_seconds must be finite and between 0 and 3600")
        if isinstance(max_retries, bool) or not 0 <= max_retries <= 5:
            raise ValueError("max_retries must be an integer between 0 and 5")
        if not math.isfinite(retry_delay_seconds) or not 0 <= retry_delay_seconds <= 60:
            raise ValueError("retry_delay_seconds must be finite and between 0 and 60")
        if api_key is not None and not api_key:
            raise ValueError("api_key must be non-empty when provided")

        headers = {"Accept": "application/json"}
        if api_key is not None:
            headers["Authorization"] = f"Bearer {api_key}"
        self._model = model
        self._model_version = model_version
        self._max_retries = max_retries
        self._retry_delay_seconds = retry_delay_seconds
        self._client = httpx.AsyncClient(
            base_url=_validated_api_base_url(api_base_url),
            headers=headers,
            timeout=httpx.Timeout(timeout_seconds),
            follow_redirects=False,
            trust_env=False,
            transport=transport,
        )

    def __repr__(self) -> str:
        return f"{type(self).__name__}(model={self._model!r})"

    async def aclose(self) -> None:
        await self._client.aclose()

    async def _backoff(self, attempt: int) -> None:
        base_delay = self._retry_delay_seconds * (2**attempt)
        jitter = random.uniform(0, base_delay * 0.25) if base_delay else 0.0
        delay = min(_MAX_RETRY_SLEEP_SECONDS, base_delay + jitter)
        if delay:
            await asyncio.sleep(delay)

    @staticmethod
    def _is_out_of_memory(response: httpx.Response) -> bool:
        if response.status_code in _OOM_STATUS_CODES:
            return True
        if response.status_code < 500:
            return False
        body_prefix = response.text[:4096].lower()
        return "out of memory" in body_prefix or "cuda oom" in body_prefix

    async def _post_json(
        self,
        endpoint: str,
        payload: Mapping[str, object],
    ) -> Mapping[str, object]:
        for attempt in range(self._max_retries + 1):
            try:
                response = await self._client.post(endpoint, json=payload)
            except httpx.TransportError:
                if attempt >= self._max_retries:
                    raise AiServiceUnavailableError(
                        "NIM request failed after bounded transient retries"
                    ) from None
                await self._backoff(attempt)
                continue

            if self._is_out_of_memory(response):
                raise _NimOutOfMemoryError("NIM rejected the batch because memory was exhausted")
            if response.status_code in _TRANSIENT_STATUS_CODES:
                if attempt >= self._max_retries:
                    raise AiServiceUnavailableError(
                        f"NIM remained unavailable with HTTP {response.status_code}"
                    )
                await self._backoff(attempt)
                continue
            if not 200 <= response.status_code < 300:
                raise AiClientError(f"NIM rejected the request with HTTP {response.status_code}")
            return _response_json(response)
        raise AssertionError("bounded retry loop terminated unexpectedly")

    async def _stream_events(
        self,
        endpoint: str,
        payload: Mapping[str, object],
    ) -> AsyncIterator[Mapping[str, object]]:
        for attempt in range(self._max_retries + 1):
            emitted_event = False
            retry_status: int | None = None
            try:
                async with self._client.stream("POST", endpoint, json=payload) as response:
                    if response.status_code in _TRANSIENT_STATUS_CODES:
                        retry_status = response.status_code
                    elif not 200 <= response.status_code < 300:
                        raise AiClientError(
                            f"NIM rejected the stream request with HTTP {response.status_code}"
                        )
                    else:
                        async for line in response.aiter_lines():
                            if not line or line.startswith(":") or not line.startswith("data:"):
                                continue
                            data = line.removeprefix("data:").lstrip()
                            if data == "[DONE]":
                                return
                            try:
                                event: object = json.loads(data)
                            except json.JSONDecodeError:
                                raise AiProtocolError(
                                    "NIM stream contained an invalid JSON event"
                                ) from None
                            emitted_event = True
                            yield _mapping(event, "stream event")
                        raise AiProtocolError("NIM stream ended without the [DONE] marker")
            except httpx.TransportError:
                if emitted_event or attempt >= self._max_retries:
                    raise AiServiceUnavailableError(
                        "NIM stream failed and was not replayed after emitting data"
                    ) from None
                await self._backoff(attempt)
                continue

            if retry_status is not None:
                if attempt >= self._max_retries:
                    raise AiServiceUnavailableError(
                        f"NIM stream remained unavailable with HTTP {retry_status}"
                    )
                await self._backoff(attempt)
                continue
        raise AssertionError("bounded stream retry loop terminated unexpectedly")

    def _response_model(self, payload: Mapping[str, object]) -> str:
        raw_model = payload.get("model")
        if raw_model is None:
            return self._model
        model = _string(raw_model, "model")
        if model != self._model:
            raise AiProtocolError("NIM response model does not match the configured model")
        return model


class NimLlmClient(_NimHttpAdapter):
    """OpenAI-compatible chat completion adapter for an LLM NIM."""

    def __init__(
        self,
        *,
        api_base_url: str,
        model: str,
        model_version: str | None = None,
        api_key: str | None = None,
        timeout_seconds: float = 120,
        max_retries: int = 2,
        retry_delay_seconds: float = 0.1,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        super().__init__(
            api_base_url=api_base_url,
            model=model,
            model_version=model_version,
            api_key=api_key,
            timeout_seconds=timeout_seconds,
            max_retries=max_retries,
            retry_delay_seconds=retry_delay_seconds,
            transport=transport,
        )

    def _request_payload(self, request: ChatRequest, *, stream: bool) -> dict[str, object]:
        if self._model == SELECTED_NIM_LLM_MODEL:
            _validate_selected_nemotron_reasoning_control(request)
        payload: dict[str, object] = {
            "model": self._model,
            "messages": [
                {"role": message.role, "content": message.content} for message in request.messages
            ],
            "max_tokens": request.max_tokens,
            "temperature": request.temperature,
            "top_p": request.top_p,
            "stream": stream,
        }
        if request.seed is not None:
            payload["seed"] = request.seed
        if stream:
            payload["stream_options"] = {"include_usage": True}
        return payload

    async def chat(self, request: ChatRequest) -> ChatResponse:
        started = time.perf_counter()
        payload = await self._post_json(
            "chat/completions",
            self._request_payload(request, stream=False),
        )
        choices = _list(payload.get("choices"), "choices")
        if not choices:
            raise AiProtocolError("NIM response choices must not be empty")
        choice = _mapping(choices[0], "choices[0]")
        message = _mapping(choice.get("message"), "choices[0].message")
        content = _string(message.get("content"), "choices[0].message.content")
        if self._model == SELECTED_NIM_LLM_MODEL:
            raw_reasoning = message.get("reasoning_content")
            structured_reasoning_present = False
            if raw_reasoning is not None:
                structured_reasoning_present = bool(
                    _string(raw_reasoning, "choices[0].message.reasoning_content")
                )
            content = _visible_nemotron_chat_content(
                content,
                reasoning_enabled=_selected_nemotron_reasoning_enabled(request),
                structured_reasoning_present=structured_reasoning_present,
            )
        return ChatResponse(
            content=content,
            model=self._response_model(payload),
            latency_seconds=time.perf_counter() - started,
            finish_reason=_optional_string(choice.get("finish_reason"), "choices[0].finish_reason"),
            usage=_token_usage(payload),
            model_version=self._model_version,
        )

    async def stream(self, request: ChatRequest) -> AsyncIterator[ChatStreamChunk]:
        started = time.perf_counter()
        selected_nemotron = self._model == SELECTED_NIM_LLM_MODEL
        reasoning_enabled = selected_nemotron and _selected_nemotron_reasoning_enabled(request)
        reasoning_boundary_found = not reasoning_enabled
        structured_reasoning_seen = False
        reasoning_buffer = ""
        async for event in self._stream_events(
            "chat/completions",
            self._request_payload(request, stream=True),
        ):
            model = self._response_model(event)
            usage = _token_usage(event)
            choices = _list(event.get("choices"), "choices")
            if not choices:
                if usage is not None:
                    yield ChatStreamChunk(
                        content_delta="",
                        model=model,
                        elapsed_seconds=time.perf_counter() - started,
                        usage=usage,
                        model_version=self._model_version,
                    )
                    continue
                raise AiProtocolError("NIM stream event choices must not be empty")

            choice = _mapping(choices[0], "choices[0]")
            delta = _mapping(choice.get("delta"), "choices[0].delta")
            raw_content = delta.get("content")
            content = "" if raw_content is None else _string(raw_content, "delta.content")
            structured_reasoning_delta = False
            if selected_nemotron and delta.get("reasoning_content") is not None:
                structured_reasoning_delta = bool(
                    _string(delta["reasoning_content"], "delta.reasoning_content")
                )
                if structured_reasoning_delta and content:
                    raise AiProtocolError(
                        "NIM stream mixed hidden reasoning and visible content in one delta"
                    )
                structured_reasoning_seen = structured_reasoning_seen or structured_reasoning_delta
            finish_reason = _optional_string(choice.get("finish_reason"), "finish_reason")
            if reasoning_enabled and not reasoning_boundary_found:
                if structured_reasoning_seen:
                    if structured_reasoning_delta:
                        content = ""
                    elif content:
                        reasoning_boundary_found = True
                else:
                    reasoning_buffer += content
                    boundary = _NEMOTRON_REASONING_END.search(reasoning_buffer)
                    if boundary is None:
                        content = ""
                    else:
                        content = reasoning_buffer[boundary.end() :].lstrip()
                        reasoning_buffer = ""
                        reasoning_boundary_found = True
            if (
                selected_nemotron
                and reasoning_boundary_found
                and _NEMOTRON_REASONING_TAG.search(content)
            ):
                raise AiProtocolError("NIM visible answer contains a reasoning tag")
            if reasoning_enabled and finish_reason is not None and not reasoning_boundary_found:
                raise AiProtocolError("NIM reasoning stream has no safe visible-answer boundary")
            if content or finish_reason is not None or usage is not None:
                yield ChatStreamChunk(
                    content_delta=content,
                    model=model,
                    elapsed_seconds=time.perf_counter() - started,
                    finish_reason=finish_reason,
                    usage=usage,
                    model_version=self._model_version,
                )


class NimEmbeddingClient(_NimHttpAdapter):
    """OpenAI-compatible embedding adapter with strict finite dimensions."""

    def __init__(
        self,
        *,
        api_base_url: str,
        model: str,
        model_version: str | None = None,
        expected_dimension: int | None = None,
        max_batch_size: int = 32,
        allow_batch_downshift: bool = True,
        minimum_downshift_batch_size: int = 1,
        api_key: str | None = None,
        timeout_seconds: float = 120,
        max_retries: int = 2,
        retry_delay_seconds: float = 0.1,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        if expected_dimension is not None and (
            isinstance(expected_dimension, bool) or expected_dimension <= 0
        ):
            raise ValueError("expected_dimension must be a positive integer")
        self._expected_dimension = expected_dimension
        if isinstance(max_batch_size, bool) or not 1 <= max_batch_size <= 2048:
            raise ValueError("max_batch_size must be an integer between 1 and 2048")
        self._max_batch_size = max_batch_size
        if not isinstance(allow_batch_downshift, bool):
            raise ValueError("allow_batch_downshift must be a boolean")
        self._allow_batch_downshift = allow_batch_downshift
        if (
            isinstance(minimum_downshift_batch_size, bool)
            or not 1 <= minimum_downshift_batch_size <= max_batch_size
        ):
            raise ValueError("minimum_downshift_batch_size must be between 1 and max_batch_size")
        self._minimum_downshift_batch_size = minimum_downshift_batch_size
        super().__init__(
            api_base_url=api_base_url,
            model=model,
            model_version=model_version,
            api_key=api_key,
            timeout_seconds=timeout_seconds,
            max_retries=max_retries,
            retry_delay_seconds=retry_delay_seconds,
            transport=transport,
        )

    async def _embed_once(self, request: EmbeddingRequest) -> EmbeddingResponse:
        started = time.perf_counter()
        payload = await self._post_json(
            "embeddings",
            {
                "model": self._model,
                "input": list(request.texts),
                "input_type": request.input_type,
                "truncate": request.truncate,
                "encoding_format": "float",
            },
        )
        items = _list(payload.get("data"), "data")
        if len(items) != len(request.texts):
            raise AiProtocolError("NIM returned the wrong number of embedding vectors")

        indexed_vectors: dict[int, tuple[float, ...]] = {}
        for position, raw_item in enumerate(items):
            item = _mapping(raw_item, f"data[{position}]")
            raw_index = item.get("index")
            index = position if raw_index is None else _non_negative_integer(raw_index, "index")
            if index >= len(request.texts) or index in indexed_vectors:
                raise AiProtocolError("NIM returned an invalid or duplicate embedding index")
            raw_vector = _list(item.get("embedding"), "embedding")
            if not raw_vector:
                raise AiProtocolError("NIM returned an empty embedding vector")
            indexed_vectors[index] = tuple(
                _finite_number(value, "embedding value") for value in raw_vector
            )

        vectors = tuple(indexed_vectors[index] for index in range(len(request.texts)))
        dimension = len(vectors[0])
        if any(len(vector) != dimension for vector in vectors):
            raise AiProtocolError("NIM returned inconsistent embedding dimensions")
        if self._expected_dimension is not None and dimension != self._expected_dimension:
            raise AiProtocolError("NIM embedding dimension does not match the configured dimension")

        input_tokens: int | None = None
        raw_usage = payload.get("usage")
        if raw_usage is not None:
            usage = _mapping(raw_usage, "usage")
            token_value = usage.get("prompt_tokens", usage.get("total_tokens"))
            input_tokens = _non_negative_integer(token_value, "usage input tokens")

        return EmbeddingResponse(
            vectors=vectors,
            dimension=dimension,
            model=self._response_model(payload),
            latency_seconds=time.perf_counter() - started,
            model_version=self._model_version,
            input_tokens=input_tokens,
        )

    async def _embed_with_downshift(self, request: EmbeddingRequest) -> EmbeddingResponse:
        started = time.perf_counter()
        try:
            return await self._embed_once(request)
        except _NimOutOfMemoryError:
            if (
                not self._allow_batch_downshift
                # Never issue a recursive request below the operator's configured
                # floor.  Checking only ``len <= floor`` is insufficient: a
                # three-item batch split at a floor of two would otherwise emit
                # an unexpected one-item request.
                or len(request.texts) < self._minimum_downshift_batch_size * 2
            ):
                raise

        midpoint = len(request.texts) // 2
        left = await self._embed_with_downshift(
            EmbeddingRequest(
                texts=request.texts[:midpoint],
                input_type=request.input_type,
                truncate=request.truncate,
            )
        )
        right = await self._embed_with_downshift(
            EmbeddingRequest(
                texts=request.texts[midpoint:],
                input_type=request.input_type,
                truncate=request.truncate,
            )
        )
        if left.dimension != right.dimension or left.model != right.model:
            raise AiProtocolError("NIM batch downshift returned inconsistent embedding metadata")
        input_tokens = (
            left.input_tokens + right.input_tokens
            if left.input_tokens is not None and right.input_tokens is not None
            else None
        )
        return EmbeddingResponse(
            vectors=left.vectors + right.vectors,
            dimension=left.dimension,
            model=left.model,
            latency_seconds=time.perf_counter() - started,
            model_version=self._model_version,
            input_tokens=input_tokens,
        )

    async def embed(self, request: EmbeddingRequest) -> EmbeddingResponse:
        """Embed with a configured cap, downshifting only after an explicit OOM."""

        if len(request.texts) <= self._max_batch_size:
            return await self._embed_with_downshift(request)

        started = time.perf_counter()
        responses: list[EmbeddingResponse] = []
        for offset in range(0, len(request.texts), self._max_batch_size):
            responses.append(
                await self._embed_with_downshift(
                    EmbeddingRequest(
                        texts=request.texts[offset : offset + self._max_batch_size],
                        input_type=request.input_type,
                        truncate=request.truncate,
                    )
                )
            )

        first = responses[0]
        if any(
            response.dimension != first.dimension
            or response.model != first.model
            or response.model_version != first.model_version
            for response in responses[1:]
        ):
            raise AiProtocolError("NIM capped batches returned inconsistent embedding metadata")
        input_token_total = 0
        complete_usage = True
        for response in responses:
            if response.input_tokens is None:
                complete_usage = False
                break
            input_token_total += response.input_tokens
        input_tokens = input_token_total if complete_usage else None
        return EmbeddingResponse(
            vectors=tuple(vector for response in responses for vector in response.vectors),
            dimension=first.dimension,
            model=first.model,
            latency_seconds=time.perf_counter() - started,
            model_version=first.model_version,
            input_tokens=input_tokens,
        )


class NimRerankClient(_NimHttpAdapter):
    """NIM ranking adapter that retains each input passage's source index."""

    def __init__(
        self,
        *,
        api_base_url: str,
        model: str,
        model_version: str | None = None,
        api_key: str | None = None,
        timeout_seconds: float = 120,
        max_retries: int = 2,
        retry_delay_seconds: float = 0.1,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        super().__init__(
            api_base_url=api_base_url,
            model=model,
            model_version=model_version,
            api_key=api_key,
            timeout_seconds=timeout_seconds,
            max_retries=max_retries,
            retry_delay_seconds=retry_delay_seconds,
            transport=transport,
        )

    async def rerank(self, request: RerankRequest) -> RerankResponse:
        started = time.perf_counter()
        payload = await self._post_json(
            "ranking",
            {
                "model": self._model,
                "query": {"text": request.query},
                "passages": [{"text": passage} for passage in request.passages],
                "truncate": request.truncate,
            },
        )
        raw_rankings = _list(payload.get("rankings"), "rankings")
        if len(raw_rankings) != len(request.passages):
            raise AiProtocolError("NIM returned the wrong number of reranking results")

        rankings: list[RankedPassage] = []
        seen_indices: set[int] = set()
        for position, raw_ranking in enumerate(raw_rankings):
            ranking = _mapping(raw_ranking, f"rankings[{position}]")
            source_index = _non_negative_integer(ranking.get("index"), "ranking index")
            if source_index >= len(request.passages) or source_index in seen_indices:
                raise AiProtocolError("NIM returned an invalid or duplicate ranking index")
            seen_indices.add(source_index)
            raw_score = ranking.get("logit", ranking.get("score"))
            rankings.append(
                RankedPassage(
                    source_index=source_index,
                    passage=request.passages[source_index],
                    score=_finite_number(raw_score, "ranking score"),
                )
            )

        if any(current.score < following.score for current, following in pairwise(rankings)):
            raise AiProtocolError("NIM reranking scores are not ordered from highest to lowest")
        input_tokens: int | None = None
        raw_usage = payload.get("usage")
        if raw_usage is not None:
            usage = _mapping(raw_usage, "usage")
            token_value = usage.get("prompt_tokens", usage.get("total_tokens"))
            input_tokens = _non_negative_integer(token_value, "usage input tokens")
        return RerankResponse(
            rankings=tuple(rankings),
            model=self._response_model(payload),
            latency_seconds=time.perf_counter() - started,
            model_version=self._model_version,
            input_tokens=input_tokens,
        )

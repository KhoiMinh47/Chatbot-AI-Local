"""Application-facing contracts for local AI inference services.

These types deliberately contain no HTTP, NVIDIA, or framework dependencies.
Infrastructure adapters implement the protocols at the edge of the application.
"""

from __future__ import annotations

import math
from collections.abc import AsyncIterator
from dataclasses import dataclass
from itertools import pairwise
from typing import Literal, Protocol

type ChatRole = Literal["system", "user", "assistant"]
type EmbeddingInputType = Literal["query", "passage"]
type EmbeddingTruncatePolicy = Literal["NONE", "START", "END"]
type RerankTruncatePolicy = Literal["NONE", "END"]


class AiClientError(RuntimeError):
    """Base error safe for application code to handle or log."""


class AiServiceUnavailableError(AiClientError):
    """The inference service failed transiently or exhausted bounded retries."""


class AiProtocolError(AiClientError):
    """The inference service returned an invalid or incompatible response."""


def _require_non_blank(value: str, field_name: str) -> None:
    if not value.strip():
        raise ValueError(f"{field_name} must not be blank")


def _require_non_negative_integer(value: int, field_name: str) -> None:
    if isinstance(value, bool) or value < 0:
        raise ValueError(f"{field_name} must be a non-negative integer")


@dataclass(frozen=True, slots=True)
class ChatMessage:
    role: ChatRole
    content: str

    def __post_init__(self) -> None:
        _require_non_blank(self.content, "message content")


@dataclass(frozen=True, slots=True)
class ChatRequest:
    messages: tuple[ChatMessage, ...]
    max_tokens: int
    temperature: float = 0.0
    top_p: float = 1.0
    seed: int | None = None

    def __post_init__(self) -> None:
        if not self.messages:
            raise ValueError("messages must not be empty")
        if isinstance(self.max_tokens, bool) or self.max_tokens <= 0:
            raise ValueError("max_tokens must be a positive integer")
        if not math.isfinite(self.temperature) or self.temperature < 0:
            raise ValueError("temperature must be a finite non-negative number")
        if not math.isfinite(self.top_p) or not 0 < self.top_p <= 1:
            raise ValueError("top_p must be finite and in the interval (0, 1]")
        if self.seed is not None and isinstance(self.seed, bool):
            raise ValueError("seed must be an integer")


@dataclass(frozen=True, slots=True)
class TokenUsage:
    input_tokens: int
    output_tokens: int
    total_tokens: int

    def __post_init__(self) -> None:
        _require_non_negative_integer(self.input_tokens, "input_tokens")
        _require_non_negative_integer(self.output_tokens, "output_tokens")
        _require_non_negative_integer(self.total_tokens, "total_tokens")
        if self.total_tokens != self.input_tokens + self.output_tokens:
            raise ValueError("total_tokens must equal input_tokens plus output_tokens")


@dataclass(frozen=True, slots=True)
class ChatResponse:
    content: str
    model: str
    latency_seconds: float
    finish_reason: str | None
    usage: TokenUsage | None
    model_version: str | None = None

    def __post_init__(self) -> None:
        _require_non_blank(self.model, "model")
        if not math.isfinite(self.latency_seconds) or self.latency_seconds < 0:
            raise ValueError("latency_seconds must be a finite non-negative number")
        if self.model_version is not None:
            _require_non_blank(self.model_version, "model_version")


@dataclass(frozen=True, slots=True)
class ChatStreamChunk:
    content_delta: str
    model: str
    elapsed_seconds: float
    finish_reason: str | None = None
    usage: TokenUsage | None = None
    model_version: str | None = None

    def __post_init__(self) -> None:
        _require_non_blank(self.model, "model")
        if not math.isfinite(self.elapsed_seconds) or self.elapsed_seconds < 0:
            raise ValueError("elapsed_seconds must be a finite non-negative number")
        if self.model_version is not None:
            _require_non_blank(self.model_version, "model_version")


@dataclass(frozen=True, slots=True)
class EmbeddingRequest:
    texts: tuple[str, ...]
    input_type: EmbeddingInputType
    truncate: EmbeddingTruncatePolicy = "NONE"

    def __post_init__(self) -> None:
        if not self.texts:
            raise ValueError("texts must not be empty")
        if self.input_type not in {"query", "passage"}:
            raise ValueError("input_type must be query or passage")
        if self.truncate not in {"NONE", "START", "END"}:
            raise ValueError("embedding truncate must be NONE, START, or END")
        for text in self.texts:
            _require_non_blank(text, "embedding text")


@dataclass(frozen=True, slots=True)
class EmbeddingResponse:
    vectors: tuple[tuple[float, ...], ...]
    dimension: int
    model: str
    latency_seconds: float
    model_version: str | None = None
    input_tokens: int | None = None

    def __post_init__(self) -> None:
        if not self.vectors:
            raise ValueError("vectors must not be empty")
        if isinstance(self.dimension, bool) or self.dimension <= 0:
            raise ValueError("dimension must be a positive integer")
        if any(len(vector) != self.dimension for vector in self.vectors):
            raise ValueError("every vector must match dimension")
        if any(not math.isfinite(value) for vector in self.vectors for value in vector):
            raise ValueError("vectors must contain only finite numbers")
        _require_non_blank(self.model, "model")
        if not math.isfinite(self.latency_seconds) or self.latency_seconds < 0:
            raise ValueError("latency_seconds must be a finite non-negative number")
        if self.model_version is not None:
            _require_non_blank(self.model_version, "model_version")
        if self.input_tokens is not None:
            _require_non_negative_integer(self.input_tokens, "input_tokens")


@dataclass(frozen=True, slots=True)
class RerankRequest:
    query: str
    passages: tuple[str, ...]
    truncate: RerankTruncatePolicy = "NONE"

    def __post_init__(self) -> None:
        _require_non_blank(self.query, "query")
        if not self.passages:
            raise ValueError("passages must not be empty")
        if self.truncate not in {"NONE", "END"}:
            raise ValueError("rerank truncate must be NONE or END")
        for passage in self.passages:
            _require_non_blank(passage, "passage")


@dataclass(frozen=True, slots=True)
class RankedPassage:
    source_index: int
    passage: str
    score: float

    def __post_init__(self) -> None:
        _require_non_negative_integer(self.source_index, "source_index")
        _require_non_blank(self.passage, "passage")
        if not math.isfinite(self.score):
            raise ValueError("score must be finite")


@dataclass(frozen=True, slots=True)
class RerankResponse:
    rankings: tuple[RankedPassage, ...]
    model: str
    latency_seconds: float
    model_version: str | None = None
    input_tokens: int | None = None

    def __post_init__(self) -> None:
        if not self.rankings:
            raise ValueError("rankings must not be empty")
        _require_non_blank(self.model, "model")
        if not math.isfinite(self.latency_seconds) or self.latency_seconds < 0:
            raise ValueError("latency_seconds must be a finite non-negative number")
        if self.model_version is not None:
            _require_non_blank(self.model_version, "model_version")
        if self.input_tokens is not None:
            _require_non_negative_integer(self.input_tokens, "input_tokens")
        if any(current.score < following.score for current, following in pairwise(self.rankings)):
            raise ValueError("rankings must be ordered by descending score")


class AsyncAiClient(Protocol):
    """Own resources whose lifetime is bounded by the API process."""

    async def aclose(self) -> None:
        """Release transport resources; repeated calls must remain safe."""


class LlmClient(AsyncAiClient, Protocol):
    """Generate complete or streamed chat responses."""

    async def chat(self, request: ChatRequest) -> ChatResponse:
        """Return one complete assistant response."""

    def stream(self, request: ChatRequest) -> AsyncIterator[ChatStreamChunk]:
        """Yield final-answer deltas without exposing hidden reasoning."""


class EmbeddingClient(AsyncAiClient, Protocol):
    """Create query or passage embeddings through one stable contract."""

    async def embed(self, request: EmbeddingRequest) -> EmbeddingResponse:
        """Return one finite, fixed-dimension vector per input text."""


class RerankClient(AsyncAiClient, Protocol):
    """Rank passages while preserving their original source positions."""

    async def rerank(self, request: RerankRequest) -> RerankResponse:
        """Return all passages in service score order."""

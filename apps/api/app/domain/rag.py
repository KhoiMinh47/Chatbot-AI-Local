"""Framework-independent domain types for the Phase 6 grounded RAG flow."""

from __future__ import annotations

import hashlib
import math
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from types import MappingProxyType
from typing import Any, Literal
from uuid import UUID

from app.domain.memory import MemoryContext
from app.domain.retrieval import AccessScope


class RagMode(StrEnum):
    FAST = "fast"
    REASONING = "reasoning"


class ResponseDepth(StrEnum):
    CONCISE = "concise"
    NORMAL = "normal"
    DETAILED = "detailed"


class ReasoningControl(StrEnum):
    """Trusted Nemotron chat-template control selected by the server."""

    DISABLED = "no_think"
    ENABLED = "think"

    @property
    def system_signal(self) -> str:
        return "/no_think" if self is ReasoningControl.DISABLED else "/think"


class TraceOutcome(StrEnum):
    ANSWERED = "answered"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"
    INVALID_GENERATION = "invalid_generation"
    ERROR = "error"
    CANCELLED = "cancelled"


class RagEventType(StrEnum):
    STATUS = "status"
    RETRIEVAL_SUMMARY = "retrieval_summary"
    TOKEN = "token"
    CITATION = "citation"
    USAGE = "usage"
    DONE = "done"
    ERROR = "error"


@dataclass(frozen=True, slots=True)
class ModePolicy:
    """Hard, reviewable bounds for one graph mode."""

    mode: RagMode
    max_subqueries: int
    max_retrieval_rounds: int
    candidate_limit_per_query: int
    max_dense_candidates: int
    rerank_limit: int
    final_context_limit: int
    context_window_tokens: int
    context_token_cap: int
    max_output_tokens: int
    safety_tokens: int
    temperature: float
    top_p: float
    reasoning_control: ReasoningControl

    def __post_init__(self) -> None:
        integer_fields = (
            self.max_subqueries,
            self.max_retrieval_rounds,
            self.candidate_limit_per_query,
            self.max_dense_candidates,
            self.rerank_limit,
            self.final_context_limit,
            self.context_window_tokens,
            self.context_token_cap,
            self.max_output_tokens,
            self.safety_tokens,
        )
        if any(isinstance(value, bool) or value <= 0 for value in integer_fields):
            raise ValueError("mode policy integer bounds must be positive")
        if self.candidate_limit_per_query * self.max_subqueries > self.max_dense_candidates:
            raise ValueError("per-query candidates can exceed max_dense_candidates")
        if self.rerank_limit > self.max_dense_candidates:
            raise ValueError("rerank_limit cannot exceed max_dense_candidates")
        if self.final_context_limit > self.rerank_limit:
            raise ValueError("final_context_limit cannot exceed rerank_limit")
        if self.context_token_cap + self.max_output_tokens + self.safety_tokens >= (
            self.context_window_tokens
        ):
            raise ValueError("mode policy leaves no room for instructions, history, and query")
        if not math.isfinite(self.temperature) or self.temperature < 0:
            raise ValueError("temperature must be finite and non-negative")
        if not math.isfinite(self.top_p) or not 0 < self.top_p <= 1:
            raise ValueError("top_p must be finite and in the interval (0, 1]")


FAST_POLICY = ModePolicy(
    mode=RagMode.FAST,
    max_subqueries=1,
    max_retrieval_rounds=1,
    candidate_limit_per_query=12,
    max_dense_candidates=12,
    rerank_limit=10,
    final_context_limit=6,
    context_window_tokens=32_768,
    context_token_cap=8_192,
    max_output_tokens=768,
    safety_tokens=1_536,
    temperature=0.0,
    top_p=1.0,
    reasoning_control=ReasoningControl.DISABLED,
)

REASONING_POLICY = ModePolicy(
    mode=RagMode.REASONING,
    max_subqueries=3,
    max_retrieval_rounds=2,
    candidate_limit_per_query=10,
    max_dense_candidates=30,
    rerank_limit=20,
    final_context_limit=12,
    context_window_tokens=32_768,
    context_token_cap=16_384,
    max_output_tokens=1_024,
    safety_tokens=2_048,
    temperature=0.6,
    top_p=0.95,
    # Reasoning mode earns its quality gain from deeper planning/retrieval and a
    # larger answer budget.  Keep model-side hidden thinking disabled: on the
    # current NIM runtime `/think` can consume the whole request without ever
    # reaching a visible-answer boundary, leaving the chat stream stuck.
    reasoning_control=ReasoningControl.DISABLED,
)


def policy_for(mode: RagMode) -> ModePolicy:
    return FAST_POLICY if mode is RagMode.FAST else REASONING_POLICY


@dataclass(frozen=True, slots=True)
class ConversationTurn:
    role: Literal["user", "assistant"]
    content: str

    def __post_init__(self) -> None:
        if not self.content.strip():
            raise ValueError("conversation turn content must not be blank")


@dataclass(frozen=True, slots=True)
class RagRequest:
    """Trusted application command; actor and ACL values are not HTTP body fields."""

    request_id: UUID
    user_id: UUID
    tenant_id: UUID
    conversation_id: UUID
    mode: RagMode
    question: str
    language: Literal["vi", "en"]
    acl_principals: tuple[str, ...]
    selected_document_ids: tuple[UUID, ...] = ()
    recent_messages: tuple[ConversationTurn, ...] = ()
    conversation_summary: str | None = None
    long_term_memories: tuple[MemoryContext, ...] = ()
    response_depth: ResponseDepth = ResponseDepth.DETAILED

    def __post_init__(self) -> None:
        if not self.question.strip():
            raise ValueError("question must not be blank")
        if len(self.question) > 8_000:
            raise ValueError("question exceeds the 8000-character safety bound")
        if not self.acl_principals:
            raise ValueError("acl_principals must not be empty")
        if len(self.acl_principals) != len(set(self.acl_principals)):
            raise ValueError("acl_principals must not contain duplicates")
        if any(not value.strip() for value in self.acl_principals):
            raise ValueError("acl_principals must contain only non-blank values")
        if f"user:{self.user_id}" not in self.acl_principals:
            raise ValueError("acl_principals must contain the trusted user principal")
        if len(self.selected_document_ids) != len(set(self.selected_document_ids)):
            raise ValueError("selected_document_ids must not contain duplicates")
        if self.conversation_summary is not None and not self.conversation_summary.strip():
            raise ValueError("conversation_summary must not be blank when provided")
        memory_ids = tuple(memory.id for memory in self.long_term_memories)
        if len(memory_ids) != len(set(memory_ids)):
            raise ValueError("long_term_memories must not contain duplicate IDs")

    @property
    def access_scope(self) -> AccessScope:
        return AccessScope(
            tenant_id=self.tenant_id,
            acl_principals=self.acl_principals,
            document_ids=self.selected_document_ids,
        )


@dataclass(frozen=True, slots=True)
class ContextBlock:
    """A server-owned source block; the model may only reference citation_id."""

    citation_id: str
    document_id: UUID
    version_id: UUID
    chunk_id: UUID
    source_name: str
    text: str
    page: int | None
    slide: int | None
    section_path: tuple[str, ...]
    dense_rank: int
    final_rank: int
    score: float
    content_hash: str
    sheet: str | None = None
    cell_range: str | None = None
    line_start: int | None = None
    line_end: int | None = None

    def __post_init__(self) -> None:
        expected = f"C{self.chunk_id.hex}"
        if self.citation_id != expected:
            raise ValueError(f"citation_id must be stable chunk-bound ID {expected}")
        if not self.source_name.strip() or not self.text.strip():
            raise ValueError("context source_name and text must not be blank")
        if self.dense_rank <= 0 or self.final_rank <= 0:
            raise ValueError("context ranks must be positive")
        if not math.isfinite(self.score):
            raise ValueError("context score must be finite")


@dataclass(frozen=True, slots=True)
class Citation:
    citation_id: str
    document_id: UUID
    version_id: UUID
    chunk_id: UUID
    source_name: str
    page: int | None
    slide: int | None
    section_path: tuple[str, ...]
    sheet: str | None
    cell_range: str | None
    line_start: int | None
    line_end: int | None
    score: float
    verified: bool

    @classmethod
    def from_block(cls, block: ContextBlock) -> Citation:
        return cls(
            citation_id=block.citation_id,
            document_id=block.document_id,
            version_id=block.version_id,
            chunk_id=block.chunk_id,
            source_name=block.source_name,
            page=block.page,
            slide=block.slide,
            section_path=block.section_path,
            sheet=block.sheet,
            cell_range=block.cell_range,
            line_start=block.line_start,
            line_end=block.line_end,
            score=block.score,
            verified=True,
        )


@dataclass(frozen=True, slots=True)
class TokenBudget:
    tokenizer_id: str
    tokenizer_sha256: str
    exact: bool
    context_window_tokens: int
    prompt_tokens: int
    context_tokens: int
    output_reserved_tokens: int
    safety_reserved_tokens: int

    def __post_init__(self) -> None:
        if not self.tokenizer_id.strip():
            raise ValueError("tokenizer_id must not be blank")
        if len(self.tokenizer_sha256) != 64:
            raise ValueError("tokenizer_sha256 must be a SHA-256 hex digest")
        values = (
            self.context_window_tokens,
            self.prompt_tokens,
            self.context_tokens,
            self.output_reserved_tokens,
            self.safety_reserved_tokens,
        )
        if any(isinstance(value, bool) or value < 0 for value in values):
            raise ValueError("token budget values must be non-negative integers")
        if self.prompt_tokens + self.output_reserved_tokens + self.safety_reserved_tokens > (
            self.context_window_tokens
        ):
            raise ValueError("token budget exceeds the model context window")


@dataclass(frozen=True, slots=True)
class TraceContextRef:
    citation_id: str
    document_id: UUID
    chunk_id: UUID
    dense_rank: int
    final_rank: int
    score: float
    content_hash: str


@dataclass(frozen=True, slots=True)
class GenerationTrace:
    """Durable audit record that deliberately excludes prompts, documents, and CoT."""

    request_id: UUID
    user_id: UUID
    tenant_id: UUID
    conversation_id: UUID
    mode: RagMode
    outcome: TraceOutcome
    prompt_version: str
    prompt_sha256: str
    graph_version: str
    question_sha256: str
    answer_sha256: str
    model: str | None
    model_version: str | None
    index_fingerprint: str
    retrieval_policy_fingerprint: str
    rewritten_query_sha256: str
    subquery_count: int
    retrieval_rounds: int
    context_refs: tuple[TraceContextRef, ...]
    citations: tuple[Citation, ...]
    token_budget: TokenBudget | None
    input_tokens: int | None
    output_tokens: int | None
    node_path: tuple[str, ...]
    timings_ms: Mapping[str, float]
    error_codes: tuple[str, ...] = ()
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def __post_init__(self) -> None:
        for value, field_name in (
            (self.prompt_version, "prompt_version"),
            (self.graph_version, "graph_version"),
            (self.index_fingerprint, "index_fingerprint"),
            (self.retrieval_policy_fingerprint, "retrieval_policy_fingerprint"),
        ):
            if not value.strip():
                raise ValueError(f"{field_name} must not be blank")
        for fingerprint in (self.index_fingerprint, self.retrieval_policy_fingerprint):
            if len(fingerprint) != 64 or any(
                char not in "0123456789abcdef" for char in fingerprint
            ):
                raise ValueError("trace fingerprints must be lowercase SHA-256 values")
        for digest in (
            self.prompt_sha256,
            self.question_sha256,
            self.answer_sha256,
            self.rewritten_query_sha256,
        ):
            if len(digest) != 64 or any(char not in "0123456789abcdef" for char in digest):
                raise ValueError("trace digests must be lowercase SHA-256 values")
        if self.subquery_count < 0 or self.retrieval_rounds < 0:
            raise ValueError("trace query and retrieval counts must be non-negative")
        if self.created_at.tzinfo is None or self.created_at.utcoffset() is None:
            raise ValueError("trace created_at must be timezone-aware")
        object.__setattr__(self, "timings_ms", MappingProxyType(dict(self.timings_ms)))


_EVENT_KEYS: Mapping[RagEventType, frozenset[str]] = {
    RagEventType.STATUS: frozenset({"phase", "mode"}),
    RagEventType.RETRIEVAL_SUMMARY: frozenset({"query_count", "candidate_count", "context_count"}),
    RagEventType.TOKEN: frozenset({"text"}),
    RagEventType.CITATION: frozenset(
        {
            "citation_id",
            "document_id",
            "version_id",
            "chunk_id",
            "source_name",
            "page",
            "slide",
            "section_path",
            "sheet",
            "cell_range",
            "line_start",
            "line_end",
            "excerpt",
            "score",
            "verified",
        }
    ),
    RagEventType.USAGE: frozenset({"input_tokens", "output_tokens", "total_tokens"}),
    RagEventType.DONE: frozenset({"outcome"}),
    RagEventType.ERROR: frozenset({"code", "message"}),
}


@dataclass(frozen=True, slots=True)
class RagEvent:
    """Transport-neutral, field-whitelisted stream event."""

    event_type: RagEventType
    request_id: UUID
    sequence: int
    data: Mapping[str, Any]

    def __post_init__(self) -> None:
        if isinstance(self.sequence, bool) or self.sequence <= 0:
            raise ValueError("event sequence must be positive")
        expected = _EVENT_KEYS[self.event_type]
        if frozenset(self.data) != expected:
            raise ValueError(f"{self.event_type.value} event requires exactly {sorted(expected)}")
        object.__setattr__(self, "data", MappingProxyType(dict(self.data)))

    def as_dict(self) -> dict[str, Any]:
        return {
            "type": self.event_type.value,
            "request_id": str(self.request_id),
            "sequence": self.sequence,
            **dict(self.data),
        }


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()

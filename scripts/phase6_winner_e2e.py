#!/usr/bin/env python3
"""Run immutable Phase 6 winner evidence on the activated Phase 4/5 corpus.

The runner deliberately has no HTTP/product-backend surface (Phase 7).  It invokes
the Phase 6 application graph directly while exercising the exact active Qdrant
alias, Embed-300M NIM, Nemotron Nano 9B v2 NIM, exact tokenizer, and PostgreSQL
trace adapter.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import re
from collections.abc import AsyncIterator, Mapping, Sequence
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter
from typing import Literal, cast
from urllib.parse import urlsplit
from uuid import UUID, uuid4

import httpx2 as httpx
from app.application.ai_clients import (
    ChatRequest,
    ChatResponse,
    ChatStreamChunk,
    LlmClient,
)
from app.application.rag import GRAPH_VERSION, PROMPT_SHA256, PROMPT_VERSION
from app.application.retrieval import DenseRetriever
from app.core.settings import SELECTED_NIM_LLM_MODEL, SELECTED_NIM_LLM_MODEL_VERSION
from app.domain.rag import (
    FAST_POLICY,
    REASONING_POLICY,
    GenerationTrace,
    RagEvent,
    RagEventType,
    RagMode,
    RagRequest,
    TraceOutcome,
    sha256_text,
)
from app.domain.retrieval import AccessScope, IndexConfig, RetrievalPolicy
from app.infrastructure.exact_token_counter import ExactHuggingFaceTokenCounter
from app.infrastructure.generation_trace_store import PostgresGenerationTraceStore
from app.infrastructure.nim_clients import NimEmbeddingClient, NimLlmClient
from app.infrastructure.qdrant_store import QdrantVectorIndex
from app.rag.graph import GroundedRagGraph
from app.rag.planner import LlmQueryPlanner
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

EMBEDDING_MODEL = "nvidia/llama-nemotron-embed-300m-v2"
EMBEDDING_MODEL_VERSION = "1.13.0"
EMBEDDING_DIMENSION = 2048
ACTIVE_ALIAS = "ntc_chunks_active"
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_HIDDEN_REASONING = re.compile(
    r"<\s*/?\s*(?:think|analysis|reasoning)\b|^(?:analysis|reasoning)\s*:",
    re.IGNORECASE | re.MULTILINE,
)
_PROVENANCE = (
    "apps/api/app/domain/rag.py",
    "apps/api/app/domain/retrieval.py",
    "apps/api/app/application/rag.py",
    "apps/api/app/application/retrieval.py",
    "apps/api/app/rag/graph.py",
    "apps/api/app/rag/planner.py",
    "apps/api/app/infrastructure/exact_token_counter.py",
    "apps/api/app/infrastructure/generation_trace_store.py",
    "apps/api/app/infrastructure/nim_clients.py",
    "apps/api/app/infrastructure/qdrant_store.py",
    "migrations/versions/0005_phase6_winner_trace_binding.py",
    "scripts/phase6_winner_e2e.py",
    "uv.lock",
)


class WinnerE2EError(RuntimeError):
    """Stable runner failure that never includes a credential or response body."""


@dataclass(frozen=True, slots=True)
class GoldCase:
    case_id: str
    split: str
    query: str
    answerable: bool
    expected_source_names: tuple[str, ...]
    language: Literal["vi", "en"]


@dataclass(frozen=True, slots=True)
class WinnerBinding:
    config: IndexConfig
    policy: RetrievalPolicy
    phase5_run_id: str
    decision_sha256: str
    receipt_sha256: str
    expected_point_count: int
    gold_sha256: str


@dataclass(slots=True)
class CountingLlm:
    inner: LlmClient
    chat_calls: int = 0
    stream_calls: int = 0

    async def chat(self, request: ChatRequest) -> ChatResponse:
        self.chat_calls += 1
        return await self.inner.chat(request)

    def stream(self, request: ChatRequest) -> AsyncIterator[ChatStreamChunk]:
        self.stream_calls += 1
        return self.inner.stream(request)

    async def aclose(self) -> None:
        await self.inner.aclose()


@dataclass(slots=True)
class DurableCaptureTraceStore:
    durable: PostgresGenerationTraceStore
    traces: list[GenerationTrace]

    async def save(self, trace: GenerationTrace) -> None:
        await self.durable.save(trace)
        self.traces.append(trace)


@dataclass(frozen=True, slots=True)
class CaseResult:
    case: GoldCase
    mode: RagMode
    elapsed_seconds: float
    events: tuple[RagEvent, ...]
    trace: GenerationTrace
    visible_answer: str
    llm_chat_calls: int
    llm_stream_calls: int

    def retrieval_summary(self) -> dict[str, int] | None:
        summaries = [
            event for event in self.events if event.event_type is RagEventType.RETRIEVAL_SUMMARY
        ]
        if len(summaries) != 1:
            return None
        data = summaries[0].data
        values = (data["query_count"], data["candidate_count"], data["context_count"])
        if any(isinstance(value, bool) or not isinstance(value, int) for value in values):
            return None
        return {
            "query_count": cast(int, values[0]),
            "candidate_count": cast(int, values[1]),
            "context_count": cast(int, values[2]),
        }

    def report_dict(self) -> dict[str, object]:
        event_citations = [
            {
                "citation_id": event.data["citation_id"],
                "chunk_id": event.data["chunk_id"],
                "document_id": event.data["document_id"],
                "page": event.data["page"],
                "slide": event.data["slide"],
                "source_name": event.data["source_name"],
            }
            for event in self.events
            if event.event_type is RagEventType.CITATION
        ]
        return {
            "case_id": self.case.case_id,
            "question_sha256": sha256_text(self.case.query),
            "mode": self.mode.value,
            "elapsed_seconds": self.elapsed_seconds,
            "event_types": [event.event_type.value for event in self.events],
            "event_sequence_contiguous": [event.sequence for event in self.events]
            == list(range(1, len(self.events) + 1)),
            "retrieval_summary": self.retrieval_summary(),
            "outcome": self.trace.outcome.value,
            "answer_sha256": self.trace.answer_sha256,
            "visible_answer_recorded": False,
            "citations": event_citations,
            "context_refs": [
                {
                    "citation_id": reference.citation_id,
                    "chunk_id": str(reference.chunk_id),
                    "document_id": str(reference.document_id),
                    "content_hash": reference.content_hash,
                    "dense_rank": reference.dense_rank,
                    "final_rank": reference.final_rank,
                    "score": reference.score,
                }
                for reference in self.trace.context_refs
            ],
            "token_budget": (
                asdict(self.trace.token_budget) if self.trace.token_budget is not None else None
            ),
            "input_tokens": self.trace.input_tokens,
            "output_tokens": self.trace.output_tokens,
            "subquery_count": self.trace.subquery_count,
            "retrieval_rounds": self.trace.retrieval_rounds,
            "model": self.trace.model,
            "model_version": self.trace.model_version,
            "index_fingerprint": self.trace.index_fingerprint,
            "retrieval_policy_fingerprint": self.trace.retrieval_policy_fingerprint,
            "node_path": list(self.trace.node_path),
            "error_codes": list(self.trace.error_codes),
            "llm_calls": {
                "chat": self.llm_chat_calls,
                "stream": self.llm_stream_calls,
            },
            "contains_hidden_reasoning": bool(_HIDDEN_REASONING.search(self.visible_answer)),
        }


def _mapping(value: object, field_name: str) -> Mapping[str, object]:
    if not isinstance(value, dict):
        raise WinnerE2EError(f"{field_name} must be a JSON object")
    return cast(dict[str, object], value)


def _array(value: object, field_name: str) -> list[object]:
    if not isinstance(value, list):
        raise WinnerE2EError(f"{field_name} must be a JSON array")
    return cast(list[object], value)


def _string(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise WinnerE2EError(f"{field_name} must be a non-blank string")
    return value.strip()


def _integer(value: object, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise WinnerE2EError(f"{field_name} must be an integer")
    return value


def _number_or_none(value: object, field_name: str) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise WinnerE2EError(f"{field_name} must be numeric or null")
    return float(value)


def _boolean(value: object, field_name: str) -> bool:
    if not isinstance(value, bool):
        raise WinnerE2EError(f"{field_name} must be a boolean")
    return value


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _read_json(path: Path, field_name: str) -> tuple[bytes, Mapping[str, object]]:
    try:
        raw = path.resolve(strict=True).read_bytes()
        parsed: object = json.loads(raw)
    except (OSError, UnicodeError, json.JSONDecodeError):
        raise WinnerE2EError(f"{field_name} is unreadable or invalid JSON") from None
    return raw, _mapping(parsed, field_name)


def _require_sha256(value: object, field_name: str) -> str:
    result = _string(value, field_name)
    if not _SHA256.fullmatch(result):
        raise WinnerE2EError(f"{field_name} must be a lowercase SHA-256 digest")
    return result


def load_winner_binding(decision_path: Path, receipt_path: Path) -> WinnerBinding:
    """Verify the immutable Phase 5 decision and post-decision alias receipt."""

    decision_bytes, decision = _read_json(decision_path, "Phase 5 decision report")
    receipt_bytes, receipt = _read_json(receipt_path, "Phase 5 activation receipt")
    decision_sha256 = _sha256_bytes(decision_bytes)
    if _string(decision.get("status"), "decision status") != "APPROVED_FOR_ACTIVATION":
        raise WinnerE2EError("Phase 5 decision is not approved for activation")
    if _string(receipt.get("status"), "receipt status") != "ACTIVATED":
        raise WinnerE2EError("Phase 5 activation receipt is not activated")
    if (
        _require_sha256(receipt.get("decision_report_sha256"), "receipt decision_report_sha256")
        != decision_sha256
    ):
        raise WinnerE2EError("Phase 5 activation receipt does not bind the decision bytes")
    inputs = _mapping(decision.get("inputs"), "decision inputs")
    gold_sha256 = _require_sha256(inputs.get("gold_sha256"), "decision gold_sha256")

    winner = _mapping(decision.get("winner_index"), "winner_index")
    config = IndexConfig(
        collection_name=_string(winner.get("collection_name"), "collection_name"),
        index_version=_string(winner.get("index_version"), "index_version"),
        embedding_model=_string(winner.get("embedding_model"), "embedding_model"),
        embedding_model_version=_string(
            winner.get("embedding_model_version"), "embedding_model_version"
        ),
        vector_dimension=_integer(winner.get("dimension"), "dimension"),
        chunk_size=_integer(winner.get("chunk_size"), "chunk_size"),
        overlap_percent=_integer(winner.get("overlap_percent"), "overlap_percent"),
        distance=cast(Literal["Cosine", "Dot"], _string(winner.get("distance"), "distance")),
    )
    if (
        config.embedding_model != EMBEDDING_MODEL
        or config.embedding_model_version != EMBEDDING_MODEL_VERSION
        or config.vector_dimension != EMBEDDING_DIMENSION
    ):
        raise WinnerE2EError("Phase 5 winner is not the exact selected Embed-300M contract")
    if (
        _require_sha256(winner.get("index_config_fingerprint"), "index_config_fingerprint")
        != config.fingerprint
    ):
        raise WinnerE2EError("Phase 5 decision index fingerprint is not reproducible")

    raw_policy = _mapping(decision.get("retrieval_policy"), "retrieval_policy")
    reranker_enabled = _boolean(raw_policy.get("reranker_enabled"), "reranker_enabled")
    policy = RetrievalPolicy(
        index_config_fingerprint=config.fingerprint,
        dense_candidate_limit=_integer(
            raw_policy.get("dense_candidate_limit"), "dense_candidate_limit"
        ),
        final_limit=_integer(raw_policy.get("final_limit"), "final_limit"),
        dense_threshold=_number_or_none(raw_policy.get("dense_threshold"), "dense_threshold"),
        hnsw_ef=_integer(raw_policy.get("hnsw_ef"), "hnsw_ef"),
        reranker_enabled=reranker_enabled,
        reranker_model=(
            _string(raw_policy.get("reranker_model"), "reranker_model")
            if reranker_enabled
            else None
        ),
        reranker_model_version=(
            _string(raw_policy.get("reranker_model_version"), "reranker_model_version")
            if reranker_enabled
            else None
        ),
        rerank_threshold=(
            _number_or_none(raw_policy.get("rerank_threshold"), "rerank_threshold")
            if reranker_enabled
            else None
        ),
        deduplication_policy=cast(
            Literal["content_hash_and_document_section_v1"],
            _string(raw_policy.get("deduplication_policy"), "deduplication_policy"),
        ),
    )
    if reranker_enabled:
        raise WinnerE2EError(
            "this selected Phase 6 baseline requires the approved reranker-off policy"
        )
    if _require_sha256(raw_policy.get("fingerprint"), "policy fingerprint") != policy.fingerprint:
        raise WinnerE2EError("Phase 5 retrieval-policy fingerprint is not reproducible")

    approval = _mapping(receipt.get("approval"), "receipt approval")
    if (
        _require_sha256(approval.get("config_fingerprint"), "receipt config_fingerprint")
        != config.fingerprint
    ):
        raise WinnerE2EError("activation receipt is not bound to the selected index")
    if (
        _require_sha256(
            approval.get("retrieval_policy_fingerprint"),
            "receipt retrieval_policy_fingerprint",
        )
        != policy.fingerprint
    ):
        raise WinnerE2EError("activation receipt is not bound to the selected retrieval policy")
    expected_count = _integer(winner.get("expected_point_count"), "expected_point_count")
    if (
        expected_count <= 0
        or _integer(approval.get("expected_point_count"), "receipt expected_point_count")
        != expected_count
    ):
        raise WinnerE2EError("activation receipt point count differs from the decision")
    if (
        _string(receipt.get("alias"), "receipt alias") != ACTIVE_ALIAS
        or not _boolean(receipt.get("alias_verified"), "receipt alias_verified")
        or _string(receipt.get("alias_readback"), "receipt alias_readback")
        != config.collection_name
        or _string(receipt.get("activated_collection"), "activated_collection")
        != config.collection_name
    ):
        raise WinnerE2EError("activation receipt does not verify the active alias target")

    return WinnerBinding(
        config=config,
        policy=policy,
        phase5_run_id=_string(decision.get("run_id"), "Phase 5 run_id"),
        decision_sha256=decision_sha256,
        receipt_sha256=_sha256_bytes(receipt_bytes),
        expected_point_count=expected_count,
        gold_sha256=gold_sha256,
    )


def load_live_cases(path: Path) -> tuple[GoldCase, GoldCase]:
    """Select one answerable and one same-language unanswerable held-out case."""

    try:
        lines = path.resolve(strict=True).read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeError):
        raise WinnerE2EError("canonical Phase 4 gold JSONL is unreadable") from None
    cases: list[GoldCase] = []
    for line_number, line in enumerate(lines, start=1):
        try:
            record = _mapping(json.loads(line), f"gold line {line_number}")
        except json.JSONDecodeError:
            raise WinnerE2EError(f"gold line {line_number} is invalid JSON") from None
        split = _string(record.get("split"), "gold split")
        if split != "evaluation":
            continue
        raw_language = _string(record.get("language"), "gold language")
        if raw_language not in {"vi", "en"}:
            raise WinnerE2EError("gold language must be vi or en")
        answerable = _boolean(record.get("answerable"), "gold answerable")
        sources = tuple(
            _string(item, "expected_source_names[]")
            for item in _array(record.get("expected_source_names"), "expected_source_names")
        )
        if answerable != bool(sources):
            raise WinnerE2EError("gold answerability and expected sources are inconsistent")
        cases.append(
            GoldCase(
                case_id=_string(record.get("id"), "gold id"),
                split=split,
                query=_string(record.get("query"), "gold query"),
                answerable=answerable,
                expected_source_names=sources,
                language=cast(Literal["vi", "en"], raw_language),
            )
        )
    answerable_case = next((case for case in cases if case.answerable), None)
    if answerable_case is None:
        raise WinnerE2EError("held-out gold has no answerable case")
    unanswerable_case = next(
        (
            case
            for case in cases
            if not case.answerable and case.language == answerable_case.language
        ),
        None,
    )
    if unanswerable_case is None:
        raise WinnerE2EError("held-out gold has no same-language unanswerable case")
    return answerable_case, unanswerable_case


def verify_gold_binding(path: Path, expected_sha256: str) -> str:
    """Require the exact held-out gold bytes used by the Phase 5 winner decision."""

    if not _SHA256.fullmatch(expected_sha256):
        raise WinnerE2EError("expected gold binding is not a lowercase SHA-256 digest")
    try:
        observed = _sha256_bytes(path.resolve(strict=True).read_bytes())
    except OSError:
        raise WinnerE2EError("canonical Phase 4 gold JSONL is unreadable") from None
    if observed != expected_sha256:
        raise WinnerE2EError("gold JSONL is not the exact held-out set bound by Phase 5")
    return observed


def _async_database_url(value: str) -> str:
    parsed = urlsplit(value)
    if (
        parsed.scheme not in {"postgres", "postgresql", "postgresql+asyncpg"}
        or not parsed.hostname
        or not parsed.path
    ):
        raise WinnerE2EError("database URL environment value is not a PostgreSQL URL")
    if value.startswith("postgresql+asyncpg://"):
        return value
    return re.sub(r"^postgres(?:ql)?://", "postgresql+asyncpg://", value, count=1)


def _service_url(value: str, field_name: str, *, require_v1: bool) -> str:
    candidate = value.strip().rstrip("/")
    parsed = urlsplit(candidate)
    valid_path = parsed.path.endswith("/v1") if require_v1 else parsed.path in {"", "/"}
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
        or not valid_path
    ):
        raise WinnerE2EError(f"{field_name} is not a credential-free expected service URL")
    return candidate


async def _advertised_model_ids(base_url: str, field_name: str) -> tuple[str, ...]:
    """Read only advertised IDs; never retain an error body or full model metadata."""

    async with httpx.AsyncClient(
        base_url=f"{base_url.rstrip('/')}/",
        timeout=httpx.Timeout(30),
        follow_redirects=False,
        trust_env=False,
    ) as client:
        try:
            response = await client.get("models")
        except httpx.TransportError:
            raise WinnerE2EError(f"{field_name} model identity request failed") from None
    if response.status_code != 200:
        raise WinnerE2EError(f"{field_name} model identity returned HTTP {response.status_code}")
    try:
        payload = _mapping(response.json(), f"{field_name} models response")
        data = _array(payload.get("data"), f"{field_name} models data")
        ids = tuple(
            _string(_mapping(item, f"{field_name} model").get("id"), f"{field_name} model id")
            for item in data
        )
    except (ValueError, UnicodeError):
        raise WinnerE2EError(f"{field_name} model identity response is invalid") from None
    if not ids or len(ids) != len(set(ids)):
        raise WinnerE2EError(f"{field_name} advertised model IDs are empty or duplicated")
    return ids


async def _run_case(
    *,
    graph: GroundedRagGraph,
    trace_store: DurableCaptureTraceStore,
    llm: CountingLlm,
    case: GoldCase,
    mode: RagMode,
    tenant_id: UUID,
    user_id: UUID,
    conversation_id: UUID,
) -> CaseResult:
    request = RagRequest(
        request_id=uuid4(),
        user_id=user_id,
        tenant_id=tenant_id,
        conversation_id=conversation_id,
        mode=mode,
        question=case.query,
        language=case.language,
        acl_principals=(f"user:{user_id}",),
    )
    trace_start = len(trace_store.traces)
    chat_start = llm.chat_calls
    stream_start = llm.stream_calls
    started = perf_counter()
    events = tuple([event async for event in graph.stream(request)])
    elapsed = perf_counter() - started
    new_traces = trace_store.traces[trace_start:]
    if len(new_traces) != 1 or new_traces[0].request_id != request.request_id:
        raise WinnerE2EError("graph did not persist exactly one matching trace")
    visible_answer = "".join(
        str(event.data["text"]) for event in events if event.event_type is RagEventType.TOKEN
    )
    return CaseResult(
        case=case,
        mode=mode,
        elapsed_seconds=elapsed,
        events=events,
        trace=new_traces[0],
        visible_answer=visible_answer,
        llm_chat_calls=llm.chat_calls - chat_start,
        llm_stream_calls=llm.stream_calls - stream_start,
    )


async def _trace_readback(
    engine: AsyncEngine,
    traces: Sequence[GenerationTrace],
) -> tuple[dict[str, dict[str, object]], bool]:
    request_ids = [trace.request_id for trace in traces]
    query = text(
        """
        SELECT request_id, tenant_id, user_id, conversation_id, mode, outcome,
               prompt_version, prompt_sha256, graph_version, question_sha256,
               answer_sha256, model, model_version, index_fingerprint,
               retrieval_policy_fingerprint, rewritten_query_sha256,
               subquery_count, retrieval_rounds, context_refs, citations,
               token_budget, input_tokens, output_tokens, node_path,
               timings_ms, error_codes, created_at
          FROM rag_generation_traces
         WHERE request_id = ANY(:request_ids)
        """
    )
    async with engine.connect() as connection:
        rows = (await connection.execute(query, {"request_ids": request_ids})).mappings().all()
        columns = {
            str(row[0])
            for row in (
                await connection.execute(
                    text(
                        "SELECT column_name FROM information_schema.columns "
                        "WHERE table_name = 'rag_generation_traces'"
                    )
                )
            ).all()
        }
    forbidden_raw_columns = {
        "answer",
        "chain_of_thought",
        "context_text",
        "prompt",
        "question",
        "reasoning",
        "rewritten_query",
    }
    redacted_schema = not columns.intersection(forbidden_raw_columns)
    summaries: dict[str, dict[str, object]] = {}
    for row in rows:
        summaries[str(row["request_id"])] = {
            "mode": row["mode"],
            "outcome": row["outcome"],
            "question_sha256": row["question_sha256"],
            "answer_sha256": row["answer_sha256"],
            "model": row["model"],
            "model_version": row["model_version"],
            "index_fingerprint": row["index_fingerprint"],
            "retrieval_policy_fingerprint": row["retrieval_policy_fingerprint"],
            "context_ref_count": len(row["context_refs"]),
            "citation_count": len(row["citations"]),
            "token_budget_present": row["token_budget"] is not None,
            "error_codes": row["error_codes"],
            "created_at": row["created_at"].isoformat(),
        }
    return summaries, redacted_schema


def _valid_citations(result: CaseResult) -> bool:
    allowed = {reference.citation_id for reference in result.trace.context_refs}
    trace_ids = {citation.citation_id for citation in result.trace.citations}
    event_ids = {
        str(event.data["citation_id"])
        for event in result.events
        if event.event_type is RagEventType.CITATION
    }
    return bool(trace_ids) and trace_ids == event_ids and trace_ids.issubset(allowed)


def _source_match(result: CaseResult) -> bool:
    expected = set(result.case.expected_source_names)
    return bool(expected.intersection(citation.source_name for citation in result.trace.citations))


def _budget_safe(result: CaseResult) -> bool:
    budget = result.trace.token_budget
    return budget is not None and (
        budget.prompt_tokens + budget.output_reserved_tokens + budget.safety_reserved_tokens
        <= budget.context_window_tokens
        and budget.context_tokens
        <= (FAST_POLICY if result.mode is RagMode.FAST else REASONING_POLICY).context_token_cap
    )


async def run(args: argparse.Namespace) -> dict[str, object]:
    binding = load_winner_binding(args.phase5_decision, args.phase5_activation_receipt)
    observed_gold_sha256 = verify_gold_binding(args.gold, binding.gold_sha256)
    answerable_case, unanswerable_case = load_live_cases(args.gold)
    tokenizer = ExactHuggingFaceTokenCounter(
        tokenizer_path=args.tokenizer_path,
        tokenizer_id=SELECTED_NIM_LLM_MODEL,
        expected_sha256=args.tokenizer_sha256,
    )
    database_url = os.getenv(args.database_url_env)
    if database_url is None or not database_url.strip():
        raise WinnerE2EError(
            f"required database URL environment variable is missing: {args.database_url_env}"
        )
    engine = create_async_engine(_async_database_url(database_url), pool_pre_ping=True)
    embedding_url = _service_url(args.embedding_base_url, "embedding base URL", require_v1=True)
    llm_url = _service_url(args.llm_base_url, "LLM base URL", require_v1=True)
    qdrant_url = _service_url(args.qdrant_url, "Qdrant URL", require_v1=False)
    advertised_embedding_ids, advertised_llm_ids = await asyncio.gather(
        _advertised_model_ids(embedding_url, "embedding NIM"),
        _advertised_model_ids(llm_url, "LLM NIM"),
    )
    embedding = NimEmbeddingClient(
        api_base_url=embedding_url,
        model=EMBEDDING_MODEL,
        model_version=EMBEDDING_MODEL_VERSION,
        expected_dimension=EMBEDDING_DIMENSION,
        timeout_seconds=args.timeout_seconds,
        max_retries=0,
    )
    nim_llm = NimLlmClient(
        api_base_url=llm_url,
        model=SELECTED_NIM_LLM_MODEL,
        model_version=SELECTED_NIM_LLM_MODEL_VERSION,
        timeout_seconds=args.timeout_seconds,
        max_retries=0,
    )
    llm = CountingLlm(nim_llm)
    qdrant = QdrantVectorIndex(
        base_url=qdrant_url,
        timeout_seconds=args.timeout_seconds,
        hnsw_ef=binding.policy.hnsw_ef,
    )
    capture = DurableCaptureTraceStore(
        durable=PostgresGenerationTraceStore(engine),
        traces=[],
    )
    retriever = DenseRetriever(
        embedding=embedding,
        vector_index=qdrant,
        collection_target=ACTIVE_ALIAS,
    )
    graph = GroundedRagGraph(
        llm=llm,
        retriever=retriever,
        planner=LlmQueryPlanner(llm),
        token_counter=tokenizer,
        trace_store=capture,
        index_config=binding.config,
        retrieval_policy=binding.policy,
    )
    conversation_id = uuid4()
    try:
        owner_acl_result = await retriever.retrieve(
            query=answerable_case.query,
            scope=AccessScope(args.tenant_id, (f"user:{args.user_id}",)),
            config=binding.config,
            retrieval_policy=binding.policy,
        )
        unrelated_user_id = uuid4()
        while unrelated_user_id == args.user_id:
            unrelated_user_id = uuid4()
        unrelated_acl_result = await retriever.retrieve(
            query=answerable_case.query,
            scope=AccessScope(args.tenant_id, (f"user:{unrelated_user_id}",)),
            config=binding.config,
            retrieval_policy=binding.policy,
        )
        fast = await _run_case(
            graph=graph,
            trace_store=capture,
            llm=llm,
            case=answerable_case,
            mode=RagMode.FAST,
            tenant_id=args.tenant_id,
            user_id=args.user_id,
            conversation_id=conversation_id,
        )
        reasoning = await _run_case(
            graph=graph,
            trace_store=capture,
            llm=llm,
            case=answerable_case,
            mode=RagMode.REASONING,
            tenant_id=args.tenant_id,
            user_id=args.user_id,
            conversation_id=conversation_id,
        )
        unanswerable = await _run_case(
            graph=graph,
            trace_store=capture,
            llm=llm,
            case=unanswerable_case,
            mode=RagMode.FAST,
            tenant_id=args.tenant_id,
            user_id=args.user_id,
            conversation_id=conversation_id,
        )
        readback, redacted_schema = await _trace_readback(engine, capture.traces)
    finally:
        await llm.aclose()
        await embedding.aclose()
        await qdrant.aclose()
        await engine.dispose()

    results = (fast, reasoning, unanswerable)
    answered = (fast, reasoning)
    fast_retrieval = fast.retrieval_summary()
    reasoning_retrieval = reasoning.retrieval_summary()
    readback_bound = len(readback) == 3 and all(
        row["index_fingerprint"] == binding.config.fingerprint
        and row["retrieval_policy_fingerprint"] == binding.policy.fingerprint
        for row in readback.values()
    )
    owner_sources = {ranked.hit.payload.source_name for ranked in owner_acl_result.hits}
    checks = {
        "embedding_models_endpoint_exact": advertised_embedding_ids == (EMBEDDING_MODEL,),
        "llm_models_endpoint_exact": advertised_llm_ids == (SELECTED_NIM_LLM_MODEL,),
        "active_alias_owner_scope_retrieves": bool(owner_acl_result.hits)
        and bool(set(answerable_case.expected_source_names).intersection(owner_sources))
        and owner_acl_result.retrieval_policy_fingerprint == binding.policy.fingerprint,
        "active_alias_unrelated_scope_is_empty": not unrelated_acl_result.hits
        and unrelated_acl_result.retrieval_policy_fingerprint == binding.policy.fingerprint,
        "same_question_exercised_in_both_modes": fast.trace.question_sha256
        == reasoning.trace.question_sha256,
        "fast_and_reasoning_answered": all(
            result.trace.outcome is TraceOutcome.ANSWERED for result in answered
        ),
        "answer_citations_are_server_issued": all(_valid_citations(result) for result in answered),
        "answer_cites_expected_phase4_source": all(_source_match(result) for result in answered),
        "no_fabricated_citation": all(_valid_citations(result) for result in answered)
        and unanswerable.trace.citations == (),
        "unanswerable_refused_without_generation": unanswerable.trace.outcome
        is TraceOutcome.INSUFFICIENT_EVIDENCE
        and not unanswerable.trace.context_refs
        and unanswerable.llm_stream_calls == 0,
        "mode_token_budgets_differ": fast.trace.token_budget is not None
        and reasoning.trace.token_budget is not None
        and fast.trace.token_budget.output_reserved_tokens
        != reasoning.trace.token_budget.output_reserved_tokens,
        "mode_retrieval_budgets_distinct_and_bounded": (
            FAST_POLICY.max_subqueries,
            FAST_POLICY.max_dense_candidates,
            FAST_POLICY.final_context_limit,
        )
        != (
            REASONING_POLICY.max_subqueries,
            REASONING_POLICY.max_dense_candidates,
            REASONING_POLICY.final_context_limit,
        )
        and 1 <= fast.trace.subquery_count <= FAST_POLICY.max_subqueries
        and 1 <= reasoning.trace.subquery_count <= REASONING_POLICY.max_subqueries
        and fast_retrieval is not None
        and reasoning_retrieval is not None
        and fast_retrieval["candidate_count"]
        <= min(
            binding.policy.dense_candidate_limit,
            FAST_POLICY.candidate_limit_per_query,
        )
        * fast.trace.subquery_count
        and reasoning_retrieval["candidate_count"]
        <= min(
            binding.policy.dense_candidate_limit,
            REASONING_POLICY.candidate_limit_per_query,
        )
        * reasoning.trace.subquery_count
        and fast_retrieval["candidate_count"] <= FAST_POLICY.max_dense_candidates
        and reasoning_retrieval["candidate_count"] <= REASONING_POLICY.max_dense_candidates
        and len(fast.trace.context_refs) <= FAST_POLICY.final_context_limit
        and len(reasoning.trace.context_refs) <= REASONING_POLICY.final_context_limit,
        "mode_live_latencies_differ": abs(fast.elapsed_seconds - reasoning.elapsed_seconds) > 0.001,
        "context_never_exceeds_budget": all(_budget_safe(result) for result in results),
        "nim_usage_matches_exact_tokenizer": all(
            result.trace.token_budget is not None
            and result.trace.input_tokens == result.trace.token_budget.prompt_tokens
            for result in answered
        ),
        "client_received_no_chain_of_thought": all(
            not _HIDDEN_REASONING.search(result.visible_answer) for result in results
        ),
        "hidden_reasoning_field_absent_from_events": all(
            "reasoning_content" not in event.data for result in results for event in result.events
        ),
        "visible_answer_hashes_match_traces": all(
            sha256_text(result.visible_answer) == result.trace.answer_sha256 for result in results
        ),
        "nemotron_identity_exact": all(
            result.trace.model == SELECTED_NIM_LLM_MODEL
            and result.trace.model_version == SELECTED_NIM_LLM_MODEL_VERSION
            for result in answered
        ),
        "selected_index_and_policy_bound_in_memory": all(
            result.trace.index_fingerprint == binding.config.fingerprint
            and result.trace.retrieval_policy_fingerprint == binding.policy.fingerprint
            for result in results
        ),
        "postgres_trace_readback_bound": readback_bound,
        "postgres_trace_schema_redacts_content": redacted_schema,
        "event_sequences_contiguous": all(
            [event.sequence for event in result.events] == list(range(1, len(result.events) + 1))
            for result in results
        ),
    }
    root = Path(__file__).resolve().parents[1]
    provenance = {
        relative: _sha256_bytes((root / relative).read_bytes()) for relative in _PROVENANCE
    }
    return {
        "schema_version": 1,
        "scope": "phase6-live-winner-e2e-no-phase7-surface",
        "created_at": datetime.now(UTC).isoformat(),
        "status": "PASS" if all(checks.values()) else "FAIL",
        "winner_binding": {
            "phase5_run_id": binding.phase5_run_id,
            "phase5_decision_sha256": binding.decision_sha256,
            "phase5_activation_receipt_sha256": binding.receipt_sha256,
            "active_alias": ACTIVE_ALIAS,
            "physical_collection": binding.config.collection_name,
            "expected_point_count": binding.expected_point_count,
            "index_config": {**asdict(binding.config), "fingerprint": binding.config.fingerprint},
            "retrieval_policy": {
                **asdict(binding.policy),
                "fingerprint": binding.policy.fingerprint,
            },
        },
        "model_binding": {
            "llm_model": SELECTED_NIM_LLM_MODEL,
            "llm_model_version": SELECTED_NIM_LLM_MODEL_VERSION,
            "embedding_model": EMBEDDING_MODEL,
            "embedding_model_version": EMBEDDING_MODEL_VERSION,
            "embedding_dimension": EMBEDDING_DIMENSION,
            "tokenizer_id": tokenizer.tokenizer_id,
            "tokenizer_sha256": tokenizer.tokenizer_sha256,
            "exact_tokenizer": tokenizer.exact,
            "embedding_models_endpoint_ids": list(advertised_embedding_ids),
            "llm_models_endpoint_ids": list(advertised_llm_ids),
        },
        "prompt_binding": {
            "prompt_version": PROMPT_VERSION,
            "prompt_sha256": PROMPT_SHA256,
            "graph_version": GRAPH_VERSION,
            "fast_reasoning_control": FAST_POLICY.reasoning_control.system_signal,
            "reasoning_reasoning_control": REASONING_POLICY.reasoning_control.system_signal,
        },
        "mode_policy_binding": {
            "approved_base_dense_candidate_limit": binding.policy.dense_candidate_limit,
            "effective_candidate_limit_formula": "min(approved_base, mode_cap)",
            "effective_candidate_limits": {
                "fast": min(
                    binding.policy.dense_candidate_limit,
                    FAST_POLICY.candidate_limit_per_query,
                ),
                "reasoning": min(
                    binding.policy.dense_candidate_limit,
                    REASONING_POLICY.candidate_limit_per_query,
                ),
            },
            "fast": asdict(FAST_POLICY),
            "reasoning": asdict(REASONING_POLICY),
        },
        "gold_binding": {
            "gold_sha256": observed_gold_sha256,
            "matches_phase5_decision": observed_gold_sha256 == binding.gold_sha256,
            "answerable_case_id": answerable_case.case_id,
            "unanswerable_case_id": unanswerable_case.case_id,
            "questions_recorded": False,
        },
        "results": {
            "fast": fast.report_dict(),
            "reasoning": reasoning.report_dict(),
            "unanswerable": unanswerable.report_dict(),
        },
        "active_alias_acl_evidence": {
            "owner_hit_count": len(owner_acl_result.hits),
            "owner_expected_source_retrieved": bool(
                set(answerable_case.expected_source_names).intersection(owner_sources)
            ),
            "unrelated_user_hit_count": len(unrelated_acl_result.hits),
            "query_sha256": sha256_text(answerable_case.query),
            "query_recorded": False,
            "unrelated_principal_recorded": False,
        },
        "postgres_readback": readback,
        "checks": checks,
        "acceptance_pass": all(checks.values()),
        "source_provenance": provenance,
        "source_provenance_sha256": hashlib.sha256(
            json.dumps(provenance, separators=(",", ":"), sort_keys=True).encode()
        ).hexdigest(),
        "security": {
            "database_url_recorded": False,
            "service_credentials_recorded": False,
            "questions_recorded": False,
            "answers_recorded": False,
            "prompts_recorded": False,
            "document_text_recorded": False,
            "chain_of_thought_recorded": False,
            "raw_event_payloads_recorded": False,
        },
    }


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--phase5-decision", required=True, type=Path)
    parser.add_argument("--phase5-activation-receipt", required=True, type=Path)
    parser.add_argument("--gold", required=True, type=Path)
    parser.add_argument("--qdrant-url", required=True)
    parser.add_argument("--embedding-base-url", required=True)
    parser.add_argument("--llm-base-url", required=True)
    parser.add_argument("--tenant-id", required=True, type=UUID)
    parser.add_argument("--user-id", required=True, type=UUID)
    parser.add_argument("--tokenizer-path", required=True, type=Path)
    parser.add_argument("--tokenizer-sha256", required=True)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--database-url-env", default="PHASE6_DATABASE_URL")
    parser.add_argument("--timeout-seconds", default=300.0, type=float)
    return parser.parse_args(argv)


def main() -> int:
    args = parse_args()
    if not re.fullmatch(r"[A-Z_][A-Z0-9_]*", args.database_url_env):
        raise SystemExit("database URL environment variable name is invalid")
    if not _SHA256.fullmatch(args.tokenizer_sha256):
        raise SystemExit("tokenizer SHA-256 must be a lowercase digest")
    output_dir = args.output_dir.resolve()
    try:
        output_dir.mkdir(parents=True, exist_ok=False)
    except FileExistsError:
        raise SystemExit("refusing to reuse an existing Phase 6 evidence directory") from None
    try:
        report = asyncio.run(run(args))
        report_bytes = (
            json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
        ).encode()
        with (output_dir / "report.json").open("xb") as target:
            target.write(report_bytes)
        with (output_dir / "report.sha256").open("x", encoding="ascii") as target:
            target.write(_sha256_bytes(report_bytes) + "  report.json\n")
    except WinnerE2EError as error:
        raise SystemExit(str(error)) from None
    return 0 if report["acceptance_pass"] else 3


if __name__ == "__main__":
    raise SystemExit(main())

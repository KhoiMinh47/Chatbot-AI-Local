#!/usr/bin/env python3
"""Run a non-production Phase 6 direct-evidence candidate against one live NIM."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
from collections.abc import AsyncIterator
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter
from typing import Any
from uuid import UUID

from app.application.ai_clients import (
    ChatRequest,
    ChatResponse,
    ChatStreamChunk,
    LlmClient,
)
from app.application.rag import GRAPH_VERSION, PROMPT_SHA256, PROMPT_VERSION
from app.application.retrieval import RetrievalResult
from app.domain.rag import (
    FAST_POLICY,
    REASONING_POLICY,
    ConversationTurn,
    GenerationTrace,
    RagEvent,
    RagMode,
    RagRequest,
)
from app.domain.retrieval import (
    ChunkPayload,
    IndexConfig,
    RankedHit,
    RetrievalPolicy,
    SearchHit,
)
from app.infrastructure.exact_token_counter import ExactHuggingFaceTokenCounter
from app.infrastructure.nim_clients import NimLlmClient
from app.rag.graph import GroundedRagGraph

TENANT_ID = UUID("00000000-0000-4000-8000-000000000601")
USER_ID = UUID("00000000-0000-4000-8000-000000000602")
DOCUMENT_ID = UUID("00000000-0000-4000-8000-000000000603")
VERSION_ID = UUID("00000000-0000-4000-8000-000000000604")
CHUNK_ID = UUID("00000000-0000-4000-8000-000000000605")
CONVERSATION_ID = UUID("00000000-0000-4000-8000-000000000606")
ANSWERABLE_QUESTION = "Nhân viên toàn thời gian có bao nhiêu ngày phép năm?"
UNANSWERABLE_QUESTION = "Ai là CEO của công ty vào năm 2035?"
SOURCE_TEXT = (
    "Chính sách nghỉ phép quy định nhân viên toàn thời gian có 15 ngày phép năm. "
    "Yêu cầu nghỉ phép cần được gửi trước ít nhất 3 ngày làm việc."
)
ROOT = Path(__file__).resolve().parents[1]
PROVENANCE_FILES = (
    "apps/api/app/domain/rag.py",
    "apps/api/app/application/rag.py",
    "apps/api/app/rag/graph.py",
    "apps/api/app/infrastructure/exact_token_counter.py",
    "apps/api/app/infrastructure/nim_clients.py",
    "scripts/phase6_candidate_eval.py",
    "uv.lock",
)


@dataclass(slots=True)
class MemoryTraceStore:
    traces: list[GenerationTrace]

    async def save(self, trace: GenerationTrace) -> None:
        if any(existing.request_id == trace.request_id for existing in self.traces):
            raise RuntimeError("duplicate candidate trace")
        self.traces.append(trace)


class StaticPlanner:
    async def rewrite_followup(
        self,
        *,
        question: str,
        recent_messages: tuple[ConversationTurn, ...],
        language: str,
    ) -> str:
        del recent_messages, language
        return question

    async def decompose(
        self,
        *,
        query: str,
        language: str,
        max_subqueries: int,
    ) -> tuple[str, ...]:
        del language
        return (
            query,
            "quy định số ngày phép năm cho nhân viên toàn thời gian",
            "chính sách nghỉ phép hằng năm",
        )[:max_subqueries]


class StaticEvidenceRetriever:
    def __init__(self, *, evidence_available: bool) -> None:
        self.evidence_available = evidence_available
        self.calls = 0

    async def retrieve(self, **kwargs: Any) -> RetrievalResult:
        self.calls += 1
        policy = kwargs["retrieval_policy"]
        if not isinstance(policy, RetrievalPolicy):
            raise RuntimeError("candidate retriever requires a retrieval policy")
        if not self.evidence_available:
            return RetrievalResult(
                hits=(),
                dense_candidates=0,
                embedding_model="candidate-static-evidence",
                embedding_model_version="phase6-v1",
                retrieval_policy_fingerprint=policy.fingerprint,
            )
        scope = kwargs["scope"]
        payload = ChunkPayload(
            tenant_id=TENANT_ID,
            document_id=DOCUMENT_ID,
            version_id=VERSION_ID,
            chunk_id=CHUNK_ID,
            parent_id=None,
            owner_id=USER_ID,
            acl_principals=(f"user:{USER_ID}",),
            source_name="phase6-synthetic-leave-policy.txt",
            mime_type="text/plain",
            page=1,
            slide=None,
            section_path=("Chính sách nghỉ phép",),
            language="vi",
            text=SOURCE_TEXT,
            token_count=40,
            content_hash=hashlib.sha256(SOURCE_TEXT.encode()).hexdigest(),
            index_version="phase6-candidate-v1",
            created_at=datetime(2026, 7, 15, tzinfo=UTC),
        )
        if scope.tenant_id != TENANT_ID:
            raise RuntimeError("candidate tenant scope mismatch")
        hit = SearchHit(point_id=CHUNK_ID, score=0.99, payload=payload)
        return RetrievalResult(
            hits=(RankedHit(hit=hit, dense_rank=1, final_rank=1),),
            dense_candidates=1,
            embedding_model="candidate-static-evidence",
            embedding_model_version="phase6-v1",
            retrieval_policy_fingerprint=policy.fingerprint,
        )


class CountingLlmClient:
    def __init__(self, inner: LlmClient) -> None:
        self.inner = inner
        self.chat_calls = 0
        self.stream_calls = 0

    async def chat(self, request: ChatRequest) -> ChatResponse:
        self.chat_calls += 1
        return await self.inner.chat(request)

    def stream(self, request: ChatRequest) -> AsyncIterator[ChatStreamChunk]:
        self.stream_calls += 1
        return self.inner.stream(request)

    async def aclose(self) -> None:
        await self.inner.aclose()


def candidate_index() -> IndexConfig:
    return IndexConfig(
        collection_name="phase6_candidate_static",
        index_version="phase6-candidate-v1",
        embedding_model="candidate-static-evidence",
        embedding_model_version="phase6-v1",
        vector_dimension=1,
        chunk_size=256,
        overlap_percent=10,
    )


def candidate_retrieval_policy() -> RetrievalPolicy:
    return RetrievalPolicy(
        index_config_fingerprint=candidate_index().fingerprint,
        dense_candidate_limit=20,
        final_limit=10,
        dense_threshold=0.5,
        hnsw_ef=128,
        reranker_enabled=False,
    )


async def collect(graph: GroundedRagGraph, request: RagRequest) -> tuple[list[RagEvent], float]:
    started = perf_counter()
    events = [event async for event in graph.stream(request)]
    return events, perf_counter() - started


def make_request(*, mode: RagMode, question: str, request_id: UUID) -> RagRequest:
    return RagRequest(
        request_id=request_id,
        user_id=USER_ID,
        tenant_id=TENANT_ID,
        conversation_id=CONVERSATION_ID,
        mode=mode,
        question=question,
        language="vi",
        acl_principals=(f"user:{USER_ID}",),
    )


def summarize(
    *, events: list[RagEvent], elapsed_seconds: float, trace: GenerationTrace
) -> dict[str, Any]:
    answer = "".join(
        str(event.data["text"]) for event in events if event.event_type.value == "token"
    )
    return {
        "elapsed_seconds": elapsed_seconds,
        "event_types": [event.event_type.value for event in events],
        "sequence_contiguous": [event.sequence for event in events]
        == list(range(1, len(events) + 1)),
        "outcome": trace.outcome.value,
        "answer": answer,
        "answer_sha256": trace.answer_sha256,
        "citations": [citation.citation_id for citation in trace.citations],
        "subquery_count": trace.subquery_count,
        "retrieval_rounds": trace.retrieval_rounds,
        "budget": asdict(trace.token_budget) if trace.token_budget is not None else None,
        "input_tokens": trace.input_tokens,
        "output_tokens": trace.output_tokens,
        "model": trace.model,
        "model_version": trace.model_version,
        "node_path": list(trace.node_path),
        "error_codes": list(trace.error_codes),
        "contains_hidden_reasoning_marker": any(
            marker in answer.lower() for marker in ("<think", "<analysis", "reasoning:")
        ),
    }


async def run(args: argparse.Namespace) -> dict[str, Any]:
    tokenizer_path = Path(args.tokenizer_path)
    counter = ExactHuggingFaceTokenCounter(
        tokenizer_path=tokenizer_path,
        tokenizer_id=args.tokenizer_id,
        expected_sha256=args.tokenizer_sha256,
    )
    nim = NimLlmClient(
        api_base_url=args.base_url,
        model=args.model,
        model_version=args.model_version,
        timeout_seconds=args.timeout_seconds,
        max_retries=0,
    )
    llm = CountingLlmClient(nim)
    results: dict[str, Any] = {}
    try:
        for ordinal, mode in enumerate((RagMode.FAST, RagMode.REASONING), start=1):
            store = MemoryTraceStore(traces=[])
            retriever = StaticEvidenceRetriever(evidence_available=True)
            graph = GroundedRagGraph(
                llm=llm,
                retriever=retriever,
                planner=StaticPlanner(),
                token_counter=counter,
                trace_store=store,
                index_config=candidate_index(),
                retrieval_policy=candidate_retrieval_policy(),
            )
            request = make_request(
                mode=mode,
                question=ANSWERABLE_QUESTION,
                request_id=UUID(f"00000000-0000-4000-8000-00000000061{ordinal}"),
            )
            events, elapsed = await collect(graph, request)
            results[mode.value] = summarize(
                events=events,
                elapsed_seconds=elapsed,
                trace=store.traces[0],
            )
            results[mode.value]["retriever_calls"] = retriever.calls

        refusal_store = MemoryTraceStore(traces=[])
        refusal_retriever = StaticEvidenceRetriever(evidence_available=False)
        refusal_graph = GroundedRagGraph(
            llm=llm,
            retriever=refusal_retriever,
            planner=StaticPlanner(),
            token_counter=counter,
            trace_store=refusal_store,
            index_config=candidate_index(),
            retrieval_policy=candidate_retrieval_policy(),
        )
        refusal_events, refusal_elapsed = await collect(
            refusal_graph,
            make_request(
                mode=RagMode.FAST,
                question=UNANSWERABLE_QUESTION,
                request_id=UUID("00000000-0000-4000-8000-000000000619"),
            ),
        )
        results["unanswerable"] = summarize(
            events=refusal_events,
            elapsed_seconds=refusal_elapsed,
            trace=refusal_store.traces[0],
        )
    finally:
        await llm.aclose()

    fast = results["fast"]
    reasoning = results["reasoning"]
    refusal = results["unanswerable"]
    checks = {
        "fast_answered_with_valid_s1": fast["outcome"] == "answered"
        and fast["citations"] == ["S1"]
        and "15" in fast["answer"],
        "reasoning_answered_with_valid_s1": reasoning["outcome"] == "answered"
        and reasoning["citations"] == ["S1"]
        and "15" in reasoning["answer"],
        "mode_budget_differs": fast["budget"]["output_reserved_tokens"]
        != reasoning["budget"]["output_reserved_tokens"],
        "mode_retrieval_differs": fast["retriever_calls"] == 1
        and reasoning["retriever_calls"] == 3,
        "context_never_overflows": all(
            item["budget"]["prompt_tokens"]
            + item["budget"]["output_reserved_tokens"]
            + item["budget"]["safety_reserved_tokens"]
            <= item["budget"]["context_window_tokens"]
            for item in (fast, reasoning, refusal)
        ),
        "nim_prompt_usage_matches_exact_counter": all(
            item["input_tokens"] == item["budget"]["prompt_tokens"] for item in (fast, reasoning)
        ),
        "no_hidden_reasoning": not fast["contains_hidden_reasoning_marker"]
        and not reasoning["contains_hidden_reasoning_marker"],
        "unanswerable_refused_without_llm": refusal["outcome"] == "insufficient_evidence"
        and refusal["citations"] == []
        and llm.stream_calls == 2,
        "event_sequences_contiguous": all(
            item["sequence_contiguous"] for item in (fast, reasoning, refusal)
        ),
    }
    index = candidate_index()
    return {
        "schema_version": 1,
        "scope": "phase6-live-direct-evidence-candidate-not-production-acceptance",
        "created_at": datetime.now(UTC).isoformat(),
        "model": args.model,
        "model_version": args.model_version,
        "runtime_image": args.runtime_image,
        "runtime_arm64_digest": args.runtime_arm64_digest,
        "tokenizer_id": counter.tokenizer_id,
        "tokenizer_sha256": counter.tokenizer_sha256,
        "exact_tokenizer": counter.exact,
        "prompt_version": PROMPT_VERSION,
        "prompt_sha256": PROMPT_SHA256,
        "graph_version": GRAPH_VERSION,
        "index_config": {**asdict(index), "fingerprint": index.fingerprint},
        "retrieval_policy": {
            **asdict(candidate_retrieval_policy()),
            "fingerprint": candidate_retrieval_policy().fingerprint,
        },
        "source_sha256": {
            relative: hashlib.sha256((ROOT / relative).read_bytes()).hexdigest()
            for relative in PROVENANCE_FILES
        },
        "policies": {
            "fast": asdict(FAST_POLICY),
            "reasoning": asdict(REASONING_POLICY),
        },
        "questions": {
            "answerable": ANSWERABLE_QUESTION,
            "unanswerable": UNANSWERABLE_QUESTION,
        },
        "results": results,
        "llm_calls": {"chat": llm.chat_calls, "stream": llm.stream_calls},
        "checks": checks,
        "candidate_pass": all(checks.values()),
        "limitations": [
            "Direct synthetic evidence bypasses Phase 4 ingestion and Phase 5 vector retrieval.",
            "The LLM and index are candidates, not approved winners or active production aliases.",
            "This three-case smoke is not the required full human-reviewed generation set.",
        ],
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--model-version", required=True)
    parser.add_argument("--runtime-image", required=True)
    parser.add_argument("--runtime-arm64-digest", required=True)
    parser.add_argument("--tokenizer-path", required=True)
    parser.add_argument("--tokenizer-id", required=True)
    parser.add_argument("--tokenizer-sha256", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--timeout-seconds", type=float, default=180.0)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.output.exists():
        raise SystemExit("refusing to overwrite an existing candidate report")
    report = asyncio.run(run(args))
    args.output.parent.mkdir(parents=True, exist_ok=False)
    args.output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return 0 if report["candidate_pass"] else 3


if __name__ == "__main__":
    raise SystemExit(main())

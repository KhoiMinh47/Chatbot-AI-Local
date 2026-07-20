"""PostgreSQL adapter for append-only, redacted Phase 6 generation traces."""

from __future__ import annotations

import json
from dataclasses import asdict
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from app.domain.rag import GenerationTrace

_INSERT = text(
    """
    INSERT INTO rag_generation_traces (
        request_id, user_id, tenant_id, conversation_id, mode, outcome,
        prompt_version, prompt_sha256, graph_version, question_sha256, answer_sha256,
        model, model_version, index_fingerprint, retrieval_policy_fingerprint,
        rewritten_query_sha256,
        subquery_count, retrieval_rounds, context_refs, citations, token_budget,
        input_tokens, output_tokens, node_path, timings_ms, error_codes, created_at
    ) VALUES (
        :request_id, :user_id, :tenant_id, :conversation_id, :mode, :outcome,
        :prompt_version, :prompt_sha256, :graph_version, :question_sha256, :answer_sha256,
        :model, :model_version, :index_fingerprint, :retrieval_policy_fingerprint,
        :rewritten_query_sha256,
        :subquery_count, :retrieval_rounds, CAST(:context_refs AS JSONB),
        CAST(:citations AS JSONB), CAST(:token_budget AS JSONB), :input_tokens,
        :output_tokens, CAST(:node_path AS JSONB), CAST(:timings_ms AS JSONB),
        CAST(:error_codes AS JSONB), :created_at
    )
    """
)


class PostgresGenerationTraceStore:
    """Insert one trace by request ID; duplicate requests fail closed."""

    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

    async def save(self, trace: GenerationTrace) -> None:
        parameters: dict[str, Any] = {
            "request_id": trace.request_id,
            "user_id": trace.user_id,
            "tenant_id": trace.tenant_id,
            "conversation_id": trace.conversation_id,
            "mode": trace.mode.value,
            "outcome": trace.outcome.value,
            "prompt_version": trace.prompt_version,
            "prompt_sha256": trace.prompt_sha256,
            "graph_version": trace.graph_version,
            "question_sha256": trace.question_sha256,
            "answer_sha256": trace.answer_sha256,
            "model": trace.model,
            "model_version": trace.model_version,
            "index_fingerprint": trace.index_fingerprint,
            "retrieval_policy_fingerprint": trace.retrieval_policy_fingerprint,
            "rewritten_query_sha256": trace.rewritten_query_sha256,
            "subquery_count": trace.subquery_count,
            "retrieval_rounds": trace.retrieval_rounds,
            "context_refs": self._json(
                [
                    {
                        **asdict(reference),
                        "document_id": str(reference.document_id),
                        "chunk_id": str(reference.chunk_id),
                    }
                    for reference in trace.context_refs
                ]
            ),
            "citations": self._json(
                [
                    {
                        **asdict(citation),
                        "document_id": str(citation.document_id),
                        "version_id": str(citation.version_id),
                        "chunk_id": str(citation.chunk_id),
                    }
                    for citation in trace.citations
                ]
            ),
            "token_budget": (
                self._json(asdict(trace.token_budget)) if trace.token_budget is not None else None
            ),
            "input_tokens": trace.input_tokens,
            "output_tokens": trace.output_tokens,
            "node_path": self._json(list(trace.node_path)),
            "timings_ms": self._json(dict(trace.timings_ms)),
            "error_codes": self._json(list(trace.error_codes)),
            "created_at": trace.created_at,
        }
        async with self._engine.begin() as connection:
            await connection.execute(_INSERT, parameters)

    @staticmethod
    def _json(value: object) -> str:
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)

"""Opt-in PostgreSQL readback evidence for the Phase 6 trace adapter."""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from app.domain.rag import GenerationTrace, RagMode, TokenBudget, TraceOutcome, sha256_text
from app.infrastructure.generation_trace_store import PostgresGenerationTraceStore
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import create_async_engine


@pytest.mark.anyio
@pytest.mark.integration
async def test_phase6_trace_is_durable_redacted_and_exactly_once() -> None:
    database_url = os.getenv("PHASE6_DATABASE_URL")
    if not database_url:
        pytest.skip("set PHASE6_DATABASE_URL to run the Phase 6 PostgreSQL integration test")

    request_id = uuid4()
    trace = GenerationTrace(
        request_id=request_id,
        user_id=uuid4(),
        tenant_id=uuid4(),
        conversation_id=uuid4(),
        mode=RagMode.FAST,
        outcome=TraceOutcome.ANSWERED,
        prompt_version="test-prompt-v1",
        prompt_sha256=sha256_text("SYSTEM_SECRET_SENTINEL"),
        graph_version="test-graph-v1",
        question_sha256=sha256_text("QUESTION_SECRET_SENTINEL"),
        answer_sha256=sha256_text("ANSWER_SECRET_SENTINEL"),
        model="test-model",
        model_version="test-version",
        index_fingerprint=sha256_text("index-config"),
        retrieval_policy_fingerprint=sha256_text("retrieval-policy"),
        rewritten_query_sha256=sha256_text("REWRITTEN_SECRET_SENTINEL"),
        subquery_count=1,
        retrieval_rounds=1,
        context_refs=(),
        citations=(),
        token_budget=TokenBudget(
            tokenizer_id="test-tokenizer",
            tokenizer_sha256=sha256_text("tokenizer"),
            exact=True,
            context_window_tokens=32_768,
            prompt_tokens=100,
            context_tokens=20,
            output_reserved_tokens=768,
            safety_reserved_tokens=1_536,
        ),
        input_tokens=100,
        output_tokens=20,
        node_path=("validate_request", "persist_message_and_trace"),
        timings_ms={"validate_request": 1.0},
        created_at=datetime.now(UTC),
    )
    engine = create_async_engine(database_url, pool_pre_ping=True)
    store = PostgresGenerationTraceStore(engine)
    try:
        await store.save(trace)
        async with engine.connect() as connection:
            row = (
                (
                    await connection.execute(
                        text(
                            "SELECT mode, outcome, question_sha256, answer_sha256, "
                            "retrieval_policy_fingerprint, context_refs, citations, "
                            "token_budget, node_path, error_codes "
                            "FROM rag_generation_traces WHERE request_id = :request_id"
                        ),
                        {"request_id": request_id},
                    )
                )
                .mappings()
                .one()
            )
        assert row["mode"] == "fast"
        assert row["outcome"] == "answered"
        assert row["retrieval_policy_fingerprint"] == sha256_text("retrieval-policy")
        assert row["question_sha256"] == sha256_text("QUESTION_SECRET_SENTINEL")
        serialized = json.dumps(dict(row), default=str, ensure_ascii=False)
        assert "SECRET_SENTINEL" not in serialized
        with pytest.raises(IntegrityError):
            await store.save(trace)
    finally:
        async with engine.begin() as connection:
            await connection.execute(
                text("DELETE FROM rag_generation_traces WHERE request_id = :request_id"),
                {"request_id": request_id},
            )
        await engine.dispose()

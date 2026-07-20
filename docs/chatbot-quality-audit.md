# Chatbot quality audit

Audit date: 2026-07-17. Scope: source tree, current Compose configuration, live
container health, PostgreSQL RAG/ingestion traces, Qdrant collection state and the
existing CPU test suite. Private message/document content was not inspected.

## Executive result

The selected generator is the correct local-engineering winner,
`nvidia/nemotron-nano-9b-v2` served by NVIDIA NIM 1.0.0. The largest observed quality
problems are currently system-layer problems rather than proof that the model must be
replaced: conversation memory is not working live, the retrieval policy has drifted,
the reranker is disabled, token counting has had an approximate fallback, and model
deltas are buffered until generation completes.

## Inventory

| Component | Current technology | Main files/config | Evidence/problem | Direction |
|---|---|---|---|---|
| Frontend chat | Next.js 16, React 19, custom SSE reader | `apps/web/app/components/use-chat.ts`, `apps/web/app/lib/api.ts` | Incremental renderer exists; persisted history code is partial | Preserve API compatibility; load authoritative server history |
| Chat API | FastAPI | `apps/api/app/api/conversations.py` | Memory persistence was partially added but live DB/source schemas differ | Reconcile schema; persist before terminal event; token-bound loader |
| Prompt builder | Python domain service | `apps/api/app/application/rag.py` | Grounding/citation is strong but answer policy is very concise | Add versioned response-depth modules |
| Model runtime | NVIDIA NIM, Nemotron Nano 9B v2 | `compose.phase3.yaml`, `infra/compose/phase3.env` | Correct instruct model and 131072 capability; app uses 32768 | Keep model; benchmark profiles before runtime changes |
| Conversation store | PostgreSQL | `application/auth.py`, `infrastructure/auth.py`, migrations | Live: 23 conversations and 0 messages; schema drift | Forward-compatible migration and server-side memory |
| File ingestion | FastAPI + MinIO + RabbitMQ + Celery + Docling | `application/ingestion.py`, worker tasks | Full-file RAM copies; long monolithic task | Bounded streaming and stage telemetry |
| Chunking | Parent 2000 / child 256 / overlap 10% | worker chunker/settings | Structurally aware baseline; not tuned on current corpus | Versioned A/B only |
| Embedding | NIM Embed 300M v2, 2048d | Compose and worker indexing | Correct selected local model | Cache/batch tuning; no model switch without eval |
| Vector/keyword search | Qdrant dense search | `qdrant_store.py`, `retrieval.py` | Dense-only; active alias has 820 points; full scan under threshold | Hybrid experiment behind flag |
| Reranker | NIM adapter available | NIM factory/retrieval | Disabled in runtime | Enable only with endpoint + held-out quality win |
| Citation builder | Server-issued S1 IDs | `application/rag.py`, `rag/graph.py` | Validator exists; live invalid generation is 20% | Keep fail-closed; bounded repair pass later |
| Observability | Generation trace timings, container health | PostgreSQL, Compose | Good node timings; no real browser TTFT or ingestion waterfall | Add redacted correlation/stage metrics |
| Tests/evals | Pytest/Vitest plus historical Phase artifacts | `tests/`, `packages/rag-eval/`, `artifacts/` | 355 pass/6 skip baseline; live schema drift not covered | Add migration/live memory and benchmark tests |

## Verified request trace

1. Browser submits `conversation_id`, question and selected document IDs.
2. API authorizes the conversation.
3. Source contains a recent-turn loader, but no messages exist in the live DB and the
   source repository currently expects columns absent from the live table.
4. Graph classifies follow-up using a simple regex.
5. Reasoning mode may invoke LLM rewrite/decomposition; Fast uses the original query.
6. NIM embedding creates one query vector.
7. Qdrant performs dense search with tenant/user/document filters.
8. Hits are deduplicated and context-packed.
9. Nemotron streams deltas to the backend.
10. Backend buffers all deltas, validates citations, then emits visible chunks.
11. Generation trace is persisted.
12. Endpoint source attempts to persist the assistant message after the terminal event,
    which is vulnerable to client disconnect/cancellation.

## Root causes and evidence

### RC-01: memory is not live

- PostgreSQL snapshot: 23 conversations, 0 messages.
- Live `app.messages` columns are `id, conversation_id, role, content, metadata,
  created_at`; current repository source also queries `user_id`, `content_sha256` and
  `generation_trace_id`.
- Alembic reports revision `0007`, so a new idempotent forward migration is required;
  replaying or rewriting old migrations is unsafe.

### RC-02: perceived streaming latency equals almost full generation latency

`GroundedRagGraph._generate` collects model deltas in memory. Only
`_validate_citations` emits visible tokens. This protects users from unvalidated claims
but prevents true TTFT.

### RC-03: retrieval is not the Phase 5 winner contract end-to-end

Phase 5 selected a calibrated threshold of 0.2300481. Source recently gained settings
for this value, but the running API image predates that change. Reranking remains off,
and selected-document requests remove the dense threshold entirely.

### RC-04: token counting can silently downgrade

An exact, hash-bound Nemotron tokenizer is present with SHA-256
`32bd2509c1acc93dc18bdd0f9a2d9a15e72fd3110f24cfc9ff3fb820f4e20b6b`.
The factory source attempts to load it but falls back to an approximate counter that
reports itself as exact. Quality mode must fail closed or expose a truthful degraded
state rather than silently accepting this fallback.

### RC-05: answer failures are visible in live traces

Of 25 traces: 13 answered, 5 insufficient-evidence, 5 invalid-generation and 2 error.
The five invalid generations contain three `uncited_claim` and two
`missing_citation` failures.

### RC-06: upload/index stability is not closed

- RabbitMQ is unhealthy with `Failed to create dirty io scheduler thread 4, error = 11`.
- Ingestion DB has 9 successful and 7 failed jobs.
- Success duration average is 67.62 s and maximum 551.23 s.
- API and worker each read full file contents; the public/worker cap is 500 MB.

## Baseline

| Metric | Observed baseline | Limitation |
|---|---:|---|
| CPU test gate | 355 passed, 6 skipped | Not a live quality score |
| Answered traces | 13/25 (52%) | User traffic mix, not fixed eval set |
| Invalid generation | 5/25 (20%) | Same limitation |
| RAG core answered p50 | 2522.60 ms | retrieve/planner/generate sum |
| RAG core answered p95 | 9099.76 ms | Not browser total latency |
| Average generate node | 3157.7 ms | Answered Fast traces |
| Average retrieve node | 466.2 ms | Answered Fast traces |
| Ingestion success average | 67.62 s | Mixed file sizes/types |
| Ingestion success max | 551.23 s | Mixed file sizes/types |

The immutable machine-readable snapshot is in
`artifacts/evals/baseline-2026-07-17.json`. A production-like fixed Vietnamese eval
dataset is still required before claiming a final quality gain.

## Files expected to change first

- `migrations/versions/0008_chat_memory_contract.py`
- `apps/api/app/domain/auth.py`
- `apps/api/app/application/auth.py`
- `apps/api/app/infrastructure/auth.py`
- `apps/api/app/api/conversations.py`
- `apps/api/app/infrastructure/rag_factory.py`
- `apps/api/app/core/settings.py`
- `apps/api/app/domain/rag.py`
- `apps/api/app/application/rag.py`
- `apps/api/app/rag/graph.py`
- corresponding API/unit/integration tests and Compose settings


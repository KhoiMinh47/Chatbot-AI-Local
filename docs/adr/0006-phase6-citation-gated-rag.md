# ADR 0006 — Citation-gated LangGraph RAG remains candidate-only

- Status: Superseded in part by ADR 0008; safety design retained
- Date: 2026-07-15
- Phase: 6
- Decision gates: DG-02, DG-03, verified Phase 4 corpus

> Current-state addendum (2026-07-15): the missing local winner/corpus/index
> prerequisites described below were later satisfied. ADR 0008 binds the graph
> to exact Nemotron, Embed 300M, the active Qdrant alias and PostgreSQL policy
> traces, and records a local-engineering PASS. This ADR remains authoritative
> for citation gating, exact budgets, refusal, trace redaction and no-CoT rules.

## Context

Phase 6 requires one grounded generation flow with valid citations, bounded Fast
and Reasoning modes, exact token budgeting, refusal on insufficient evidence,
streaming, and durable traces. The current workspace has reusable NIM and
retrieval ports, but no approved LLM winner, no approved embedding/index winner,
no active Qdrant alias, and no verified Phase 4 corpus.

Raw token streaming is unsafe when validity is known only after the final model
delta: an invented citation or a `<think>` block may already have reached the
client. The NIM adapter discards `reasoning_content`, but hidden reasoning can
still appear inside ordinary `content`.

## Decision

1. Implement the flow as a compiled LangGraph in the outer `app.rag` layer;
   domain and application services remain framework-independent.
2. Keep tenant, user, ACL principals, and selected documents in a trusted
   application command. The graph never derives or expands access scope from an
   LLM response.
3. Enforce hard mode caps: Fast uses one query/round, top 12, at most six context
   blocks, and 768 output tokens; Reasoning uses at most three queries, two
   rounds, 30 candidates, 12 context blocks, and 4096 output tokens.
4. Require an exact, local, hash-bound active-model tokenizer. Approximate
   counters fail closed and cannot satisfy budget acceptance.
5. Assign request-local source IDs `S1..Sn` on the backend. The model may emit
   only those IDs; citation metadata always comes from retrieved payloads.
6. Buffer the upstream model stream, reject hidden-reasoning markers and invalid
   citations, then emit only the validated visible answer. This preserves the
   application streaming contract without leaking a response later found unsafe.
7. Route empty packed context to a fixed localized refusal without invoking the
   LLM.
8. Persist one append-only trace per request. Store hashes, versions, IDs,
   ranks, scores, budgets, usage, timings, and error codes; never store the full
   question, answer, prompt, document text, secret, or chain-of-thought.
9. Keep the graph unbound from production composition while DG-02/DG-03 and the
   real-corpus gate are open. Candidate tests may use temporary/static evidence
   but cannot activate a model or Qdrant alias. This historical restriction is
   superseded for local engineering by the exact bindings in ADR 0008; it still
   applies to any unapproved or fingerprint-mismatched configuration.

## Consequences

Validated answer tokens begin later than raw NIM TTFT because safety requires a
full-answer citation/CoT gate. Both upstream generation time and client-visible
TTFT must therefore be reported separately in later performance work.

The implementation can prove routing, bounds, citation-ID integrity, refusal,
event isolation, and redacted trace persistence now. Semantic groundedness on
real documents, production unanswerable quality, and production latency remain
blocked until upstream winners and corpus evidence exist.

## Phase boundary

This ADR does not authorize Phase 7. It adds no public chat endpoint, auth/RBAC,
conversation CRUD, SSE reconnect/idempotency, rate limiting, or admin API.

## Revisit when

- Any selected model, tokenizer, prompt, index or retrieval-policy fingerprint
  changes.
- Corporate legal review approves or rejects the local Nemotron selection.
- The fresh full generation set receives human correctness/faithfulness review.
- Phase 10 supplies p50/p95, concurrency and throughput evidence.

See [ADR 0008](0008-phase6-winner-bound-local-rag.md) for the current local
winner-bound decision.

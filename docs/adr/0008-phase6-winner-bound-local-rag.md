# ADR 0008 — Phase 6 local RAG is bound to the activated winners

- Status: Accepted for local engineering; production release gates remain open
- Date: 2026-07-15
- Phase: 6
- Supersedes: ADR 0006 candidate-only binding restriction
- Retains: ADR 0006 citation, token-budget, redaction and no-CoT safety design
- Does not authorize: Phase 7

## Context

ADR 0006 intentionally kept the LangGraph flow candidate-only because no LLM
winner, real ingestion corpus, embedding/index winner or active Qdrant alias
existed. Those local engineering prerequisites are now present:

- ADR 0007 selects exact Nemotron Nano 9B v2 for local engineering;
- Phase 4 has ten real parsed sources and a stratified 100-case gold file;
- Phase 5 selects Embed 300M v2, activates one exact physical index through
  `ntc_chunks_active`, and records the retrieval-policy fingerprint;
- migration `0005_phase6_winner_binding` lets every new generation trace bind
  that exact retrieval policy.

The winner-bound runner then exercised the real Embed NIM, active Qdrant alias,
Nemotron NIM, exact tokenizer and PostgreSQL trace store. Canonical run
`20260715T025554Z-nemotron-embed300m-winner-r7` passed every Phase 6 acceptance
criterion. Its report SHA-256 is
`07701b7ba3ca0e694726753ab92442a3b98f5280c514328346f81fa00a9f264f`.

## Decision

1. Bind the local Phase 6 graph to LLM
   `nvidia/nemotron-nano-9b-v2`, version `1.0.0`. Fast injects `/no_think` and
   Reasoning injects `/think` only in a trusted system instruction. Model IDs
   returned by the live `/models` endpoint must match exactly.
2. Bind retrieval to `nvidia/llama-nemotron-embed-300m-v2` version `1.13.0`,
   dimension `2048`, active alias `ntc_chunks_active`, physical collection
   `ntc_chunks_embed300m_v2_s256_o10_095bc081a101_recall95_v3`, index
   fingerprint
   `a3cc25bb8e65a03ac1146c227c4c2b8c5a86370f4852eb35eb4d66330dd20290`
   and policy fingerprint
   `37a6fb7d83d292ba67f7709ce5e8e77483a73b86cd470938486d37b2d38c65b8`.
3. Preserve the Phase 5 policy as activated: dense threshold `0.2300481`,
   candidate limit `20`, final limit `10`, HNSW `ef=128`, and reranker disabled.
   Changing any field creates a different policy fingerprint and requires new
   evidence.
4. Treat the Phase 5 dense limit `20` as an approved **base ceiling**, not the
   Phase 6 per-mode limit. Graph v2 computes effective Qdrant top-k as
   `min(approved base, mode cap)`: Fast `12`, Reasoning `10`, and passes the cap
   into the actual retriever call. The base policy fingerprint does not encode
   these mode caps; bind them through `mode_policy_binding`, graph version
   `phase6-stategraph-v2` and graph/retrieval source provenance together.
5. Require the exact local Nemotron tokenizer. The accepted tokenizer SHA-256
   is `32bd2509c1acc93dc18bdd0f9a2d9a15e72fd3110f24cfc9ff3fb820f4e20b6b`;
   NIM usage must reconcile with it and an approximate counter fails closed.
6. Keep Fast and Reasoning policy caps distinct even when a simple question
   legitimately needs only one subquery and one retrieval round. Acceptance is
   based on bound caps, actual bounded execution and measured latency/budget;
   it does not force artificial decomposition.
7. Keep backend-issued `S1..Sn` citations, buffered generation validation and
   allowlist checks. Citation metadata comes from retrieved payloads, never from
   model-generated metadata.
8. Route empty/below-threshold evidence to the fixed insufficient-evidence
   branch with no LLM call.
9. Enforce tenant/owner/ACL filtering inside the active-alias query. The
   canonical probe must return the expected source for the owner and zero hits
   for an unrelated principal.
10. Persist a redacted, append-only PostgreSQL trace containing hashes, model and
   policy/index bindings, token budgets, citations, context references and
   timings. Never persist raw question, prompt, answer, document text, event
   payload, credential or chain-of-thought.

## Exact upstream bindings

| Artifact | SHA-256 |
|---|---|
| Phase 5 decision report | `290d1b34f7c350658207dea14c8e1f045314fc2126c3522adeecf1eea12cb610` |
| Phase 5 activation receipt | `2b0f68582a8e1398b4507e73a596887fa271cf33308456efeb294225f08fd76f` |
| Stratified 100-case gold | `393c9147f6a59a41e1a038a7622dc7d4183571fb4a1aa3a1940514629c155ca3` |
| Migration 0005 source | `7668b4e05a5b5d91b0053b3e5ec56013fde8dd1f6db97b37e6e7215683c1f985` |
| Winner E2E runner source | `b997b608c64732ff9c686b2450a4dd9da3737172a14cfbbcc700d2e92a220c10` |

The Phase 5 receipt verifies that `ntc_chunks_active` reads back the expected
physical collection and that it contains 12 points. Phase 6 additionally proves
the alias through owner/unrelated-principal retrieval, rather than trusting the
receipt alone.

## Canonical observed behavior

- Same answerable case and question hash in both modes.
- Fast: `1.166743 s`, 347 input / 27 output tokens, output reserve `768`, one
  streaming LLM call, valid `S1` to `01_leave_policy.pdf` page 1.
- Reasoning: `9.394018 s`, 345 input / 223 output tokens, output reserve `4096`,
  one planning call plus one streaming call, valid `S1` to the same source.
- Unanswerable: `0.029814 s`, empty context, zero chat/stream LLM calls, zero
  citations, outcome `insufficient_evidence`.
- ACL: owner hit count `1`; unrelated principal hit count `0`.
- PostgreSQL readback matched answer/question hashes, model version, index and
  retrieval-policy fingerprints for all three traces.
- Client events contained no hidden-reasoning field or chain-of-thought.

These latencies are single live observations, not p50/p95 or a Phase 10 load
benchmark.

## Debug trail and canonical selection

- Winner r1: failed because the Reasoning path ended in `rag_execution_failed`;
  the report correctly remained FAIL.
- Winner r2: failed closed on Reasoning output containing hidden-reasoning and
  uncited-claim markers.
- Winner r3: passed the technical graph checks but used the earlier gold hash
  `23fae69f...`; it does not match the Phase 5 decision and is noncanonical.
- Winner r4: used the correct stratified gold, but an overly strict report check
  required the actual simple-query retrieval plan to differ by mode. Both
  executions legitimately used one subquery/round, so r4 remained FAIL.
- Winner r5: passed the functional bindings, then became historical when the
  repository format gate rewrote three provenance-bound source files.
- Winner r6: reran on the formatted source, but audit found the per-mode cap did not reach
  the actual Qdrant request; it remains historical.
- Winner r7: Graph v2 enforces Fast 12/Reasoning 10 effective limits in the
  retriever, binds exact Phase 5 gold/decision/receipt and matches all 13 current
  source hashes. It is canonical.

Earlier Llama direct-evidence runs remain historical candidate evidence only.

## Consequences and remaining release gates

Phase 6 is **PASS 6/6 for local engineering**. This does not mean the complete
product is production-ready:

- corporate legal approval for Nemotron remains pending;
- the 40–50+ tok/s target and concurrency/p50/p95 work remain Phase 10;
- r7 covers one answerable question in both modes and one unanswerable question;
  the fresh full release generation set still needs independent human review of
  correctness, faithfulness, citation coverage and refusal behavior;
- Phase 7 must add public chat/SSE transport, authenticated identity, RBAC,
  conversation lifecycle, reconnect/idempotency, cancellation and rate limits.

No Phase 7 surface is created or authorized by this ADR.

## Evidence

- [Phase 6 acceptance](../../artifacts/phase-6/acceptance.md)
- [Canonical r7 report](../../artifacts/phase-6/runs/20260715T025554Z-nemotron-embed300m-winner-r7/report.json)
- [Phase 5 decision](../../artifacts/phase-5/runs/20260715T022157Z-embed300m-final-r3/decision-report.json)
- [Phase 5 activation receipt](../../artifacts/phase-5/runs/20260715T022157Z-embed300m-final-r3/activation-receipt.json)
- [ADR 0007](0007-nemotron-nano-9b-v2-local-engineering-winner.md)

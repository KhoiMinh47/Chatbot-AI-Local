# Phase 6 completion — winner-bound Fast/Reasoning RAG

- Status: **COMPLETE for local engineering — 6/6 acceptance criteria PASS**
- Canonical run: `20260715T025554Z-nemotron-embed300m-winner-r7`
- Report SHA-256:
  `07701b7ba3ca0e694726753ab92442a3b98f5280c514328346f81fa00a9f264f`
- Phase 7: **not started by this work**

## Outcome

The internal LangGraph RAG flow is now bound to exact Nemotron Nano 9B v2,
Embed 300M v2, the activated Phase 5 Qdrant index/policy, the Phase 4 corpus,
the exact Nemotron tokenizer and PostgreSQL winner-policy traces.

The same answerable question ran through Fast and Reasoning modes with distinct
budgets and live latency. Both answers cited backend-issued `S1` mapped to the
expected real PDF/page. A real unanswerable gold case took the no-evidence
branch with zero LLM calls. Tenant/ACL filtering returned `1` owner hit and `0`
unrelated-principal hits through the active alias.

## Acceptance sign-off

- [x] Same question demonstrated different Fast/Reasoning budgets and latency.
- [x] Both generated answers had a valid server-issued citation to the expected
  Phase 4 source.
- [x] Citation allowlist and trace/hash checks found no fabricated citation.
- [x] Unanswerable case refused with zero chat/stream generation calls.
- [x] Exact token budgets stayed below the 32K runtime window and reconciled
  with NIM usage.
- [x] Client events and PostgreSQL traces contained no chain-of-thought.

Observed single-run latency: Fast `1.166743 s`, Reasoning `9.394018 s`,
unanswerable `0.029814 s`. These are acceptance observations, not p50/p95.

## Binding and trace closure

- Nemotron: `nvidia/nemotron-nano-9b-v2`, NIM `1.0.0`.
- Embed: `nvidia/llama-nemotron-embed-300m-v2`, NIM `1.13.0`, dimension 2048.
- Alias: `ntc_chunks_active`, expected physical collection with 12 points.
- Index fingerprint: `a3cc25bb...20290`.
- Retrieval-policy fingerprint: `37a6fb7d...65b8`.
- Exact tokenizer SHA-256: `32bd2509...20b6b`.
- Migration head used: `0005_phase6_winner_binding`.
- Three live trace rows were read back with exact model/index/policy/outcome and
  redacted-content guarantees.

Full values and upstream hashes are in [`INVENTORY.md`](INVENTORY.md).

## Debug closure

- r1/r2 remained FAIL and exposed Reasoning execution/validation failures.
- r3 passed technical checks but used the pre-Phase-5 gold hash, so it is not
  canonical.
- r4 used correct inputs but an overly strict checker incorrectly demanded
  different actual retrieval plans for an easy fact question; it remains FAIL.
- r5 passed functionally but predates the repository format-gate rewrite, so its
  source provenance is historical rather than current.
- r6 reran on the formatted source, but later audit proved its mode cap had not
  reached the actual Qdrant request; it remains historical.
- r7 Graph v2 passes `candidate_limit_cap` into the retriever. Effective top-k
  is `min(Phase5 base 20, mode cap)`: Fast 12 and Reasoning 10. It binds the
  exact Phase 5 decision/receipt/gold and matches all 13 current source hashes.

Historical reports were not modified or deleted.

## Remaining limits

This sign-off is local engineering acceptance, not complete production release:

- corporate legal approval for Nemotron remains pending;
- Phase 10 must address the throughput deviation and produce p50/p95,
  concurrency and load evidence;
- the fresh full generation set still needs independent human semantic review;
- authenticated public chat/SSE, RBAC, reconnect/idempotency, cancellation,
  conversation lifecycle and rate limiting belong to Phase 7.

See [`acceptance.md`](acceptance.md) and
[`ADR 0008`](../../docs/adr/0008-phase6-winner-bound-local-rag.md).

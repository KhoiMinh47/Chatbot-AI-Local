# Phase 6 evidence index

Phase 6 is **PASS 6/6 for local engineering** on the exact selected Nemotron +
Embed 300M + active Qdrant index. The canonical evidence is winner-bound run
`20260715T025554Z-nemotron-embed300m-winner-r7`.

This directory documents the internal LangGraph application flow. It does not
contain or authorize the public authenticated chat surface from Phase 7.

## Canonical files

- [`acceptance.md`](acceptance.md) — criterion-by-criterion live evidence,
  debug history and remaining release gates.
- [`COMPLETION.md`](COMPLETION.md) — Phase 6 handoff summary.
- [`INVENTORY.md`](INVENTORY.md) — exact model, tokenizer, index, policy,
  prompt, migration and upstream evidence fingerprints.
- [`r7/report.json`](runs/20260715T025554Z-nemotron-embed300m-winner-r7/report.json)
  — machine-readable source of truth.
- [`r7/report.sha256`](runs/20260715T025554Z-nemotron-embed300m-winner-r7/report.sha256)
  — report digest
  `07701b7ba3ca0e694726753ab92442a3b98f5280c514328346f81fa00a9f264f`.
- [`ADR 0008`](../../docs/adr/0008-phase6-winner-bound-local-rag.md) — current
  winner-bound design decision.
- `runtime-cleanup.md` — separate post-run runtime cleanup record; it is not part
  of the acceptance report and is maintained after NIM shutdown.

## What r7 exercised

```text
trusted Phase 6 command
  -> exact Embed 300M query embedding
  -> ntc_chunks_active with tenant/owner/ACL filter
  -> selected index + retrieval-policy fingerprint checks
  -> Fast or Reasoning LangGraph policy
  -> exact Nemotron token budget
  -> Nemotron NIM generation, or deterministic no-evidence refusal
  -> buffered citation/CoT validation
  -> safe application events
  -> redacted append-only PostgreSQL trace + live readback
```

Live results:

- Fast `1.166743 s`, `/no_think`, output reserve 768, effective dense cap 12,
  valid `S1`;
- Reasoning `9.394018 s`, `/think`, output reserve 4096, effective dense cap
  10, valid `S1`;
- unanswerable `0.029814 s`, no context, no LLM call and no citation;
- active-alias ACL owner/unrelated hit counts `1/0`;
- no chain-of-thought in client events or stored traces.

## Implementation map

- RAG application/domain:
  [`apps/api/app/application/rag.py`](../../apps/api/app/application/rag.py) and
  [`apps/api/app/domain/rag.py`](../../apps/api/app/domain/rag.py).
- LangGraph and planner:
  [`apps/api/app/rag/graph.py`](../../apps/api/app/rag/graph.py) and
  [`apps/api/app/rag/planner.py`](../../apps/api/app/rag/planner.py).
- Exact tokenizer, NIM and trace adapters:
  [`exact_token_counter.py`](../../apps/api/app/infrastructure/exact_token_counter.py),
  [`nim_clients.py`](../../apps/api/app/infrastructure/nim_clients.py), and
  [`generation_trace_store.py`](../../apps/api/app/infrastructure/generation_trace_store.py).
- Active-alias retrieval:
  [`qdrant_store.py`](../../apps/api/app/infrastructure/qdrant_store.py).
- Trace policy migration:
  [`0005_phase6_winner_trace_binding.py`](../../migrations/versions/0005_phase6_winner_trace_binding.py).
- Immutable runner:
  [`phase6_winner_e2e.py`](../../scripts/phase6_winner_e2e.py).

## Re-running

Inspect the complete argument contract with:

```bash
uv run --locked --no-sync python scripts/phase6_winner_e2e.py --help
```

The runner requires:

- the exact Phase 5 decision and activation receipt;
- stratified gold file `gold-final-100-v2-stratified.jsonl`;
- live private Qdrant, Embed 300M NIM and Nemotron NIM URLs;
- the canonical Phase 4 tenant/user scope;
- the exact local tokenizer path and expected SHA-256;
- PostgreSQL URL supplied through the named environment variable;
- a new output directory, which is created exclusively and never overwritten.

Credentials, URLs containing credentials and raw content must never be added to
the output report.

Focused regression tests:

```bash
uv run --locked --no-sync pytest -q \
  apps/api/tests/test_phase6_rag.py \
  apps/api/tests/test_retrieval.py \
  tests/test_phase6_winner_e2e.py \
  tests/test_phase6_trace_integration.py
```

The PostgreSQL integration test skips unless its explicit database URL is
provided; canonical r7 contains separate live database readback evidence.

## Run history

Winner-bound r1/r2/r4 are FAIL and retained. r3 passed against the old gold but
is noncanonical. R5 passed before the repository format-gate rewrite; r6 did not enforce its
mode cap in the actual Qdrant request. Only r7 binds the exact Phase 5
decision/receipt/gold, applies Fast 12/Reasoning 10 effective top-k through
Graph v2, and matches current source hashes. Earlier Llama direct runs are
pre-winner candidate evidence only.

See [`acceptance.md`](acceptance.md) for the full disposition of every attempt.

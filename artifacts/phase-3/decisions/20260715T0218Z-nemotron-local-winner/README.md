# Phase 3 decision addendum — Nemotron Nano 9B v2

- Decision: **selected as the primary local-engineering LLM**
- Scope: Phase 6 and later local validation
- Exact model: `nvidia/nemotron-nano-9b-v2`
- NIM: `1.0.0`
- Profile: `f9db61d5a467d46be7733e90a26705798764b93d480c842143d525c1932b01e2`
- Precision: `NVFP4`
- Image digest: `sha256:82028e38ab950edd32f5053ca2030ee14d965e8fd4fe1c6e06468eb0be07a9a4`
- Decision JSON SHA-256: `1206a3db86aebdd87f5c08395546340d95c69c18d5c55f86d8a8f4ebacbfd00c`

This is an append-only decision made after the canonical bake-off. It does not
modify or reinterpret the historical `20260714T1120Z-full-r2` scorecard, whose
original decision remains `not_selected`. The new authority is the workspace
operator's explicit 2026-07-15 directive.

## Why Nemotron

The canonical run measured a provisional weighted score of `0.931828384971`
for Nemotron versus `0.907959259806` for Llama. Nemotron passed the 10/10
automatic quality hard gate, the six-scenario workload, live 32K/64K/128K
tests, exact runtime identity checks, and the target LLM + Embed + Rerank
no-OOM combination.

## Open gates

This is an engineering selection, not corporate legal approval. The canonical
case-level human review and corporate license approval remain pending.
Nemotron's measured p50 decode was `26.95 tok/s` for engine-short c1 and
`26.49 tok/s` for RAG-8K c1, below the plan's 40–50+ tok/s target. The operator
accepts that deviation for local Phase 6 work; it remains a Phase 10 performance
follow-up and must not be reported as a production performance pass.

The machine-readable decision and every canonical source hash are in
[`decision.json`](decision.json).

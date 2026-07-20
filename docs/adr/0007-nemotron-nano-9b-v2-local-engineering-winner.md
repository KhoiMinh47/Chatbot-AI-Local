# ADR 0007 — Nemotron Nano 9B v2 is the primary local-engineering LLM

- Status: Accepted with performance deviation; corporate legal approval pending
- Date: 2026-07-15
- Phase: Phase 3 decision addendum, consumed by Phase 6
- Decision gate: DG-02; DG-04 remains open for Phase 10
- Authority: explicit workspace-operator directive

## Context

The immutable Phase 3 run `20260714T1120Z-full-r2` deliberately selected no
winner because its formal human and legal reviews were pending. It nevertheless
provides complete comparable runtime evidence for Llama 3.1 8B and Nemotron
Nano 9B v2. The workspace operator has now explicitly chosen Nemotron Nano 9B
v2 as the main LLM so downstream local RAG validation can bind one exact model.

Historical evidence must remain historical: this ADR does not edit the
scorecard's original `not_selected` value. The operator decision is captured as
a separate append-only artifact whose JSON SHA-256 is
`1206a3db86aebdd87f5c08395546340d95c69c18d5c55f86d8a8f4ebacbfd00c`.

## Decision

Use this exact LLM identity for the local application and Phase 6 validation:

| Field | Binding |
|---|---|
| Model | `nvidia/nemotron-nano-9b-v2` |
| NIM version | `1.0.0` |
| Image | `nvcr.io/nim/nvidia/nvidia-nemotron-nano-9b-v2-dgx-spark:1.0.0-variant` |
| Image digest | `sha256:82028e38ab950edd32f5053ca2030ee14d965e8fd4fe1c6e06468eb0be07a9a4` |
| Architecture | `linux/arm64` |
| Runtime profile | `f9db61d5a467d46be7733e90a26705798764b93d480c842143d525c1932b01e2` |
| Precision | `NVFP4` |
| Maximum model length | `131072` |

Fast Mode uses `/no_think` and Reasoning Mode uses `/think` only in trusted
system instructions. Hidden reasoning remains server-side and must never be
sent to the client.

## Evidence basis

- Provisional weighted score: Nemotron `0.931828384971`; Llama
  `0.907959259806`.
- Nemotron automatic quality hard gate: 10/10 passed.
- Complete six-scenario benchmark and 32K/64K/128K capability gates: passed.
- Exact runtime identity/profile/license-evidence consistency: passed.
- Nemotron + Embed 300M + Rerank 500M combination: no OOM, no restart, healthy,
  clean logs, telemetry and cleanup passed.

The decision artifact binds the exact SHA-256 of the scorecard, summary,
quality, benchmark, runtime-verification and combination reports:
[`artifacts/phase-3/decisions/20260715T0218Z-nemotron-local-winner/decision.json`](../../artifacts/phase-3/decisions/20260715T0218Z-nemotron-local-winner/decision.json).

## Accepted deviation and remaining gates

The canonical workload measured p50 decode throughput of `26.95 tok/s` for
engine-short c1 and `26.49 tok/s` for RAG-8K c1. These values do not meet the
40–50+ tok/s target. They are accepted only to unblock local engineering and
Phase 6 validation; DG-04 remains open for Phase 10 bottleneck/profile and
concurrency analysis. The numbers must not be renamed or presented as a pass.

The operator directive is not a corporate legal opinion. Formal case-level
human review in the canonical run and corporate approval of the NVIDIA license
terms remain pending. Production/commercial use must remain gated on that
approval.

## Consequences

- Local application configuration may fail closed unless the exact Nemotron
  model/version is supplied.
- Phase 6 can bind a concrete tokenizer, think/no-think policy and runtime
  identity instead of a candidate placeholder.
- Phase 3's canonical run and hashes remain unchanged and auditable.
- This ADR does not choose an embedding or reranker, activate a Qdrant alias,
  complete Phase 6, or authorize Phase 7.

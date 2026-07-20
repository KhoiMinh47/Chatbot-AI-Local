# Phase 5 provisional retrieval benchmark

- Status: **BLOCKED**
- Run ID: `20260714T175000Z-embed300m-r5`
- Scope: Embed-300M chunk grid plus optional Rerank-500M; BGE-M3 unavailable.
- Active alias changed: **No**

| Chunk | Overlap | Recall@10 | MRR@10 | nDCG@10 | p95 Qdrant ms |
|---:|---:|---:|---:|---:|---:|
| 256 | 0% | 1.0000 | 1.0000 | 0.9962 | 4.01 |
| 256 | 10% | 1.0000 | 1.0000 | 0.9972 | 5.71 |
| 256 | 20% | 1.0000 | 1.0000 | 0.9967 | 4.13 |
| 512 | 0% | 1.0000 | 1.0000 | 0.9947 | 3.80 |
| 512 | 10% | 1.0000 | 1.0000 | 0.9967 | 4.30 |
| 512 | 20% | 1.0000 | 1.0000 | 0.9952 | 4.05 |
| 768 | 0% | 1.0000 | 1.0000 | 0.9944 | 4.71 |
| 768 | 10% | 1.0000 | 1.0000 | 0.9944 | 5.15 |
| 768 | 20% | 1.0000 | 1.0000 | 0.9944 | 3.82 |
| 1024 | 0% | 1.0000 | 1.0000 | 0.9944 | 6.19 |
| 1024 | 10% | 1.0000 | 1.0000 | 0.9944 | 5.36 |
| 1024 | 20% | 1.0000 | 1.0000 | 0.9944 | 5.74 |

## Provisional chunk winner

`chunk_size=256, overlap=10%`.
This is not an embedding winner and is not authorized for the active alias.
Provisional retrieval policy: reranker `off`, score threshold `0.31797254`.
Reason: Reranking did not meet the material-gain, calibrated no-regression, and <=2x p95 latency policy.

## Blocking gates

- BGE-M3 exact runtime remains blocked by NGC HTTP 402, so the embedding bake-off is incomplete.
- Phase 4 does not yet provide a verified 10+ document end-to-end corpus.
- `ntc_chunks_active` was inspected before/after and never mutated.

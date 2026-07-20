# Phase 5 provisional retrieval benchmark

- Status: **BLOCKED**
- Run ID: `20260714T172546Z-embed300m-r4`
- Scope: Embed-300M chunk grid plus optional Rerank-500M; BGE-M3 unavailable.
- Active alias changed: **No**

| Chunk | Overlap | Recall@10 | MRR@10 | nDCG@10 | p95 Qdrant ms |
|---:|---:|---:|---:|---:|---:|
| 256 | 0% | 1.0000 | 1.0000 | 0.9962 | 5.58 |
| 256 | 10% | 1.0000 | 1.0000 | 0.9972 | 5.87 |
| 256 | 20% | 1.0000 | 1.0000 | 0.9967 | 5.02 |
| 512 | 0% | 1.0000 | 1.0000 | 0.9947 | 5.66 |
| 512 | 10% | 1.0000 | 1.0000 | 0.9967 | 4.39 |
| 512 | 20% | 1.0000 | 1.0000 | 0.9952 | 4.75 |
| 768 | 0% | 1.0000 | 1.0000 | 0.9944 | 4.74 |
| 768 | 10% | 1.0000 | 1.0000 | 0.9944 | 4.19 |
| 768 | 20% | 1.0000 | 1.0000 | 0.9944 | 6.06 |
| 1024 | 0% | 1.0000 | 1.0000 | 0.9944 | 4.43 |
| 1024 | 10% | 1.0000 | 1.0000 | 0.9944 | 5.38 |
| 1024 | 20% | 1.0000 | 1.0000 | 0.9944 | 4.51 |

## Provisional chunk winner

`chunk_size=256, overlap=10%`.
This is not an embedding winner and is not authorized for the active alias.
Provisional retrieval policy: reranker `off`, score threshold `0.31797254`.
Reason: Reranking did not meet the material-gain, calibrated no-regression, and <=2x p95 latency policy.

## Blocking gates

- BGE-M3 exact runtime remains blocked by NGC HTTP 402, so the embedding bake-off is incomplete.
- Phase 4 does not yet provide a verified 10+ document end-to-end corpus.
- `ntc_chunks_active` was inspected before/after and never mutated.

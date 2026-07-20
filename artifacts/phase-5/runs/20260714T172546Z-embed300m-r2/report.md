# Phase 5 provisional retrieval benchmark

- Status: **BLOCKED**
- Run ID: `20260714T172546Z-embed300m-r2`
- Scope: Embed-300M chunk grid plus optional Rerank-500M; BGE-M3 unavailable.
- Active alias changed: **No**

| Chunk | Overlap | Recall@10 | MRR@10 | nDCG@10 | p95 Qdrant ms |
|---:|---:|---:|---:|---:|---:|
| 256 | 0% | 1.0000 | 1.0000 | 0.9962 | 4.10 |
| 256 | 10% | 1.0000 | 1.0000 | 0.9972 | 4.63 |
| 256 | 20% | 1.0000 | 1.0000 | 0.9967 | 6.02 |
| 512 | 0% | 1.0000 | 1.0000 | 0.9947 | 5.53 |
| 512 | 10% | 1.0000 | 1.0000 | 0.9967 | 5.38 |
| 512 | 20% | 1.0000 | 1.0000 | 0.9952 | 4.27 |
| 768 | 0% | 1.0000 | 1.0000 | 0.9944 | 5.95 |
| 768 | 10% | 1.0000 | 1.0000 | 0.9944 | 5.04 |
| 768 | 20% | 1.0000 | 1.0000 | 0.9944 | 5.01 |
| 1024 | 0% | 1.0000 | 1.0000 | 0.9944 | 4.82 |
| 1024 | 10% | 1.0000 | 1.0000 | 0.9944 | 5.67 |
| 1024 | 20% | 1.0000 | 1.0000 | 0.9944 | 4.53 |

## Provisional chunk winner

`chunk_size=256, overlap=10%`.
This is not an embedding winner and is not authorized for the active alias.

## Blocking gates

- BGE-M3 exact runtime remains blocked by NGC HTTP 402, so the embedding bake-off is incomplete.
- Phase 4 does not yet provide a verified 10+ document end-to-end corpus.
- `ntc_chunks_active` was inspected before/after and never mutated.

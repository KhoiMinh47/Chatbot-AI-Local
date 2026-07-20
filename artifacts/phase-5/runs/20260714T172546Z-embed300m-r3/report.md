# Phase 5 provisional retrieval benchmark

- Status: **BLOCKED**
- Run ID: `20260714T172546Z-embed300m-r3`
- Scope: Embed-300M chunk grid plus optional Rerank-500M; BGE-M3 unavailable.
- Active alias changed: **No**

| Chunk | Overlap | Recall@10 | MRR@10 | nDCG@10 | p95 Qdrant ms |
|---:|---:|---:|---:|---:|---:|
| 256 | 0% | 1.0000 | 1.0000 | 0.9962 | 4.55 |
| 256 | 10% | 1.0000 | 1.0000 | 0.9972 | 4.43 |
| 256 | 20% | 1.0000 | 1.0000 | 0.9967 | 4.86 |
| 512 | 0% | 1.0000 | 1.0000 | 0.9947 | 4.55 |
| 512 | 10% | 1.0000 | 1.0000 | 0.9967 | 4.35 |
| 512 | 20% | 1.0000 | 1.0000 | 0.9952 | 4.51 |
| 768 | 0% | 1.0000 | 1.0000 | 0.9944 | 4.59 |
| 768 | 10% | 1.0000 | 1.0000 | 0.9944 | 5.66 |
| 768 | 20% | 1.0000 | 1.0000 | 0.9944 | 5.72 |
| 1024 | 0% | 1.0000 | 1.0000 | 0.9944 | 5.47 |
| 1024 | 10% | 1.0000 | 1.0000 | 0.9944 | 5.94 |
| 1024 | 20% | 1.0000 | 1.0000 | 0.9944 | 4.71 |

## Provisional chunk winner

`chunk_size=256, overlap=10%`.
This is not an embedding winner and is not authorized for the active alias.

## Blocking gates

- BGE-M3 exact runtime remains blocked by NGC HTTP 402, so the embedding bake-off is incomplete.
- Phase 4 does not yet provide a verified 10+ document end-to-end corpus.
- `ntc_chunks_active` was inspected before/after and never mutated.

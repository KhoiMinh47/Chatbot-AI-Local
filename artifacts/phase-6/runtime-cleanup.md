# Phase 6 runtime cleanup

- Cleanup completed: `2026-07-15T10:02:06+07:00`
- Canonical evidence captured first:
  `20260715T025554Z-nemotron-embed300m-winner-r7`
- Report SHA-256:
  `07701b7ba3ca0e694726753ab92442a3b98f5280c514328346f81fa00a9f264f`

## Temporary winner runtimes

The live winner run used exactly these two private Phase 3 services:

- `nim-llm-nemotron` — `nvidia/nemotron-nano-9b-v2`, NIM `1.0.0`;
- `nim-embedding-300m` — `nvidia/llama-nemotron-embed-300m-v2`,
  NIM `1.13.0`.

Immediately before cleanup, both containers were `healthy`, restart count `0`
and `OOMKilled=false`. They were then stopped and removed. Their named model
cache volumes remain present:

- `ntc-rag-phase3_nim_nemotron_cache`;
- `ntc-rag-phase3_nim_embed_300m_cache`.

No Phase 3 winner container remains after cleanup. The standalone Phase 4
Celery worker used for ingestion acceptance was also shut down cleanly.

## Persistent state retained and re-read after cleanup

- Phase 2 PostgreSQL, Redis, RabbitMQ, MinIO and Qdrant: all `healthy`.
- Qdrant alias `ntc_chunks_active` still targets
  `ntc_chunks_embed300m_v2_s256_o10_095bc081a101_recall95_v3`.
- Winner collection: `green`, 12 points, dimension `2048`.
- Index fingerprint:
  `a3cc25bb8e65a03ac1146c227c4c2b8c5a86370f4852eb35eb4d66330dd20290`.
- PostgreSQL Alembic head: `0005_phase6_winner_binding`.
- Rows in `rag_generation_traces`: `21`.

The traces are append-only evidence from the winner-bound debug/canonical runs
and were intentionally retained. The active alias was selected in Phase 5 and
was not changed by Phase 6 execution or cleanup. No named datastore volume,
Qdrant collection, alias, trace row or model cache was deleted.

No Phase 7 service, route, table or container was started.

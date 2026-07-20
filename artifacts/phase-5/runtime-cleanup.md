# Phase 5 runtime and cleanup evidence

- Observed: 2026-07-15 (Asia/Ho_Chi_Minh), after canonical run
  `20260714T175000Z-embed300m-r5`
- Scope: retriever NIM containers started for Phase 5 and existing Phase 2
  Qdrant core

Before cleanup:

```text
nim-embedding-300m: Running=true, Health=healthy, OOMKilled=false,
  RestartCount=0, Mem=4.745 GiB / 16 GiB
nim-reranking-500m: Running=true, Health=healthy, OOMKilled=false,
  RestartCount=0, Mem=5.066 GiB / 16 GiB
Qdrant: healthz passed, collections=[], aliases=[]
```

Cleanup stopped and removed exactly:

```text
ntc-rag-phase3-nim-embedding-300m-1
ntc-rag-phase3-nim-reranking-500m-1
```

The two model-cache volumes remain:

```text
ntc-rag-phase3_nim_embed_300m_cache
ntc-rag-phase3_nim_rerank_500m_cache
```

After cleanup, the Phase 3 retriever Compose project has zero containers. The
pre-existing Phase 2 PostgreSQL, Redis, RabbitMQ, MinIO, and Qdrant containers
remain running and healthy. No named volume was deleted.


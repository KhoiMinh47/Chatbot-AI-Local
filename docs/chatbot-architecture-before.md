# Chatbot architecture before quality optimization

Snapshot: 2026-07-17.

```mermaid
flowchart LR
    U[Browser / Next.js] -->|multipart upload| A[FastAPI]
    U -->|chat SSE| A
    A -->|raw object| M[MinIO]
    A -->|document job| Q[RabbitMQ]
    Q --> W[Celery worker]
    W --> D[Docling / parsers]
    D --> C[Hierarchical chunker]
    C --> E[NIM Embed 300M]
    E --> V[Qdrant]
    A --> P[(PostgreSQL)]
    A --> R[(Redis)]
    A -->|query embedding| E
    A -->|dense search| V
    A -->|buffered generation| L[NIM Nemotron Nano 9B v2]
    L -->|complete answer| CV[Citation validator]
    CV -->|SSE chunks after validation| U
```

Important properties of the current flow:

- Upload is asynchronous after API acceptance, but the API and worker each load the
  entire file into memory on their respective paths.
- Retrieval is dense-only. The reranking adapter exists but is disabled in the live
  policy.
- The model streams internally, but the graph buffers the full answer until citation
  validation finishes. End users therefore do not receive true token TTFT.
- Conversation/message support exists partially in source, but the live database schema
  and repository contract have drifted and runtime still has no persisted messages.
- The NIM runtime is capable of 131072 tokens, while the application policies use a
  32768-token window with smaller evidence caps.


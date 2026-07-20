# RAG and citation design

## Retrieval

Active-document questions use two tenant/ACL-scoped retrievers in parallel:

- dense vector search in Qdrant using Embed 300M v2;
- PostgreSQL full-text lexical search over the same immutable chunk versions.

Results are fused deterministically with RRF (`k=60`, dense/lexical weight `1.0`) and then
deduplicated/diversified before exact token packing. The dense threshold is `0.2300481` for
corpus policy and is removed for explicitly attached documents so short/cross-language
queries do not discard their chosen source.

Live verification on 2026-07-17: alias `ntc_chunks_active` points to
`ntc_chunks_embed300m_v2_uploads_v1`; Qdrant reports green/optimizer-ok, Cosine distance,
2048 dimensions and 879 points. The older `ntc_chunks_local_v1` collection is not active
and has only one 768-dimensional fixture point. Qdrant reports `indexed_vectors_count=0`
because the active collection is below its `full_scan_threshold=10000`; it is therefore
using exact full scan today, not an HNSW graph. That is expected for the current corpus but
must be rechecked as the collection grows.

The reranker adapter remains disabled. The available historical comparison showed lower
recall (about 0.91 to 0.86) and higher p95 retrieval latency (about 23 to 72 ms) when the
threshold reranker was enabled. Enabling it merely to satisfy a checklist would reduce the
measured result; it needs a new held-out A/B and tuned candidate policy first.

## Evidence and stable citations

Each admitted block receives `C<chunk_uuid.hex>`. The prompt can cite it only as
`[CITE:C<32 lowercase hex>]`. Because the chunk UUID binds document version, position,
index version and text, the ID is stable across retrieval order and requests.

Citation metadata carries document/version/chunk IDs, source name, page, slide, section,
sheet/cell range or line range, score and verified state. Only the authorized excerpt is
sent in the SSE citation event and UI drawer; raw text is not retained in generation trace
objects.

## Output validation

The validator rejects unknown/malformed IDs, missing citations on grounded answers,
uncited grounded claims and hidden reasoning. It performs at most one constrained repair;
the second failure becomes `invalid_generation`. Prompt-only chat uses a separate system
prompt and requires no citation, but invented citation markers are still rejected.

The answer cache is off because a safe cache key must include recent turns, rolling
summary, semantic memory, active document versions, prompt hash, retrieval-policy hash and
response policy. Safe true streaming also remains open: today output is buffered until the
validator succeeds.

## Feature flags and open gate

`ENABLE_HYBRID_RETRIEVAL` can roll back lexical/RRF fusion. `ENABLE_RERANKER` defaults to
false. Stable citations and validation are correctness boundaries, not optional production
flags. Semantic claim-support verification beyond syntactic ID binding is not yet
implemented and is explicitly not claimed.

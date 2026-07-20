# Chatbot quality optimization progress

Plan source: `plan.md`. Snapshot: 2026-07-17.

| Plan area | Status | Evidence / remaining gap |
|---|---|---|
| Audit and baseline | Complete | Before architecture, audit and immutable baseline artifact exist |
| Nemotron runtime/generation | Partial | Correct NIM/NVFP4 winner, exact tokenizer, depth and reasoning policies live; BF16 A/B and Mamba cache dtype proof missing |
| Conversation memory | Implemented | Persistent exact turns, rolling summary, semantic memory, state, APIs and isolation tests |
| File ingestion | Implemented with open scale work | Streamed upload, queue retry, parsers, selective OCR, quality report and location metadata; long-file hierarchy pending |
| RAG retrieval/vector DB | Implemented except reranker | Qdrant active alias + 2048d Embed 300M vectors, ACL filters and dense/lexical RRF active; reranker deliberately off after negative historical result |
| Citations | Implemented, semantic verifier pending | Stable chunk-bound IDs, metadata/UI, validator and one repair; claim-level NLI/support scorer absent |
| Prompt architecture | Implemented | Separate general/RAG prompts, depth policy, memory/evidence ordering, prompt v8/hash |
| Latency | Partial | Parallel retrieval, concurrency cap, cache safety and measured runner; safe true streaming/dashboard matrix pending |
| Very long files | Partial | Parent-child chunks exist; hierarchical document summaries/map-reduce absent |
| Evaluation | Partial | No fake fallback, automated contracts and live smoke/benchmark; fixed 100+ quality suites not yet supplied |
| Fine-tuning | Deferred correctly | No LoRA/SFT attempted before system-level gates |

## Completed implementation

- [x] Forward migrations for message/memory, lexical retrieval, parse quality, location
  metadata, missing `conversation_documents` repair and active Embed 300M index-contract
  alignment (`0014_align_embed300m_index`).
- [x] Message persistence no longer depends on the enhanced-memory feature flag.
- [x] Exact recent-turn token budget, versioned rolling summary and explicit semantic memory.
- [x] Active document state reused by follow-ups.
- [x] Nemotron Fast/Reasoning/depth policies and 8192 adaptive multi-document cap.
- [x] Prompt-only requests invoke Nemotron instead of returning `insufficient_evidence`.
- [x] Dense and lexical retrieval run in parallel and fuse deterministically.
- [x] Qdrant active alias and vector contract verified live: `ntc_chunks_active` ->
  `ntc_chunks_embed300m_v2_uploads_v1`, Cosine/2048d, 879 points, green status.
- [x] Worker now records child `vector_id` and `embedding_model` in `app.chunks`; this
  fixes the previous DB/index telemetry mismatch for new or reprocessed documents.
- [x] Stable `[CITE:C<chunk UUID hex>]`, fail-closed validation and one repair pass.
- [x] Streamed/spooled upload, RabbitMQ retry/health repair, selective OCR and parse report.
- [x] XLSX, HTML and source-code provenance through API, PostgreSQL and Qdrant payloads.
- [x] Unsafe query-only final-answer cache removed.
- [x] Real-only eval/load scripts, full regression, live upload/RAG/follow-up smoke and
  prompt-only benchmark.

## Unmet production DoD

- [ ] Held-out reranker experiment that improves quality enough to justify latency.
- [ ] BF16 versus active NVFP4 comparison on the same chatbot eval set.
- [ ] Verified `mamba_ssm_cache_dtype=float32` control in the selected NIM profile.
- [ ] 100+ memory and 100+ citation answer-key scenarios plus blind answer-quality A/B.
- [ ] Semantic citation claim-support scorer.
- [ ] Hierarchical summaries/map-reduce for very long and multi-file questions.
- [ ] Safe incremental output validator for true token TTFT and a full latency dashboard.
- [ ] Repository-wide Prettier cleanup; changed web files pass, but 73 pre-existing files
  outside this scope still fail the global formatting gate.

The project is materially more correct and usable, but this document intentionally does
not label the full `plan.md` Definition of Done as complete.

# Phase 3 retriever metadata correction run

- Scope: Phase 3 only; targeted Embed 300M and Rerank 500M benchmark rerun.
- Parent acceptance run: `20260714T1120Z-full-r2`.
- Result: **PASS** for the targeted correction.
- Workload: 20 measured requests plus 2 warmup requests per scenario.
- Execution: Embed and Rerank ran concurrently, so this run is not used to
  replace the parent scorecard latency observations.

## Why this run exists

The parent run correctly executed the embedding and reranking workloads, but
their successful reports incorrectly described the LLM-only prompt uniqueness
control as `enabled`. The control was never applied to either retriever request.
The report generator now emits:

```json
{"llm_prompt_uniqueness_control":{"status":"not_applicable"}}
```

The corrected live reports are:

- `candidates/embedding-300m/benchmark/report.json`
- `candidates/reranking-500m/benchmark/report.json`

Both reports pass their exact two-scenario matrices, semantic sanity checks,
20 measured + 2 warmup counts, immutable candidate identity fields and the
corrected metadata assertion. No LLM, winner selection, ingestion, indexing or
Phase 4 workflow was run by this correction.

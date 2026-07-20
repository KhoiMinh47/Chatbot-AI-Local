# Chatbot evaluation methodology

## Rules

All reports must distinguish measured observations from fixtures and historical traffic.
The evaluator fails closed when a real retrieval observation file is absent; it never
substitutes mock recall or latency. User/document content is excluded from artifacts unless
the dataset is explicitly approved for evaluation.

## Reproducible commands

```bash
make eval-chatbot
make benchmark-chatbot NTC_BENCHMARK_TOKEN=<real-short-lived-token>
uv run pytest -q
pnpm --dir apps/web test
```

`make eval-chatbot` runs the current memory/citation/ingestion contracts and optionally
scores a real observation file. `scripts/phase12_rag_eval.py` refuses fake fallback data.
`scripts/load_test_rag.py` creates real conversations, consumes real SSE events and reports
request success, TTFT, total latency, throughput, tokens and outcomes.

## Current evidence

- Baseline snapshot: `artifacts/evals/baseline-2026-07-17.json`.
- Final implementation snapshot: `artifacts/evals/final-2026-07-17.json`.
- Contract evaluation: 22 passed; measured corpus scoring skipped because no approved real
  observation file was supplied.
- Full regression: 375 passed, 6 skipped; web: 12 passed; Python source type check:
  65 files.
- Live prompt-only Fast run: 3/3 answered, p50 TTFT 3786.01 ms, p95 TTFT 3813.88 ms,
  p50 total 3803.73 ms and p95 total 3835.66 ms. Because validated output is buffered,
  this is visible-answer latency rather than raw first decoder-token latency.
- Live RAG smoke: upload completed, 3 verified stable citations on the first question and
  2 on a follow-up without reattaching the document.

## Claims that are not allowed yet

No percentage quality improvement is claimed because the fixed 100+ memory, citation and
production-like Vietnamese answer-key suites required by `plan.md` have not been populated
and run. BF16/NVFP4 chatbot A/B, semantic claim support, long-document hierarchy and the
full input/output/concurrency performance matrix are also pending. The historical Phase 12
mock report is marked `invalid_mock_data` and cannot pass a gate.

The next evaluation owner should add approved datasets under `evals/datasets`, produce raw
observations under `evals/reports`, run blind baseline/candidate scoring, and only then set
numeric relative acceptance targets.

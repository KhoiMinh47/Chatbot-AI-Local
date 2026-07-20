# Evaluation runners

- `make eval-chatbot` runs the offline memory, citation, tokenizer, and ingestion
  contract gates. If `EVAL_OBSERVATIONS` and `EVAL_CONFIG_FINGERPRINT` are set, it
  also scores real retrieval observations against the 100-question gold set.
- `scripts/phase12_rag_eval.py` rejects missing/incomplete observations and has no
  mock fallback.
- `make benchmark-chatbot` measures the running HTTP/SSE path. Set
  `NTC_BENCHMARK_TOKEN`; use `scripts/load_test_rag.py --help` for concurrency, model
  mode, query, and document options.

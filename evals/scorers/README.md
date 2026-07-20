# Evaluation scorers

Retrieval scoring is implemented in `packages/rag-eval/src/ntc_rag_eval`. Reports
are bound to canonical dataset and observation hashes and expose Recall@5/10,
MRR@10, nDCG@10, context precision, no-answer behavior, and p50/p95 latency.

Citation format/allowlist/coverage and memory isolation are fail-closed executable
contracts in the application test suite. Semantic claim-support judging remains a
separate, currently unclosed acceptance item; deterministic citation validity must
not be mislabeled as semantic precision.

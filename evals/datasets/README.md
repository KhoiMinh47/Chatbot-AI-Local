# Evaluation datasets

The fixed 100-question Vietnamese/English retrieval gold set remains at
`benchmarks/phase5/gold.jsonl`, with its source corpus at
`benchmarks/phase5/corpus.jsonl`. Keeping the existing immutable paths preserves all
historical hashes and Phase 5 receipts.

Memory, citation, exact-token, and parse-quality contract scenarios are executable
fixtures in the corresponding API/worker test modules. They are run by
`make eval-chatbot` and reported to `evals/reports/chatbot-contract.xml`.

Production answer-quality evaluation still requires a permitted real corpus and a
blind human A/B annotation set. No synthetic model score is accepted as a substitute.

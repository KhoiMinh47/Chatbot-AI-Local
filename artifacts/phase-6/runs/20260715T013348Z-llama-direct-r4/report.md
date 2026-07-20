# Phase 6 live direct-evidence candidate r4

- Status: **PASS in direct synthetic candidate scope**
- Production activation status: **BLOCKED**
- JSON SHA-256:
  `9cc37a8440391935a0924239268a86fffffbc46aa7a4d5ac6fde0d507b8978e1`
- Model: `meta/llama-3.1-8b-instruct`
- NIM: `2.0.6`, pinned image and ARM64 manifest recorded in `report.json`
- Prompt: `phase6-grounded-v3`
- Graph: `phase6-stategraph-v1`
- Exact tokenizer SHA-256:
  `5d14a41f5b175a0b6d8f7d25896913fe9c2b0ca111c2180ffa2a1e805b2720f0`

## Same-question mode evidence

| Observation | Fast | Reasoning |
|---|---:|---:|
| Retrieval queries | 1 | 3 |
| Retrieval calls | 1 | 3 |
| Output reserve | 768 tokens | 4096 tokens |
| Exact prompt count | 338 | 338 |
| NIM prompt usage | 338 | 338 |
| End-to-end candidate latency | 0.702653 s | 0.704587 s |
| Outcome | answered | answered |
| Citation | S1 | S1 |

Both modes returned:

```text
Nhân viên toàn thời gian có 15 ngày phép năm [S1].
```

The latency values are one warm candidate observation, not p50/p95 or a
production performance claim. The material mode evidence is the bounded graph
path and budget difference.

## Refusal and safety

The no-evidence question returned `insufficient_evidence`, emitted no citation,
and did not call the LLM. Every event sequence was contiguous. No visible answer
contained hidden-reasoning markers. Prompt tokens plus output and safety reserves
remained within the configured context window.

The source is intentionally synthetic and passed directly to the retrieval port.
This run does not prove Phase 4 ingestion, Phase 5 vector quality, real-document
semantic groundedness, or a production winner.

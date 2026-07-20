# Phase 6 canonical binding inventory

This inventory is derived from canonical report
`20260715T025554Z-nemotron-embed300m-winner-r7`. Values below are exact unless
explicitly labeled as an upstream Phase 3 selection binding.

## Canonical report

| Field | Value |
|---|---|
| Status | `PASS`, `acceptance_pass=true` |
| Scope | `phase6-live-winner-e2e-no-phase7-surface` |
| Report SHA-256 | `07701b7ba3ca0e694726753ab92442a3b98f5280c514328346f81fa00a9f264f` |
| Source-provenance aggregate SHA-256 | `aea8338d28fd4d6bb982b038495e3bf5b40e304a1581f653c03a98a9de9e711c` |
| Prompt | `phase6-grounded-v4`, SHA-256 `d6199475354b9cf097aaaf7f04a274b8d37f427a1a6575a8fea4490cf81a89c3` |
| Graph | `phase6-stategraph-v2` |

## Model and tokenizer

| Field | Value |
|---|---|
| LLM | `nvidia/nemotron-nano-9b-v2` |
| LLM NIM version | `1.0.0` |
| Live LLM `/models` IDs | only `nvidia/nemotron-nano-9b-v2` |
| Fast / Reasoning control | `/no_think` / `/think` |
| Tokenizer ID | `nvidia/nemotron-nano-9b-v2` |
| Tokenizer SHA-256 | `32bd2509c1acc93dc18bdd0f9a2d9a15e72fd3110f24cfc9ff3fb820f4e20b6b` |
| Exact counter and NIM usage | matched |
| Embedding | `nvidia/llama-nemotron-embed-300m-v2` |
| Embedding NIM version/dimension | `1.13.0` / `2048` |
| Live embedding `/models` IDs | only `nvidia/llama-nemotron-embed-300m-v2` |

The Phase 3 upstream selection binds the Nemotron NIM image digest
`sha256:82028e38ab950edd32f5053ca2030ee14d965e8fd4fe1c6e06468eb0be07a9a4`,
NVFP4 profile
`f9db61d5a467d46be7733e90a26705798764b93d480c842143d525c1932b01e2`
and maximum model length `131072`. Canonical r7 directly verifies the served
model ID/version and tokenizer; it does not claim to re-hash the container
image. See
[`ADR 0007`](../../docs/adr/0007-nemotron-nano-9b-v2-local-engineering-winner.md).

## Active retrieval configuration

| Field | Value |
|---|---|
| Alias | `ntc_chunks_active` |
| Physical collection | `ntc_chunks_embed300m_v2_s256_o10_095bc081a101_recall95_v3` |
| Expected point count | `12` |
| Index version | `embed300m-v2-phase4` |
| Chunk size / overlap | `256` / `10%` |
| Distance | `Cosine` |
| Index fingerprint | `a3cc25bb8e65a03ac1146c227c4c2b8c5a86370f4852eb35eb4d66330dd20290` |
| Retrieval-policy fingerprint | `37a6fb7d83d292ba67f7709ce5e8e77483a73b86cd470938486d37b2d38c65b8` |
| Dense threshold | `0.2300481` |
| Dense candidate / final limits | `20` / `10` |
| HNSW ef | `128` |
| Dedup | `content_hash_and_document_section_v1` |
| Reranker | disabled; model/version/threshold null |

The retrieval-policy fingerprint above binds the approved Phase 5 base dense
ceiling `20`, not the mode-specific effective top-k. Graph v2 resolves
`min(base, mode cap)`, producing Fast `12` and Reasoning `10`, and passes that
cap to the actual Qdrant search. The mode binding, Graph v2 identifier and source
provenance must be checked together; the policy fingerprint alone is
insufficient evidence for those two effective limits.

## Upstream input artifacts

| Artifact | SHA-256 |
|---|---|
| [`gold-final-100-v2-stratified.jsonl`](../phase-4/runs/20260715T0912Z-live-e2e-r3/gold-final-100-v2-stratified.jsonl) | `393c9147f6a59a41e1a038a7622dc7d4183571fb4a1aa3a1940514629c155ca3` |
| [Phase 5 decision report](../phase-5/runs/20260715T022157Z-embed300m-final-r3/decision-report.json) | `290d1b34f7c350658207dea14c8e1f045314fc2126c3522adeecf1eea12cb610` |
| [Phase 5 activation receipt](../phase-5/runs/20260715T022157Z-embed300m-final-r3/activation-receipt.json) | `2b0f68582a8e1398b4507e73a596887fa271cf33308456efeb294225f08fd76f` |
| [`0005_phase6_winner_trace_binding.py`](../../migrations/versions/0005_phase6_winner_trace_binding.py) | `7668b4e05a5b5d91b0053b3e5ec56013fde8dd1f6db97b37e6e7215683c1f985` |
| [`phase6_winner_e2e.py`](../../scripts/phase6_winner_e2e.py) | `b997b608c64732ff9c686b2450a4dd9da3737172a14cfbbcc700d2e92a220c10` |

Phase 5 run ID: `20260715T022157Z-embed300m-final-r3`. Its activation receipt
records `alias_verified=true`, the same index/policy fingerprints, and exact
readback of the physical collection.

## Canonical observations

| Path | Outcome | Elapsed | LLM calls | Citation/context |
|---|---|---:|---|---|
| Fast answerable `p4-001-v1` | answered | `1.166743 s` | chat 0, stream 1 | `S1`, 1 context ref |
| Reasoning answerable `p4-001-v1` | answered | `9.394018 s` | chat 1, stream 1 | `S1`, 1 context ref |
| Fast unanswerable `p4-019-v1` | insufficient evidence | `0.029814 s` | chat 0, stream 0 | no citation/context |
| Owner ACL probe | expected source | n/a | Embed only | 1 hit |
| Unrelated ACL probe | empty | n/a | Embed only | 0 hits |

These are single live observations. The report stores hashes and safe metadata,
not the raw questions or visible answers.

## Winner-bound run trail

| Run | Report SHA-256 | Status |
|---|---|---|
| `20260715T022730Z-nemotron-embed300m-winner-r1` | `5fbbd8ad673a537597acf05bc795dc64f09d59c4f511983bbd391725adcf6e8a` | FAIL |
| `20260715T022911Z-nemotron-embed300m-winner-r2` | `8233579a3e22f3f783ff2b13a2ea534484f77080ca1b8a5ec758bd1ca0a9f85a` | FAIL |
| `20260715T023134Z-nemotron-embed300m-winner-r3` | `3537d1f5e6674d857d528bff012030c540168482b17374cae24328af24a89272` | PASS but old-gold/noncanonical |
| `20260715T023547Z-nemotron-embed300m-winner-r4` | `fa6f1b0048ed0f802f81d0d3f64715ffa27e2d6be127c0d3cfdf94fbe45f9f25` | FAIL |
| `20260715T023711Z-nemotron-embed300m-winner-r5` | `07ac5aa689c19903c2d0d88332534cadf71b21c75a10ce866617b884c3745c40` | PASS historical; pre-format-gate source snapshot |
| `20260715T024856Z-nemotron-embed300m-winner-r6` | `4d3ba5c299a00824ee5b81e1b59f6510f66845854a80c0c61ae1301ff087ee53` | PASS historical; mode cap not enforced in actual Qdrant call |
| `20260715T025554Z-nemotron-embed300m-winner-r7` | `07701b7ba3ca0e694726753ab92442a3b98f5280c514328346f81fa00a9f264f` | **PASS canonical/current source + effective caps** |

No report in this inventory authorizes Phase 7 or resolves corporate legal,
Phase 10 performance, or full release human-evaluation gates.

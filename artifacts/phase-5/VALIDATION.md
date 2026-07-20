# Phase 5 validation report

- Date: 2026-07-15
- Status: **PASS / COMPLETE** for local engineering
- Acceptance: **4/4**
- Canonical run: `20260715T022157Z-embed300m-final-r3`

The previous validation snapshot described the provisional synthetic run
`20260714T175000Z-embed300m-r5` as BLOCKED. It is retained in historical run
artifacts, but it is no longer the Phase 5 conclusion. The canonical run now
uses the real Phase 4 ingestion output, a held-out split, an explicit operator
decision and an atomic alias activation receipt.

The split is held out from numeric threshold fitting, but it is not an untouched
release holdout: the failed `r2` evaluation was inspected before the calibration
objective changed for `r3`. Acceptance thresholds stayed fixed; Phase 12 still
needs a fresh frozen test set that has not informed method selection.

## Validated winner

| Contract | Value |
|---|---|
| Model | `nvidia/llama-nemotron-embed-300m-v2` |
| Version / dimension | `1.13.0` / `2048` |
| Chunk | `256`, overlap `10%` |
| Threshold | `0.2300481` |
| Index fingerprint | `a3cc25bb8e65a03ac1146c227c4c2b8c5a86370f4852eb35eb4d66330dd20290` |
| Policy fingerprint | `37a6fb7d83d292ba67f7709ce5e8e77483a73b86cd470938486d37b2d38c65b8` |
| Collection | `ntc_chunks_embed300m_v2_s256_o10_095bc081a101_recall95_v3` |
| Alias | `ntc_chunks_active` (verified) |

Input: 10 READY documents, 10 current versions and 12 child chunks from Phase
4. Gold: 100 stratified cases, 50 calibration and 50 held-out evaluation, gold
SHA-256
`393c9147f6a59a41e1a038a7622dc7d4183571fb4a1aa3a1940514629c155ca3`.

Held-out approved-policy metrics:

```text
Recall@5 = 1.0
Recall@10 = 1.0
MRR@10 = 1.0
nDCG@10 = 1.0
Context precision@10 = 0.9375
p50 / p95 = 16.09 / 58.23 ms
unanswerable_nonempty_rate = 0.1
```

The last value is diagnostic: one of ten unanswerable retrieval queries still
returned a dense candidate. It is not an incorrect generated answer. Phase 6
owns the insufficient-evidence/refusal acceptance gate.

## Evidence integrity and security

- Decision report SHA-256:
  `290d1b34f7c350658207dea14c8e1f045314fc2126c3522adeecf1eea12cb610`.
- Activation receipt SHA-256:
  `2b0f68582a8e1398b4507e73a596887fa271cf33308456efeb294225f08fd76f`.
- Live ACL/dimension JUnit SHA-256:
  `f62ff66e3ed876efec12ac32645b13b79e2bbf874c06f8c220ba123ea18d789c`;
  one test passed with zero failures, errors or skips.
- Decision report records neither database URL nor document plaintext.
- Receipt binds decision hash, both fingerprints and expected point count.
- Live alias read-back and collection metadata match the receipt.

BGE-M3 same-gold comparison remains unexecuted because the exact NGC source
returns HTTP `402`. The workspace operator explicitly waived that comparison
and selected Embed-300M; the report does not mislabel BGE-M3 as tested.

Full acceptance details: [`acceptance.md`](acceptance.md). Hash inventory:
[`INVENTORY.md`](INVENTORY.md). Completion checklist:
[`COMPLETION.md`](COMPLETION.md).

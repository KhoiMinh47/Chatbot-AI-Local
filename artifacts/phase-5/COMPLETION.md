# Phase 5 completion record

- Completed: 2026-07-15
- Scope: local engineering Phase 5 only
- Status: **COMPLETE / PASS**
- Acceptance: **4/4**
- Canonical run: `20260715T022157Z-embed300m-final-r3`

## What was completed

- [x] Chạy embedding batch trên 12 current child chunk lấy từ 10 READY document
  của Phase 4.
- [x] Khóa exact Embed-300M identity: model
  `nvidia/llama-nemotron-embed-300m-v2`, version `1.13.0`, dimension `2048`.
- [x] Tạo durable physical Qdrant collection với immutable metadata và
  `points_count=12`, state `green`.
- [x] Tách 100 gold case thành 50 calibration/50 held-out evaluation; mỗi split
  có 40 answerable và 10 unanswerable.
- [x] Fit threshold chỉ trên calibration split với recall floor `0.95`.
- [x] Held-out Recall@10/MRR@10/nDCG@10 đều `1.0`; quality gate pass.
- [x] Chốt retrieval policy threshold `0.2300481`, candidate/final `20/10`,
  `hnsw_ef=128`, reranker off, dedup policy versioned.
- [x] Ghi immutable decision report trước activation và bind SHA-256 trong
  activation receipt.
- [x] Atomic switch `ntc_chunks_active`, read-back đúng winner collection.
- [x] Live ACL/dimension contract test pass: 1 test, 0 failure/error/skip.
- [x] Giữ `r1` và `r2` là rejected evidence; không backfill thành PASS.
- [x] Ghi BGE-M3 comparison là explicitly waived, không ghi như đã benchmark.

## Final winner

```text
model: nvidia/llama-nemotron-embed-300m-v2
version: 1.13.0
dimension: 2048
distance: Cosine
chunk: 256 / 10%
index version: embed300m-v2-phase4
collection: ntc_chunks_embed300m_v2_s256_o10_095bc081a101_recall95_v3
index fingerprint: a3cc25bb8e65a03ac1146c227c4c2b8c5a86370f4852eb35eb4d66330dd20290
retrieval policy fingerprint: 37a6fb7d83d292ba67f7709ce5e8e77483a73b86cd470938486d37b2d38c65b8
alias: ntc_chunks_active
```

## Evidence closure

| Evidence | SHA-256 |
|---|---|
| `decision-report.json` | `290d1b34f7c350658207dea14c8e1f045314fc2126c3522adeecf1eea12cb610` |
| `activation-receipt.json` | `2b0f68582a8e1398b4507e73a596887fa271cf33308456efeb294225f08fd76f` |
| Gold 100 v2 stratified | `393c9147f6a59a41e1a038a7622dc7d4183571fb4a1aa3a1940514629c155ca3` |
| READY corpus manifest | `095bc081a101f02197934cdc8849c20287fba99aeede3d6730ea94ffa55b5bac` |
| Live ACL/dimension JUnit | `f62ff66e3ed876efec12ac32645b13b79e2bbf874c06f8c220ba123ea18d789c` |

Receipt xác nhận decision SHA, expected point count, index fingerprint,
retrieval-policy fingerprint và alias read-back. Xem chi tiết tại
[`acceptance.md`](acceptance.md) và [`INVENTORY.md`](INVENTORY.md).

## Boundary còn lại

`unanswerable_nonempty_rate=0.1` chỉ nói 1/10 unanswerable query còn dense
candidate; nó không nói chatbot đã trả lời. Insufficient-evidence/refusal,
grounded answer và citation validation là acceptance của Phase 6.

BGE-M3 same-gold comparison vẫn chưa chạy vì exact NGC source trả HTTP `402`.
Operator đã waive comparison và chọn Embed-300M cho local engineering. Corporate
legal/license approval cho phát hành thương mại, nếu cần, là gate riêng ngoài
completion record kỹ thuật này.

Evaluation split đã được xem ở failed `r2` trước khi chọn objective
recall-first cho `r3`; do đó kết quả này đóng Phase 5 engineering regression,
không thay cho một blind release holdout mới ở Phase 12.

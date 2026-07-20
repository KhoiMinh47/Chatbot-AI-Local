# Phase 5 artifacts

Trạng thái tổng thể: **PASS — 4/4 acceptance criteria** cho local engineering.
Embed-300M đã được chốt làm embedding winner, physical collection đã ở trạng
thái `green`, và alias `ntc_chunks_active` đã được switch rồi read-back đúng.

## Evidence chuẩn

- Acceptance mapping: [`acceptance.md`](acceptance.md)
- Completion record: [`COMPLETION.md`](COMPLETION.md)
- Artifact inventory và SHA-256: [`INVENTORY.md`](INVENTORY.md)
- Decision report:
  [`runs/20260715T022157Z-embed300m-final-r3/decision-report.json`](runs/20260715T022157Z-embed300m-final-r3/decision-report.json)
  — SHA-256 `290d1b34f7c350658207dea14c8e1f045314fc2126c3522adeecf1eea12cb610`
- Activation receipt:
  [`runs/20260715T022157Z-embed300m-final-r3/activation-receipt.json`](runs/20260715T022157Z-embed300m-final-r3/activation-receipt.json)
  — SHA-256 `2b0f68582a8e1398b4507e73a596887fa271cf33308456efeb294225f08fd76f`
- Live ACL/dimension JUnit:
  [`runs/20260715T022157Z-embed300m-final-r3/acl-qdrant-contract.xml`](runs/20260715T022157Z-embed300m-final-r3/acl-qdrant-contract.xml)
  — SHA-256 `f62ff66e3ed876efec12ac32645b13b79e2bbf874c06f8c220ba123ea18d789c`

## Winner đã activate

```text
embedding: nvidia/llama-nemotron-embed-300m-v2
model version: 1.13.0
dimension / distance: 2048 / Cosine
chunk: 256 tokens, overlap 10%
dense candidates / final: 20 / 10
threshold: 0.2300481
hnsw_ef: 128
reranker: off
collection: ntc_chunks_embed300m_v2_s256_o10_095bc081a101_recall95_v3
active alias: ntc_chunks_active
```

Winner dùng 10 document/10 READY current version/12 child chunk lấy trực tiếp
từ corpus Phase 4 đã ingest end-to-end. Gold set có 100 case, tách cố định 50
calibration và 50 evaluation; mỗi split gồm 40 answerable và 10 unanswerable.
Gold SHA-256 là
`393c9147f6a59a41e1a038a7622dc7d4183571fb4a1aa3a1940514629c155ca3`.

Held-out evaluation của approved policy đạt Recall@10, MRR@10 và nDCG@10 đều
`1.0`; context precision@10 `0.9375`; p50/p95 `16.09/58.23 ms`. Chỉ số
`unanswerable_nonempty_rate=0.1` nghĩa là 1/10 câu unanswerable vẫn nhận ít nhất
một dense candidate sau threshold. Đây là diagnostic của retriever, không phải
chatbot đã trả lời sai; Phase 6 sở hữu gate insufficient-evidence/refusal.

## Lịch sử debug không được dùng làm winner

- `20260715T021639Z-embed300m-final` (`r1`): **REJECTED**, dùng gold query bản
  đầu, held-out Recall/MRR `0.65` và không activate alias.
- `20260715T022021Z-embed300m-final-r2` (`r2`): **REJECTED**, max-F1 threshold
  `0.3152053` làm calibration recall còn `0.875` và held-out Recall `0.775`;
  không activate alias.
- `20260715T022157Z-embed300m-final-r3`: đổi sang calibration-only policy
  `minimum recall 0.95, rồi tối đa precision`; held-out gate pass và mới được
  activate.

Các benchmark `20260714...` vẫn là candidate/synthetic history, không thay thế
canonical finalization run ở trên. BGE-M3 same-gold comparison không được giả
vờ là đã chạy: workspace operator đã **explicitly waive** comparison vì exact
NGC source vẫn trả HTTP `402`, đồng thời chỉ định Embed-300M cho local
engineering activation.

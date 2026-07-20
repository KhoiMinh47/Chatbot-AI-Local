# Phase 5 acceptance evidence

- Phạm vi: Phase 5 — Embedding, Qdrant và Retrieval Benchmark
- Master plan: `NTC_NVIDIA_LOCAL_RAG_CHATBOT_MASTER_PLAN.md`, mục Phase 5
- Run chuẩn: `artifacts/phase-5/runs/20260715T022157Z-embed300m-final-r3`
- Kết quả: **PASS — 4/4 acceptance criteria** cho local engineering
- Winner: `nvidia/llama-nemotron-embed-300m-v2` version `1.13.0`
- Active alias: `ntc_chunks_active` →
  `ntc_chunks_embed300m_v2_s256_o10_095bc081a101_recall95_v3`
- Phase boundary: refusal/generation/citation vẫn thuộc Phase 6

## Đối chiếu từng acceptance criterion

| Acceptance Phase 5 | Kết quả | Evidence |
|---|---|---|
| Recall/MRR/nDCG report tái lập được | **PASS** | Decision report khóa input/runtime/source hashes, 3 observation JSONL và exact policy. Held-out approved policy: Recall@5/10 `1.0`, MRR@10 `1.0`, nDCG@10 `1.0`, context precision@10 `0.9375`; p50/p95 `16.09/58.23 ms` |
| Không đổi vector dimension trong cùng collection | **PASS** | Winner collection metadata là dimension `2048`, Cosine, exact model/version/config fingerprint. Live integration test chứng minh dimension/model drift trên cùng physical collection bị `CollectionContractError` |
| ACL test chứng minh user không retrieve tài liệu trái quyền | **PASS** | Live Qdrant test dùng 2 tenant và 2 user, mỗi scope chỉ nhận point được phép; JUnit `1 passed`, không skip/failure/error. Alias winner không đổi trong lúc test |
| Có config winner và lý do | **PASS** | Operator chỉ định Embed-300M; calibration giữ recall floor; held-out gate pass; reranker off; decision hash được bind vào activation receipt và alias được read-back đúng |

## Input corpus và gold set

Finalizer đọc authoritative READY rows từ PostgreSQL của Phase 4, không dựng
synthetic text trong Phase 5:

| Input | Giá trị |
|---|---:|
| READY document | 10 |
| READY current version | 10 |
| Current child chunk | 12 |
| Chunk size / overlap | 256 / 10% |
| Corpus manifest SHA-256 | `095bc081a101f02197934cdc8849c20287fba99aeede3d6730ea94ffa55b5bac` |

Corpus gồm 10 source đã đi qua ingestion E2E: PDF text, scanned PDF/OCR,
table PDF, hai PPTX, DOCX, TXT, Markdown và hai CSV. Đây là corpus file hợp lệ,
không chứa dữ liệu doanh nghiệp nhạy cảm.

Gold chuẩn là
[`../phase-4/runs/20260715T0912Z-live-e2e-r3/gold-final-100-v2-stratified.jsonl`](../phase-4/runs/20260715T0912Z-live-e2e-r3/gold-final-100-v2-stratified.jsonl),
SHA-256
`393c9147f6a59a41e1a038a7622dc7d4183571fb4a1aa3a1940514629c155ca3`.
Gold có 100 case và bao phủ cả 10 source:

- calibration: 50 case = 40 answerable + 10 unanswerable;
- evaluation held-out: 50 case = 40 answerable + 10 unanswerable;
- language: 75 English + 25 Vietnamese;
- evaluation không được dùng để fit **giá trị số** của threshold.

Methodology note: kết quả evaluation của `r2` đã được xem để chẩn đoán việc
max-F1 làm recall calibration tụt xuống `0.875`, rồi objective được đổi sang
recall-first trước `r3`. Vì vậy 50 case này là evaluation/regression split có
leakage ở mức **chọn phương pháp**, không còn là blind release holdout hoàn
toàn chưa từng quan sát. Threshold `0.2300481` vẫn chỉ được tính từ calibration
và các gate Recall/MRR không bị hạ. Trước release phải chạy một test set mới,
đóng băng và chưa dùng để tune ở Phase 12.

Dataset hash mà evaluator tạo cho riêng 50 held-out case là
`31f83b428bc1d0432758068a93e44733c768966a33a067e33f97de1c810b3bfe`.

## Exact winner contract

| Trường | Winner value |
|---|---|
| Embedding model | `nvidia/llama-nemotron-embed-300m-v2` |
| Model version | `1.13.0` |
| Vector dimension / distance | `2048` / `Cosine` |
| Index version | `embed300m-v2-phase4` |
| Chunk size / overlap | `256` / `10%` |
| Physical collection | `ntc_chunks_embed300m_v2_s256_o10_095bc081a101_recall95_v3` |
| Expected / observed points | `12` / `12` |
| Collection state | `green` |
| Index config fingerprint | `a3cc25bb8e65a03ac1146c227c4c2b8c5a86370f4852eb35eb4d66330dd20290` |
| Dense candidate / final limit | `20` / `10` |
| Dense threshold | `0.2300481` |
| HNSW ef | `128` |
| Reranker | `off` |
| Dedup policy | `content_hash_and_document_section_v1` |
| Retrieval policy fingerprint | `37a6fb7d83d292ba67f7709ce5e8e77483a73b86cd470938486d37b2d38c65b8` |

Index fingerprint khóa physical vector contract. Retrieval-policy fingerprint
khóa thêm threshold, candidate/final limits, `hnsw_ef`, reranker state và dedup
policy. Phase 6 phải bind cả hai, không chỉ model name hoặc collection alias.

## Threshold calibration

Threshold chỉ được fit trên 50 calibration case. Mỗi query giữ tối đa 10 source
score, tạo 40 relevant positives và 460 negatives. Policy chọn threshold có
recall tối thiểu `0.95`, sau đó tối đa precision:

| Calibration metric | Kết quả |
|---|---:|
| Threshold | `0.2300481` |
| Precision | `0.8666667` |
| Recall | `0.975` |
| F1 | `0.9176471` |
| TP / FP / FN | `39 / 6 / 1` |

Max-F1 diagnostic cho threshold `0.3152053` có precision `0.9722222` nhưng
recall chỉ `0.875`. `r2` cho thấy threshold này làm evaluation Recall@10 còn
`0.775`, nên objective được đổi có audit trail; acceptance gate vẫn giữ nguyên.
Do thay đổi phương pháp sau khi quan sát `r2`, giới hạn blind-holdout được ghi
rõ ở trên thay vì gọi `r3` là release-quality test.

## Held-out evaluation

| Metric | Raw dense | Approved policy |
|---|---:|---:|
| Recall@5 | 1.0000 | 1.0000 |
| Recall@10 | 1.0000 | 1.0000 |
| MRR@10 | 1.0000 | 1.0000 |
| nDCG@10 | 1.0000 | 1.0000 |
| Context precision@10 | 0.1000 | 0.9375 |
| Unanswerable non-empty rate | 1.0000 | 0.1000 |
| Client p50 | 15.81 ms | 16.09 ms |
| Client p95 | 19.87 ms | 58.23 ms |

Latency đo toàn bộ `DenseRetriever.retrieve` phía client cho từng query, gồm
query embedding, Qdrant search và policy processing; đây không phải server-only
Qdrant latency.

`unanswerable_nonempty_rate=0.1` nghĩa là đúng **1/10** held-out unanswerable
query còn ít nhất một candidate sau threshold. Nó không có nghĩa LLM đã trả lời
câu đó, cũng không phải 10% answer hallucination. Dense cosine retrieval không
phải open-set classifier hoàn hảo; Phase 5 ghi chỉ số này làm diagnostic. Gate
"Unanswerable test từ chối đúng" nằm ở Phase 6, nơi insufficient-evidence branch
và citation validator có thể quyết định từ chối dựa trên nội dung retrieved.

## Activation và evidence binding

Decision report được ghi immutable trước khi switch alias:

- [`runs/20260715T022157Z-embed300m-final-r3/decision-report.json`](runs/20260715T022157Z-embed300m-final-r3/decision-report.json)
  — SHA-256 `290d1b34f7c350658207dea14c8e1f045314fc2126c3522adeecf1eea12cb610`;
- [`runs/20260715T022157Z-embed300m-final-r3/activation-receipt.json`](runs/20260715T022157Z-embed300m-final-r3/activation-receipt.json)
  — SHA-256 `2b0f68582a8e1398b4507e73a596887fa271cf33308456efeb294225f08fd76f`.

Receipt bind đúng decision SHA, index fingerprint, retrieval-policy fingerprint,
expected point count `12` và operator. Atomic activation ghi:

```text
previous_alias_target: null
alias: ntc_chunks_active
activated_collection: ntc_chunks_embed300m_v2_s256_o10_095bc081a101_recall95_v3
alias_readback: ntc_chunks_embed300m_v2_s256_o10_095bc081a101_recall95_v3
alias_verified: true
```

Live read-back ngày 2026-07-15 vẫn thấy alias trỏ đúng collection, state
`green`, `points_count=12`, dimension `2048`, model/version và index fingerprint
khớp receipt.

## ACL và immutable collection contract

Live command:

```text
PHASE5_QDRANT_URL=http://<private-qdrant-ip>:6333 \
  uv run --locked --no-sync pytest -q \
  tests/test_phase5_qdrant_integration.py \
  --junitxml=artifacts/phase-5/runs/20260715T022157Z-embed300m-final-r3/acl-qdrant-contract.xml

1 passed
```

JUnit:
[`runs/20260715T022157Z-embed300m-final-r3/acl-qdrant-contract.xml`](runs/20260715T022157Z-embed300m-final-r3/acl-qdrant-contract.xml),
SHA-256
`f62ff66e3ed876efec12ac32645b13b79e2bbf874c06f8c220ba123ea18d789c`;
`tests=1`, `failures=0`, `errors=0`, `skipped=0`.

Test chứng minh đồng thời:

1. tenant + ACL principals được filter trong Qdrant query;
2. response được validate fail-closed;
3. đổi dimension hoặc model metadata trên cùng collection bị từ chối;
4. temporary test collection được cleanup;
5. `ntc_chunks_active` vẫn trỏ winner trước và sau test.

## BGE-M3 waiver và phạm vi phê duyệt

Exact BGE-M3 NGC source vẫn trả HTTP `402`, nên same-gold comparison **không
được chạy** và không được ghi là PASS. Workspace operator đã explicitly chọn
Embed-300M và waive comparison này cho local engineering activation. Waiver
reason được lưu nguyên văn trong decision report; đây là decision có audit trail,
không phải runner tự động coi candidate còn thiếu là winner.

Waiver chỉ chốt lựa chọn kỹ thuật trong workspace. Nếu phát hành thương mại cần
corporate legal/license review riêng, việc đó không thay đổi 4 acceptance
criteria kỹ thuật của Phase 5.

## Failed-run history

| Run | Status | Nguyên nhân và kết quả | Alias |
|---|---|---|---|
| `20260715T021639Z-embed300m-final` (`r1`) | **REJECTED** | Gold query bản đầu và threshold `0.3152053`; held-out Recall/MRR/nDCG `0.65` | Không activate |
| `20260715T022021Z-embed300m-final-r2` (`r2`) | **REJECTED** | Gold v2 stratified nhưng max-F1 threshold giữ calibration recall `0.875`; held-out Recall/MRR/nDCG `0.775`, dưới Recall gate `0.90` | Không activate |
| `20260715T022157Z-embed300m-final-r3` | **APPROVED_FOR_ACTIVATION / ACTIVATED** | Calibration-only recall-first threshold; held-out quality gate pass | `ntc_chunks_active` verified |

Hai rejected physical collections hiện chỉ là debug history và không được alias
`ntc_chunks_active` tham chiếu. Các candidate run `20260714...` cũng không được
dùng thay canonical finalization evidence.

## Kết luận và Phase boundary

Phase 5 đã có reproducible retrieval report, immutable vector contract, live
ACL proof và config winner có lý do; do đó **PASS 4/4**. Phase 6 phải dùng active
alias cùng exact index/retrieval-policy fingerprints và chịu trách nhiệm cho
grounded generation, citation validation, context budget và unanswerable
refusal. Tài liệu này không tuyên bố các acceptance criterion của Phase 6 đã đạt.

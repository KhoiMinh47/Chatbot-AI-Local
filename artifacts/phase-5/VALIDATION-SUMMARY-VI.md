# Tóm tắt validation Phase 5

- Ngày: 2026-07-15
- Trạng thái: **PASS / HOÀN THÀNH** cho local engineering
- Acceptance: **4/4**
- Run chuẩn: `20260715T022157Z-embed300m-final-r3`

Embed-300M đã được chốt và activate:

```text
nvidia/llama-nemotron-embed-300m-v2 1.13.0
dimension 2048, Cosine
chunk 256, overlap 10%
threshold 0.2300481
reranker off
alias ntc_chunks_active
```

Finalizer dùng 10 READY document/10 current version/12 child chunk từ pipeline
Phase 4 thật. Gold 100 case được tách 50 calibration và 50 evaluation; mỗi split
có 40 answerable và 10 unanswerable. Threshold chỉ fit trên calibration split.

Held-out approved policy đạt Recall@10, MRR@10, nDCG@10 đều `1.0`, context
precision `0.9375`, p50/p95 `16.09/58.23 ms`. Live ACL/dimension integration
test pass `1/1`, không skip; alias vẫn trỏ exact winner collection có 12 point,
state `green`.

`unanswerable_nonempty_rate=0.1` là diagnostic: 1/10 câu unanswerable còn nhận
dense candidate. Nó không phải chatbot answer sai; refusal/citation gate thuộc
Phase 6.

Hai lần chạy trước được giữ đúng trạng thái:

- `r1`: REJECTED, held-out Recall/MRR/nDCG `0.65`, không activate;
- `r2`: REJECTED, threshold max-F1 làm held-out Recall `0.775`, không activate;
- `r3`: recall-first calibration pass và alias được activate/read-back.

BGE-M3 chưa được benchmark do NGC HTTP `402`; operator đã explicitly waive
same-gold comparison và chọn Embed-300M. Waiver này được ghi trong immutable
decision report, không bị trình bày sai thành comparison PASS.

Chi tiết: [`acceptance.md`](acceptance.md). SHA-256 inventory:
[`INVENTORY.md`](INVENTORY.md). Completion: [`COMPLETION.md`](COMPLETION.md).

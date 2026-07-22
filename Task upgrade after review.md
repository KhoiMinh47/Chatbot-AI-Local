# Task Upgrade After Review

## Mục tiêu

Nâng cấp project từ hybrid RAG baseline hiện tại lên pipeline ổn định hơn cho PDF dài, bảng dữ liệu và câu trả lời có kiểm chứng.

## Ưu tiên cao

### 1. Parse PDF dài theo batch

- Chia PDF thành các page batch, ví dụ 10–30 trang/batch.
- Mỗi batch có trạng thái, checkpoint và retry riêng.
- Khi một batch lỗi, chỉ chạy lại batch đó.
- Giữ heading context giữa các batch.
- Lưu kết quả parse trung gian theo batch.

### 2. Biến `needs_review` thành quality gate thật

- Coverage đạt ngưỡng: cho phép chunk/index/publish.
- Coverage thấp: thử OCR hoặc fallback parser.
- Vẫn không đạt: dừng index và chuyển manual review.
- Không đặt document thành `ready` nếu quality gate chưa pass.
- Lưu missing pages, missing blocks, reading-order issues và OCR confidence.

### 3. Cải thiện table-aware chunking

- Không cắt giữa row hoặc cell.
- Bảng dài phải chia theo row hoàn chỉnh.
- Lặp lại header ở mỗi chunk mới.
- Giữ table nhỏ nguyên vẹn.
- Lưu `table_id`, `row_start`, `row_end`, column metadata và page range.
- Với paragraph/code/formula, ưu tiên boundary có cấu trúc trước khi cắt theo token.

### 4. Bảo đảm PostgreSQL và Qdrant nhất quán

- Không để vector được ghi vào Qdrant nhưng document chưa được publish.
- Dùng staged collection hoặc trạng thái index trung gian.
- Kiểm tra số lượng child chunks trong PostgreSQL khớp số vectors trong Qdrant.
- Có cleanup/reconciliation cho orphan vectors.
- Chỉ cho retrieval thấy version đã đạt trạng thái `ready`.

### 5. Thêm semantic claim verification

- Tách câu trả lời thành các claim.
- Đối chiếu từng claim với evidence được citation.
- Kiểm tra đặc biệt số liệu, ngày tháng, điều kiện `trên/dưới`, phạm vi và ngoại lệ.
- Nếu claim không được evidence hỗ trợ: retrieve thêm, sửa câu trả lời hoặc abstain.
- Bổ sung NLI/cross-encoder/verifier cho semantic entailment.

## Ưu tiên trung bình

### 6. Đánh giá reranker trước khi bật

- So sánh hybrid không reranker với hybrid có reranker trên held-out dataset.
- Đo recall@k, MRR/nDCG, citation quality và p50/p95 latency.
- Chỉ bật reranker nếu chất lượng tăng đủ lớn so với chi phí latency.

### 7. Tách Fast và Reasoning rõ hơn

Fast path:

```text
query
  → một hybrid retrieval pass
  → context nhỏ
  → generate
  → citation validation
```

Reasoning path:

```text
intent/router
  → decomposition
  → parallel retrieval
  → evidence dedup
  → contradiction check
  → retrieve thêm nếu thiếu
  → draft
  → critic/revise
  → citation verification
```

Không chỉ tăng `max_tokens` để định nghĩa Reasoning.

### 8. Cải thiện retrieval cho tài liệu rất dài

- Tạo page summary.
- Tạo section/chapter summary.
- Tạo document summary.
- Dùng summary cho câu hỏi tổng quan.
- Dùng child chunk cho câu hỏi fact cụ thể.
- Hỗ trợ parent/neighbor expansion có giới hạn.

### 9. Bổ sung quota và bảo mật upload

- Quota tổng theo tenant/user.
- Giới hạn dung lượng MinIO.
- Virus/malware scanning.
- Cleanup artifact và version cũ.
- Theo dõi dung lượng MinIO, PostgreSQL và Qdrant.

## Roadmap sau cùng

### 10. Graph RAG

- Entity/relation extraction.
- Entity resolution.
- Graph store.
- Graph traversal có provenance.
- Kết hợp graph với dense/lexical retrieval.

### 11. Agent RAG

- Planner và tool selector.
- Tool schema, ACL, timeout và retry budget.
- Evidence recorder.
- Sufficiency/contradiction judge.
- Giới hạn số vòng gọi tool.

Graph RAG và Agent RAG chỉ nên triển khai sau khi parse, chunking, quality gate, retrieval và citation đã ổn định.

## Thứ tự triển khai ngắn gọn

```text
Batch parse PDF dài
  → quality gate thật
  → table-aware chunking
  → index consistency
  → semantic citation verification
  → reranker benchmark
  → Fast/Reasoning workflow
  → long-document hierarchy
  → quota/security
  → Graph RAG/Agent RAG
```

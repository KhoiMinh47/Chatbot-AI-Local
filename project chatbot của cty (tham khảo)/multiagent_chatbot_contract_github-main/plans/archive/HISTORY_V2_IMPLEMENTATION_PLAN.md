# HISTORY PIPELINE IMPLEMENTATION PLAN (DIRECT CUTOVER)

## 1) Mục tiêu
- Thay trực tiếp cơ chế history cũ bằng pipeline history mới cho:
  - RAG Fast (query tài liệu nội bộ).
  - RAG Web Search (open-web flow).
- Giữ nguyên pipeline Create Contract.
- Không duy trì song song cơ chế cũ/mới trong runtime.
- Giảm quên ngữ cảnh quan trọng và giảm mâu thuẫn khi user đổi ý theo thời gian.

## 2) Phạm vi và không-phạm-vi
### 2.1 Phạm vi
- Thiết kế lại data model history để phục vụ semantic retrieval.
- Xây ingestion async: noise reduction -> summary theo task -> embedding -> lưu metadata.
- Retrieval hợp nhất: short-term + semantic + conflict resolver.
- Đổi thứ tự prompt theo chuẩn tối ưu cache.
- Cutover toàn bộ read-path của RAG Fast và Web Search sang pipeline history mới.

### 2.2 Không-phạm-vi
- Không đổi pipeline Create Contract.
- Không thêm model embedding/rerank mới trong phase này.
- Không đổi API contract frontend hiện tại.

## 3) Nguyên tắc triển khai
1. Không toggle, không shadow mode, không canary theo phần trăm.
2. Khi cutover thì cả RAG Fast và Web Search dùng chung read-path history mới.
3. Rollback theo release (re-deploy bản trước), không rollback bằng feature flag.
4. Thực hiện backup DB đầy đủ trước migration và trước cutover.

## 4) Kiến trúc đích
### 4.1 Mô hình memory
1. Raw History Layer
- Vẫn lưu user/bot message nguyên văn để audit và hiển thị lịch sử chat.

2. Semantic History Layer
- Lưu summary đã khử nhiễu + embedding + metadata.
- Metadata tối thiểu:
  - session_id, user_id, turn_id, role, task_type.
  - summary_text, entity_keys, time_scope.
  - is_negation, supersedes_turn_id (nếu có).
  - created_at.

3. Decision Layer (khuyến nghị triển khai cùng)
- Lưu fact chuẩn hóa theo entity/slot để xử lý ca đổi ý.

### 4.2 Retrieval hợp nhất trước LLM
1. Lấy short-term window (2-4 turns gần nhất).
2. Semantic search theo query hiện tại.
3. Group theo entity/slot, resolve conflict theo recency và phủ định.
4. Compose history context gọn, tránh nhồi raw history.

### 4.3 Prompt ordering chuẩn
1. System prompt.
2. Core context chính:
- RAG Fast: tài liệu nội bộ đã retrieve.
- Web Search: evidence đã rerank.
3. Semantic history đã resolve.
4. Short-term window.
5. User question mới.

## 5) Kế hoạch triển khai theo phase

## Phase 0 - Design Freeze và Cutover Readiness
### Mục tiêu
- Chốt thiết kế kỹ thuật và chuẩn bị điều kiện cutover một lần.

### Công việc
1. Chốt contract giữa ingest service, retriever và prompt composer.
2. Chốt schema semantic history + indexes.
3. Chốt quy trình deploy/migrate/cutover/rollback theo release.
4. Chốt checklist kiểm thử bắt buộc trước cutover.
5. Chốt dashboard KPI giám sát sau cutover.

### Deliverables
- Spec kỹ thuật final.
- Sequence diagram ingest/retrieve.
- Cutover runbook và rollback runbook (release-based).

### Exit Criteria
- Duyệt spec và duyệt runbook triển khai.

### Ước lượng
- 3-4 ngày.

## Phase 1 - Data Layer và Async Ingestion
### Mục tiêu
- Hoàn thiện data layer và ingestion pipeline mới.

### Công việc
1. Tạo bảng/collection semantic history.
2. Tạo ingestion worker:
- classify task_type: rag_fast hoặc web_search.
- summarize theo prompt riêng từng task.
- gọi embedding endpoint hiện có.
- upsert semantic record.
3. Gắn enqueue ingest sau khi lưu raw history thành công.
4. Bổ sung retry và dead-letter queue.
5. Log trace_id để truy vết raw -> semantic.

### Deliverables
- Module history pipeline mới.
- Migration + index.
- Dashboard ingestion technical metrics.

### Exit Criteria
- Ingest success rate >= 99%.
- Không tăng p95 latency endpoint chat.

### Ước lượng
- 1-1.5 tuần.

## Phase 2 - Retrieval và Prompt Composer mới
### Mục tiêu
- Hoàn thiện read-path history mới cho cả RAG Fast và Web Search.

### Công việc
1. Build retriever mới:
- short_window_retrieve.
- semantic_retrieve.
- conflict_resolve.
- compose_history_context.
2. Tích hợp prompt ordering mới vào:
- assistant của RAG Fast.
- synthesizer của Web Search.
3. Chuẩn hóa error handling:
- semantic retrieve lỗi -> degrade graceful bằng short-window.
- conflict resolver lỗi -> fallback rule tối thiểu theo recency.
4. Viết integration tests end-to-end cho 2 flow.

### Deliverables
- Read-path history mới hoạt động end-to-end trên staging.
- Bộ test pass đầy đủ cho 2 flow.

### Exit Criteria
- Tất cả test bắt buộc pass.
- Không còn dependency runtime vào logic history cũ trong 2 flow.

### Ước lượng
- 1 tuần.

## Phase 3 - Cutover Production (One-shot)
### Mục tiêu
- Deploy release mới và chuyển hoàn toàn sang pipeline history mới.

### Công việc
1. Pre-cutover checklist:
- backup DB.
- verify migration status.
- verify worker health.
- verify dashboard alerting.
2. Deploy release đã tích hợp read-path mới.
3. Smoke test ngay sau deploy:
- RAG Fast: ca hỏi tiếp nối và ca đổi ý.
- Web Search: ca citation và ca đổi ý đa lượt.
4. Theo dõi 24-48h đầu với war-room monitoring.

### Deliverables
- Production chạy hoàn toàn với history pipeline mới.

### Exit Criteria
- Không có sự cố nghiêm trọng trong 48h.
- KPI chất lượng đạt ngưỡng tối thiểu đã chốt.

### Ước lượng
- 2-3 ngày (bao gồm monitoring sau cutover).

## Phase 4 - Hardening và tối ưu
### Mục tiêu
- Ổn định dài hạn và giảm chi phí context.

### Công việc
1. Tối ưu top-k retrieval theo task.
2. Tối ưu độ dài summary để giảm token nhưng giữ chất lượng.
3. Bổ sung bộ regression cases cho đổi ý/phủ định/sửa số liệu.
4. Tối ưu observability và cảnh báo tự động.

### Deliverables
- Bộ regression chuẩn.
- Ngưỡng KPI production chính thức.
- Runbook vận hành hoàn chỉnh.

### Exit Criteria
- KPI ổn định ít nhất 7 ngày liên tiếp.

### Ước lượng
- 1 tuần.

## 6) Cơ chế xử lý Semantic vs Temporal
1. Chuẩn hóa fact keys theo entity/slot.
2. Với facts tương tự nhau:
- Ưu tiên turn_id/created_at mới nhất.
- Nếu fact mới là phủ định/hủy thì supersede fact cũ.
3. Prompt rule:
- Trong cùng entity, thông tin mới hơn là thông tin quyết định cuối cùng.

## 7) KPI và SLO bắt buộc
### 7.1 Hệ thống
- p95 latency end-to-end không tăng quá 10% so với baseline.
- Tỷ lệ lỗi hệ thống <= 2%.

### 7.2 Quality history
- Contradiction rate theo session.
- Recency correctness rate cho intent đổi ý.
- Avg history tokens/request.
- Follow-up correction rate từ người dùng.

### 7.3 Riêng Web Search
- Citation valid rate.
- Citation coverage rate.

## 8) Rollback Plan (không dùng toggle)
1. Rollback bằng release:
- Re-deploy image/tag backend trước cutover.
2. Rollback dữ liệu khi cần:
- Restore từ backup snapshot đã chụp trước cutover.
3. Rollback vận hành:
- Tạm dừng ingestion worker mới nếu cần cô lập lỗi.

## 9) Rủi ro và giảm thiểu
1. Over-compression làm mất facts quan trọng.
- Giảm thiểu: luôn lưu raw history và mapping trace tới semantic.
2. Queue backlog giờ cao điểm.
- Giảm thiểu: autoscale worker, alert queue lag, backpressure.
3. Resolver sai ở ca phủ định phức tạp.
- Giảm thiểu: regression test chuyên biệt + rule recency cứng.
4. Cutover one-shot có blast radius lớn.
- Giảm thiểu: checklist pre-cutover nghiêm ngặt và rollback release tức thì.

## 10) Lộ trình theo tuần
1. Tuần 1:
- Phase 0 + Phase 1.
2. Tuần 2:
- Phase 2.
3. Tuần 3:
- Phase 3 + Phase 4.

## 11) Tiêu chí nghiệm thu cuối cùng
1. RAG Fast và Web Search chạy hoàn toàn bằng history pipeline mới.
2. Chất lượng hội thoại cải thiện rõ ở ca đổi ý theo thời gian.
3. Citation web không suy giảm chất lượng.
4. Có dashboard KPI và rollback theo release hoạt động tốt.
5. Create Contract giữ nguyên hành vi.

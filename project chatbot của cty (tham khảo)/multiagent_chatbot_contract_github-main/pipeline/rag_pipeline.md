# RAG Pipeline (Retrieval-Augmented Generation)

## 1. Tổng quan
Pipeline RAG chịu trách nhiệm toàn bộ luồng truy vấn hội thoại có tăng cường tìm kiếm tri thức (retrieval) và tổng hợp trả lời tự nhiên, bao gồm:
- Tiếp nhận câu hỏi từ user (qua API hoặc giao diện).
- Tiền xử lý, chuẩn hóa, xác định session, user, ngữ cảnh.
- Truy xuất lịch sử hội thoại (semantic + short-term window).
- Thực thi truy vấn tìm kiếm (nội bộ hoặc web search).
- Tổng hợp ngữ cảnh, evidence, prompt.
- Gọi LLM (vLLM) sinh câu trả lời.
- Lưu lại kết quả, semantic history, audit, cập nhật cache.

## 2. Các bước chi tiết
### 2.1. Tiếp nhận truy vấn
- API nhận request gồm: user_id, session_id, câu hỏi, metadata.
- Xác thực user, kiểm tra quota, enforce rate limit.

### 2.2. Tiền xử lý
- Chuẩn hóa câu hỏi, loại bỏ noise, detect intent (recap/history/web search).
- Gán session, tạo session mới nếu cần.

### 2.3. Truy xuất lịch sử hội thoại
- Lấy short-term window (tin nhắn gần nhất).
- Truy xuất semantic_history (theo user_id, session_id, turn, role, task).
- Áp dụng conflict resolver (entity bucket, recency, negation).
- Kết hợp thành context tự nhiên (không gắn nhãn [Sx] cho history).

### 2.4. Truy vấn tri thức
- Nếu intent là recap/history: chỉ dùng context hội thoại.
- Nếu intent là knowledge/web search:
    - Gọi pipeline web_search (SearxNG hoặc API khác).
    - Chuẩn hóa evidence, lọc duplicate, ranking theo relevance.

### 2.5. Tổng hợp prompt
- Ghép context hội thoại + evidence web (nếu có).
- Sinh prompt chuẩn hóa, enforce rule citation [Sx] chỉ cho evidence web.

### 2.6. Gọi LLM (vLLM)
- Gửi prompt tới vLLM server (qua REST/gRPC).
- Nhận kết quả trả về, post-process (lọc, format, enforce rule).

### 2.7. Lưu kết quả
- Lưu semantic_history (idempotent theo turn).
- Lưu history_mess, cập nhật session.
- Audit log (nếu bật SEARCH_LOG_ENABLED).
- Cập nhật cache Redis (history, session).

## 3. Thành phần chính
- FastAPI backend: orchestrator.
- Qdrant: lưu embedding, semantic retrieval.
- Redis: cache session/history, rate limit.
- PostgreSQL: lưu session, history, semantic_history.
- vLLM: sinh câu trả lời.
- SearxNG: web search evidence.
- MinIO: lưu file hợp đồng.

## 4. Đặc điểm nổi bật
- Semantic memory chuẩn hóa, conflict resolver mạnh.
- Tách biệt rõ context hội thoại và evidence web.
- Prompt tối ưu cho LLM, enforce citation đúng logic.
- Audit, logging, metrics Prometheus đầy đủ.
- Có backfill, regression, smoke test tự động.

## 5. Sơ đồ pipeline

```mermaid
graph TD;
    A[User/API] --> B[Tiền xử lý]
    B --> C[Lấy history]
    C --> D[Truy vấn web (nếu cần)]
    D --> E[Tổng hợp prompt]
    E --> F[Gọi vLLM]
    F --> G[Lưu kết quả]
    G --> H[Cập nhật cache]
```

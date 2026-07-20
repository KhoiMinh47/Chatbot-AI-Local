# Model & System Card — NTC Local RAG Chatbot

Tài liệu đặc tả các thông số kỹ thuật, cấu hình mô hình, và các giới hạn hệ thống chính thức của NTC Local RAG Chatbot dành cho bản phát hành Release Candidate.

---

## 1. Model Card (Đặc tả Mô hình AI)

### Mô hình ngôn ngữ lớn (LLM NIM)
- **Tên mô hình:** `nvidia/nemotron-nano-9b-v2`
- **Phiên bản phát hành:** `1.0.0`
- **Môi trường chạy:** Cục bộ trên NVIDIA DGX NIM container.
- **Mục tiêu tối ưu:** Đảm bảo khả năng sinh câu trả lời chính xác, bám sát văn bản ngữ cảnh, và hỗ trợ đa ngôn ngữ (tiếng Việt/tiếng Anh).

### Mô hình nhúng (Embedding NIM)
- **Tên mô hình:** `nvidia/llama-nemotron-embed-300m-v2`
- **Phiên bản phát hành:** `1.13.0`
- **Số chiều vector (Dimension):** `2048`
- **Khoảng cách tìm kiếm (Distance):** Cosine

### Tokenizer
- **Cơ chế đếm token:** Sử dụng exact Hugging Face tokenizer được ghim và kiểm chứng mã hash sha256 tương ứng để khớp chính xác lượng token tiêu thụ đầu vào/đầu ra với NIM.

---

## 2. System Card (Đặc tả Cấu hình Hệ thống)

### Cấu hình Indexing & Chunking
- **Kích thước chunk (Chunk Size):** `256` tokens
- **Tỷ lệ trùng lặp (Overlap):** `10%`
- **Cơ chế phân tách văn bản:** Phân tách dựa trên cấu trúc ngữ nghĩa ngữ cảnh (Semantic-aware chunking).

### Cấu hình Vector Database (Qdrant)
- **Collection Alias chính thức:** `ntc_chunks_active`
- **Chỉ mục phụ trợ (Payload Indexes):** Tự động tạo chỉ mục cho `tenant_id` và các trường ACL nhằm phục vụ tìm kiếm an toàn (scoped access).
- **HNSW ef Tuning:** `256` (được cấu hình trong Phase 10 nhằm tối ưu tốc độ đọc đồng thời khi có tải ingestion lớn).

### Tham số chính sách truy xuất (Retrieval Policy)
- **Giới hạn ứng viên dày (Dense Candidate Limit):** `20`
- **Giới hạn ngữ cảnh cuối (Final Context Limit):** `10`
- **Ngưỡng tìm kiếm tối thiểu (Dense Threshold):** `0.23`

### An toàn & Giới hạn tải (Safety Bounds & Limits)
- **Giới hạn câu hỏi người dùng:** Tối đa `8,000` ký tự (chặn tại domain boundary).
- **Giới hạn tải file tài liệu:** Tối đa `100 MB` (chặn tại HTTP boundary).
- **Giới hạn luồng đồng thời (Concurrency limit):** Tối đa `8 requests` xử lý RAG song song thông qua cơ chế Semaphore, ngăn ngừa quá tải VRAM.

### Prompts & Chỉ thị hệ thống (Grounded System Prompt)
- **Mã hash định danh cấu hình:** `PROMPT_SHA256` cố định.
- **Hành vi được kiểm soát:** LLM bắt buộc hoạt động dưới chỉ thị "Grounded", trích dẫn bằng mã nguồn server cung cấp dạng `[S1]`, và từ chối sinh nội dung khi ngữ cảnh không đủ thông tin (Outcome: `INSUFFICIENT_EVIDENCE`), loại bỏ hiện tượng ảo giác (hallucination).

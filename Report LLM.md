# PLANNING

Dựa vào project LLM của công ty, xây dựng một chatbot local có các tính năng tương tự: một hệ thống hỏi đáp tài liệu dựa trên RAG.

## Outcomes

- **Sản phẩm:** Chatbot local hỗ trợ upload tài liệu, chat, SSE (streaming response), citation và hai chế độ Fast Mode/Reasoning Mode.
- **Kỹ thuật:**

  `Tài liệu → parse → clean → chunk → embedding → vector database → retrieval → rerank → LLM → response có citation`

- **Chất lượng:** Retrieval tìm đúng tài liệu; câu trả lời đúng và bám context; citation chính xác; hệ thống đủ nhanh, ổn định, an toàn và giao diện dễ sử dụng.

# OBJECTIVE

## Phase 0 — Requirement và kiểm tra compatibility

- Setup DGX Spark, Linux ARM64, Python 3.14, các thành phần NVIDIA cần thiết, Docker Compose và Node.js.
- Kiểm tra các NVIDIA NIM image/model.
- Kiểm tra các library cần dùng có cài được trên cùng Python version và có tương thích với nhau không.
- Chạy smoke test để kiểm tra model hoạt động trên GPU.
- Tạo repository structure và file cấu hình môi trường.
- Ghi lại các vấn đề về permission, compatibility hoặc resource nếu có.

## Phase 1 — Tạo bộ khung project

- Tạo folder cho backend, frontend, worker và shared code.
- Tạo FastAPI cơ bản cho backend.
- Tạo Next.js cơ bản cho frontend.
- Tạo worker skeleton để xử lý các tác vụ nền.
- Thiết lập Git và các quy tắc code cơ bản.
- Cài formatter, linter và type checker.
- Tạo endpoint kiểm tra API có hoạt động không.
- Viết README hướng dẫn chạy project.

## Phase 2 — Dựng hạ tầng cơ bản

Chuẩn bị các service cho project hoạt động:

- **PostgreSQL:** lưu user, tài liệu, đoạn chat và metadata.
- **Redis:** làm cache/bộ nhớ đệm.
- **RabbitMQ:** nhận và quản lý job xử lý tài liệu.
- **MinIO:** lưu file tài liệu gốc.
- **Qdrant:** lưu vector embedding.
- **Nginx:** làm cổng kết nối giữa frontend và backend.
- **Prometheus:** theo dõi trạng thái service và GPU.
- **Docker Compose:** chạy và kết nối các service.

## Phase 3 — Kiểm tra và chọn model AI

- Chạy thử các NVIDIA NIM.
- Kiểm tra LLM có trả lời tiếng Việt không.
- Kiểm tra embedding model có tạo vector đúng không.
- Kiểm tra reranker có chấm điểm tài liệu đúng không.
- Đo tốc độ phản hồi, throughput và mức sử dụng GPU.
- Kiểm tra model có thiếu VRAM hoặc crash khi chạy cùng nhau không.
- Chọn model hoạt động phù hợp với phần cứng hiện tại.

## Phase 4 — Xây dựng hệ thống upload và phân tích file

`Upload → đọc file → chuẩn hóa → kiểm tra chất lượng → chunking → lưu index`

## Phase 5 — Xây dựng hệ thống RAG

`Câu hỏi user → tạo embedding → tìm kiếm vector và keyword → gộp, loại bỏ chunk trùng → reranker xếp hạng → chọn evidence → mở rộng context → gửi cho LLM → kiểm tra citation → trả lời user`

### Các chức năng chính

- Chuyển câu hỏi thành standalone query, đặc biệt với câu hỏi nối tiếp.
- Tìm kiếm bằng vector similarity, keyword/BM25 và metadata như tên file, trang, section.
- Kết hợp kết quả từ nhiều phương pháp tìm kiếm.
- Dùng reranker để xếp hạng lại chunk theo độ liên quan.
- Mở rộng parent chunk hoặc chunk lân cận nếu đoạn được chọn chưa đủ ngữ cảnh.
- Tách câu hỏi thành nhiều sub-question nếu câu hỏi có nhiều ý.
- Đóng gói evidence gồm nội dung file, tên file, trang/section, document version và evidence ID.
- Nếu không tìm đủ thông tin thì trả lời rõ là không đủ bằng chứng, không tự bịa thêm.

### Ví dụ kết quả truy xuất

**Query:** Kỹ năng cần có của AI Engineer

**Evidence:** `JD_AI_Engineer.pdf` — Section: Yêu cầu — Page: 1 — Content: Python, machine learning, deep learning, LLM, ...

## Phase 6 — Kiểm tra citation và tạo câu trả lời có căn cứ

`Evidence từ Phase 5 → đóng gói source record → tạo prompt cho LLM → nhận câu trả lời → kiểm tra citation → kiểm tra claim có evidence hỗ trợ → retry nếu lỗi → trả câu trả lời an toàn`

- Tạo citation ID cố định cho từng chunk.
- Gửi cho model nội dung chunk kèm tên file, trang, section và version.
- Kiểm tra citation có tồn tại và có đúng nguồn không.
- Kiểm tra claim trong câu trả lời có được evidence hỗ trợ không.
- Nếu citation sai, thiếu hoặc model bịa thông tin thì yêu cầu model viết lại.
- Nếu vẫn không hợp lệ thì trả nội dung an toàn từ evidence hoặc thông báo không đủ bằng chứng.
- Lưu token usage, citation và nguồn tài liệu để kiểm tra sau này.

## Phase 7 — Backend Chat System

Xây dựng phần xử lý phía server:

`Đăng ký/đăng nhập → xác thực JWT → phân quyền → tạo conversation → lưu message → tạo API chat → stream response bằng SSE`

Backend có thể nhận câu hỏi, xử lý RAG và trả dữ liệu về frontend.

## Phase 8 — Frontend Chat System

`Login/Register UI → giao diện conversation → upload file → chọn Fast/Reasoning → gửi câu hỏi → nhận SSE → hiển thị câu trả lời/citation`

## Phase 9 — Memory nâng cao

`Lưu thông tin quan trọng → truy xuất khi cần → đưa vào context → model trả lời liên tục hơn`

Phase 7 lưu user, conversation, câu hỏi và câu trả lời. Phase 9 phân tích các message đó để tạo summary, preference, project state và tìm lại memory liên quan.

- **Preference:** sở thích hoặc cách user muốn hệ thống phản hồi.
- **Project state:** trạng thái hiện tại của project hoặc công việc đang làm.

## Phase 10 — Evaluation & Performance

`Tạo bộ test → chạy test → đo độ chính xác/tốc độ → tìm lỗi → tối ưu`

- Kiểm tra câu trả lời có đúng tài liệu không.
- Kiểm tra citation.
- Test nhiều request cùng lúc.
- Kiểm tra lỗi từ backend và frontend.
- Kiểm tra Reasoning Mode khi context nhỏ.

## Phase 11 — Phân tích lỗi và Fine-tuning

Tập trung xác định lỗi đến từ model hay pipeline, sau đó fine-tune nếu thật sự cần.

Dataset có thể gồm:

- Câu hỏi về tài liệu.
- Context liên quan.
- Câu trả lời đúng.
- Citation đúng.

Mục tiêu model học cách:

- Trả lời đúng format hơn.
- Phân biệt Fast Mode và Reasoning Mode.
- Không trộn nội dung giữa nhiều file.
- Trích dẫn đúng citation.
- Không bịa khi tài liệu không có thông tin.

Pipeline:

`Thu thập câu hỏi thực tế → tạo dataset chuẩn → fine-tune model → chạy evaluation lại → so sánh với model gốc`

## Phase 12 — Final RAG Evaluation

`Đóng băng bộ dữ liệu test → chạy toàn bộ pipeline RAG → chấm điểm → so sánh kết quả → tổng hợp báo cáo`

Kiểm tra retrieval, reranker, độ chính xác câu trả lời, citation, khả năng xử lý nhiều file, Fast/Reasoning Mode, thời gian phản hồi và các lỗi còn lại.

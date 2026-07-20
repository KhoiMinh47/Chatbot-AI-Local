# Tổng quan backend

Cập nhật lần cuối: 2026-05-13

## 1. Vai trò

Backend là trung tâm điều phối toàn bộ nghiệp vụ:

- Xác thực và phân quyền.
- API cho RAG, contract, quản trị.
- Điều phối workflow LangGraph.
- Tích hợp dữ liệu và dịch vụ AI bên ngoài.

## 2. Cấu trúc thư mục chính

- `backend/main.py`: entrypoint FastAPI, startup lifecycle, middleware.
- `backend/controller/`: lớp API handlers.
- `backend/service/`: nghiệp vụ cốt lõi.
- `backend/agent_chatbot/`: state, graph, nodes cho workflow RAG.
- `backend/database/`: setup DB, models, storage helpers.
- `backend/auth/`: middleware và tiện ích bảo mật.
- `backend/request/`: schemas request/validation.

## 3. API nhóm chức năng

- Auth: đăng nhập, xác thực, quyền truy cập.
- RAG: upload tài liệu, chat theo session, quản lý lịch sử.
- Contract: upload template, sinh hợp đồng, download.
- Admin: cấu hình prompt, provider, metrics, quản trị tài khoản.

## 4. Dịch vụ phụ thuộc

- Parse-data service để chuyển đổi tài liệu sang markdown.
- Embedding service để sinh vector và rerank.
- vLLM để sinh câu trả lời/tài liệu.
- Redis/Qdrant/PostgreSQL/MinIO cho tầng dữ liệu.

## 5. Lưu ý vận hành

- Cần chuẩn bị file `.env` đúng trước khi startup.
- Luôn theo dõi logs backend và metrics Redis/Postgres.
- Với web search production, ưu tiên cấu hình provider và guardrail mạng.

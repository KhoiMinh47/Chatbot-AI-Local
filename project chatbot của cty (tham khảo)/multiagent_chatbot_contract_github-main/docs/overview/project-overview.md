# Tổng quan dự án

Cập nhật lần cuối: 2026-05-13

## 1. Dự án này giải quyết bài toán gì?

RAG Chat là nền tảng chatbot nội bộ kết hợp:

- Tra cứu tài liệu (RAG) dựa trên dữ liệu doanh nghiệp.
- Sinh và quản lý hợp đồng theo template hoặc AI.
- Web search có kiểm soát để bổ sung bằng chứng ngoài hệ thống.
- Quản trị người dùng, phân quyền và giám sát vận hành.

Mục tiêu là cung cấp một hệ thống AI trợ lý có thể đi từ dữ liệu nội bộ đến trả lời có căn cứ, có log, có khả năng vận hành production.

## 2. Các module chính

- `backend/`: API FastAPI, điều phối pipeline, auth, DB, cache.
- `frontend/`: giao diện Next.js cho chat, quản trị, thao tác tài liệu.
- `parse-data/`: dịch vụ parse tài liệu sang markdown.
- `embedding/`: dịch vụ embedding + rerank.
- `prometheus-collector/`: thu thập metrics và tổng hợp số liệu.
- `config/`: cấu hình Nginx, Prometheus, Redis, SearxNG.
- `docker/`: Dockerfile cho từng thành phần theo amd/arm.

## 3. Năng lực chức năng hiện có

- Upload tài liệu, parse, chunk, embedding, lưu vector.
- Hỏi đáp RAG theo session với lưu lịch sử và cache.
- Tạo hợp đồng theo nhiều luồng (template/fast/reasoning).
- Web search pipeline có broker đa provider và hardening.
- Quản trị tài khoản, role, cấu hình prompt/provider.

## 4. Công nghệ sử dụng

- Backend: FastAPI, SQLAlchemy, Redis, Qdrant, PostgreSQL, MinIO.
- Frontend: Next.js, React, Axios.
- AI stack: vLLM, LangGraph, embedding/rerank service.
- Infra: Docker Compose, Nginx, Prometheus.

## 5. Đối tượng đọc tài liệu

- Dev backend/frontend.
- DevOps/SRE vận hành hệ thống.
- QA cần nắm luồng nghiệp vụ để kiểm thử.
- PM/Tech lead cần theo dõi kế hoạch kỹ thuật.

# Kiến trúc hệ thống

Cập nhật lần cuối: 2026-05-13

## 1. Bức tranh tổng thể

Hệ thống theo kiến trúc dịch vụ tách lớp:

- Lớp giao diện: frontend Next.js.
- Lớp API điều phối: backend FastAPI.
- Lớp AI chuyên dụng: parse-data, embedding/rerank, vLLM.
- Lớp dữ liệu: PostgreSQL, Qdrant, Redis, MinIO.
- Lớp vận hành: Nginx, Prometheus, exporters, Docker Compose.

## 2. Luồng chính từ user đến phản hồi

1. User gửi truy vấn từ frontend.
2. Backend xác thực, nạp session/history.
3. Backend chọn flow (RAG nội bộ, web search, contract).
4. Nếu cần dữ liệu tài liệu: đọc vector từ Qdrant + metadata PostgreSQL/MinIO.
5. Nếu cần web: gọi broker/provider để lấy evidence.
6. Tổng hợp context + prompt.
7. Gọi vLLM để sinh kết quả.
8. Lưu history, semantic context, cache.
9. Trả kết quả về frontend.

## 3. Thành phần dữ liệu

- PostgreSQL: user, role, session, lịch sử, cấu hình hệ thống.
- Qdrant: vector chunks và payload phục vụ semantic retrieval.
- Redis: cache lịch sử, khóa runtime, rate-limit, hỗ trợ hiệu năng.
- MinIO: lưu file gốc và artifact hợp đồng.

## 4. Tính sẵn sàng và an toàn

- Web search hardening: provider priority, retry, cache, circuit breaker.
- Rate-limit theo user và global policy.
- Ghi log/metrics để theo dõi vận hành.
- Ràng buộc outbound search qua cấu hình bảo mật.

## 5. Môi trường vận hành

- Local/dev: có thể chạy bằng script `run_all_services.sh`.
- Docker compose: bật toàn bộ hạ tầng qua file compose.
- Production: khuyến nghị tách cấu hình secrets và bật đầy đủ guardrail mạng.

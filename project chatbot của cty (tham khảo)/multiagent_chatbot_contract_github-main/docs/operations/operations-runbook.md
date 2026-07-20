# Runbook vận hành

Cập nhật lần cuối: 2026-05-13

## 1. Mục tiêu vận hành

- Duy trì hệ thống ổn định khi tải tăng.
- Phát hiện sớm lỗi và phản ứng theo checklist.
- Đảm bảo chất lượng phản hồi AI và citation.

## 2. Nguồn quan sát chính

- Logs container qua `docker compose logs`.
- Metrics Prometheus và exporter (node, redis, postgres, gpu).
- Trạng thái backend endpoints và pipeline jobs.

## 3. Sự cố thường gặp và cách xử lý

### 3.1 Backend không khởi động

1. Kiểm tra biến môi trường bắt buộc trong `.env`.
2. Kiểm tra Postgres/Redis/Qdrant đã sẵn sàng.
3. Kiểm tra lỗi migration hoặc kết nối DB trong logs backend.

### 3.2 Upload parse lỗi

1. Kiểm tra parse-data service và endpoint parse.
2. Kiểm tra định dạng file upload có được hỗ trợ.
3. Kiểm tra giới hạn dung lượng và timeout.

### 3.3 Trả lời web search kém chất lượng

1. Kiểm tra provider và rate-limit.
2. Kiểm tra evidence count, domain diversity, citation validity.
3. Điều chỉnh cấu hình broker/fallback theo tài liệu hardening.

### 3.4 Chậm hoặc timeout khi chat

1. Kiểm tra tải GPU và vLLM queue.
2. Kiểm tra Redis hit ratio và độ trễ DB.
3. Giảm budget web fetch hoặc tối ưu prompt context.

## 4. Checklist release vận hành

1. CI pass toàn bộ checks.
2. Docker compose config hợp lệ.
3. Smoke test backend/frontend thành công.
4. Theo dõi 30-60 phút sau deploy.
5. Có kế hoạch rollback rõ ràng.

# Runbook triển khai

Cập nhật lần cuối: 2026-05-13

## 1. Chuẩn bị trước khi chạy

- Cài Docker + Docker Compose plugin.
- Chuẩn bị file `.env` (và `.env.all` nếu dùng compose all).
- Đảm bảo thư mục cache đủ dung lượng lưu model/data.

## 2. Cách chạy tiêu chuẩn

### Cách 1: Script tổng

```bash
bash ./run_all_services.sh
```

Script sẽ:

- Setup dependencies cục bộ (theo biến môi trường).
- Kiểm tra image vLLM.
- Kiểm tra GeoIP.
- Startup các dịch vụ qua docker compose.

### Cách 2: Docker Compose trực tiếp

```bash
docker compose -f docker-compose.yml up -d --build
```

## 3. Dịch vụ và cổng mặc định

- Backend API: `http://localhost:9000`
- Frontend qua Nginx: `http://localhost:3000`
- Parse-data: `http://localhost:8005`
- Embedding/Rerank: `http://localhost:8006`
- vLLM: `http://localhost:8007`
- PostgreSQL: `localhost:7000`
- Qdrant: `http://localhost:7002`
- MinIO: `http://localhost:7003` và console `http://localhost:7004`
- Redis: `localhost:7005`
- Prometheus: `http://localhost:7007`

## 4. Kiểm tra sức khỏe nhanh

```bash
curl -f http://localhost:9000/api/v1/health || true
curl -f http://localhost:8005/health || true
curl -f http://localhost:8006/api/v1/embed -H "Content-Type: application/json" -d '{"texts":["ping"]}' || true
```

## 5. Backup và restore

- Backup: dùng `backup.sh`.
- Restore: dùng `restore.sh <duong_dan_backup>`.
- Có thể bật auto restore lần đầu qua biến môi trường script runtime.

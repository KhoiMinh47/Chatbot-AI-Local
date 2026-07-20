# Checklist khôi phục trên máy mới

Repository này chứa source code và cấu hình mẫu. Khi chuyển sang máy khác,
cần chuẩn bị lại các mục sau.

## Hạ tầng bắt buộc

- Linux ARM64/NVIDIA DGX Spark hoặc máy NVIDIA tương thích
- Docker Engine
- NVIDIA Container Toolkit
- NVIDIA NGC API key
- Docker Compose
- Python 3.14
- `uv`
- Node.js 22.13.x
- pnpm 10.32.0

## NVIDIA NIM/model

- Nemotron LLM: `nvidia/nemotron-nano-9b-v2`
- Embedding: `nvidia/llama-nemotron-embed-300m-v2`
- Rerank: model NIM được khai báo trong `NIM_RERANK_MODEL` nếu bật rerank
- NIM services và network `ntc-rag-phase3_runtime`
- Model cache/weights

## Docker images

- PostgreSQL
- Redis
- Qdrant
- MinIO
- RabbitMQ
- Prometheus
- Grafana
- Nginx
- DCGM exporter
- Python runtime image
- uv image
- Node image
- Các image API, worker và web của project

Tải image bằng:

```bash
make phase2-images
```

## Cấu hình cần tạo lại

- `.env`
- `.secrets/phase2/database_password`
- `.secrets/phase2/grafana_admin_password`
- `.secrets/phase2/minio_root_password`
- `.secrets/phase2/postgres_password`
- `.secrets/phase2/rabbitmq_password`
- `.secrets/phase2/redis_password`
- `.secrets/phase3/ngc_api_key`

Tạo thư mục secret ban đầu bằng:

```bash
make phase2-secrets
```

## Dữ liệu runtime cần backup riêng

- PostgreSQL database
- Qdrant collections/vector index
- MinIO uploaded documents
- Redis data nếu cần giữ cache/session
- RabbitMQ state nếu cần giữ queue
- Docker volumes
- Tài liệu người dùng đã upload

## Khởi động sau khi clone

```bash
git clone git@github.com:KhoiMinh47/Chatbot-AI-Local.git
cd Chatbot-AI-Local
make phase2-secrets
make phase2-images
docker compose --profile core --profile app up -d
make migrate
docker compose --profile core --profile app ps
```

Gateway: `http://localhost:8080`  
Web: `http://localhost:3000`  
API: `http://localhost:8000`  
Swagger: `http://localhost:8000/docs`

## Lưu ý

Source code không chứa giá trị thật của password, API key, model weights,
database hoặc Docker volumes. Các mục này phải được backup/nhập riêng.

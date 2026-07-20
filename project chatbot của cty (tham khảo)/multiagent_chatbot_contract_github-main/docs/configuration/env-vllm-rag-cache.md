# Cấu hình Env, vLLM, RAG và Cache

Cập nhật: 2026-05-23 18:27

## Env tập trung

Các service code hiện đọc env từ thư mục gốc:

- `.env.all`: cấu hình Docker Compose all.
- `.env`: cấu hình local/prod override.
- `.env.example`: mẫu đầy đủ không chứa secret thật.

Không dùng `.env` riêng trong `backend`, `embedding`, `parse-data`, `prometheus-collector`. Frontend vẫn có thể dùng `frontend/.env.local`.

## vLLM hiện tại

- Model: `google/gemma-4-E4B-it`.
- Context: `LLM_CONTEXT_WINDOW=65536`.
- GPU memory: `GPU_MEMORY_UTIL=0.37`.
- KV cache: `--kv-cache-dtype fp8`.
- Kết quả kiểm tra ngày 2026-05-23: `0.30` và `0.35` không đủ KV cache cho 64k; `0.37` chạy được.

## Budget RAG

Các budget được đặt trong env để chỉnh số lượng mà không đổi pipeline:

- `RAG_INPUT_TOKEN_BUDGET=50000`
- `RAG_OUTPUT_TOKEN_BUDGET=10000`
- `RAG_FILE_CONTEXT_TOKEN_BUDGET=40000`
- `RAG_HISTORY_TOKEN_BUDGET=10000`
- `RAG_SELECTED_PATH_TOKEN_BUDGET=50000`
- `RAG_AVG_TOKENS_PER_CHUNK=600`
- `RAG_CHARS_PER_TOKEN=2.5`

Pipeline vẫn giữ cách xử lý path, vector search, rerank, history và assistant node như cũ.

## Cache đang giữ

- `cache/huggingface/hub/models--google--gemma-4-E4B-it`: model vLLM đang chạy.
- `cache/minio`: dữ liệu object storage.
- `cache/pgdata`: dữ liệu PostgreSQL.
- `cache/qdrant_storage`: dữ liệu vector DB.
- `cache/redis_data`: dữ liệu Redis.
- `cache/prometheus_data`: dữ liệu Prometheus.

Không xóa các volume dữ liệu nếu chưa backup hoặc chưa chủ động reset môi trường.

## Cache đã dọn

Ngày 2026-05-23 đã xóa cache cũ không còn được project hiện tại mount/reference:

- `cache/bge`
- `cache/marker`
- `cache/huggingface/hub/models--Qwen--Qwen3-VL-8B-Instruct-FP8`
- `cache/huggingface/hub/models--khazarai--Qwen3-4B-Qwen3.6-plus-Reasoning-Distilled`
- root `.next`
- `__pycache__` trong các service Python

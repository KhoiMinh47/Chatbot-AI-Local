# Log task: Tối ưu vLLM, RAG, Env, Cleanup và Tài liệu

- Thời gian bắt đầu: 2026-05-23 17:53
- Trạng thái: in_progress
- Plan liên quan: `plans/plan-toi-uu-vllm-rag-env-cleanup-docs.md`

## Mục tiêu phiên này

Lập kế hoạch theo `plan-skill` cho việc giảm VRAM vLLM, chuẩn hóa env, chỉnh budget RAG đúng pipeline, dọn source, cập nhật docs/logs/README và chuẩn bị quy trình test có ảnh/GIF.

## Khảo sát đã làm

- Đọc `plan-skill`.
- Kiểm tra env hiện có ở root và từng service.
- Kiểm tra logic load env trong `backend/main.py`, `embedding/main.py`, `parse-data/main.py`.
- Kiểm tra các hằng số RAG liên quan đến context/output/path budget trong `backend/agent_chatbot/node/util/rag_query_util.py`.
- Kiểm tra `run_all_services.sh` để nắm cách chạy tmux và nginx upstream.
- Kiểm tra dung lượng cache/venv/build artifact trong project.
- Kiểm tra trạng thái Git để ghi nhận worktree đang có nhiều thay đổi chưa commit.

## Ghi nhận quan trọng

- `.env` vẫn đặt `GPU_MEMORY_UTIL=0.65`, `LLM_CONTEXT_WINDOW=128000`.
- Service entrypoint đang load root env rồi override bằng env riêng của service.
- RAG hiện kiểm soát context bằng hằng số hard-code và một phần là ký tự, cần chuyển sang env nhưng không đổi flow.
- Cleanup phải phân loại kỹ vì có nhiều thư mục runtime/cache/venv và worktree đang bẩn.
- Cache lớn: `cache/huggingface` khoảng `33G`, `cache/bge` khoảng `20G`, `cache/marker` khoảng `3.3G`.
- Volume dữ liệu service cần giữ/backup trước khi xóa: `cache/minio`, `cache/pgdata`, `cache/qdrant_storage`, `cache/redis_data`, `cache/prometheus_data`.
- Artifact/cache có thể đưa vào danh sách dọn an toàn: `__pycache__`, `.pytest_cache`, root `.next`; `frontend/.next` chỉ xóa khi không cần bản build hiện tại; venv/node_modules chỉ xóa khi chấp nhận cài lại hoặc chuyển hẳn sang Docker.

## Audit cache cập nhật

- Container đang chạy mount trực tiếp:
  - `vllm_gemma4`: `cache/huggingface` -> `/root/.cache/huggingface`.
  - `postgres`: `cache/pgdata` -> `/var/lib/postgresql/data`.
  - `qdrant`: `cache/qdrant_storage` -> `/qdrant/storage`.
  - `minio`: `cache/minio` -> `/data`.
  - `redis`: `cache/redis_data` -> `/data`.
  - `prometheus`: `cache/prometheus_data` -> `/prometheus`.
- `cache/huggingface` đang chứa:
  - Giữ: `models--google--gemma-4-E4B-it` khoảng `15G`, đang là model vLLM hiện tại.
  - Có thể xóa nếu không cần đổi model nhanh: `models--Qwen--Qwen3-VL-8B-Instruct-FP8` khoảng `9.9G`.
  - Có thể xóa nếu không cần fallback cũ: `models--khazarai--Qwen3-4B-Qwen3.6-plus-Reasoning-Distilled` khoảng `7.6G`.
- `cache/bge` không thấy mount/reference trong compose hiện tại:
  - `models--BAAI--bge-reranker-v2-m3` khoảng `2.2G`.
  - `models--BAAI--bge-m3` khoảng `4.3G`.
  - `models--intfloat--e5-mistral-7b-instruct` khoảng `14G`.
  - Embedding service hiện code dùng `nvidia/llama-nemotron-embed-1b-v2` và `nvidia/llama-nemotron-rerank-1b-v2`, cache đang nằm ở `/home/ntcai/.cache/huggingface`, không phải `cache/bge`.
- `cache/marker` không thấy mount/reference trong compose hiện tại khi đang chạy local `parse-data`; có thể là cache Marker cũ.
- Cache user-level `/home/ntcai/.cache/huggingface` khoảng `30G` đang có nhiều model phục vụ embedding/parse-data/Riva hoặc tool khác, không thuộc cleanup project root nếu chưa audit riêng ngoài repo.

## Việc chưa làm

- Chưa sửa source runtime.
- Chưa xóa env/service folder.
- Chưa xóa cache nào.
- Chưa restart container hoặc tmux.
- Chưa chạy test web/screenshot/GIF.

## Bước tiếp theo

Chờ xác nhận bắt đầu implementation theo plan. Khi triển khai, cập nhật log sau từng phase và chỉ xóa file/folder sau khi đã phân loại an toàn.

## 2026-05-23 18:00 - Bắt đầu triển khai

- Baseline:
  - vLLM đang chạy `GPU_MEMORY_UTIL=0.65`, `LLM_CONTEXT_WINDOW=128000`.
  - VRAM tổng đang dùng khoảng `45278MiB`, riêng `VLLM::EngineCore` khoảng `31744MiB`.
  - Env lẻ còn tồn tại ở `backend/.env`, `embedding/.env`, `parse-data/.env`, `prometheus-collector/.env`; frontend có `frontend/.env.local`.
- Bắt đầu phase chuẩn hóa env gốc và bỏ override env theo service.

## 2026-05-23 18:04 - Env gốc và budget RAG

- Đã bỏ load env riêng trong `backend`, `embedding`, `parse-data`, `prometheus-collector`.
- Đã xóa env lẻ của các service code; chỉ còn `.env`, `.env.all`, `.env.example`, `frontend/.env.local`.
- Đã thêm biến root cho parser, embedding, prometheus collector, tmux window names.
- Đã đổi vLLM env về `GPU_MEMORY_UTIL=0.30`, `LLM_CONTEXT_WINDOW=65536`, `LLM_MAX_TOKENS=10000`.
- Đã thêm budget RAG: input `50000`, output `10000`, file context `40000`, history `10000`, selected path `50000`.
- Đã chỉnh RAG util đọc budget từ env; pipeline path/rerank/node giữ nguyên.
- Verify đã chạy:
  - `docker compose --env-file .env -f docker-compose.yml config`
  - `docker compose --env-file .env.all -f docker-compose.all.yml config`
  - `python3 -m py_compile` cho các entrypoint và RAG util.

## 2026-05-23 18:09 - Thử vLLM 64k với GPU util 0.30

- Restart riêng service `vllm`.
- vLLM nhận đúng command `--gpu-memory-utilization 0.30` và `--max-model-len 65536`.
- Kết quả: fail khi khởi tạo KV cache với lỗi `No available memory for the cache blocks`.
- Áp dụng fallback theo plan: giữ `LLM_CONTEXT_WINDOW=65536`, tăng `GPU_MEMORY_UTIL` từ `0.30` lên `0.35`.

## 2026-05-23 18:16 - Thử vLLM 64k với GPU util 0.35

- vLLM vẫn fail KV cache.
- Log cho biết cần khoảng `0.55 GiB` KV cache cho max seq len `65536`, nhưng mức `0.35` chỉ còn khoảng `0.3 GiB` KV cache khả dụng; vLLM ước tính max model len chỉ khoảng `33376`.
- Tăng fallback lên `GPU_MEMORY_UTIL=0.37`, vẫn thấp hơn nhiều so với `0.65` ban đầu.

## 2026-05-23 18:22 - vLLM 64k chạy ổn ở GPU util 0.37

- `/v1/models` trả `google/gemma-4-E4B-it` với `max_model_len=65536`.
- Log vLLM ghi `Available KV cache memory: 1.25 GiB` và maximum concurrency cho request 65,536 token khoảng `2.27x`.
- `nvidia-smi`: riêng `VLLM::EngineCore` còn khoảng `18544MiB`, giảm từ baseline khoảng `31744MiB`.
- Tổng VRAM máy còn khoảng `30367MiB` vì còn embedding, parse-data, Riva/face-recognition cùng dùng GPU.

## 2026-05-23 18:25 - Cleanup cache/source

- Trước cleanup: `cache/bge` khoảng `20G`, `cache/huggingface` khoảng `33G`, `cache/marker` khoảng `3.3G`, root `.next` khoảng `8K`.
- Đã xóa:
  - `cache/bge`
  - `cache/marker`
  - `cache/huggingface/hub/models--Qwen--Qwen3-VL-8B-Instruct-FP8`
  - `cache/huggingface/hub/models--khazarai--Qwen3-4B-Qwen3.6-plus-Reasoning-Distilled`
  - root `.next`
  - toàn bộ `__pycache__` trong `backend`, `embedding`, `parse-data`, `prometheus-collector`
- Phải dùng container root để xóa các cache do container tạo vì user host không có quyền ghi.
- Sau cleanup: `cache/huggingface` còn khoảng `15G`, chỉ còn `.locks` và `models--google--gemma-4-E4B-it`; giữ nguyên `cache/minio`, `cache/pgdata`, `cache/qdrant_storage`, `cache/redis_data`, `cache/prometheus_data`.

## 2026-05-23 18:27 - Cấu trúc lại tài liệu/log/plan

- Tạo thêm thư mục:
  - `logs/tasks/2026`
  - `logs/testing/2026`
  - `logs/cleanup/2026`
  - `plans/archive`
  - `plans/active`
  - `docs/configuration`
  - `docs/testing`
  - `docs/assets`
- Di chuyển log task cũ vào `logs/tasks/2026`.
- Di chuyển plan lịch sử vào `plans/archive`; giữ plan đang làm ở `plans/` để bám `plan-skill`.

## 2026-05-23 18:34 - Test web và tạo banner

- Restart service code trong tmux `rag-chat-code`: `backend`, `parse-data`, `embedding`, `prometheus-collector`.
- Frontend đang chạy trong tmux `frontend` ở port `3100`; Nginx tiếp tục public port `3000`.
- Smoke test API và UI đạt, chi tiết ở `logs/testing/2026/2026-05-23-smoke-test-vllm-rag-web.md`.
- Tạo screenshot: `docs/assets/rag-chat-web-response.png`.
- Tạo GIF banner khoảng 30 giây, delay tương đương khoảng 24fps: `docs/assets/rag-chat-demo.gif`.

## 2026-05-23 18:38 - CI/CD và đóng task

- Tạo lại CI tối thiểu tại `.github/workflows/ci.yml`.
- Verify thêm:
  - `docker compose --env-file .env.example -f docker-compose.yml config`
  - `npm run lint` trong `frontend` đạt, còn 24 warning hiện hữu về hook dependency và `<img>`.
- Ghi nhận worktree có thay đổi tồn tại từ trước task:
  - `.github/workflows/backend-release.yml` và `.github/workflows/frontend-release.yml` đang bị delete.
  - Một số file frontend và `.codex/skills` đã dirty từ trước, không revert.
- Plan chuyển sang `closed`.

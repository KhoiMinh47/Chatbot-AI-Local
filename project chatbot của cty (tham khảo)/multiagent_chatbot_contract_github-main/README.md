<div align="center">

![RAG Chat demo](docs/assets/rag-chat-demo.gif)

# RAG Chat Platform

**Nền tảng hỏi đáp tài liệu, tìm kiếm web có kiểm chứng và tạo hợp đồng chạy bằng pipeline AI nội bộ.**

[Tổng quan](#tổng-quan) •
[Kiến trúc](#kiến-trúc) •
[Pipeline RAG](#pipeline-rag) •
[Vận hành](#vận-hành) •
[Tài liệu](#tài-liệu)

![Python](https://img.shields.io/badge/Python-3.11+-3776AB?style=for-the-badge&logo=python&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-Backend-009688?style=for-the-badge&logo=fastapi&logoColor=white)
![Next.js](https://img.shields.io/badge/Next.js-Frontend-000000?style=for-the-badge&logo=next.js&logoColor=white)
![LangGraph](https://img.shields.io/badge/LangGraph-Pipeline-1d4ed8?style=for-the-badge)
![vLLM](https://img.shields.io/badge/vLLM-64k%20context%20%7C%200.37%20GPU-7c3aed?style=for-the-badge)
![License](https://img.shields.io/badge/License-MIT-2ea44f?style=for-the-badge)

</div>

## Tổng quan

Repo này là một workspace production cho chatbot nội bộ. Hệ thống không chỉ gọi LLM, mà tổ chức đầy đủ các bước cần có để trả lời có căn cứ: nhập tài liệu, parse, chunk, embedding, truy xuất vector, rerank, gom context theo ngân sách token, nạp lịch sử hội thoại, stream phản hồi và lưu lại kết quả.

Các runtime chính:

- `backend`: FastAPI điều phối auth, RAG, hợp đồng, history, admin, analytics.
- `frontend`: Next.js cho chat, quản trị, file manager, session và contract UI.
- `parse-data`: service parse tài liệu sang markdown.
- `embedding`: service embedding và rerank.
- `vllm`: OpenAI-compatible inference server cho model chat nội bộ.
- `postgres`, `qdrant`, `redis`, `minio`: lớp dữ liệu, cache và object storage.
- `nginx`, `prometheus`, exporters: reverse proxy và vận hành.

Mục tiêu kỹ thuật của dự án là giữ pipeline rõ ràng, giảm chi phí GPU, kiểm soát token theo từng nhánh xử lý và vẫn đủ bằng chứng để trả lời ổn định trong môi trường triển khai thật.

## Kiến trúc

```mermaid
flowchart LR
  User[Người dùng] --> Nginx[Nginx / Cloudflare Tunnel]
  Nginx --> FE[Next.js Frontend]
  Nginx --> API[FastAPI Backend]

  API --> Auth[Auth / Role / Session]
  API --> RAG[LangGraph RAG]
  API --> Contract[LangGraph Contract]
  API --> Web[Web Search Pipeline]

  RAG --> Parse[parse-data]
  RAG --> Embed[embedding / rerank]
  RAG --> Qdrant[(Qdrant Vector DB)]
  RAG --> PG[(PostgreSQL)]
  RAG --> Redis[(Redis Cache)]
  RAG --> MinIO[(MinIO File Store)]
  RAG --> LLM[vLLM Gemma 4]

  Web --> Broker[Search Broker]
  Broker --> SearxNG[SearxNG]
  Broker --> Brave[Brave Search]
  Broker --> Bing[Bing Search]

  API --> Prom[Prometheus Collector]
```

Thiết kế tách service theo trách nhiệm. Backend giữ vai trò orchestrator, còn parse, embedding, rerank và inference chạy như các service độc lập để dễ scale, restart và đo tài nguyên.

## Module Matrix

| Module | Vai trò | Điểm cần biết khi sửa |
| --- | --- | --- |
| `backend/agent_chatbot/graph` | Khai báo LangGraph workflow | Giữ thứ tự node và router rõ ràng, tránh nhét logic xử lý vào graph |
| `backend/agent_chatbot/node` | Node pipeline và SSE event | Mỗi node đẩy trạng thái cho frontend, logic nặng nằm ở `util` |
| `backend/agent_chatbot/node/util` | Retrieval, rerank, prompt, web evidence | Đây là lõi hiệu năng RAG, thay đổi phải có test smoke |
| `backend/service/history_pipeline_service.py` | Nạp history liên quan | Giảm nhiễu prompt bằng history có chọn lọc |
| `embedding/src/service` | Embedding và rerank | Tách khỏi backend để tránh nghẽn CPU/GPU trong API |
| `parse-data/src/service` | Parse tài liệu | Chuẩn hóa tài liệu đầu vào trước khi chunk |
| `frontend/src/app/chat` | Chat UI và SSE | Phản ánh tiến độ từng node để user không thấy hệ thống bị đứng |
| `docker-compose*.yml` | Hạ tầng local/prod | Dùng cache volume cố định, vLLM chạy GPU, Nginx là public entrypoint |

## Pipeline RAG

### 1. Upload và index tài liệu

```mermaid
flowchart LR
  A[Upload file] --> B[docling_parse_node]
  B --> C[chunking_node]
  C --> D[embedding_node]
  D --> E[Qdrant payload + vector]
  D --> F[PostgreSQL metadata]
  A --> G[MinIO file gốc]
```

Luồng upload có ba node chính trong `backend/agent_chatbot/graph/rag_graph.py`:

1. `docling_parse_node`: gọi parse service để chuyển file thành markdown sạch.
2. `chunking_node`: cắt theo heading, giữ `heading_group_id` để các phần thuộc cùng mục có thể được ghép lại.
3. `embedding_node`: tạo vector cho từng chunk và ghi vào Qdrant.

Điểm quan trọng là chunk không chỉ là lát cắt text. Mỗi chunk mang theo heading, path, group id và metadata để retrieval có thể lấy lại đúng đoạn theo cấu trúc tài liệu.

### 2. Truy vấn RAG tự động

```mermaid
flowchart LR
  A[Query] --> B[node_check_path_session]
  B --> C[node_search]
  C --> D[node_seach_with_path]
  D --> E[node_fetch_history]
  E --> F[node_asisstant]
  F --> G[SSE response]
```

Khi user không chọn file cụ thể, backend chạy nhánh tự động:

1. Tạo embedding cho câu hỏi.
2. Query Qdrant theo group path để tìm tài liệu ứng viên.
3. Rerank các chunk bằng service rerank, chỉ giữ path có điểm đủ tốt.
4. Với từng path đạt ngưỡng, truy vấn lại theo heading để lấy context chi tiết.
5. Nạp history liên quan.
6. Gọi vLLM và stream token về frontend qua SSE.

Nhánh này tối ưu tốc độ bằng cách không đọc toàn bộ tài liệu ngay từ đầu. Hệ thống tìm path trước, rerank trước, rồi mới mở rộng context cho những path có khả năng trả lời cao.

### 3. Truy vấn theo file user chọn

```mermaid
flowchart LR
  A[Query + path_list] --> B[node_check_path_session]
  B --> C[node_search_path_user_chose]
  C --> D{Số file}
  D -->|1 file| E[Load full path trong budget]
  D -->|2-10 file| F[Search full từng path + rerank]
  D -->|>10 file| G[Vector search từng path + rerank]
  E --> H[node_fetch_history]
  F --> H
  G --> H
  H --> I[node_asisstant]
```

Đây là điểm đáng giá của pipeline hiện tại. Logic không xử lý mọi trường hợp như nhau:

- Một file: ưu tiên lấy nội dung file trong budget để tránh mất chi tiết.
- Từ 2 đến 10 file: search hết chunk theo từng path, rerank riêng từng file, giữ nguyên heading quan trọng.
- Trên 10 file: dùng vector search theo path để giảm tải, sau đó rerank và ghép context.

Nhờ vậy hệ thống vừa nhanh khi người dùng chọn nhiều file, vừa ít rủi ro bỏ sót khi chỉ hỏi trên một tài liệu.

### 4. Budget token và prompt

Các ngưỡng hiện đọc từ env root, không hard-code vào pipeline:

| Biến | Mặc định hiện tại | Vai trò |
| --- | --- | --- |
| `LLM_CONTEXT_WINDOW` | `65536` | Cửa sổ context vLLM |
| `LLM_MAX_TOKENS` | `10000` | Output tối đa cho model |
| `RAG_INPUT_TOKEN_BUDGET` | `50000` | Ngân sách input tổng |
| `RAG_OUTPUT_TOKEN_BUDGET` | `10000` | Ngân sách output RAG |
| `RAG_FILE_CONTEXT_TOKEN_BUDGET` | `40000` | Phần context tài liệu |
| `RAG_HISTORY_TOKEN_BUDGET` | `10000` | Phần history liên quan |
| `RAG_SELECTED_PATH_TOKEN_BUDGET` | `50000` | Budget khi user chọn path |
| `RAG_AVG_TOKENS_PER_CHUNK` | `600` | Ước lượng chunk để chia quota theo path |
| `RAG_CHARS_PER_TOKEN` | `2.5` | Quy đổi token sang ký tự khi cắt context |

Prompt cuối cùng được xếp theo thứ tự ổn định cho cache: context chính, history liên quan, câu hỏi mới. Cách này giúp giảm nhiễu từ history và giữ phần tài liệu có giá trị ở gần đầu prompt.

## Web Search Pipeline

```mermaid
flowchart LR
  A[User query] --> B[node_web_coordinator]
  B --> C[node_web_domain_mapper]
  C --> D[node_web_url_selector]
  D --> E[node_web_fetch_clean]
  E --> F[node_web_rerank]
  F --> G[node_web_summarize]
  G --> H[node_fetch_history]
  H --> I[node_web_synthesize]
  I --> J[node_web_verify]
  J -->|Cần thêm evidence| B
  J -->|Đủ tin cậy| K[Answer + citations]
```

Web search không chỉ lấy vài URL rồi nhét vào prompt. Pipeline có broker đa provider, source policy, title-aware URL selection, fetch clean, rerank evidence, tóm tắt theo câu hỏi nghiên cứu và verifier loop. Nếu evidence chưa đủ, verifier có thể yêu cầu research loop tiếp theo trong giới hạn cấu hình.

Các biến `WEB_*` trong `.env.example` kiểm soát timeout, số URL, cache, retry, circuit breaker, domain allow/block và citation validation.

## Contract Pipeline

```mermaid
flowchart LR
  A[Template upload] --> B[parse_docling_node]
  B --> C[save_template_node]

  D[Create contract] --> E[ask_llm_node]
  E --> F[create_word_node]

  G[Reasoning contract] --> H[drafter_node]
  H --> I[critic_node]
  I -->|FAIL| J[reviser_node]
  J --> I
  I -->|PASS| K[generate_word_node]
```

Contract module có ba nhánh: tạo thường, tạo nhanh và reasoning nhiều bước. Nhánh reasoning tách drafter, critic, reviser để kiểm tra bản nháp trước khi xuất file Word.

## Điểm Mạnh Kỹ Thuật

| Nhóm | Cách dự án xử lý |
| --- | --- |
| Tốc độ RAG | Tìm path trước, rerank trước, mở rộng context sau; nhánh path_list có chiến lược riêng theo số file |
| Độ đúng ngữ cảnh | Chunk theo heading, giữ heading integrity, ghép đủ mục thay vì chỉ lấy một đoạn rời |
| Kiểm soát token | Budget input, output, file context, history và selected path nằm trong env |
| Trải nghiệm realtime | Node pipeline đẩy SSE event để frontend hiển thị tiến độ parse/search/rerank/answer |
| Vận hành GPU | vLLM 64k context, `GPU_MEMORY_UTIL=0.37`, KV cache fp8, tắt multimodal limit không dùng |
| Production data layer | PostgreSQL qua PgBouncer, Qdrant vector DB, Redis cache, MinIO object store |
| Web evidence | Broker đa provider, retry, cache, source policy, citation validation và verifier loop |
| Bảo trì | Graph khai báo luồng, util giữ logic nặng, docs/logs/plans có taxonomy riêng |

## Vận hành

### Chuẩn bị env

```bash
cp .env.example .env
```

Điền secret thật trong `.env` ở thư mục gốc. Các service backend, embedding, parse-data và prometheus-collector đọc env root; không dùng `.env` riêng trong từng service. Frontend có thể giữ `frontend/.env.local`.

### Chạy local bằng script

```bash
bash ./run_all_services.sh
```

Script dùng tmux session/window theo env:

- `CODE_TMUX_SESSION=rag-chat-code`
- `BACKEND_TMUX_WINDOW=backend`
- `FRONTEND_TMUX_WINDOW=frontend`
- `PARSER_TMUX_WINDOW=parse-data`
- `EMBEDDING_TMUX_WINDOW=embedding`
- `PROMETHEUS_COLLECTOR_TMUX_WINDOW=prometheus-collector`

### Chạy hạ tầng Docker

```bash
docker compose --env-file .env -f docker-compose.yml up -d
```

Nginx là public entrypoint, phù hợp triển khai Cloudflare Tunnel qua `NGINX_PUBLIC_PORT=3000`.

### Endpoint kiểm tra nhanh

```bash
curl http://localhost:9000/docs
curl http://localhost:8005/docs
curl http://localhost:8006/docs
curl http://localhost:8007/v1/models
curl http://localhost:3000/
```

### Validation trước khi push

```bash
python3 -m py_compile \
  backend/main.py \
  embedding/main.py \
  parse-data/main.py \
  prometheus-collector/main.py \
  backend/service/prometheus_service.py \
  prometheus-collector/src/service/prometheus_service.py \
  backend/agent_chatbot/node/util/rag_query_util.py

docker compose --env-file .env.example -f docker-compose.yml config >/tmp/compose-main.yml

cd frontend
npm run lint
```

CI strict trên GitHub còn chạy workflow lint, markdownlint, secret scan, backend quality, frontend quality và compose validate.

## Cấu Trúc Repo

```text
backend/                 FastAPI, auth, LangGraph, service, database setup
frontend/                Next.js app, chat UI, admin UI, contract/file manager
parse-data/              Parse service cho tài liệu upload
embedding/               Embedding và rerank service
prometheus-collector/    API thu metrics từ Prometheus
config/                  Nginx, Redis, Prometheus, SearxNG, vLLM template
docker/                  Dockerfile theo service/kiến trúc
docs/                    Tài liệu kỹ thuật tiếng Việt
logs/                    Log task, testing, cleanup theo năm
plans/                   Plan hiện tại và archive
pipeline/                Benchmark và ghi chú pipeline cũ
scripts/                 Script hỗ trợ capture demo GIF/screenshot
cache/                   Runtime data/cache local, không commit secret hoặc dữ liệu lớn
```

## Tài liệu

- [Docs hub](docs/README.md)
- [Tổng quan dự án](docs/overview/project-overview.md)
- [Kiến trúc hệ thống](docs/architecture/system-architecture.md)
- [Tổng quan backend](docs/backend/backend-overview.md)
- [Tổng quan frontend](docs/frontend/frontend-overview.md)
- [Tổng quan pipeline](docs/pipeline/pipeline-overview.md)
- [Cấu hình Env, vLLM, RAG và Cache](docs/configuration/env-vllm-rag-cache.md)
- [Runbook triển khai](docs/deployment/deployment-runbook.md)
- [Runbook vận hành](docs/operations/operations-runbook.md)
- [API reference](docs/api/api-reference.md)
- [Chính sách CI/CD](docs/cicd/cicd-policy.md)
- [Logs](logs/README.md)
- [Plans](plans/README.md)

## Ghi Chú Chính Xác

- README phản ánh source hiện tại trong repo, đặc biệt là các graph tại `backend/agent_chatbot/graph`.
- vLLM đã được xác nhận chạy ở `LLM_CONTEXT_WINDOW=65536` và `GPU_MEMORY_UTIL=0.37` trong phiên kiểm thử ngày 2026-05-23. Mức `0.30` và `0.35` không đủ KV cache cho context 64k trên máy đã test.
- Cache dữ liệu như `cache/pgdata`, `cache/qdrant_storage`, `cache/minio`, `cache/redis_data` và `cache/prometheus_data` là volume runtime, không xóa nếu chưa backup.
- File `.env` thật không được commit. Chỉ commit `.env.example` không chứa secret.

## License

Repository dùng giấy phép MIT. Xem [LICENSE](LICENSE).

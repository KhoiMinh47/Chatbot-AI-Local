# Phase 1 repository scaffold

## Mục tiêu và giới hạn

Phase 1 tạo một repository có thể bootstrap và chạy quality gate trên CPU. Nó
chỉ chứng minh ba skeleton có thể được import/build/test và tuân theo ranh giới
kiến trúc:

- FastAPI cung cấp liveness endpoint.
- Worker có factory và Celery CLI entrypoint tối thiểu, chưa kết nối broker.
- Next.js render landing/login skeleton, chưa có auth backend.
- Shared contracts có vị trí sở hữu rõ ràng.

Phase này không dựng PostgreSQL, Redis, RabbitMQ, MinIO, Qdrant, Nginx, NVIDIA
NIM, observability hoặc Docker Compose. Không có migration, ingestion, retrieval
hay RAG graph. Các mục đó bắt đầu ở Phase 2 hoặc các phase sau theo master plan.

## Cấu trúc và trách nhiệm

```text
apps/
├── api/        FastAPI transport và composition root
├── worker/     factory và CLI entrypoint cho background job ở phase sau
└── web/        Next.js App Router UI skeleton
packages/
├── contracts/  schema/contract dùng chung, không chứa business adapter
└── shared-python/ tiện ích Python dùng chung có dependency tối thiểu
docs/
├── adr/        quyết định đã được chấp nhận
└── architecture/ mô tả kiến trúc theo phase
scripts/        preflight, source-secret scan và smoke có thể chạy lại
```

Thư mục rỗng không được tạo chỉ để giống cây mục tiêu. Một boundary chỉ xuất
hiện khi có skeleton hoặc tài liệu chịu trách nhiệm cho nó.

## Dependency direction

```text
HTTP API / worker entrypoint
            |
            v
       application
            |
            v
          domain

infrastructure --> application ports
```

Mũi tên là chiều dependency trong source code. Domain đứng trong cùng và không
biết FastAPI, persistence, vector store hay model runtime. Infrastructure được
gắn tại composition root; nó không trở thành dependency của domain.

Frontend dùng HTTP contract công khai thay vì import code Python. Shared
contract phải có một nguồn sở hữu và được kiểm tra bằng type/test; không copy
schema độc lập giữa nhiều app.

## Quality gate Phase 1

`make check` chạy tuần tự:

1. kiểm tra offline uv/pnpm lockfile và Python environment đã cài;
2. scan high-confidence credential trong authored source;
3. lint Python, TypeScript và shell;
4. xác minh format mà không sửa source;
5. static type check;
6. pytest và Vitest smoke;
7. production build của web với Next.js telemetry bị tắt;
8. live smoke kiểm tra API liveness và web skeleton.

Quality gate mặc định chạy CPU, offline ngoài các request loopback và không gọi
NIM. Live smoke từ chối port đã bị chiếm và bỏ qua proxy của host cho loopback,
tránh nhận nhầm response từ service/proxy khác. Gate không được diễn giải thành
bằng chứng cho database, queue, GPU, model quality hoặc RAG.

Source-secret scanner chỉ in tên file khi phát hiện mẫu đáng ngờ, không in giá
trị match. Pytest dùng một canary credential để chứng minh cả khả năng phát hiện
và việc không làm lộ giá trị ra stdout/stderr.

`make format` là command chủ động sửa source; `make format-check` chỉ đọc.
`make bootstrap` thay đổi dependency environment cục bộ nhưng không thay đổi dữ
liệu ứng dụng. Bảng đầy đủ nằm trong README.

## Environment contract

`.env.example` chỉ khai báo biến thực sự được skeleton sử dụng và giá trị
không bí mật. `.env` bị ignore. Credential tương lai phải đi qua secret file
hoặc cơ chế secret của runtime, không được đặt trong browser environment.

API server nhận host, port và log level qua `APP_HOST`, `APP_PORT` và
`APP_LOG_LEVEL`; command Uvicorn truyền chính các giá trị đó vào runtime. Worker
CLI được expose tại `worker.runtime:celery`; lệnh `celery report` kiểm tra app
contract mà không khởi động worker hoặc kết nối broker. Các script Next.js
`dev`, `build` và `start` đặt `NEXT_TELEMETRY_DISABLED=1`.

## Acceptance mapping

| Acceptance Phase 1 | Cách chứng minh |
|---|---|
| Một command lint/test chạy local | `make check` |
| API `/health/live` trả HTTP 200 | `make smoke` và API smoke test |
| Web render landing/login skeleton | `make smoke` và Vitest |
| Không có secret | `make secret-scan`, `.gitignore`, placeholder-only `.env.example` và pytest canary không làm lộ matching value |

## Known limitations

- Smoke chỉ kiểm tra skeleton, không phải production readiness.
- Secret scan dùng detector high-confidence; nó hỗ trợ review chứ không thay thế
  quản lý secret hoặc thao tác rotate credential khi đã xảy ra leak.
- Liveness không được dùng để suy diễn readiness của dependency tương lai.
- Chưa có integration test thật vì Phase 1 không có external service.
- GPU/NIM compatibility evidence vẫn thuộc Phase 0; không được chạy ngầm trong
  quality gate CPU.

## Tài liệu liên quan

- [Master plan](../../NTC_NVIDIA_LOCAL_RAG_CHATBOT_MASTER_PLAN.md)
- [ADR 0001 — architecture](../adr/0001-architecture.md)
- [ADR 0002 — Python](../adr/0002-python-version.md)
- [Phase 0 model inventory](../model-inventory.md)

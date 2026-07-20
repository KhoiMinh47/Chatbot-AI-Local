# Phase 2 core infrastructure

## Mục tiêu và ranh giới

Phase 2 cung cấp data services và observability ổn định trên Docker Compose,
đồng thời giữ một host entrypoint duy nhất. Phase này triển khai hạ tầng và cách
kiểm chứng nó; chưa triển khai nghiệp vụ RAG.

Ranh giới kết thúc Phase 2:

- PostgreSQL/Alembic, Redis, RabbitMQ, MinIO và Qdrant chạy có persistence;
- API, Celery worker và web skeleton dùng được qua Nginx;
- Prometheus scrape DCGM exporter và Grafana hiển thị GPU metric thật;
- Mailpit có mặt trong profile phát triển;
- không start NIM, không pull model, không thêm model adapter, inference smoke,
  bake-off hoặc benchmark của Phase 3.

Alembic revision đầu tiên chỉ tạo schema `app`. Worker kết nối RabbitMQ và tự
health-check bằng Celery ping nhưng chưa có product task. Đây là chủ ý để không
đưa ingestion của Phase 4 vào Phase 2.

## Topology và profiles

```text
host 127.0.0.1:8080 -> Nginx reverse-proxy
                           |
                           +-> API -> PostgreSQL / Redis / RabbitMQ / MinIO / Qdrant
                           +-> Web
                           +-> Grafana -> Prometheus -> DCGM exporter -> GPU
                           +-> Mailpit UI

Celery worker -> RabbitMQ
```

| Profile | Services | Host port |
|---|---|---|
| `core` | `postgres`, `redis`, `rabbitmq`, `minio`, `qdrant` | Không |
| `app` | `api`, `worker`, `web`, `reverse-proxy` | Chỉ proxy, `127.0.0.1:8080` mặc định |
| `observability` | `dcgm-exporter`, `prometheus`, `grafana` | Không |
| `dev` | `mailpit` | Không |

Mạng `internal` có `internal: true`; service trên đó không có đường ingress trực
tiếp từ host. Reverse proxy là service duy nhất nối cả `internal` và `edge`, và
Compose chỉ publish port của proxy lên loopback. `expose` ghi lại container port
cho nội bộ, không tạo host binding.

## Storage ownership

| Service | Storage | Ý nghĩa dữ liệu |
|---|---|---|
| PostgreSQL | `postgres_data` | relational source of truth cho metadata ở phase sau; Phase 2 mới có Alembic history và schema `app` |
| Redis | `redis_data` | cache/coordination; AOF và snapshot giúp restart an toàn nhưng Redis không trở thành source of truth |
| RabbitMQ | `rabbitmq_data` | durable message transport; queue không thay thế trạng thái job authoritative trong database |
| MinIO | `minio_data` | source bytes/object artifact ở phase ingestion sau |
| Qdrant | `qdrant_data` | vector index phục vụ retrieval; phải coi là derived/rebuildable từ source và version metadata |
| Prometheus | `prometheus_data` | metric retention 7 ngày/tối đa 10 GB, không phải application state |
| Grafana | `grafana_data` | local Grafana state; datasource/dashboard chuẩn vẫn được provision từ source |
| Mailpit | `mailpit_data` | email dev tạm, không phải delivery source of truth |

Named volume giữ mutable state qua container recreation và qua `make down`.
Bind mount chỉ dùng cho config/entrypoint/dashboard đã review. `tmpfs` chứa file
runtime hoặc writable scratch cho container read-only. Xóa container không đồng
nghĩa xóa volume; `down --volumes` là thao tác phá hủy ngoài command contract.

Acceptance seed một sentinel riêng vào từng datastore, force-recreate năm core
container, đọc lại sentinel rồi xóa đúng test key/row/queue/object/collection.
Việc này chứng minh container lifecycle không làm mất named-volume state mà
không diễn giải Redis hay RabbitMQ thành source of truth.

## Health semantics

Container health check trả lời câu hỏi hẹp: process cụ thể có phục vụ dependency
tối thiểu của nó hay không. Mọi service có health check và `restart:
unless-stopped`; các dependency Compose quan trọng chờ trạng thái healthy.

API tách ba contract:

- `/health/live` chỉ xác nhận API process đang trả request;
- `/health/dependencies` chạy probe có timeout, không trả URL hay credential;
- `/health/ready` chỉ trả 200 khi mọi dependency bắt buộc sẵn sàng.

LLM là dependency bắt buộc nhưng chưa được cấu hình ở Phase 2. Vì vậy liveness
và các probe hạ tầng có thể pass trong khi readiness trả 503 với LLM
`unconfigured`. Compose dùng liveness cho API container health để Phase 2 có thể
hoàn thành độc lập với Phase 3.

DCGM exporter chỉ healthy khi endpoint có series `DCGM_FI_DEV_GPU_UTIL` thật.
Prometheus scrape exporter mỗi 5 giây. Acceptance truy vấn metric qua Grafana
datasource proxy và yêu cầu ít nhất một result; dashboard JSON tồn tại một mình
không đủ làm bằng chứng GPU observability.

## Security contract

- External image có tag dễ đọc và digest bất biến; `pull_policy: never` ngăn
  Compose tự thay image. Script staging chỉ chấp nhận image `linux/arm64`.
- Secret local nằm ở `.secrets/phase2`, bị Git ignore. Initializer không ghi đè
  file có sẵn và áp directory mode `0750`, file mode `0640`.
- PostgreSQL, Redis, RabbitMQ, MinIO và Grafana đọc password từ file-mounted
  secret. Rendered Compose config được kiểm tra để không chứa giá trị secret.
- API, worker, web và proxy dùng read-only root filesystem cùng tmpfs cần thiết.
  Mọi service có CPU, memory, PID limit và `no-new-privileges`.
- Không service nào dùng host network, privileged mode hoặc Docker socket.
  DCGM exporter được cấp GPU và capability `SYS_ADMIN` cần cho exporter nhưng
  không chạy `privileged: true`.
- Grafana và Mailpit chỉ có thể vào qua loopback proxy. Mailpit không có auth,
  nên topology này không được mở trực tiếp ra untrusted network.

## Vận hành và mutation

`make up-core` chạy riêng datastore, không cần GPU. `make up` chạy đủ profiles
và cần GPU runtime cho DCGM exporter. `make migrate` áp revision vào PostgreSQL
đang healthy; migration không tự start database.

`make phase2-acceptance` là integration workflow có mutation và yêu cầu project
không còn container. Nó có thể pull image, build image app, tạo migration/test
state, recreate core container và ghi evidence. Mặc định trap sẽ dừng/xóa
container nhưng giữ named volume; `PHASE2_KEEP_RUNNING=1` thay đổi hành vi đó.
Không dùng workflow này trên một Compose project đang phục vụ workload khác.

## Acceptance mapping

| Acceptance Phase 2 | Cách chứng minh |
|---|---|
| `docker compose config` hợp lệ | `make phase2-config`; đồng thời kiểm tra topology, pin, limit, health, network và secret leak |
| Tất cả core service healthy | `make phase2-acceptance` ghi state/health của đủ 13 service |
| Chỉ proxy port được publish trong test profile | static rendered-config check và runtime port-binding inspection |
| Restart không mất test data | sentinel trên PostgreSQL, Redis, RabbitMQ, MinIO, Qdrant trước/sau force-recreate |
| Grafana thấy GPU metric thật | query `DCGM_FI_DEV_GPU_UTIL` qua provisioned Prometheus datasource và kiểm tra dashboard |

`make check` là quality gate CPU và chỉ chứa test tĩnh/unit cho Phase 2; không
được dùng thay bằng chứng integration ở trên.

## Giới hạn đã biết

- Không có NIM hoặc model endpoint, nên API readiness chưa mở.
- Không có ingestion, retrieval, auth hay product schema/task.
- Dashboard có thêm temperature, framebuffer memory và power panel; GB10 có thể
  không export mọi metric này. GPU utilization là metric bắt buộc duy nhất của
  acceptance và không được thay bằng dữ liệu giả.
- Prometheus/Grafana là baseline metric; centralized log aggregation chưa nằm
  trong Phase 2 acceptance.
- Loopback gateway là local-test boundary, không phải public deployment
  hardening.

## Tài liệu liên quan

- [Master plan](../../NTC_NVIDIA_LOCAL_RAG_CHATBOT_MASTER_PLAN.md)
- [Phase 1 scaffold](phase-1-scaffold.md)
- [Migration boundary](../../migrations/README.md)
- [Phase 0 model inventory](../model-inventory.md)

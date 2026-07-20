# Phase 2 acceptance evidence

- Thời điểm bắt đầu run cuối (UTC): `2026-07-14T06:06:00Z`
- Phạm vi: Phase 2 — Core Infrastructure bằng Docker Compose
- Master plan: `NTC_NVIDIA_LOCAL_RAG_CHATBOT_MASTER_PLAN.md`
- Run chuẩn: `artifacts/phase-2/runs/20260714T060600Z-208773`
- Kết quả: **PASS**

Các run trước trong `artifacts/phase-2/runs/` là evidence debug đã fail đúng khi
phát hiện endpoint RabbitMQ sai, RabbitMQ node name không ổn định và phép kiểm
tra GPU freshness quá chặt. Chỉ run chuẩn nêu trên được dùng để kết luận Phase 2.

## Môi trường đã kiểm tra

| Thành phần | Giá trị |
|---|---|
| Kiến trúc host/container | `linux/arm64` |
| GPU | NVIDIA GB10 |
| NVIDIA driver | `580.142` |
| Docker Engine | `29.1.3` |
| Docker Compose | `2.40.3` |
| Python quality gate | CPython `3.14.5`, standard GIL |

Tất cả external image của Phase 2 có tag và digest bất biến. Script staging đã
xác minh từng exact reference tồn tại local với platform `linux/arm64` trước khi
acceptance khởi động stack.

## Đối chiếu acceptance criteria

| Acceptance Phase 2 | Kết quả và evidence |
|---|---|
| `docker compose config` hợp lệ | **PASS** — `static-check.txt` và `compose-config.json`; static contract đồng thời kiểm tra service set, health check, restart policy, limits, internal network, volumes, image pin và không lộ secret |
| Tất cả core service healthy | **PASS** — `service-health.tsv`: toàn bộ 13 service của bốn profile đều `running/healthy`, bao gồm 5 core service |
| Chỉ proxy port được publish trong test profile | **PASS** — `runtime-port-bindings.tsv`: chỉ `reverse-proxy` có một binding `127.0.0.1:8080`; mọi port khác chỉ là container expose, không có host binding |
| Restart không mất dữ liệu test | **PASS** — `core-container-ids-before.tsv` và `core-container-ids-after.tsv` chứng minh cả 5 container core có ID mới và healthy; `persistence-verify.txt` xác nhận sentinel của PostgreSQL, Redis, RabbitMQ, MinIO và Qdrant còn tồn tại rồi được dọn |
| Grafana thấy metric GPU thật | **PASS** — Grafana datasource proxy trả `DCGM_FI_DEV_GPU_UTIL` có `modelName=NVIDIA GB10`; `grafana-dcgm-up.json` có target value `1`; `grafana-gpu-freshness.json` có age khoảng `3.36s`; dashboard UID `ntc-gpu-overview` đã provision |

## Kết quả runtime chi tiết

Run cuối xác minh:

- Alembic đang ở revision `0001_phase2 (head)` và schema boundary `app` tồn tại.
- API dependency probes trả `ok` cho PostgreSQL, Redis, Qdrant, RabbitMQ và
  MinIO. LLM trả `unconfigured`, vì vậy `/health/ready` trả HTTP 503 đúng ranh
  giới Phase 2; `/health/live` vẫn healthy.
- PostgreSQL row, Redis key, RabbitMQ durable message, MinIO object và Qdrant
  point đều sống qua `--force-recreate` của năm core container.
- RabbitMQ dùng hostname/node name ổn định `rabbit@rabbitmq`, nên Mnesia trong
  named volume được phục hồi bởi container mới.
- Prometheus target DCGM đang `up=1`. Acceptance lọc metric có timestamp không
  quá 30 giây, vì vậy series lịch sử trong volume không thể tạo false-positive.
- GPU dashboard dùng các metric DCGM thật cho utilization, temperature,
  framebuffer memory và power; không tạo dữ liệu giả cho metric GB10 không hỗ
  trợ.
- Cleanup kết thúc thành công, còn `0` container của project. Named volumes được
  giữ lại đúng command contract.
- Quét toàn bộ `artifacts/phase-2` theo năm giá trị secret local cho kết quả `0`
  hit.

## Quality gates

```text
make check
  PASS — lock checks và package compatibility
  PASS — source credential scan
  PASS — Ruff, ESLint, Bash syntax, ShellCheck và formatting
  PASS — mypy và TypeScript typecheck
  PASS — 48 pytest và 2 Vitest
  PASS — Next.js production build
  PASS — Phase 1 regression smoke

make phase2-config
  PASS — Compose topology/security contract

make phase2-images
  PASS — mọi pinned image có sẵn cho linux/arm64

make phase2-acceptance
  PASS — full live Compose/GPU acceptance và cleanup
```

## Debug closure

- Sửa import runtime từ package lock thực tế `httpx2`, thêm timeout tổng cho
  dependency probe và tắt inherited proxy cho traffic nội bộ/loopback.
- Mount secret API theo đúng tên `APP_*`; bổ sung runtime group để API, worker
  và Grafana non-root đọc file `0640` mà không làm secret public.
- Sửa Redis entrypoint để config tmpfs thuộc user `redis` sau khi official
  entrypoint drop privilege.
- Giữ nguyên prefix `/api/` qua Nginx; không publish MinIO console.
- RabbitMQ probe dùng endpoint tồn tại trong image pin 3.13; node name cố định
  để durable queue thực sự sống qua container recreation.
- Persistence probe xử lý đúng Kombu JSON body dạng text/bytes, verify cả năm
  datastore trước khi cleanup và không in exception có thể chứa credential.
- Acceptance trap giữ đúng exit code khi nhận signal, fail nếu cleanup/redaction
  fail, chứng minh container ID đổi và không chấp nhận GPU series cũ.
- Grafana tắt update/plugin network background phù hợp internal network; auth
  acceptance nằm trong file tạm mode `0600`, không xuất hiện trong process argv.
- Image staging có timeout và retry hữu hạn; Docker resume partial layer sau khi
  registry/CDN bị ngắt mạng.

## Boundary audit

- Không start hoặc thêm service NIM.
- Không pull model, smoke inference, benchmark, bake-off hoặc scorecard.
- Không viết LLM/embedding/reranking adapter.
- Migration chỉ tạo schema `app`; không tạo schema nghiệp vụ của ingestion,
  authentication, retrieval hay chat.
- Worker chỉ chứng minh kết nối/health với RabbitMQ; chưa có product task.

## Giới hạn đã biết

- API readiness cố ý đóng cho tới Phase 3 vì LLM chưa được cấu hình.
- Loki/Promtail được nhắc trong thiết kế observability tổng quát nhưng không nằm
  trong task/acceptance trực tiếp của Phase 2; centralized log aggregation chưa
  được triển khai.
- Grafana và Mailpit chỉ phù hợp local test qua loopback gateway. Mailpit không
  có auth riêng; không được đổi binding sang public/tunnel ở trạng thái này.
- Một số metric DCGM ngoài utilization có thể không có series trên unified-memory
  GB10; dashboard để trống thay vì giả lập dữ liệu.
- Compose cảnh báo Buildx/Bake không có trên host rồi dùng Docker builder mặc
  định thành công; cảnh báo này không ảnh hưởng image pin hoặc acceptance.

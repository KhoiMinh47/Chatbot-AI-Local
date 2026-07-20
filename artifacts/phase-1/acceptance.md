# Phase 1 acceptance evidence

- Captured at UTC: `2026-07-14T03:20:15Z`
- Scope: Phase 1 — Repository Scaffold và Developer Experience
- Master plan: `NTC_NVIDIA_LOCAL_RAG_CHATBOT_MASTER_PLAN.md`
- Phase 0 decisions retained: modular monolith, standard-GIL CPython
  `>=3.14,<3.15`, versioned dependencies and a separate application lock.

## Environment

| Tool | Reviewed version |
|---|---|
| Python | 3.14.5, `Py_GIL_DISABLED=0` |
| uv | 0.11.16, ARM64 |
| Node.js | 22.22.2 |
| pnpm | 10.32.0 |
| GNU Make | 4.3 |
| ShellCheck | 0.9.0 |

## Acceptance mapping

| Phase 1 acceptance | Evidence |
|---|---|
| Một command lint/test chạy local | `make bootstrap && make check` exit `0`; `make check` là quality gate duy nhất sau bootstrap |
| API `/health/live` trả HTTP 200 | live smoke yêu cầu exact HTTP `200`, sau đó kiểm tra JSON `status=ok` và `service=ntc-api` |
| Web render landing/login skeleton | Next production build tạo route `/` và `/login`; live smoke kiểm tra marker của cả hai trang; Vitest pass |
| Không có secret | `make secret-scan` pass; pytest canary chứng minh scanner fail khi có credential và không in matching value |

## Commands and results

```text
uv lock --check --offline --python 3.14
  PASS — 53 packages resolved from the reviewed lock

uv pip check --python .venv/bin/python
  PASS — 51 installed packages are compatible

pnpm install --frozen-lockfile --offline --lockfile-only
  PASS — pnpm-lock.yaml is current and can be verified without registry access

make bootstrap && make check
  PASS — bootstrap accepts only the reviewed uv/pnpm lockfiles
  PASS — offline lock validation, Python package compatibility and source-secret scan
  PASS — Ruff, ESLint, Bash syntax, ShellCheck and formatting
  PASS — mypy: 27 source files
  PASS — TypeScript strict typecheck
  PASS — pytest: 25 tests
  PASS — Vitest: 2 tests
  PASS — Next.js production build: / and /login statically rendered
  PASS — live smoke: API liveness, landing page and login skeleton
```

The final acceptance run was isolated: no concurrent build or smoke command was
running. The informational pnpm warning for the deliberately ignored optional
`unrs-resolver` build script is covered by `pnpm-workspace.yaml`; installation,
ESLint and the production build all passed.

## Debug closure

- Worker broker validation now converts nested DSN errors at the `SecretStr`
  boundary, preventing credentials from appearing in `str`, `repr`,
  `ValidationError.errors()` or `ValidationError.json()`.
- API liveness tests construct explicit settings and pass even when the host
  environment defines conflicting `APP_*` variables.
- The Celery CLI entrypoint loads and reports configuration without connecting
  to a broker; a socket fail-on-connect regression test protects this property.
- Live smoke bypasses host proxies for loopback, rejects already occupied ports,
  verifies the spawned process is still alive after HTTP 200 and cleans its
  process groups.
- The quality gate now enforces lock consistency and source-secret scanning;
  architecture and shared-contract edge cases have executable regression tests.

## Boundary audit

- No `compose.yaml`, Dockerfile, `infra/` or `migrations/` path was created.
- No PostgreSQL, Redis, RabbitMQ service, MinIO, Qdrant, reverse proxy, NIM
  runtime or observability stack was started.
- The Celery worker exposes a configuration/factory and CLI report entrypoint;
  neither opens a broker connection.
- Login remains visibly disabled; no fake authentication path was added.
- Smoke binds only `127.0.0.1`, rejects redirects and leaves no process or port
  behind.

## Known limitations

- Liveness proves only that the API process can respond; it is not dependency
  readiness.
- Phase 1 has unit/contract/live-skeleton tests, not external-service
  integration tests.
- Live NIM inference and the unresolved Phase 0 vendor/evidence anomalies remain
  explicitly outside this phase.
- Phase 2 has not been implemented.

# Phase 4 — Document Ingestion

Phase 4 is **complete against all five explicit acceptance criteria**. The
canonical live run is
[`20260715T0912Z-live-e2e-r3`](runs/20260715T0912Z-live-e2e-r3/) and its
machine-readable report is the source of truth.

## Delivered path

```text
FastAPI upload (HTTP 202)
  -> raw object in MinIO
  -> durable PostgreSQL document/version/job metadata
  -> RabbitMQ ingestion queue
  -> Celery worker
  -> MIME validation and parser selection
  -> Docling / CSV / plain-text parse
  -> normalized artifact + preview in MinIO
  -> structure-aware parent/child chunks in PostgreSQL
  -> READY or stable FAILED error
```

The API request persists/enqueues work and returns; the worker performs parsing
asynchronously. A worker task is keyed by `job_id` and reloads authoritative
metadata instead of trusting paths or tenant fields from a queue payload.

## Implementation map

- API application/domain ports:
  [`apps/api/app/application/ingestion.py`](../../apps/api/app/application/ingestion.py)
  and
  [`apps/api/app/domain/ingestion.py`](../../apps/api/app/domain/ingestion.py).
- PostgreSQL, MinIO and Celery adapters:
  [`apps/api/app/infrastructure/ingestion.py`](../../apps/api/app/infrastructure/ingestion.py).
- Internal Phase 4 transport:
  [`apps/api/app/api/documents.py`](../../apps/api/app/api/documents.py).
- Worker task, parser, normalization and chunking:
  [`apps/worker/worker/tasks/__init__.py`](../../apps/worker/worker/tasks/__init__.py),
  [`apps/worker/worker/parsers/__init__.py`](../../apps/worker/worker/parsers/__init__.py),
  and
  [`apps/worker/worker/chunking/__init__.py`](../../apps/worker/worker/chunking/__init__.py).
- Final Phase 4 schema hardening:
  [`0004_phase4_ingestion_completion.py`](../../migrations/versions/0004_phase4_ingestion_completion.py).
- Reproducible live runner:
  [`scripts/phase4_acceptance.py`](../../scripts/phase4_acceptance.py).

## Canonical evidence

| Artifact | SHA-256 / meaning |
|---|---|
| [`report.json`](runs/20260715T0912Z-live-e2e-r3/report.json) | `d8aa67e3c67620836519dcfb33d7d4f7ac6b5cd356d7004226b0c1376cb5797d` |
| [`gold-final-100.jsonl`](runs/20260715T0912Z-live-e2e-r3/gold-final-100.jsonl) | `23fae69fd369361106978335ca7476dbf6694a1c5e5208c2e836ad473fe56ec8` |
| [`acceptance.md`](acceptance.md) | Detailed criterion-by-criterion review and limitations |
| [`COMPLETION.md`](COMPLETION.md) | Phase handoff summary |

Canonical results: 10 ready documents, 11 versions, 26 total chunks, 12 current
child chunks, zero duplicate chunk-coordinate groups, and all five acceptance
booleans true.

## Re-running acceptance

Prerequisites:

- PostgreSQL, MinIO and RabbitMQ from the Phase 2 core stack are healthy;
- migrations are at `0004_phase4_completion` or later;
- one Celery worker consumes the `ingestion` queue with routing key
  `document.process`;
- database, MinIO and RabbitMQ secret files exist locally and are never printed;
- LibreOffice, Docling and OCR assets are installed/cached.

The runner always requires a new output directory and writes the report
exclusively, so an old run cannot be overwritten:

```bash
uv run --locked --no-sync python scripts/phase4_acceptance.py \
  --output-dir artifacts/phase-4/runs/<new-run-id> \
  --database-host <postgres-host> \
  --database-password-file .secrets/phase2/postgres_password \
  --minio-endpoint <minio-host>:9000 \
  --minio-secret-key-file .secrets/phase2/minio_root_password \
  --broker-host <rabbitmq-host> \
  --broker-password-file .secrets/phase2/rabbitmq_password
```

Do not copy transient container IPs into repository configuration. Discover
them for the current local run or execute the runner on the internal Compose
network.

Focused CPU checks:

```bash
uv run --locked --no-sync pytest -q \
  apps/api/tests/test_ingestion_application.py \
  apps/worker/tests/test_phase4_ingestion_completion.py \
  tests/test_phase4_parsers.py \
  tests/test_phase4_chunking.py \
  tests/test_phase4_integration.py
```

## Run history

- `20260715T0907Z-live-e2e-r1`: failed before report; queue topology mismatch.
- `20260715T0910Z-live-e2e-r2`: failed before report; PostgreSQL job-state
  parameter ambiguity/worker failure.
- `20260715T0912Z-live-e2e-r3`: canonical PASS after queue, SQL and OCR runtime
  fixes.

Failed directories remain evidence of debugging. Only a valid `report.json`
whose acceptance booleans are all true may be used as PASS evidence.

## Boundary

This phase intentionally does not claim embeddings, Qdrant alias activation,
RAG answer quality, public auth/RBAC or Phase 7 API contracts. The internal
trusted-header profile exists only so the ingestion pipeline can be exercised
before the authentication phase.

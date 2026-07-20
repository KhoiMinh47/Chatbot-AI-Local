# Phase 4 completion — Document Ingestion

- Status: **COMPLETE — 5/5 explicit acceptance criteria passed**
- Canonical run: `20260715T0912Z-live-e2e-r3`
- Completed at: `2026-07-15T02:12:36.884200Z`
- Report:
  [`report.json`](runs/20260715T0912Z-live-e2e-r3/report.json)
- Report SHA-256:
  `d8aa67e3c67620836519dcfb33d7d4f7ac6b5cd356d7004226b0c1376cb5797d`

## Outcome

The Phase 4 pipeline now accepts a file without blocking on parsing, persists
raw content and authoritative metadata, dispatches a real RabbitMQ/Celery job,
parses/normalizes the source, creates structure-aware chunks, stores normalized
and preview artifacts, and exposes a stable successful or failed job result.

The canonical live run processed 10 non-sensitive real file fixtures to
`READY`, including text/scanned/table PDFs, CSV, PPTX, DOCX, TXT and Markdown.
It also proved duplicate upload, concurrent reindex, completed-task redelivery,
delete and corrupt-parser behavior.

## Acceptance checklist

- [x] PDF, scanned PDF, CSV and PPTX ran end-to-end.
- [x] Upload returned HTTP 202 before asynchronous worker completion; max
  observed API latency was `60.17 ms`.
- [x] Chunk records retained source and the applicable page/slide/section
  fields, plus full text and content hash.
- [x] Duplicate upload/reindex/redelivery produced no duplicate chunk
  coordinates; replay count remained `26 → 26`.
- [x] Corrupt PDF produced `PARSER_CORRUPT_DOCUMENT` with an actionable message.

Supporting live counts: 10 active/ready documents, 11 versions, 26 chunks, 12
current child chunks, zero duplicate coordinate groups. All current-version
raw, normalized and preview paths resolved to objects in MinIO.

## Important fixes closed before PASS

1. API and worker now declare the same durable exchange, ingestion queue, DLX
   and `document.process` route.
2. PostgreSQL job state updates explicitly cast the reused state parameter,
   removing ambiguous-parameter failures.
3. RapidOCR's selected ONNX backend is backed by a locked Linux ARM64
   `onnxruntime` dependency.
4. Jobs load trusted database metadata from `job_id`; queue messages do not
   carry authoritative tenant or object paths.
5. Database constraints and idempotency keys protect active hash/version, job
   and chunk-coordinate uniqueness.
6. Raw, normalized and preview artifact paths are version-bound and verified.

The failed r1/r2 output directories are preserved without PASS reports. They
are debugging history, not acceptance evidence.

## Companion retrieval dataset

[`gold-final-100.jsonl`](runs/20260715T0912Z-live-e2e-r3/gold-final-100.jsonl)
contains 50 calibration and 50 held-out evaluation questions, with 40
answerable and 10 unanswerable in each split. Its SHA-256 is
`23fae69fd369361106978335ca7476dbf6694a1c5e5208c2e836ad473fe56ec8`.
It was added after the immutable live report and is not misrepresented as part
of that report's original 20-sample gold metadata.

## Known limitations and handoff

- The internal trusted-header acceptance profile is not production auth; Phase
  7 must supply authenticated identity/RBAC.
- A cold network-isolated worker needs Docling/OCR model assets staged before
  first parse. The canonical run used locally available assets.
- The 10-file corpus meets Phase 4 acceptance, but its three-PDF mix should be
  expanded to the broader section-19.1 release-evaluation distribution before
  Phase 12.
- Embedding, vector indexing and active Qdrant alias are Phase 5 work. Grounded
  Fast/Reasoning generation is Phase 6 work; neither is claimed by this sign-off.

See [`acceptance.md`](acceptance.md) for the full criterion mapping and
[`README.md`](README.md) for rerun instructions.

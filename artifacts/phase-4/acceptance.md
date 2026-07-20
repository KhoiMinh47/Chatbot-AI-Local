# Phase 4 acceptance evidence — Document Ingestion

- Master plan scope: Phase 4 — Document Ingestion
- Canonical live run: `20260715T0912Z-live-e2e-r3`
- Completed: `2026-07-15T02:12:36.884200Z`
- Result: **PASS — 5/5 Phase 4 acceptance criteria**
- Tenant: `d30abdd6-3154-5de9-a295-1639bc36ebd4`
- Report SHA-256:
  `d8aa67e3c67620836519dcfb33d7d4f7ac6b5cd356d7004226b0c1376cb5797d`

The canonical run exercised the real application path from an in-process ASGI
FastAPI instance through MinIO and RabbitMQ/Celery to PostgreSQL. The API did
not parse documents in the request. The worker parsed and normalized real PDF,
scanned PDF, CSV, PPTX, DOCX, TXT and Markdown files; no fake parser response or
in-memory database was used.

Primary evidence:

- [`report.json`](runs/20260715T0912Z-live-e2e-r3/report.json) — machine-readable
  source of truth.
- [`report.md`](runs/20260715T0912Z-live-e2e-r3/report.md) — short run summary.
- [`fixtures/`](runs/20260715T0912Z-live-e2e-r3/fixtures/) — exact 10-file corpus.
- [`gold-final-100.jsonl`](runs/20260715T0912Z-live-e2e-r3/gold-final-100.jsonl)
  — companion retrieval set created from the same source names after the live
  ingestion run.
- [`gold-final-100-v2-stratified.jsonl`](runs/20260715T0912Z-live-e2e-r3/gold-final-100-v2-stratified.jsonl)
  — calibration/evaluation language-stratified revision consumed by the final
  Phase 5 activation run.

## Acceptance criteria

| Criterion from master plan | Result | Live evidence |
|---|---|---|
| PDF, scanned PDF, CSV and PPTX run end-to-end | **PASS** | 10/10 documents reached `READY`: three PDF variants (text, scan/OCR, table), two CSV, two PPTX, one DOCX, one TXT and one Markdown |
| Job does not block API | **PASS** | All uploads returned HTTP 202 before worker completion; maximum measured upload latency was `60.17 ms`, below the runner's `10,000 ms` gate |
| Chunks keep source/page/slide/section | **PASS** | `text_pdf_page`, `scanned_pdf_ocr`, `pptx_slide`, `section_path_stored` and `full_text_and_hash` are all true; source name is present in the tenant-scoped chunk query |
| Rerunning jobs creates no duplicate | **PASS** | Duplicate upload reused the existing document; two concurrent reindex requests returned one job; completed-task redelivery left chunk count `26 → 26`; duplicate coordinate groups `0`; delete twice returned HTTP 204 |
| Parser failure exposes a useful error | **PASS** | Corrupt PDF ended in `failed` with stable code `PARSER_CORRUPT_DOCUMENT`, retry count `1`, and message “The document could not be parsed; verify that it is not corrupt or encrypted.” |

## Live state observed

The database counts below are scoped to the canonical tenant and exclude the
deleted corrupt-file fixture:

| Item | Count |
|---|---:|
| Active documents | 10 |
| Ready documents | 10 |
| Document versions | 11 |
| All parent/child chunks | 26 |
| Child chunks on current versions | 12 |
| Duplicate `(version, type, index)` groups | 0 |

The extra version is the successful idempotency/reindex check. The run observed
48 objects in the shared `ntc-documents` bucket; that number is bucket-wide, so
it is not presented as this run's exclusive object count. The stronger
run-scoped check passed: every current version had its raw, normalized and
preview artifact path and every referenced object existed in MinIO.

## Corpus and companion gold set

The ten accepted source files are non-sensitive generated fixtures with stable
SHA-256 values recorded in `report.json`. They cover:

- text PDF, scanned/OCR PDF and table PDF;
- CSV tables and PPTX slide metadata;
- DOCX, plain text and Markdown;
- English and Vietnamese retrieval questions in the companion set.

The live report was written by the earlier 20-sample runner and therefore
correctly records `gold.jsonl` as 10 calibration + 10 evaluation samples. The
append-only companion `gold-final-100.jsonl` is the dataset intended for the
next retrieval stage:

- SHA-256:
  `23fae69fd369361106978335ca7476dbf6694a1c5e5208c2e836ad473fe56ec8`;
- 100 lines: 50 calibration and 50 held-out evaluation;
- each split: 40 answerable and 10 unanswerable;
- expected source names cover all ten canonical files.

The companion file is not retroactively claimed as part of the immutable live
report hash. Current `scripts/phase4_acceptance.py` generates the full 100
samples for future runs.

Phase 5 used the append-only v2 companion, SHA-256
`393c9147f6a59a41e1a038a7622dc7d4183571fb4a1aa3a1940514629c155ca3`.
It keeps 50 calibration/50 evaluation cases and moves an English/Vietnamese
pair between splits so calibration is not English-only. The original companion
and its hash above remain unchanged as debug history.

## Idempotency and failure semantics

- The task receives only `job_id`; authoritative document/version/object paths
  are loaded from PostgreSQL.
- Job idempotency keys and database constraints prevent duplicate active
  versions, jobs and chunk coordinates.
- Reindex creates a new version and updates `current_version_id` only after a
  successful pipeline.
- Parser failures use stable codes and bounded retry/backoff; malformed input
  does not turn into a successful empty document.
- Delete is idempotent and the acceptance flow verified two consecutive calls.

## Debug history retained

The failed attempt directories are deliberately retained and are not counted
as passing evidence:

| Attempt | Result | What was learned/fixed |
|---|---|---|
| `20260715T0907Z-live-e2e-r1` | **FAILED before report** | API producer/worker queue topology and DLX/routing declarations did not match; exact `ingestion` exchange/queue/routing binding was applied |
| `20260715T0910Z-live-e2e-r2` | **FAILED before report** | PostgreSQL could not infer the reused state parameter in the job update; explicit varchar casts were added and worker failures were re-run |
| `20260715T0912Z-live-e2e-r3` | **PASS** | Queue, database update and OCR runtime path all completed end-to-end |

The r1/r2 directories contain fixtures and their then-current gold file but no
`report.json`; absence of a report is treated as failure, never as partial pass.
Before r3, the selected RapidOCR ONNX backend was also made reproducible by
locking `onnxruntime` for Linux ARM64.

## Scope boundary and known limitations

- The trusted actor headers used by this internal acceptance profile are not a
  public authentication mechanism. Phase 7 must replace that boundary with
  authenticated identity/RBAC without changing the ingestion use case.
- Phase 4 stores normalized text and chunks; embedding/Qdrant activation belongs
  to Phase 5 and is not claimed here.
- The canonical corpus satisfies all five explicit Phase 4 acceptance criteria.
  Its mix has three PDFs total, not the larger six-PDF distribution suggested
  for the eventual full evaluation corpus in master-plan section 19.1; expand
  the release-evaluation corpus before Phase 12.
- A cold egress-isolated worker must have Docling/OCR model assets staged before
  first use. The canonical local run used the available local cache.
- The current ingestion and generation-trace tables are in PostgreSQL's
  `public` schema, while the empty Phase 2 `app` schema remains only the original
  boundary placeholder. Moving live tables into `app` would require a separate
  reviewed data migration and query update; it is architecture debt, not an
  unreported result of this Phase 4 run.

Phase 4 is complete against its explicit acceptance criteria. This evidence
does not claim Phase 5, Phase 6, production authentication, or release-quality
evaluation completion.

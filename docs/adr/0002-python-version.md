# ADR 0002 — Use the CPython 3.14 line; keep 3.13 as an explicit fallback only

- Status: Accepted
- Date: 2026-07-13
- Phase: 0
- Decision gate: DG-01
- Owners: NTC Local RAG team

## Context

The source requirement says `Python >3.13`. That text is ambiguous in normal
conversation and unsafe when copied literally into package metadata. Under
version-specifier rules, `>3.13` can admit patch releases in the 3.13 line and
does not cap a future 3.15 release. The master plan therefore requires a real
Python 3.14 dependency lock test and permits 3.13 only through a recorded ADR
when 3.14 fails.

The host's system interpreter is Python 3.12.3, so the test used an isolated,
uv-managed interpreter rather than altering the operating system Python.

## Compatibility spike

Input: [`compatibility/python/pyproject.toml`](../../compatibility/python/pyproject.toml)
and its generated [`uv.lock`](../../compatibility/python/uv.lock). This is a
Phase 0 union of the API/RAG and worker libraries named by the master plan, not
the root application package.

| Check on Linux ARM64 / GB10 | Result |
|---|---|
| Interpreter | CPython 3.14.5, standard GIL build |
| Package manager | uv 0.11.16 for aarch64 |
| Strict project range | `>=3.14,<3.15` |
| Dependency resolution | Pass: 183 packages locked |
| Locked normal install | Pass: 180 distributions installed |
| Top-level import/Pydantic/FastAPI/LangGraph/Docling smoke | Pass |
| Torch/CUDA smoke | Pass: Torch 2.13.0+cu130 sees GB10, capability 12.1; CUDA matrix multiply returned 11.0 |
| Wheel-only install | Expected failure: `pylatexenc==2.10` and `antlr4-python3-runtime==4.9.3` require source builds; both built successfully in the normal install |
| `uv pip check` | One platform-tag warning for `nvidia-cusparselt-cu13==0.8.1`; see below |
| Python 3.13 fallback | Not run, because the 3.14 lock, normal install, imports, and CUDA smoke passed |

The first lock attempt timed out while reading Pillow metadata. A retry with a
longer HTTP timeout resolved successfully; the network failure is retained in
the artifacts and is not treated as Python incompatibility.

## Known package/platform anomaly

`uv pip check` reports `nvidia-cusparselt-cu13` as built for another platform.
Its wheel declares `py3-none-manylinux2014_sbsa`, which uv's check does not
accept as a standard `aarch64` platform tag. Direct evidence nevertheless shows
that the included `libcusparseLt.so.0` is an ARM aarch64 ELF, all dynamic
dependencies resolve, `ctypes` loads it, Torch imports, CUDA is available, and
a GPU matrix multiplication succeeds.

This is a recorded packaging-tag exception, not proof of a Python 3.14 failure.
Phase 1 must not silently suppress new `uv pip check` findings: it should either
resolve this SBSA metadata issue in the final split lock or document the exact
same exception with the final Torch/Docling versions.

The current Docling dependency graph also does not install ONNX Runtime on
Python 3.14. Phase 0 proves resolution/import, not OCR quality. Phase 4 must run
real PDF/PPTX/DOCX conversions, state the selected OCR backend, and reopen this
ADR if an essential backend excludes 3.14.

## Options considered

### 1. CPython 3.14, bounded to the tested minor line

This meets the strict business interpretation and has a successful local
lock/install/import/CUDA spike on the target architecture.

### 2. CPython 3.13 immediately

This may have a wider history of package support but does not meet a strict
`>3.13` interpretation. Selecting it without a demonstrated 3.14 failure would
be an undocumented requirement deviation.

### 3. Literal `>3.13`

Rejected because it does not encode the intended minor line reproducibly.

## Decision

- Phase 1 must use the normal-GIL **CPython 3.14** line and declare
  `requires-python = ">=3.14,<3.15"`.
- Do not use the host's Python 3.12 and do not opt into free-threaded `cp314t`
  without a separate compatibility test.
- Generate the real Phase 1 lock from split application/worker dependency
  inputs; do not copy this union spike blindly.
- Python 3.13 remains a contingency only. If a required runtime path fails on
  3.14 and cannot be corrected with a supported dependency version/backend,
  test `>=3.13,<3.14`, amend this ADR with the failing trace, and request
  confirmation that the requirement means “Python 3.13 or newer.”

## Consequences

### Positive

- The selected minor line satisfies the strict requirement and is tested on
  the target host architecture.
- The system Python stays untouched.
- The fallback cannot happen silently.

### Negative and risks

- Two transitive packages currently require reproducible source builds.
- The SBSA wheel tag produces a package-check warning even though the ARM
  library and CUDA smoke pass.
- Service round trips (PostgreSQL, RabbitMQ, Qdrant, Redis, MinIO) and real
  Docling conversions remain later-phase integration tests.
- A dependency update requires regenerating and re-running this gate.

## Validation evidence

- [`python314-lock-retry.log`](../../artifacts/preflight/20260713T090800Z/python314-lock-retry.log)
- [`python314-sync-with-sdist.log`](../../artifacts/preflight/20260713T090800Z/python314-sync-with-sdist.log)
- [`python314-sync-offline-recheck.log`](../../artifacts/preflight/20260713T090800Z/python314-sync-offline-recheck.log)
- [`python314-import-smoke.log`](../../artifacts/preflight/20260713T090800Z/python314-import-smoke.log)
- [`python314-cuda-smoke.log`](../../artifacts/preflight/20260713T090800Z/python314-cuda-smoke.log)
- [`python314-status.tsv`](../../artifacts/preflight/20260713T090800Z/python314-status.tsv)
- [`python314-environment.txt`](../../artifacts/preflight/20260713T090800Z/python314-environment.txt)

## Revisit when

- The final Phase 1 split lock differs materially from this spike.
- `uv pip check` produces a new failure or the SBSA binary smoke stops passing.
- Required Docling parsing/OCR, Celery, database, or LangGraph runtime tests fail
  specifically because of Python 3.14.
- Python 3.15 support is intentionally evaluated.

## References

- [PyPA version specifiers](https://packaging.python.org/en/latest/specifications/version-specifiers/)
- [Python 3.14 free-threading HOWTO](https://docs.python.org/3.14/howto/free-threading-python.html)
- [Python 3.14 changes](https://docs.python.org/3.14/whatsnew/3.14.html)
- [uv project locking and syncing](https://docs.astral.sh/uv/concepts/projects/sync/)
- [uv resolution](https://docs.astral.sh/uv/concepts/resolution/)
- [Master plan: DG-01](../../NTC_NVIDIA_LOCAL_RAG_CHATBOT_MASTER_PLAN.md#dg-01--python)

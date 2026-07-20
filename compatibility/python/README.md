# Phase 0 Python compatibility spike

This directory is evidence for Decision Gate DG-01 only. It is intentionally
isolated from the repository root and is not the Phase 1 application package.

The input covers the Python libraries named by the master plan whose native or
transitive dependencies are most likely to expose interpreter/ARM64 issues.
The lock file proves resolution; a locked sync and import smoke are recorded
separately under `artifacts/preflight/`.

Verify the reviewed Python 3.14 lock without changing it:

```bash
uv lock --project compatibility/python --check --offline --python 3.14
UV_PROJECT_ENVIRONMENT=/tmp/ntc-rag-python314 \
  uv sync --project compatibility/python --locked --offline --python 3.14
PYTHONDONTWRITEBYTECODE=1 \
  UV_PROJECT_ENVIRONMENT=/tmp/ntc-rag-python314 \
  uv run --project compatibility/python --locked --no-sync \
  python compatibility/python/smoke.py
uv pip check --python /tmp/ntc-rag-python314/bin/python
```

Only regenerate the compatibility-spike lock intentionally, after reviewing
dependency changes:

```bash
uv lock --project compatibility/python --python 3.14
```

The smoke imports the selected top-level libraries, exercises Pydantic/FastAPI/
LangGraph/Docling APIs, loads the cuSPARSELt shared library through `ctypes`, and
performs a CUDA matrix multiplication on the GB10.
`uv pip check` is expected to report the documented `manylinux2014_sbsa`
platform-tag anomaly for `nvidia-cusparselt-cu13`; ADR 0002 records the ELF,
dynamic-linker, `ctypes`, and live CUDA evidence used to classify that exception.
Any additional incompatibility is a new failure and must not be suppressed.
`uv pip check` is pointed at the environment's interpreter explicitly because
that subcommand does not select a project environment from
`UV_PROJECT_ENVIRONMENT`. The exact smoke source checksum and command for the reviewed run
are recorded in `artifacts/preflight/20260713T090800Z/python314-environment.txt`.

Python 3.13 is tested only if the 3.14 lock, install, or import smoke fails. It
was not invoked in this run because the strict 3.14 path passed.

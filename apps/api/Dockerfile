ARG UV_IMAGE=ghcr.io/astral-sh/uv:0.11.16@sha256:440fd6477af86a2f1b38080c539f1672cd22acb1b1a47e321dba5158ab08864d
ARG PYTHON_IMAGE=python:3.14.5-slim-bookworm@sha256:a9bee15510a364124aa24692899d269835683b883de42f7ebec8c293cf679ccb

FROM ${UV_IMAGE} AS uv-bin
FROM ${PYTHON_IMAGE} AS runtime

ENV PATH="/workspace/.venv/bin:${PATH}" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

# Install system dependencies required by Python packages
RUN apt-get update && apt-get install -y --no-install-recommends \
    libmagic1 \
    && rm -rf /var/lib/apt/lists/*

COPY --from=uv-bin /uv /uvx /bin/

WORKDIR /workspace

COPY pyproject.toml uv.lock ./
COPY apps/api/pyproject.toml apps/api/pyproject.toml
COPY apps/worker/pyproject.toml apps/worker/pyproject.toml
COPY packages/contracts/pyproject.toml packages/contracts/pyproject.toml
COPY packages/shared-python/pyproject.toml packages/shared-python/pyproject.toml

RUN uv sync --frozen --no-dev --package ntc-api --no-install-workspace

COPY apps/api/app apps/api/app
COPY packages/contracts/src packages/contracts/src
COPY packages/shared-python/src packages/shared-python/src

RUN uv sync --frozen --no-dev --package ntc-api --no-editable \
    && useradd --create-home --uid 10001 --shell /usr/sbin/nologin ntc

USER 10001:10001
EXPOSE 8000

CMD ["uvicorn", "--app-dir", "apps/api", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--log-level", "info"]

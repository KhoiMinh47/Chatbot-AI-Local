ARG UV_IMAGE=ghcr.io/astral-sh/uv:0.11.16@sha256:440fd6477af86a2f1b38080c539f1672cd22acb1b1a47e321dba5158ab08864d
ARG PYTHON_IMAGE=python:3.14.5-slim-bookworm@sha256:a9bee15510a364124aa24692899d269835683b883de42f7ebec8c293cf679ccb

FROM ${UV_IMAGE} AS uv-bin
FROM ${PYTHON_IMAGE} AS runtime

ENV PATH="/workspace/.venv/bin:${PATH}" \
    TIKTOKEN_CACHE_DIR=/opt/tiktoken-cache \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

# Install system dependencies required by Python packages (including Rust for tiktoken)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    cargo \
    curl \
    libmagic1 \
    && rm -rf /var/lib/apt/lists/*

COPY --from=uv-bin /uv /uvx /bin/

WORKDIR /workspace

COPY pyproject.toml uv.lock ./
COPY apps/api/pyproject.toml apps/api/pyproject.toml
COPY apps/worker/pyproject.toml apps/worker/pyproject.toml
COPY packages/contracts/pyproject.toml packages/contracts/pyproject.toml
COPY packages/shared-python/pyproject.toml packages/shared-python/pyproject.toml

# Set compatibility flag for Python 3.14 + PyO3/tiktoken
ENV PYO3_USE_ABI3_FORWARD_COMPATIBILITY=1

RUN uv sync --frozen --no-dev --package ntc-worker --no-install-workspace

# Runtime uses an internal-only Docker network, so tokenizer data must be staged
# in the image instead of being downloaded during the first uploaded document.
RUN mkdir -p "${TIKTOKEN_CACHE_DIR}" \
    && python -c 'import tiktoken; tiktoken.get_encoding("cl100k_base")' \
    && chmod -R a=rX "${TIKTOKEN_CACHE_DIR}"

# OpenCV (used by RapidOCR) is dynamically linked even in the headless worker.
RUN apt-get update && apt-get install -y --no-install-recommends \
    libgl1 \
    libglib2.0-0 \
    libxcb1 \
    && rm -rf /var/lib/apt/lists/*

ENV DOCLING_ARTIFACTS_PATH=/opt/docling-models

# The runtime network is intentionally internal-only. Stage exactly the models
# used by the PDF pipeline so parsing never performs a first-request download.
RUN docling-tools models download \
    --output-dir "${DOCLING_ARTIFACTS_PATH}" \
    --quiet \
    layout tableformer rapidocr \
    && chmod -R a=rX "${DOCLING_ARTIFACTS_PATH}"

ENV HF_HUB_OFFLINE=1 \
    TRANSFORMERS_OFFLINE=1

COPY apps/worker/worker apps/worker/worker
COPY infra/worker/entrypoint.sh /usr/local/bin/ntc-worker-entrypoint
COPY infra/worker/healthcheck.sh /usr/local/bin/ntc-worker-healthcheck

RUN uv sync --frozen --no-dev --package ntc-worker --no-editable \
    && chmod 0555 /usr/local/bin/ntc-worker-entrypoint /usr/local/bin/ntc-worker-healthcheck \
    && useradd --create-home --uid 10001 --shell /usr/sbin/nologin ntc

USER 10001:10001

ENTRYPOINT ["/usr/local/bin/ntc-worker-entrypoint"]

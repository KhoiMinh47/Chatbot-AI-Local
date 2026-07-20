#!/usr/bin/env bash

set -euo pipefail

ROOT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
ENV_FILE=${PHASE2_ENV_FILE:-$ROOT_DIR/infra/compose/phase2.env}
PULL_TIMEOUT_SECONDS=${PHASE2_IMAGE_PULL_TIMEOUT_SECONDS:-1200}
PULL_ATTEMPTS=${PHASE2_IMAGE_PULL_ATTEMPTS:-3}

if [[ ! -f $ENV_FILE ]]; then
  printf 'Phase 2 environment file is missing: %s\n' "$ENV_FILE" >&2
  exit 2
fi
command -v docker >/dev/null 2>&1 || {
  printf 'Required command is unavailable: docker\n' >&2
  exit 127
}
command -v timeout >/dev/null 2>&1 || {
  printf 'Required command is unavailable: timeout\n' >&2
  exit 127
}
if [[ ! $PULL_TIMEOUT_SECONDS =~ ^[1-9][0-9]*$ ]]; then
  printf 'PHASE2_IMAGE_PULL_TIMEOUT_SECONDS must be a positive integer.\n' >&2
  exit 2
fi
if [[ ! $PULL_ATTEMPTS =~ ^[1-9][0-9]*$ ]]; then
  printf 'PHASE2_IMAGE_PULL_ATTEMPTS must be a positive integer.\n' >&2
  exit 2
fi

set -a
# shellcheck disable=SC1090
. "$ENV_FILE"
set +a

IMAGE_REFS=(
  "$POSTGRES_IMAGE"
  "$REDIS_IMAGE"
  "$RABBITMQ_IMAGE"
  "$MINIO_IMAGE"
  "$QDRANT_IMAGE"
  "$NGINX_IMAGE"
  "$PROMETHEUS_IMAGE"
  "$GRAFANA_IMAGE"
  "$DCGM_EXPORTER_IMAGE"
  "$MAILPIT_IMAGE"
  "$PYTHON_IMAGE"
  "$UV_IMAGE"
  "$NODE_IMAGE"
)

for image in "${IMAGE_REFS[@]}"; do
  if [[ $image != *@sha256:* || $image == *:latest* ]]; then
    printf 'Refusing an unpinned Phase 2 image: %s\n' "$image" >&2
    exit 2
  fi
  if ! docker image inspect "$image" >/dev/null 2>&1; then
    printf 'Staging pinned ARM64 image: %s\n' "${image%@sha256:*}"
    pull_succeeded=0
    for ((attempt = 1; attempt <= PULL_ATTEMPTS; attempt++)); do
      if timeout --signal=TERM --kill-after=15s "${PULL_TIMEOUT_SECONDS}s" \
        docker pull --platform linux/arm64 "$image"; then
        pull_succeeded=1
        break
      fi
      printf 'Pinned image pull attempt %s/%s failed; Docker will resume cached layers.\n' \
        "$attempt" "$PULL_ATTEMPTS" >&2
    done
    if ((pull_succeeded == 0)); then
      printf 'Unable to stage pinned image after %s attempts: %s\n' \
        "$PULL_ATTEMPTS" "$image" >&2
      exit 1
    fi
  fi
  platform=$(docker image inspect "$image" --format '{{.Os}}/{{.Architecture}}')
  if [[ $platform != linux/arm64 ]]; then
    printf 'Pinned image has unexpected platform %s: %s\n' "$platform" "$image" >&2
    exit 1
  fi
done

printf 'All pinned Phase 2 images are present for linux/arm64.\n'

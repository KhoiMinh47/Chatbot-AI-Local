#!/usr/bin/env bash
set -Eeuo pipefail

REPOSITORY_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPOSITORY_ROOT"

UV_BIN="${UV_BIN:-uv}"
PHASE3_ENV_FILE="${PHASE3_ENV_FILE:-infra/compose/phase3.env}"
PHASE3_SECRET_GID="${PHASE3_SECRET_GID:-$(id -g)}"
export PHASE3_SECRET_GID

QDRANT_CONTAINER="${PHASE5_QDRANT_CONTAINER:-ntc-rag-phase2-qdrant-1}"
EMBED_CONTAINER="${PHASE5_EMBED_CONTAINER:-ntc-rag-phase3-nim-embedding-300m-1}"
RERANK_CONTAINER="${PHASE5_RERANK_CONTAINER:-ntc-rag-phase3-nim-reranking-500m-1}"
RUN_ID="${PHASE5_RUN_ID:-$(date -u +%Y%m%dT%H%M%SZ)-embed300m}"
OUTPUT_DIR="${PHASE5_OUTPUT_DIR:-artifacts/phase-5/runs/$RUN_ID}"
QDRANT_JUNIT="${PHASE5_QDRANT_JUNIT:-${OUTPUT_DIR}-qdrant-contract.xml}"

PHASE3_COMPOSE=(
  docker compose
  --env-file "$PHASE3_ENV_FILE"
  --file compose.phase3.yaml
  --profile retriever
)

started_services=()

is_running() {
  [[ "$(docker inspect -f '{{.State.Running}}' "$1" 2>/dev/null || true)" == "true" ]]
}

is_healthy() {
  [[ "$(docker inspect -f '{{.State.Health.Status}}' "$1" 2>/dev/null || true)" == "healthy" ]]
}

# shellcheck disable=SC2317  # Invoked indirectly by the EXIT/INT/TERM trap.
cleanup() {
  local status=$?
  if ((${#started_services[@]})); then
    "${PHASE3_COMPOSE[@]}" stop --timeout 120 "${started_services[@]}" >/dev/null || status=1
    "${PHASE3_COMPOSE[@]}" rm --force "${started_services[@]}" >/dev/null || status=1
  fi
  exit "$status"
}
trap cleanup EXIT INT TERM

command -v docker >/dev/null 2>&1 || {
  printf 'Missing required command: docker\n' >&2
  exit 127
}
command -v "$UV_BIN" >/dev/null 2>&1 || {
  printf 'Missing required command: %s\n' "$UV_BIN" >&2
  exit 127
}
docker info >/dev/null 2>&1 || {
  printf 'Docker daemon is unavailable.\n' >&2
  exit 1
}

if ! is_healthy "$QDRANT_CONTAINER"; then
  printf 'Phase 5 requires healthy %s; run make up-core first.\n' "$QDRANT_CONTAINER" >&2
  exit 1
fi

services_to_start=()
if ! is_running "$EMBED_CONTAINER"; then
  services_to_start+=(nim-embedding-300m)
  started_services+=(nim-embedding-300m)
fi
if ! is_running "$RERANK_CONTAINER"; then
  services_to_start+=(nim-reranking-500m)
  started_services+=(nim-reranking-500m)
fi
if ((${#services_to_start[@]})); then
  "${PHASE3_COMPOSE[@]}" up --detach --wait --wait-timeout 1800 "${services_to_start[@]}"
fi
if ! is_healthy "$EMBED_CONTAINER" || ! is_healthy "$RERANK_CONTAINER"; then
  printf 'Phase 5 retriever NIM services are not healthy.\n' >&2
  exit 1
fi

qdrant_ip="$(docker inspect -f '{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}' "$QDRANT_CONTAINER")"
embed_ip="$(docker inspect -f '{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}' "$EMBED_CONTAINER")"
rerank_ip="$(docker inspect -f '{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}' "$RERANK_CONTAINER")"
for address in "$qdrant_ip" "$embed_ip" "$rerank_ip"; do
  if [[ -z "$address" ]]; then
    printf 'Unable to resolve a private container IP for Phase 5.\n' >&2
    exit 1
  fi
done

if [[ -e "$QDRANT_JUNIT" ]]; then
  printf 'Refusing to overwrite Qdrant contract evidence: %s\n' "$QDRANT_JUNIT" >&2
  exit 1
fi
mkdir -p "$(dirname "$QDRANT_JUNIT")"

PHASE5_QDRANT_URL="http://$qdrant_ip:6333" \
  "$UV_BIN" run --locked --no-sync pytest -q \
  --junitxml "$QDRANT_JUNIT" \
  tests/test_phase5_qdrant_integration.py

set +e
"$UV_BIN" run --locked --no-sync python scripts/phase5_benchmark.py \
  --output-dir "$OUTPUT_DIR" \
  --qdrant-url "http://$qdrant_ip:6333" \
  --qdrant-contract-junit "$QDRANT_JUNIT" \
  --embedding-base-url "http://$embed_ip:8000/v1" \
  --rerank-base-url "http://$rerank_ip:8000/v1"
benchmark_status=$?
set -e

if [[ "$benchmark_status" -ne 3 ]]; then
  printf 'Phase 5 benchmark failed with exit code %s.\n' "$benchmark_status" >&2
  exit "$benchmark_status"
fi

printf 'Phase 5 candidate evidence written to %s; status remains BLOCKED.\n' "$OUTPUT_DIR"
exit 3

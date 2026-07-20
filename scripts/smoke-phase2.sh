#!/usr/bin/env bash

set -euo pipefail

ROOT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
ENV_FILE=${PHASE2_ENV_FILE:-$ROOT_DIR/infra/compose/phase2.env}
SECRET_DIR=${PHASE2_SECRET_DIR:-$ROOT_DIR/.secrets/phase2}
PHASE2_SECRET_GID=${PHASE2_SECRET_GID:-$(id -g)}
PHASE2_ENV_FILE=$ENV_FILE
PHASE2_SECRET_DIR=$SECRET_DIR
export PHASE2_ENV_FILE PHASE2_SECRET_DIR PHASE2_SECRET_GID
WAIT_TIMEOUT_SECONDS=${PHASE2_WAIT_TIMEOUT_SECONDS:-300}
KEEP_RUNNING=${PHASE2_KEEP_RUNNING:-0}
RUN_ID=$(date -u +%Y%m%dT%H%M%SZ)-$$
EVIDENCE_DIR=${PHASE2_EVIDENCE_DIR:-$ROOT_DIR/artifacts/phase-2/runs/$RUN_ID}
COMPOSE=(docker compose --env-file "$ENV_FILE" --file "$ROOT_DIR/compose.yaml")
PROFILES=(--profile core --profile app --profile observability --profile dev)
EXPECTED_SERVICES=(
  api
  dcgm-exporter
  grafana
  mailpit
  minio
  postgres
  prometheus
  qdrant
  rabbitmq
  redis
  reverse-proxy
  web
  worker
)
CORE_SERVICES=(postgres redis rabbitmq minio qdrant)
STARTED=0
CURL_AUTH_CONFIG=

fail() {
  printf 'Phase 2 acceptance failed: %s\n' "$1" >&2
  exit 1
}

compose() {
  "${COMPOSE[@]}" "${PROFILES[@]}" "$@"
}

container_id() {
  local service=$1
  "${COMPOSE[@]}" "${PROFILES[@]}" ps --quiet "$service"
}

container_ip() {
  local service=$1
  local id
  id=$(container_id "$service")
  [[ -n $id ]] || fail "container is missing for $service"
  docker inspect "$id" \
    --format '{{range .NetworkSettings.Networks}}{{if .IPAddress}}{{.IPAddress}}{{end}}{{end}}'
}

redact_evidence() {
  uv run --locked --no-sync python - "$SECRET_DIR" "$EVIDENCE_DIR" <<'PY'
import sys
from pathlib import Path

secret_dir = Path(sys.argv[1])
evidence_dir = Path(sys.argv[2])
if not evidence_dir.is_dir():
    raise SystemExit(0)

secrets = [
    value
    for path in secret_dir.iterdir()
    if path.is_file() and (value := path.read_bytes().strip())
]
for path in evidence_dir.rglob("*"):
    if not path.is_file():
        continue
    original = path.read_bytes()
    redacted = original
    for value in secrets:
        redacted = redacted.replace(value, b"[REDACTED]")
    if redacted != original:
        path.write_bytes(redacted)
PY
}

cleanup() {
  local status=$?
  trap - EXIT INT TERM
  if ((STARTED == 1)); then
    if ((status != 0)); then
      compose logs --no-color --tail=200 >"$EVIDENCE_DIR/container-logs.txt" 2>&1 || true
    fi
    if [[ $KEEP_RUNNING != 1 ]]; then
      if ! compose down --remove-orphans >>"$EVIDENCE_DIR/cleanup.log" 2>&1; then
        printf 'Phase 2 cleanup failed; inspect cleanup.log.\n' >&2
        ((status == 0)) && status=1
      fi
    fi
  fi
  if [[ -n $CURL_AUTH_CONFIG ]]; then
    rm -f -- "$CURL_AUTH_CONFIG"
  fi
  if ! redact_evidence; then
    printf 'Phase 2 evidence redaction failed.\n' >&2
    ((status == 0)) && status=1
  fi
  printf 'Phase 2 acceptance evidence: %s\n' "$EVIDENCE_DIR"
  exit "$status"
}
trap 'exit 130' INT
trap 'exit 143' TERM
trap cleanup EXIT

for command in docker curl jq uv; do
  command -v "$command" >/dev/null 2>&1 || fail "required command is unavailable: $command"
done
[[ $WAIT_TIMEOUT_SECONDS =~ ^[1-9][0-9]*$ ]] || fail "wait timeout must be a positive integer"
[[ $KEEP_RUNNING == 0 || $KEEP_RUNNING == 1 ]] || fail "PHASE2_KEEP_RUNNING must be 0 or 1"
[[ -f $ENV_FILE ]] || fail "environment file is missing"
[[ ! -e $EVIDENCE_DIR ]] || fail "evidence directory already exists"

umask 077
mkdir -p "$EVIDENCE_DIR"
docker info >/dev/null 2>&1 || fail "Docker daemon is unavailable"
"$ROOT_DIR/scripts/phase2-secrets.sh" check >/dev/null
"$ROOT_DIR/scripts/phase2-compose-check.sh" >"$EVIDENCE_DIR/static-check.txt"
compose config --format json >"$EVIDENCE_DIR/compose-config.json"

if [[ -n $(compose ps --all --quiet) ]]; then
  fail "project already has containers; run 'make down' before the isolated acceptance test"
fi

STARTED=1
compose up --detach --build --wait --wait-timeout "$WAIT_TIMEOUT_SECONDS"

printf 'service\tcontainer_id\tstate\thealth\n' >"$EVIDENCE_DIR/service-health.tsv"
for service in "${EXPECTED_SERVICES[@]}"; do
  id=$(container_id "$service")
  [[ -n $id ]] || fail "expected service is absent: $service"
  state=$(docker inspect "$id" --format '{{.State.Status}}')
  health=$(docker inspect "$id" --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}missing{{end}}')
  printf '%s\t%s\t%s\t%s\n' "$service" "$id" "$state" "$health" \
    >>"$EVIDENCE_DIR/service-health.tsv"
  [[ $state == running && $health == healthy ]] || fail "$service is not running and healthy"
done

printf 'service\tbindings\n' >"$EVIDENCE_DIR/runtime-port-bindings.tsv"
for service in "${EXPECTED_SERVICES[@]}"; do
  id=$(container_id "$service")
  bindings=$(docker inspect "$id" --format '{{json .NetworkSettings.Ports}}')
  printf '%s\t%s\n' "$service" "$bindings" >>"$EVIDENCE_DIR/runtime-port-bindings.tsv"
  published_count=$(jq '[to_entries[] | .value // [] | .[]] | length' <<<"$bindings")
  if [[ $service == reverse-proxy ]]; then
    [[ $published_count == 1 ]] || fail "reverse proxy does not have exactly one host binding"
    jq -e '[to_entries[] | .value // [] | .[]][0].HostIp == "127.0.0.1"' \
      <<<"$bindings" >/dev/null || fail "reverse proxy is not bound only to loopback"
  elif [[ $published_count != 0 ]]; then
    fail "$service unexpectedly publishes a host port"
  fi
done

set -a
# shellcheck disable=SC1090
. "$ENV_FILE"
set +a
proxy_url="http://127.0.0.1:${PHASE2_PROXY_PORT:-8080}"
curl --disable --noproxy '*' --fail --silent --show-error \
  "$proxy_url/gateway-health" >"$EVIDENCE_DIR/proxy-health.txt"
curl --disable --noproxy '*' --fail --silent --show-error \
  "$proxy_url/health/live" >"$EVIDENCE_DIR/api-liveness.json"
curl --disable --noproxy '*' --fail --silent --show-error \
  "$proxy_url/health/dependencies" >"$EVIDENCE_DIR/api-dependencies.json"
jq -e '
  .ready == false and .status == "degraded" and
  ([.dependencies[] | select(.name != "llm") | select(.status != "ok")] | length == 0) and
  ([.dependencies[] | select(.name == "llm" and .status == "unconfigured")] | length == 1)
' "$EVIDENCE_DIR/api-dependencies.json" >/dev/null || fail "API dependency health contract is incorrect"

readiness_status=$(curl --disable --noproxy '*' --silent --show-error \
  --output "$EVIDENCE_DIR/api-readiness.json" --write-out '%{http_code}' \
  "$proxy_url/health/ready")
[[ $readiness_status == 503 ]] || fail "API readiness must stay closed until Phase 3 LLM is configured"

PHASE2_ENV_FILE="$ENV_FILE" "$ROOT_DIR/scripts/phase2-migrate.sh" \
  >"$EVIDENCE_DIR/migration.txt" 2>&1

export PHASE2_POSTGRES_HOST
export PHASE2_POSTGRES_USER=$POSTGRES_USER
export PHASE2_POSTGRES_DB=$POSTGRES_DB
export PHASE2_POSTGRES_PASSWORD_FILE=$SECRET_DIR/postgres_password
export PHASE2_REDIS_HOST
export PHASE2_REDIS_PASSWORD_FILE=$SECRET_DIR/redis_password
export PHASE2_RABBITMQ_HOST
export PHASE2_RABBITMQ_USER=$RABBITMQ_DEFAULT_USER
export PHASE2_RABBITMQ_PASSWORD_FILE=$SECRET_DIR/rabbitmq_password
export PHASE2_MINIO_HOST
export PHASE2_MINIO_USER=$MINIO_ROOT_USER
export PHASE2_MINIO_PASSWORD_FILE=$SECRET_DIR/minio_root_password
export PHASE2_QDRANT_HOST

resolve_datastore_hosts() {
  PHASE2_POSTGRES_HOST=$(container_ip postgres)
  PHASE2_REDIS_HOST=$(container_ip redis)
  PHASE2_RABBITMQ_HOST=$(container_ip rabbitmq)
  PHASE2_MINIO_HOST=$(container_ip minio)
  PHASE2_QDRANT_HOST=$(container_ip qdrant)
}

marker="phase2-${RUN_ID,,}"
resolve_datastore_hosts
printf 'service\tcontainer_id\n' >"$EVIDENCE_DIR/core-container-ids-before.tsv"
for service in "${CORE_SERVICES[@]}"; do
  printf '%s\t%s\n' "$service" "$(container_id "$service")" \
    >>"$EVIDENCE_DIR/core-container-ids-before.tsv"
done
uv run --locked --no-sync python "$ROOT_DIR/scripts/phase2-persistence.py" seed "$marker" \
  >"$EVIDENCE_DIR/persistence-seed.txt" 2>&1

"${COMPOSE[@]}" --profile core up --detach --force-recreate --no-deps --wait \
  --wait-timeout "$WAIT_TIMEOUT_SECONDS" postgres redis rabbitmq minio qdrant
compose up --detach --wait --wait-timeout "$WAIT_TIMEOUT_SECONDS"
printf 'service\tcontainer_id\tstate\thealth\n' >"$EVIDENCE_DIR/core-container-ids-after.tsv"
for service in "${CORE_SERVICES[@]}"; do
  before_id=$(awk -v target="$service" '$1 == target { print $2 }' \
    "$EVIDENCE_DIR/core-container-ids-before.tsv")
  after_id=$(container_id "$service")
  state=$(docker inspect "$after_id" --format '{{.State.Status}}')
  health=$(docker inspect "$after_id" --format '{{.State.Health.Status}}')
  printf '%s\t%s\t%s\t%s\n' "$service" "$after_id" "$state" "$health" \
    >>"$EVIDENCE_DIR/core-container-ids-after.tsv"
  [[ -n $before_id && -n $after_id && $before_id != "$after_id" ]] \
    || fail "$service container was not recreated"
  [[ $state == running && $health == healthy ]] || fail "$service is unhealthy after recreation"
done
resolve_datastore_hosts
uv run --locked --no-sync python "$ROOT_DIR/scripts/phase2-persistence.py" verify "$marker" \
  >"$EVIDENCE_DIR/persistence-verify.txt" 2>&1

grafana_password=$(<"$SECRET_DIR/grafana_admin_password")
case "$GRAFANA_ADMIN_USER:$grafana_password" in
  *[!A-Za-z0-9_.:-]*)
    unset grafana_password
    fail "Grafana acceptance credentials contain unsupported characters"
    ;;
esac
CURL_AUTH_CONFIG=$(mktemp)
chmod 600 "$CURL_AUTH_CONFIG"
printf 'user = "%s:%s"\n' "$GRAFANA_ADMIN_USER" "$grafana_password" >"$CURL_AUTH_CONFIG"
unset grafana_password
grafana_query_url="$proxy_url/grafana/api/datasources/proxy/uid/prometheus/api/v1/query"
gpu_metric_ready=0
for _attempt in $(seq 1 30); do
  if curl --disable --config "$CURL_AUTH_CONFIG" --noproxy '*' --fail --silent --show-error \
    --get \
    --data-urlencode 'query=DCGM_FI_DEV_GPU_UTIL' "$grafana_query_url" \
    >"$EVIDENCE_DIR/grafana-gpu-query.json" \
    && jq -e '.status == "success" and (.data.result | length) > 0' \
      "$EVIDENCE_DIR/grafana-gpu-query.json" >/dev/null \
    && curl --disable --config "$CURL_AUTH_CONFIG" --noproxy '*' --fail --silent --show-error \
      --get --data-urlencode 'query=up{job="dcgm-exporter"} == 1' "$grafana_query_url" \
      >"$EVIDENCE_DIR/grafana-dcgm-up.json" \
    && jq -e '
      .status == "success" and (.data.result | length) > 0 and
      all(.data.result[].value[1]; . == "1")
    ' "$EVIDENCE_DIR/grafana-dcgm-up.json" >/dev/null \
    && curl --disable --config "$CURL_AUTH_CONFIG" --noproxy '*' --fail --silent --show-error \
      --get \
      --data-urlencode 'query=(time() - timestamp(DCGM_FI_DEV_GPU_UTIL)) <= 30' \
      "$grafana_query_url" >"$EVIDENCE_DIR/grafana-gpu-freshness.json" \
    && jq -e '
      .status == "success" and (.data.result | length) > 0 and
      all(.data.result[].value[1]; (tonumber >= -5 and tonumber <= 30))
    ' "$EVIDENCE_DIR/grafana-gpu-freshness.json" >/dev/null; then
    gpu_metric_ready=1
    break
  fi
  sleep 2
done
[[ $gpu_metric_ready == 1 ]] || fail "Grafana did not return a real DCGM GPU utilization series"

curl --disable --config "$CURL_AUTH_CONFIG" --noproxy '*' --fail --silent --show-error \
  "$proxy_url/grafana/api/dashboards/uid/ntc-gpu-overview" \
  >"$EVIDENCE_DIR/grafana-dashboard.json"
rm -f -- "$CURL_AUTH_CONFIG"
CURL_AUTH_CONFIG=
jq -e '
  .dashboard.uid == "ntc-gpu-overview" and
  ([.dashboard.panels[].targets[].expr] | index("DCGM_FI_DEV_GPU_UTIL") != null)
' "$EVIDENCE_DIR/grafana-dashboard.json" >/dev/null || fail "GPU dashboard was not provisioned"

printf 'Phase 2 acceptance passed.\n' | tee "$EVIDENCE_DIR/SUMMARY.txt"

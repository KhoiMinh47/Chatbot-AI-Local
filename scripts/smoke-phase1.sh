#!/usr/bin/env bash

# Live smoke for Phase 1 skeletons only. It starts loopback-bound API and web
# development servers with a minimal environment, verifies their public
# contracts, and always terminates the child processes. It does not call NIM,
# use a GPU, or connect to an external data service.

set -euo pipefail

ROOT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
UV_BIN=${UV_BIN:-uv}
PNPM_BIN=${PNPM_BIN:-pnpm}
API_PORT=${PHASE1_API_PORT:-18080}
WEB_PORT=${PHASE1_WEB_PORT:-13000}
TIMEOUT_SECONDS=${PHASE1_SMOKE_TIMEOUT_SECONDS:-60}
HOST=127.0.0.1

for tool in "$UV_BIN" "$PNPM_BIN" curl jq ps setsid ss tr; do
  if ! command -v "$tool" >/dev/null 2>&1; then
    printf 'Required command is unavailable: %s\n' "$tool" >&2
    exit 127
  fi
done

validate_port() {
  local name=$1
  local value=$2

  if [[ ! $value =~ ^[0-9]+$ ]] || ((value < 1024 || value > 65535)); then
    printf '%s must be an integer from 1024 through 65535.\n' "$name" >&2
    exit 2
  fi
}

validate_port PHASE1_API_PORT "$API_PORT"
validate_port PHASE1_WEB_PORT "$WEB_PORT"
if ((API_PORT == WEB_PORT)); then
  printf 'PHASE1_API_PORT and PHASE1_WEB_PORT must differ.\n' >&2
  exit 2
fi
if [[ ! $TIMEOUT_SECONDS =~ ^[1-9][0-9]*$ ]]; then
  printf 'PHASE1_SMOKE_TIMEOUT_SECONDS must be a positive integer.\n' >&2
  exit 2
fi

assert_port_unused() {
  local name=$1
  local value=$2

  if [[ -n $(ss -H -ltn "sport = :$value") ]]; then
    printf '%s is already in use on the local host: %s\n' "$name" "$value" >&2
    exit 2
  fi
}

assert_port_unused PHASE1_API_PORT "$API_PORT"
assert_port_unused PHASE1_WEB_PORT "$WEB_PORT"

WORK_DIR=$(mktemp -d)
mkdir -p "$WORK_DIR/home"
API_LOG="$WORK_DIR/api.log"
WEB_LOG="$WORK_DIR/web.log"
API_BODY="$WORK_DIR/api-health.json"
HOME_BODY="$WORK_DIR/home.html"
LOGIN_BODY="$WORK_DIR/login.html"
API_PID=
WEB_PID=
API_PGID=
WEB_PGID=

process_is_running() {
  local pid=$1
  local pgid=$2
  local candidate_pgid
  local state

  if [[ -n $pgid ]]; then
    while read -r candidate_pgid state; do
      if [[ $candidate_pgid == "$pgid" && $state != Z* ]]; then
        return 0
      fi
    done < <(ps -eo pgid=,stat=)
    return 1
  fi

  state=$(ps -o stat= -p "$pid" 2>/dev/null) || return 1
  [[ $state != Z* ]]
}

terminate_process() {
  local pid=$1
  local pgid=$2
  local attempt

  [[ -n $pid ]] || return 0
  if process_is_running "$pid" "$pgid"; then
    if [[ -n $pgid ]]; then
      kill -TERM -- "-$pgid" 2>/dev/null || true
    else
      kill -TERM "$pid" 2>/dev/null || true
    fi
  fi

  for ((attempt = 0; attempt < 50; attempt++)); do
    process_is_running "$pid" "$pgid" || break
    sleep 0.1
  done
  if process_is_running "$pid" "$pgid"; then
    if [[ -n $pgid ]]; then
      kill -KILL -- "-$pgid" 2>/dev/null || true
    else
      kill -KILL "$pid" 2>/dev/null || true
    fi
  fi
  wait "$pid" 2>/dev/null || true
}

confirm_process_group() {
  local label=$1
  local pid=$2
  local attempt
  local pgid

  for ((attempt = 0; attempt < 50; attempt++)); do
    if ! kill -0 "$pid" 2>/dev/null; then
      printf '%s exited before its process group was established.\n' "$label" >&2
      return 1
    fi
    pgid=$(ps -o pgid= -p "$pid" | tr -d '[:space:]')
    if [[ $pgid == "$pid" ]]; then
      printf '%s\n' "$pgid"
      return 0
    fi
    sleep 0.02
  done

  printf '%s did not establish an isolated process group.\n' "$label" >&2
  return 1
}

cleanup() {
  trap - EXIT INT TERM
  terminate_process "$WEB_PID" "$WEB_PGID"
  terminate_process "$API_PID" "$API_PGID"
  rm -rf "$WORK_DIR"
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

print_failure_log() {
  local label=$1
  local path=$2

  printf '%s failed to become healthy. Last log lines:\n' "$label" >&2
  if [[ -s $path ]]; then
    tail -n 40 "$path" >&2
  else
    printf '(no log output)\n' >&2
  fi
}

assert_contains() {
  local label=$1
  local expected=$2
  local path=$3

  if ! grep -Fq "$expected" "$path"; then
    printf '%s response did not contain the expected marker: %s\n' \
      "$label" "$expected" >&2
    return 1
  fi
}

wait_for_http_200() {
  local label=$1
  local url=$2
  local output_file=$3
  local pid=$4
  local log_file=$5
  local deadline=$((SECONDS + TIMEOUT_SECONDS))
  local http_code

  while ((SECONDS < deadline)); do
    if ! kill -0 "$pid" 2>/dev/null; then
      print_failure_log "$label" "$log_file"
      return 1
    fi

    http_code=$(curl --disable --silent --show-error --noproxy '*' \
      --connect-timeout 1 --max-time 2 \
      --output "$output_file" --write-out '%{http_code}' "$url" 2>/dev/null || true)
    if [[ $http_code == 200 ]]; then
      sleep 0.1
      if ! kill -0 "$pid" 2>/dev/null; then
        print_failure_log "$label" "$log_file"
        return 1
      fi
      return 0
    fi
    sleep 1
  done

  print_failure_log "$label" "$log_file"
  return 1
}

cd "$ROOT_DIR"

# A minimal inherited environment prevents unrelated host credentials from
# reaching either skeleton process. Both services have non-secret test values.
COMMON_ENV=(
  env -i
  "HOME=$WORK_DIR/home"
  "PATH=$PATH"
  "LANG=${LANG:-C.UTF-8}"
  "UV_NO_SYNC=1"
)

setsid "${COMMON_ENV[@]}" \
  APP_ENV=test \
  APP_HOST="$HOST" \
  APP_PORT="$API_PORT" \
  APP_LOG_LEVEL=warning \
  "$UV_BIN" run --locked --no-sync uvicorn \
  --app-dir apps/api app.main:app --host "$HOST" --port "$API_PORT" \
  >"$API_LOG" 2>&1 &
API_PID=$!
API_PGID=$(confirm_process_group 'API skeleton' "$API_PID")

wait_for_http_200 \
  'API skeleton' "http://$HOST:$API_PORT/health/live" \
  "$API_BODY" "$API_PID" "$API_LOG"
if ! jq -e '.status == "ok" and .service == "ntc-api"' "$API_BODY" >/dev/null; then
  printf 'API liveness response did not match the Phase 1 contract.\n' >&2
  exit 1
fi

setsid "${COMMON_ENV[@]}" \
  CI=1 \
  NEXT_TELEMETRY_DISABLED=1 \
  "$PNPM_BIN" --filter @ntc-rag/web exec next dev \
  --hostname "$HOST" --port "$WEB_PORT" >"$WEB_LOG" 2>&1 &
WEB_PID=$!
WEB_PGID=$(confirm_process_group 'Web skeleton' "$WEB_PID")

wait_for_http_200 \
  'Web landing skeleton' "http://$HOST:$WEB_PORT/" \
  "$HOME_BODY" "$WEB_PID" "$WEB_LOG"
assert_contains 'Web landing skeleton' 'Hỏi dữ liệu nội bộ.' "$HOME_BODY"

wait_for_http_200 \
  'Web login skeleton' "http://$HOST:$WEB_PORT/login" \
  "$LOGIN_BODY" "$WEB_PID" "$WEB_LOG"
assert_contains 'Web login skeleton' 'Đăng nhập' "$LOGIN_BODY"

printf 'Phase 1 smoke passed: API liveness, landing page, and login skeleton.\n'

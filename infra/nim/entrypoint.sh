#!/usr/bin/env bash

set -euo pipefail

mode=${NTC_NIM_MODE:-serve}
kind=${NTC_NIM_KIND:?set NTC_NIM_KIND}
version_expected=${NTC_NIM_IMAGE_VERSION_EXPECTED:?set NTC_NIM_IMAGE_VERSION_EXPECTED}
expected_model=${NTC_NIM_EXPECTED_MODEL_ID:?set NTC_NIM_EXPECTED_MODEL_ID}
arm64_digest=${NTC_NIM_ARM64_MANIFEST_DIGEST:?set NTC_NIM_ARM64_MANIFEST_DIGEST}
cache_key=${NTC_NIM_CACHE_KEY:?set NTC_NIM_CACHE_KEY}
cache_dir=${NTC_NIM_CACHE_DIR:-/opt/nim/.cache}
start_entrypoint=${NTC_NIM_START_ENTRYPOINT:?set NTC_NIM_START_ENTRYPOINT}
start_arg=${NTC_NIM_START_ARG:-}
secret_file=${NTC_NIM_SECRET_FILE:-/run/secrets/ngc_api_key}
stage_timeout=${NTC_NIM_STAGE_TIMEOUT_SECONDS:-7200}

if [[ ! $mode =~ ^(serve|stage)$ ]]; then
  printf 'NTC_NIM_MODE must be serve or stage.\n' >&2
  exit 2
fi
if [[ ! $kind =~ ^(llm|embedding|reranking)$ ]]; then
  printf 'NTC_NIM_KIND must be llm, embedding, or reranking.\n' >&2
  exit 2
fi
if [[ ! $cache_key =~ ^[a-z0-9][a-z0-9-]{0,127}$ ]]; then
  printf 'NTC_NIM_CACHE_KEY contains unsupported characters.\n' >&2
  exit 2
fi
if [[ ! $expected_model =~ ^[A-Za-z0-9][A-Za-z0-9._/-]{1,255}$ ]]; then
  printf 'NTC_NIM_EXPECTED_MODEL_ID contains unsupported characters.\n' >&2
  exit 2
fi
if [[ ! $arm64_digest =~ ^sha256:[0-9a-f]{64}$ ]]; then
  printf 'NTC_NIM_ARM64_MANIFEST_DIGEST is invalid.\n' >&2
  exit 2
fi
if [[ ! $stage_timeout =~ ^[1-9][0-9]*$ ]]; then
  printf 'NTC_NIM_STAGE_TIMEOUT_SECONDS must be a positive integer.\n' >&2
  exit 2
fi
if [[ $start_entrypoint != /* || ! -x $start_entrypoint ]]; then
  printf 'NIM start entrypoint is unverified, missing, or not executable: %s\n' \
    "$start_entrypoint" >&2
  exit 127
fi
if [[ -n $start_arg && $start_arg != /* ]]; then
  printf 'NTC_NIM_START_ARG must be an absolute path when set.\n' >&2
  exit 2
fi

marker=$cache_dir/.ntc-staged-$cache_key

validate_marker() {
  local expected_line

  if [[ -L $marker || ! -f $marker ]]; then
    return 1
  fi
  for expected_line in \
    "cache_key=$cache_key" \
    "kind=$kind" \
    "nim_image_version_expected=$version_expected" \
    "expected_model_id=$expected_model" \
    "served_model_id_observed=$expected_model" \
    "arm64_manifest_digest=$arm64_digest"; do
    if ! grep -Fxq -- "$expected_line" "$marker"; then
      return 1
    fi
  done
}

model_is_served() {
  local python_bin

  python_bin=$(command -v python3 || command -v python || true)
  [[ -n $python_bin ]] || return 1
  "$python_bin" - "$expected_model" "${NTC_NIM_HEALTH_PORT:-8000}" <<'PY'
import json
import sys
import urllib.request

expected_model, port = sys.argv[1:]
opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
try:
    with opener.open(f"http://127.0.0.1:{port}/v1/models", timeout=10) as response:
        payload = json.load(response)
except Exception:
    raise SystemExit(1)
models = payload.get("data") if isinstance(payload, dict) else None
if not isinstance(models, list):
    raise SystemExit(1)
observed = {
    item.get("id") for item in models if isinstance(item, dict) and isinstance(item.get("id"), str)
}
raise SystemExit(0 if expected_model in observed else 1)
PY
}

if [[ $mode == serve ]]; then
  if ! validate_marker; then
    printf 'NIM cache marker is missing, stale, or invalid for key %s. Run its explicit stage profile first.\n' \
      "$cache_key" >&2
    exit 1
  fi
  unset NGC_API_KEY NGC_CLI_API_KEY HF_TOKEN HUGGING_FACE_HUB_TOKEN
  if [[ -n $start_arg ]]; then
    exec "$start_entrypoint" "$start_arg"
  fi
  exec "$start_entrypoint"
fi

if [[ ! -f $secret_file || ! -s $secret_file ]]; then
  printf 'The staging NGC secret is missing or empty.\n' >&2
  exit 1
fi
if [[ ! -d $cache_dir || ! -w $cache_dir ]]; then
  printf 'NIM cache directory is missing or not writable: %s\n' "$cache_dir" >&2
  exit 1
fi

ngc_api_key=$(<"$secret_file")
if ((${#ngc_api_key} < 20)) || [[ ! $ngc_api_key =~ ^[-A-Za-z0-9._~+/=]+$ ]]; then
  printf 'The staging NGC secret has an invalid format.\n' >&2
  unset ngc_api_key
  exit 1
fi
export NGC_API_KEY=$ngc_api_key
unset ngc_api_key

server_pid=
terminate_server() {
  local exit_code=$1

  trap - INT TERM
  if [[ -n $server_pid ]] && kill -0 "$server_pid" 2>/dev/null; then
    kill -TERM "$server_pid" 2>/dev/null || true
    wait "$server_pid" 2>/dev/null || true
  fi
  exit "$exit_code"
}
trap 'terminate_server 130' INT
trap 'terminate_server 143' TERM

if [[ -n $start_arg ]]; then
  "$start_entrypoint" "$start_arg" &
else
  "$start_entrypoint" &
fi
server_pid=$!
unset NGC_API_KEY NGC_CLI_API_KEY HF_TOKEN HUGGING_FACE_HUB_TOKEN
deadline=$((SECONDS + stage_timeout))

while kill -0 "$server_pid" 2>/dev/null; do
  if /usr/local/bin/ntc-nim-healthcheck >/dev/null 2>&1 && model_is_served; then
    marker_tmp=$(mktemp "$cache_dir/.ntc-stage-marker.XXXXXX")
    umask 022
    {
      printf 'cache_key=%s\n' "$cache_key"
      printf 'kind=%s\n' "$kind"
      printf 'nim_image_version_expected=%s\n' "$version_expected"
      printf 'expected_model_id=%s\n' "$expected_model"
      printf 'served_model_id_observed=%s\n' "$expected_model"
      printf 'arm64_manifest_digest=%s\n' "$arm64_digest"
      printf 'staged_at_utc=%s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
    } >"$marker_tmp"
    mv -f -- "$marker_tmp" "$marker"
    sync "$marker" 2>/dev/null || true

    kill -TERM "$server_pid" 2>/dev/null || true
    wait "$server_pid" 2>/dev/null || true
    printf 'NIM cache staging completed for %s.\n' "$cache_key"
    exit 0
  fi
  if ((SECONDS >= deadline)); then
    printf 'NIM cache staging timed out for %s.\n' "$cache_key" >&2
    terminate_server 1
  fi
  sleep 5
done

if wait "$server_pid"; then
  server_status=0
else
  server_status=$?
fi
printf 'NIM exited before readiness while staging %s (status %s).\n' \
  "$cache_key" "$server_status" >&2
exit 1

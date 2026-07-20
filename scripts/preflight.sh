#!/usr/bin/env bash

# Phase 0 host inventory. This script only reads host/container metadata and
# writes the collected evidence below artifacts/preflight (or a caller-supplied
# directory). It never prints container environments or registry credentials.

set -euo pipefail

SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
ROOT_DIR=$(cd -- "$SCRIPT_DIR/.." && pwd)
RUN_ID=${PREFLIGHT_RUN_ID:-$(date -u +%Y%m%dT%H%M%SZ)-$$}
OUTPUT_DIR=${1:-"$ROOT_DIR/artifacts/preflight/$RUN_ID"}
OUTPUT_PARENT=$(dirname -- "$OUTPUT_DIR")

if ! mkdir -p -- "$OUTPUT_PARENT"; then
  printf 'Unable to create preflight output parent: %s\n' "$OUTPUT_PARENT" >&2
  exit 1
fi
if ! mkdir -- "$OUTPUT_DIR"; then
  printf 'Unable to create preflight output directory: %s\n' "$OUTPUT_DIR" >&2
  printf 'The destination must not already exist; evidence runs are immutable.\n' >&2
  exit 1
fi

COMMAND_LOG="$OUTPUT_DIR/preflight.txt"
STATUS_FILE="$OUTPUT_DIR/command-status.tsv"
if ! : >"$COMMAND_LOG"; then
  printf 'Unable to initialize preflight command log: %s\n' "$COMMAND_LOG" >&2
  exit 1
fi
if ! printf 'command\texit_code\tstatus\n' >"$STATUS_FILE"; then
  printf 'Unable to initialize preflight status file: %s\n' "$STATUS_FILE" >&2
  exit 1
fi

run_and_capture() {
  local name=$1
  shift
  local status

  {
    printf '\n## %s\n' "$name"
    printf '$'
    printf ' %q' "$@"
    printf '\n'
  } >>"$COMMAND_LOG"

  if command -v "$1" >/dev/null 2>&1; then
    if "$@" >>"$COMMAND_LOG" 2>&1; then
      status=0
      printf '%s\t%s\tok\n' "$name" "$status" >>"$STATUS_FILE"
    else
      status=$?
      printf '%s\t%s\tfailed\n' "$name" "$status" >>"$STATUS_FILE"
    fi
  else
    status=127
    printf 'UNAVAILABLE: %s is not installed or not on PATH.\n' "$1" >>"$COMMAND_LOG"
    printf '%s\t%s\tunavailable\n' "$name" "$status" >>"$STATUS_FILE"
  fi

  return 0
}

capture_docker_info() {
  local status

  {
    printf '\n## docker-info\n'
    printf '$ docker info\n'
    printf '[output projected to selected non-secret fields]\n'
  } >>"$COMMAND_LOG"

  if ! command -v docker >/dev/null 2>&1; then
    printf 'UNAVAILABLE: docker is not installed or not on PATH.\n' >>"$COMMAND_LOG"
    printf 'docker-info\t127\tunavailable\n' >>"$STATUS_FILE"
    return 0
  fi
  if ! command -v jq >/dev/null 2>&1; then
    printf 'UNAVAILABLE: jq is required for safe docker-info projection.\n' >>"$COMMAND_LOG"
    printf 'docker-info\t127\tunavailable-jq\n' >>"$STATUS_FILE"
    return 0
  fi

  if docker info --format '{{json .}}' 2>>"$COMMAND_LOG" |
    jq '{
      id: .ID,
      name: .Name,
      server_version: .ServerVersion,
      operating_system: .OperatingSystem,
      os_version: .OSVersion,
      os_type: .OSType,
      architecture: .Architecture,
      kernel_version: .KernelVersion,
      cpus: .NCPU,
      memory_bytes: .MemTotal,
      storage_driver: .Driver,
      cgroup_driver: .CgroupDriver,
      cgroup_version: .CgroupVersion,
      containers: .Containers,
      containers_running: .ContainersRunning,
      containers_paused: .ContainersPaused,
      containers_stopped: .ContainersStopped,
      images: .Images,
      runtime_names: ((.Runtimes // {}) | keys),
      default_runtime: .DefaultRuntime,
      live_restore_enabled: .LiveRestoreEnabled,
      security_options: .SecurityOptions,
      swarm_local_node_state: .Swarm.LocalNodeState
    }' >>"$COMMAND_LOG"; then
    status=0
    printf 'docker-info\t0\tok-safe-projection\n' >>"$STATUS_FILE"
  else
    status=$?
    printf 'docker-info\t%s\tfailed\n' "$status" >>"$STATUS_FILE"
  fi
}

{
  printf 'run_id=%s\n' "$RUN_ID"
  printf 'captured_at_utc=%s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  printf 'script=%s\n' "scripts/preflight.sh"
  printf 'output_dir=%s\n' "${OUTPUT_DIR#"$ROOT_DIR"/}"
} >"$OUTPUT_DIR/run-metadata.txt"

run_and_capture "uname-a" uname -a
run_and_capture "uname-m" uname -m
run_and_capture "nvidia-smi" nvidia-smi
run_and_capture "docker-version" docker version
run_and_capture "docker-compose-version" docker compose version
capture_docker_info
run_and_capture "docker-images-digests" docker images --digests
run_and_capture "disk" df -h
run_and_capture "memory" free -h

# Structured local-image evidence. Only selected non-secret metadata is stored;
# repo tags and creation times are descriptive, while IDs/digests are the
# immutable identifiers. Config.Env is excluded because it can contain secrets.
if command -v docker >/dev/null 2>&1 && command -v jq >/dev/null 2>&1; then
  if image_id_output=$(docker image ls -q 2>/dev/null); then
    mapfile -t image_ids < <(printf '%s\n' "$image_id_output" | sed '/^$/d' | sort -u)
    if ((${#image_ids[@]} > 0)); then
      local_images_tmp="$OUTPUT_DIR/local-images.json.tmp"
      local_nim_images_tmp="$OUTPUT_DIR/local-nim-images.json.tmp"

      if {
        for image_id in "${image_ids[@]}"; do
          docker image inspect "$image_id" --format '{{json .}}'
        done
      } | jq -s '[.[] | {
        image_id: .Id,
        repo_tags: (.RepoTags // []),
        repo_digests: (.RepoDigests // []),
        architecture: .Architecture,
        os: .Os,
        created: .Created,
        size_bytes: .Size,
        nim: {
          type: .Config.Labels["com.nvidia.nim.type"],
          version: .Config.Labels["com.nvidia.nim.version"],
          model: .Config.Labels["com.nvidia.nim.model"]
        }
      }]' >"$local_images_tmp" &&
        jq -e 'type == "array"' "$local_images_tmp" >/dev/null &&
        jq '[.[] | select(.nim.type != null)]' \
          "$local_images_tmp" >"$local_nim_images_tmp"; then
        mv "$local_images_tmp" "$OUTPUT_DIR/local-images.json"
        mv "$local_nim_images_tmp" "$OUTPUT_DIR/local-nim-images.json"
        printf 'local-image-inspect\t0\tok\n' >>"$STATUS_FILE"
      else
        rm -f "$local_images_tmp" "$local_nim_images_tmp"
        printf '[]\n' >"$OUTPUT_DIR/local-images.json"
        printf '[]\n' >"$OUTPUT_DIR/local-nim-images.json"
        printf 'local-image-inspect\t1\tfailed\n' >>"$STATUS_FILE"
      fi
    else
      printf '[]\n' >"$OUTPUT_DIR/local-images.json"
      printf '[]\n' >"$OUTPUT_DIR/local-nim-images.json"
      printf 'local-image-inspect\t0\tno-images\n' >>"$STATUS_FILE"
    fi
  else
    printf '[]\n' >"$OUTPUT_DIR/local-images.json"
    printf '[]\n' >"$OUTPUT_DIR/local-nim-images.json"
    printf 'local-image-inspect\t1\tdocker-image-list-failed\n' >>"$STATUS_FILE"
  fi
else
  printf '[]\n' >"$OUTPUT_DIR/local-images.json"
  printf '[]\n' >"$OUTPUT_DIR/local-nim-images.json"
  printf 'local-image-inspect\t127\tunavailable-docker-or-jq\n' >>"$STATUS_FILE"
fi

# Presence only: the shell evaluates whether each value is non-empty, but never
# emits or persists the value itself.
{
  if [[ -n ${NGC_API_KEY:-} ]]; then
    printf 'NGC_API_KEY=<present>\n'
  else
    printf 'NGC_API_KEY=absent\n'
  fi
  if [[ -n ${HF_TOKEN:-} ]]; then
    printf 'HF_TOKEN=<present>\n'
  else
    printf 'HF_TOKEN=absent\n'
  fi
} >"$OUTPUT_DIR/credential-presence.txt"

# High-confidence scan of this run's text artifacts. Only file names, never
# matching content, are reported on failure so an accidental value is not echoed.
SECRET_SCAN_FILE="$OUTPUT_DIR/secret-scan.txt"
secret_pattern='(?i)(?:https?|socks5?)://[^/[:space:]:@]+:[^/[:space:]@]+@|-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----|(?:nvapi-|sk-|hf_)[A-Za-z0-9_+=-]{20,}|(?:api[_-]?key|token|password|secret)[[:space:]]*[:=][[:space:]]*["'\'' ]?[A-Za-z0-9_./+=-]{20,}'
if scan_hits=$(rg -l --no-messages --pcre2 "$secret_pattern" "$OUTPUT_DIR" \
  --glob '!secret-scan.txt'); then
  scan_status=0
else
  scan_status=$?
fi
if ((scan_status == 0)); then
  {
    printf 'status=failed\n'
    printf 'reason=high-confidence-secret-pattern-match\n'
    printf 'files=%s\n' "$(printf '%s' "$scan_hits" | tr '\n' ',')"
  } >"$SECRET_SCAN_FILE"
  printf 'secret-pattern-scan\t1\tfailed\n' >>"$STATUS_FILE"
elif ((scan_status == 1)); then
  {
    printf 'status=ok\n'
    printf 'result=no-high-confidence-secret-pattern-match\n'
    printf 'matching_content_was_never_emitted=true\n'
  } >"$SECRET_SCAN_FILE"
  printf 'secret-pattern-scan\t0\tok\n' >>"$STATUS_FILE"
else
  {
    printf 'status=error\n'
    printf 'reason=rg-scan-failed\n'
  } >"$SECRET_SCAN_FILE"
  printf 'secret-pattern-scan\t%s\tscan-error\n' "$scan_status" >>"$STATUS_FILE"
fi

printf 'Preflight evidence written to %s\n' "$OUTPUT_DIR"

# Evidence collection continues after individual failures so the operator gets
# the whole picture, but the script itself must not report a false success.
if awk -F '\t' 'NR > 1 && $2 != 0 {failed = 1} END {exit failed ? 0 : 1}' \
  "$STATUS_FILE"; then
  printf 'One or more preflight checks failed; inspect %s\n' "$STATUS_FILE" >&2
  exit 1
else
  aggregate_status=$?
  if ((aggregate_status != 1)); then
    printf 'Unable to evaluate preflight status file: %s\n' "$STATUS_FILE" >&2
    exit 1
  fi
fi

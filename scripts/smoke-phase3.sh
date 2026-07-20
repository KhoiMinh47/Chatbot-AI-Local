#!/usr/bin/env bash

# Reproducible live acceptance for Phase 3 only. This script intentionally
# stops at the model bake-off boundary; it never creates ingestion or vector
# data. Runtime NIMs stay on Compose's private, internal network and are reached
# from this Linux host through their inspected container IP addresses.

set -Eeuo pipefail

ROOT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
ENV_FILE=${PHASE3_ENV_FILE:-$ROOT_DIR/infra/compose/phase3.env}
COMPOSE_FILE=${PHASE3_COMPOSE_FILE:-$ROOT_DIR/compose.phase3.yaml}
EVIDENCE_ROOT=${PHASE3_EVIDENCE_ROOT:-$ROOT_DIR/artifacts/phase-3/runs}
RUN_ID=${PHASE3_RUN_ID:-$(date -u +%Y%m%dT%H%M%SZ)-$$-$RANDOM}
MEASURED_REQUESTS=${PHASE3_MEASURED_REQUESTS:-20}
WARMUP_REQUESTS=${PHASE3_WARMUP_REQUESTS:-2}
READY_TIMEOUT_SECONDS=${PHASE3_READY_TIMEOUT_SECONDS:-3600}
REQUEST_TIMEOUT_SECONDS=${PHASE3_REQUEST_TIMEOUT_SECONDS:-600}
TELEMETRY_INTERVAL_SECONDS=${PHASE3_TELEMETRY_INTERVAL_SECONDS:-5}
STAGE_CACHES=${PHASE3_STAGE_CACHES:-0}
INCLUDE_LONG_CONTEXT=${PHASE3_INCLUDE_LONG_CONTEXT:-1}
ALLOW_REDUCED_WORKLOAD=${PHASE3_ALLOW_REDUCED_WORKLOAD:-0}
COMBINATION_LLM=${PHASE3_COMBINATION_LLM:-llama}
PHASE3_SECRET_GID=${PHASE3_SECRET_GID:-$(id -g)}
PHASE3_NGC_API_KEY_FILE=${PHASE3_NGC_API_KEY_FILE:-$ROOT_DIR/.secrets/phase3/ngc_api_key}
PHASE3_ENV_FILE=$ENV_FILE
PHASE3_COMPOSE_FILE=$COMPOSE_FILE
export PHASE3_SECRET_GID PHASE3_NGC_API_KEY_FILE PHASE3_ENV_FILE PHASE3_COMPOSE_FILE

RUN_DIR=$EVIDENCE_ROOT/$RUN_ID
EXECUTION_FILE=$RUN_DIR/execution.tsv
ACCEPTANCE_FILE=$RUN_DIR/acceptance.tsv
CANDIDATE_FILE=$RUN_DIR/candidates.tsv
SUMMARY_FILE=$RUN_DIR/summary.json
CURRENT_STEP=initialization
CURRENT_CONTAINER_ID=
CURRENT_SERVICE=
SAMPLER_PID=
MUTATION_STARTED=0
SUMMARY_WRITTEN=0
EVIDENCE_CLAIMED=0
HAD_EXECUTION_FAILURE=0
HAD_QUALITY_GATE_FAILURE=0
COMBINATION_PROVEN=0
WORKLOAD_CONFORMANT=1
BGE_LIVE_HTTP_STATUS=000
SECRETS_SCAN_PERFORMED=0
SECRETS_SCAN_PASSED=0
CLEANUP_PERFORMED=0
CLEANUP_PASSED=0
CACHE_VOLUMES_PRESERVED=0

usage() {
  cat <<'EOF'
Usage: ./scripts/smoke-phase3.sh

Important environment controls:
  PHASE3_STAGE_CACHES=0|1             Stage model caches first (default: 0).
  PHASE3_MEASURED_REQUESTS=20         Per scenario (master-plan minimum: 20).
  PHASE3_WARMUP_REQUESTS=2          Full acceptance requires at least 1.
  PHASE3_INCLUDE_LONG_CONTEXT=0|1     32K, 64K, 128K tests (default: 1).
  PHASE3_COMBINATION_LLM=llama|nemotron
  PHASE3_EVIDENCE_ROOT=<directory>
  PHASE3_RUN_ID=<safe-unique-id>

Reduced/debug workloads require PHASE3_ALLOW_REDUCED_WORKLOAD=1 and can never
produce a passing acceptance result. The reviewed BGE-M3 HTTP 402 is re-probed
live; any result remains BLOCKED until an exact immutable image is reviewed.
EOF
}

fail() {
  printf 'Phase 3 acceptance failed during %s: %s\n' "$CURRENT_STEP" "$1" >&2
  return 1
}

is_positive_integer() {
  [[ $1 =~ ^[1-9][0-9]*$ ]]
}

is_non_negative_integer() {
  [[ $1 =~ ^[0-9]+$ ]]
}

validate_inputs() {
  [[ -f $ENV_FILE ]] || {
    fail "environment file is missing: $ENV_FILE"
    return 1
  }
  [[ -f $COMPOSE_FILE ]] || {
    fail "Compose file is missing: $COMPOSE_FILE"
    return 1
  }
  [[ $RUN_ID =~ ^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$ ]] ||
    { fail 'PHASE3_RUN_ID contains unsupported characters'; return 1; }
  is_positive_integer "$MEASURED_REQUESTS" ||
    { fail 'PHASE3_MEASURED_REQUESTS must be a positive integer'; return 1; }
  is_non_negative_integer "$WARMUP_REQUESTS" ||
    { fail 'PHASE3_WARMUP_REQUESTS must be a non-negative integer'; return 1; }
  is_positive_integer "$READY_TIMEOUT_SECONDS" ||
    { fail 'PHASE3_READY_TIMEOUT_SECONDS must be a positive integer'; return 1; }
  is_positive_integer "$REQUEST_TIMEOUT_SECONDS" ||
    { fail 'PHASE3_REQUEST_TIMEOUT_SECONDS must be a positive integer'; return 1; }
  is_positive_integer "$TELEMETRY_INTERVAL_SECONDS" ||
    { fail 'PHASE3_TELEMETRY_INTERVAL_SECONDS must be a positive integer'; return 1; }
  [[ $STAGE_CACHES == 0 || $STAGE_CACHES == 1 ]] ||
    { fail 'PHASE3_STAGE_CACHES must be 0 or 1'; return 1; }
  [[ $INCLUDE_LONG_CONTEXT == 0 || $INCLUDE_LONG_CONTEXT == 1 ]] ||
    { fail 'PHASE3_INCLUDE_LONG_CONTEXT must be 0 or 1'; return 1; }
  [[ $ALLOW_REDUCED_WORKLOAD == 0 || $ALLOW_REDUCED_WORKLOAD == 1 ]] ||
    { fail 'PHASE3_ALLOW_REDUCED_WORKLOAD must be 0 or 1'; return 1; }
  [[ $COMBINATION_LLM == llama || $COMBINATION_LLM == nemotron ]] ||
    { fail 'PHASE3_COMBINATION_LLM must be llama or nemotron'; return 1; }
  if ((MEASURED_REQUESTS < 20 || WARMUP_REQUESTS < 1)) || \
    [[ $INCLUDE_LONG_CONTEXT != 1 ]]; then
    if [[ $ALLOW_REDUCED_WORKLOAD != 1 ]]; then
      fail 'reduced requests/warm-up/long-context require PHASE3_ALLOW_REDUCED_WORKLOAD=1'
      return 1
    fi
    WORKLOAD_CONFORMANT=0
  fi
}

compose() {
  docker compose --env-file "$ENV_FILE" --file "$COMPOSE_FILE" "$@"
}

record_execution() {
  local item=$1
  local status=$2
  local evidence=${3:-}
  printf '%s\t%s\t%s\n' "$item" "$status" "$evidence" >>"$EXECUTION_FILE"
}

record_candidate() {
  local candidate=$1
  local status=$2
  local evidence=$3
  printf '%s\t%s\t%s\n' "$candidate" "$status" "$evidence" >>"$CANDIDATE_FILE"
}

record_acceptance() {
  local criterion=$1
  local status=$2
  local evidence=$3
  printf '%s\t%s\t%s\n' "$criterion" "$status" "$evidence" >>"$ACCEPTANCE_FILE"
}

redact_stream() {
  sed -E \
    -e 's/(NGC_API_KEY|NGC_CLI_API_KEY|HF_TOKEN|HUGGING_FACE_HUB_TOKEN)([=:][^[:space:]]*)?/\1=[REDACTED]/Ig' \
    -e 's/(nvapi-|hf_|sk-|github_pat_|gh[pousr]_)[A-Za-z0-9._~+\/=:-]{12,}/[REDACTED_CREDENTIAL]/Ig'
}

scan_exact_secret_artifacts() {
  local scan_status
  local result=fail

  if [[ $SECRETS_SCAN_PERFORMED == 1 ]]; then
    [[ $SECRETS_SCAN_PASSED == 1 ]]
    return
  fi
  SECRETS_SCAN_PERFORMED=1
  if rg --hidden --no-ignore --files-with-matches --fixed-strings \
    --file "$PHASE3_NGC_API_KEY_FILE" \
    "$RUN_DIR" >/dev/null 2>&1; then
    scan_status=0
  else
    scan_status=$?
  fi
  if ((scan_status == 1)); then
    SECRETS_SCAN_PASSED=1
    result=pass
  else
    SECRETS_SCAN_PASSED=0
  fi
  jq -n --arg status "$result" --argjson scanner_exit_code "$scan_status" '{
    status: $status,
    exact_secret_value_persisted: ($status != "pass"),
    matched_file_names_persisted: false,
    matched_values_persisted: false,
    scanner_exit_code: $scanner_exit_code
  }' >"$RUN_DIR/secret-artifact-scan.json" || {
    SECRETS_SCAN_PASSED=0
    return 1
  }
  [[ $SECRETS_SCAN_PASSED == 1 ]]
}

stop_sampler() {
  if [[ -n $SAMPLER_PID ]] && kill -0 "$SAMPLER_PID" 2>/dev/null; then
    kill -TERM "$SAMPLER_PID" 2>/dev/null || true
    wait "$SAMPLER_PID" 2>/dev/null || true
  fi
  SAMPLER_PID=
}

cleanup_runtime() {
  local status=0
  local existing=
  local project=${COMPOSE_PROJECT_NAME:-ntc-rag-phase3}
  local project_container_count=0
  local volume
  local -a cache_volumes=()

  if [[ $CLEANUP_PERFORMED == 1 ]]; then
    [[ $CLEANUP_PASSED == 1 ]]
    return
  fi
  CLEANUP_PERFORMED=1
  stop_sampler
  if [[ $MUTATION_STARTED != 1 ]]; then
    CLEANUP_PASSED=1
    if [[ $EVIDENCE_CLAIMED == 1 && -d $RUN_DIR ]]; then
      jq -n '{
        status: "pass",
        mutation_started: false,
        project_container_count_after_cleanup: null,
        expected_cache_volume_count: 4,
        cache_volumes_preserved: null,
        cleanup_scope: "not_applicable_no_phase3_mutation_started"
      }' >"$RUN_DIR/cleanup.json" || {
        CLEANUP_PASSED=0
        return 1
      }
    fi
    return 0
  fi
  # Activate every Phase 3 profile so an abrupt exit also removes services
  # created by a profile-gated `up` or cache-stage `run`. Volumes are
  # intentionally omitted and therefore preserved.
  compose --profile llama --profile nemotron --profile retriever \
    --profile stage-llama --profile stage-nemotron --profile stage-retriever \
    down --remove-orphans --timeout 120 >"$RUN_DIR/cleanup-compose.log" 2>&1 || status=1
  existing=$(docker ps -aq --filter "label=com.docker.compose.project=$project" \
    2>/dev/null) || status=1
  [[ -z $existing ]] || status=1
  project_container_count=$(wc -w <<<"$existing")

  cache_volumes=(
    "${project}_nim_llama_cache"
    "${project}_nim_nemotron_cache"
    "${project}_nim_embed_300m_cache"
    "${project}_nim_rerank_500m_cache"
  )
  CACHE_VOLUMES_PRESERVED=1
  for volume in "${cache_volumes[@]}"; do
    if ! docker volume inspect "$volume" >/dev/null 2>&1; then
      CACHE_VOLUMES_PRESERVED=0
      status=1
    fi
  done
  if ((status == 0)); then
    CLEANUP_PASSED=1
  fi
  if [[ $EVIDENCE_CLAIMED == 1 && -d $RUN_DIR ]]; then
    jq -n \
      --arg status "$([[ $status == 0 ]] && printf pass || printf fail)" \
      --argjson project_container_count "$project_container_count" \
      --argjson cache_volumes_preserved "$CACHE_VOLUMES_PRESERVED" \
      --argjson mutation_started "$MUTATION_STARTED" \
      --argjson expected_cache_volume_count "${#cache_volumes[@]}" '{
        status: $status,
        mutation_started: ($mutation_started == 1),
        project_container_count_after_cleanup: $project_container_count,
        expected_cache_volume_count: $expected_cache_volume_count,
        cache_volumes_preserved: ($cache_volumes_preserved == 1)
      }' >"$RUN_DIR/cleanup.json" || status=1
  fi
  if ((status != 0)); then
    CLEANUP_PASSED=0
  fi
  CURRENT_CONTAINER_ID=
  CURRENT_SERVICE=
  [[ $status == 0 ]]
}

write_summary() {
  local exit_code=$1
  local result=$2
  local reason=$3
  local temporary=$RUN_DIR/.summary.json.tmp

  [[ $EVIDENCE_CLAIMED == 1 && -d $RUN_DIR ]] || return 0
  if ! jq -n \
    --arg result "$result" \
    --arg reason "$reason" \
    --arg run_id "$RUN_ID" \
    --arg current_step "$CURRENT_STEP" \
    --arg current_service "$CURRENT_SERVICE" \
    --arg current_container_id "$CURRENT_CONTAINER_ID" \
    --arg completed_at "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
    --argjson exit_code "$exit_code" \
    --argjson measured_requests "$MEASURED_REQUESTS" \
    --argjson warmup_requests "$WARMUP_REQUESTS" \
    --argjson workload_conformant "$WORKLOAD_CONFORMANT" \
    --argjson include_long_context "$INCLUDE_LONG_CONTEXT" \
    --argjson quality_gate_failure "$HAD_QUALITY_GATE_FAILURE" \
    --argjson combination_proven "$COMBINATION_PROVEN" \
    --argjson secrets_scan_performed "$SECRETS_SCAN_PERFORMED" \
    --argjson secrets_scan_passed "$SECRETS_SCAN_PASSED" \
    --argjson cleanup_performed "$CLEANUP_PERFORMED" \
    --argjson cleanup_passed "$CLEANUP_PASSED" \
    --argjson cache_volumes_preserved "$CACHE_VOLUMES_PRESERVED" \
    --argjson mutation_started "$MUTATION_STARTED" \
    --arg combination_llm "$COMBINATION_LLM" \
    --slurpfile execution <(jq -Rn '
      [inputs | split("\t") | {item: .[0], status: .[1], evidence: .[2]}]
    ' "$EXECUTION_FILE" 2>/dev/null || printf '[]\n') \
    --slurpfile candidates <(jq -Rn '
      [inputs | split("\t") | {candidate: .[0], status: .[1], evidence: .[2]}]
    ' "$CANDIDATE_FILE" 2>/dev/null || printf '[]\n') \
    --slurpfile acceptance <(jq -Rn '
      [inputs | split("\t") | {criterion: .[0], status: .[1], evidence: .[2]}]
    ' "$ACCEPTANCE_FILE" 2>/dev/null || printf '[]\n') \
    '{
      schema_version: 1,
      phase: 3,
      run_id: $run_id,
      result: $result,
      exit_code: $exit_code,
      reason: $reason,
      current_step: $current_step,
      current_service_at_finalize: $current_service,
      current_container_id_at_finalize: $current_container_id,
      completed_at_utc: $completed_at,
      workload: {
        measured_requests_per_scenario: $measured_requests,
        warmup_requests_per_scenario: $warmup_requests,
        includes_32k_64k_128k: ($include_long_context == 1),
        conforms_to_master_plan_minimum: ($workload_conformant == 1)
      },
      metric_scope: {
        ttft_seconds: "client-observed request start to first non-empty streamed generated-token delta (content or reasoning_content)",
        master_backend_receive_ttft_measured: false,
        decode_tokens_per_second: "server-reported completion tokens divided by first-to-last client-observed generated-token delta duration (content or reasoning_content)",
        total_latency_seconds: "client-observed direct NIM HTTP request duration; not application end-to-end"
      },
      target_combination: {
        llms_tested: ["llama", "nemotron"],
        operator_preference_not_used_as_acceptance_shortcut: $combination_llm,
        selection_status: "both_llm_candidates_tested_before_final_winner",
        no_oom_live_proven: ($combination_proven == 1)
      },
      decision_gates: {
        llm_winner: "not_selected_human_review_pending",
        embedding_winner: "blocked_exact_bge_m3_runtime_missing",
        any_llm_automatic_quality_gate_failed: ($quality_gate_failure == 1),
        phase3_complete: false
      },
      execution: ($execution[0] // []),
      candidates: ($candidates[0] // []),
      acceptance: ($acceptance[0] // []),
      exact_secret_scan: {
        performed: ($secrets_scan_performed == 1),
        status: (if $secrets_scan_performed != 1 then "not_run"
          elif $secrets_scan_passed == 1 then "pass" else "fail" end),
        evidence: (if $secrets_scan_performed == 1 then "secret-artifact-scan.json" else null end)
      },
      secrets_persisted: (if $secrets_scan_performed != 1 then null
        else ($secrets_scan_passed != 1) end),
      cleanup: {
        performed: ($cleanup_performed == 1),
        status: (if $cleanup_performed != 1 then "not_run"
          elif $cleanup_passed == 1 then "pass" else "fail" end),
        evidence: (if $cleanup_performed == 1 then "cleanup.json" else null end)
      },
      cache_volumes_preserved: (if $cleanup_performed == 1 and $mutation_started == 1
        then ($cache_volumes_preserved == 1) else null end),
      phase4_started: false
    }' >"$temporary"; then
    rm -f -- "$temporary"
    return 1
  fi
  if ! chmod 640 "$temporary" || ! mv -f -- "$temporary" "$SUMMARY_FILE"; then
    rm -f -- "$temporary"
    return 1
  fi
  SUMMARY_WRITTEN=1
}

on_exit() {
  local exit_code=$?
  local finalize_reason
  trap - EXIT INT TERM
  set +e +u
  if [[ $EVIDENCE_CLAIMED == 1 ]]; then
    if ! cleanup_runtime; then
      HAD_EXECUTION_FAILURE=1
      exit_code=1
    fi
    if ! scan_exact_secret_artifacts; then
      HAD_EXECUTION_FAILURE=1
      exit_code=1
    fi
  fi
  if [[ $SUMMARY_WRITTEN != 1 ]]; then
    if ((exit_code == 0 || exit_code == 3)); then
      finalize_reason='acceptance exited without a final decision'
      exit_code=1
    else
      finalize_reason="unexpected failure during $CURRENT_STEP"
    fi
    write_summary "$exit_code" failed "$finalize_reason"
  fi
  exit "$exit_code"
}
run_logged() {
  local log_file=$1
  local status
  shift
  "$@" >"$log_file" 2>&1 && return 0
  status=$?
  return "$status"
}

assert_no_preexisting_containers() {
  local existing
  existing=$(docker ps -aq --filter \
    "label=com.docker.compose.project=$COMPOSE_PROJECT_NAME") || return 1
  if [[ -n $existing ]]; then
    fail "refusing pre-existing $COMPOSE_PROJECT_NAME containers; inspect or remove them explicitly"
  fi
}

wait_healthy() {
  local container_id=$1
  local deadline=$((SECONDS + READY_TIMEOUT_SECONDS))
  local status state
  while ((SECONDS < deadline)); do
    state=$(docker inspect --format '{{.State.Status}}' "$container_id" 2>/dev/null) || return 1
    status=$(docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}missing{{end}}' \
      "$container_id" 2>/dev/null) || return 1
    if [[ $state == running && $status == healthy ]]; then
      return 0
    fi
    if [[ $state == exited || $state == dead || $status == unhealthy ]]; then
      return 1
    fi
    sleep 5
  done
  return 1
}

container_ip() {
  local container_id=$1
  local ip
  ip=$(docker inspect "$container_id" | jq -er '
    .[0].NetworkSettings.Networks
    | to_entries
    | map(select(.value.IPAddress | type == "string" and length > 0))
    | .[0].value.IPAddress
  ') || return 1
  [[ $ip =~ ^([0-9]{1,3}\.){3}[0-9]{1,3}$ ]] || return 1
  printf '%s\n' "$ip"
}

assert_no_published_ports() {
  docker inspect "$1" | jq -e '
    .[0].HostConfig.NetworkMode != "host" and
    all(.[0].NetworkSettings.Ports | to_entries[]?; .value == null)
  ' >/dev/null
}

capture_endpoint() {
  local api_v1_base=$1
  local endpoint=$2
  local directory=$3
  local name=${endpoint//\//_}
  local raw=$directory/.$name.raw
  local status
  status=$(curl --disable --noproxy '*' --silent --show-error \
    --max-time "$REQUEST_TIMEOUT_SECONDS" --max-filesize 10485760 \
    --output "$raw" --write-out '%{http_code}' "$api_v1_base/$endpoint") || status=000
  printf '/v1/%s\t%s\n' "$endpoint" "$status" >>"$directory/http-status.tsv" || return 1
  if [[ -f $raw ]]; then
    redact_stream <"$raw" >"$directory/$name.body" || return 1
    rm -f -- "$raw" || return 1
  fi
}

capture_runtime_evidence() {
  local candidate=$1
  local container_id=$2
  local api_base=$3
  local image_ref=$4
  local license_id=$5
  local directory=$RUN_DIR/candidates/$candidate
  local endpoint

  mkdir -p -- "$directory/endpoints" || return 1
  chmod 750 "$directory" "$directory/endpoints" || return 1
  docker image inspect "$image_ref" | jq '[.[] | {
    Id, RepoTags, RepoDigests, Architecture, Os,
    Config: {User: .Config.User, Entrypoint: .Config.Entrypoint,
      Cmd: .Config.Cmd, Labels: .Config.Labels}
  }]' >"$directory/image-inspect.json" || return 1
  docker inspect "$container_id" | jq '[.[] | {
    Id, Image, Name,
    Config: {NIM_MODEL_PROFILE: ([.Config.Env[]? |
      select(startswith("NIM_MODEL_PROFILE=")) |
      ltrimstr("NIM_MODEL_PROFILE=")] | first // null)},
    State: {Status: .State.Status, Running: .State.Running,
      OOMKilled: .State.OOMKilled, Health: .State.Health},
    HostConfig: {NetworkMode: .HostConfig.NetworkMode,
      PortBindings: .HostConfig.PortBindings},
    NetworkSettings: {Ports: .NetworkSettings.Ports, Networks: .NetworkSettings.Networks}
  }]' >"$directory/container-inspect.json" || return 1
  jq -n --arg license_id "$license_id" \
    --arg source 'reviewed-model-card-and-container-catalog; live-license-endpoint-probed' \
    '{license_id: $license_id, evidence_source: $source}' >"$directory/license.json" || return 1
  : >"$directory/endpoints/http-status.tsv" || return 1
  for endpoint in health/live health/ready models metrics metadata version manifest license; do
    capture_endpoint "$api_base" "$endpoint" "$directory/endpoints" || return 1
  done
}

capture_logs() {
  local container_id=$1
  local output=$2
  docker logs "$container_id" 2>&1 | redact_stream >"$output"
}

probe_bge_access() {
  local secret_value
  local status
  local url='https://nvcr.io/proxy_auth?scope=repository%3Anim%2Fbaai%2Fbge-m3%3Apull'

  # The credential is fed to curl through config stdin, never argv, output, or
  # an evidence file. Only the HTTP status is retained; the response body is
  # discarded even when the registry returns an error payload.
  secret_value=$(<"$PHASE3_NGC_API_KEY_FILE") || return 1
  [[ -n $secret_value ]] || return 1
  # `$oauthtoken` is the literal NGC registry username, not a shell variable.
  # shellcheck disable=SC2016
  status=$(printf 'user = "$oauthtoken:%s"\n' "$secret_value" |
    curl --disable --config - --noproxy '*' --silent --show-error \
      --max-time "$REQUEST_TIMEOUT_SECONDS" --output /dev/null \
      --write-out '%{http_code}' --url "$url") || status=000
  unset secret_value
  if [[ $status =~ ^[0-9]{3}$ && $status != 000 ]]; then
    printf '%s\n' "$status"
    return 0
  fi
  printf '000\n'
  return 1
}

write_bge_evidence() {
  local output=$1
  local probe_result=$2

  jq -n --arg model "$BGE_M3_MODEL" --arg state "$BGE_M3_ACCESS_STATE" \
    --argjson reviewed_http_status "$BGE_M3_ACCESS_HTTP_STATUS" \
    --arg live_http_status "$BGE_LIVE_HTTP_STATUS" \
    --arg probe_result "$probe_result" '{
      model: $model,
      reviewed_state: $state,
      previously_observed_http_status: $reviewed_http_status,
      live_authenticated_token_scope_probe: {
        endpoint: "nvcr.io/proxy_auth",
        scope: "repository:nim/baai/bge-m3:pull",
        result: $probe_result,
        http_status_raw: $live_http_status,
        http_status: (
          if ($live_http_status | test("^[1-9][0-9]{2}$"))
          then ($live_http_status | tonumber)
          else null
          end
        ),
        response_body_persisted: false,
        credential_persisted: false
      },
      exact_pinned_image_selected: false,
      mutable_latest_used: false,
      substitute_used: false,
      acceptance_effect: "blocked",
      block_reason: (if $live_http_status == "402" then
        "payment-or-entitlement-required"
      elif $live_http_status == "200" then
        "access-now-available-but-exact-tag-digest-and-arm64-manifest-not-reviewed"
      elif $live_http_status == "000" then
        "live-registry-probe-failed-without-an-http-response"
      else
        "registry-scope-probe-did-not-authorize-an-exact-reviewed-image"
      end)
    }' >"$output"
}

telemetry_loop() {
  local container_ids=$1
  local output=$2
  local gpu_output host_memory_output container_stats_output
  while :; do
    printf 'sample_at_utc=%s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
    if command -v nvidia-smi >/dev/null 2>&1; then
      if gpu_output=$(nvidia-smi --query-gpu=name,driver_version,memory.used,memory.total,utilization.gpu,temperature.gpu,power.draw \
        --format=csv,noheader,nounits 2>&1); then
        printf 'gpu_observation_status=pass\n%s\n' "$gpu_output"
      else
        printf 'gpu_observation_status=fail\n%s\n' "$gpu_output"
      fi
    else
      printf 'gpu_observation_status=fail\n'
      printf 'nvidia-smi=unavailable\n'
    fi
    if host_memory_output=$(free -b 2>&1); then
      printf 'host_memory_status=pass\n%s\n' "$host_memory_output"
    else
      printf 'host_memory_status=fail\n%s\n' "$host_memory_output"
    fi
    # Container IDs are generated by Docker, not user input. Word splitting is
    # intentional so docker stats receives one argument per ID.
    # shellcheck disable=SC2086
    if container_stats_output=$(docker stats --no-stream --format '{{json .}}' \
      $container_ids 2>&1); then
      printf 'container_stats_status=pass\n%s\n' "$container_stats_output"
    else
      printf 'container_stats_status=fail\n%s\n' "$container_stats_output"
    fi
    printf 'sample_complete=1\n'
    printf '\n'
    sleep "$TELEMETRY_INTERVAL_SECONDS"
  done >"$output"
}

start_sampler() {
  local container_ids=$1
  local output=$2
  local deadline=$((SECONDS + 30))
  stop_sampler
  telemetry_loop "$container_ids" "$output" &
  SAMPLER_PID=$!
  while ((SECONDS < deadline)); do
    if grep -Fxq 'sample_complete=1' "$output" 2>/dev/null; then
      return 0
    fi
    if ! kill -0 "$SAMPLER_PID" 2>/dev/null; then
      return 1
    fi
    sleep 0.2
  done
  return 1
}

validate_telemetry() {
  local container_ids=$1
  local telemetry_file=$2
  local output=$3
  local id
  local timestamp_ok=0
  local gpu_ok=0
  local host_memory_ok=0
  local docker_stats_ok=0
  local expected_containers_ok=1
  local sample_complete_ok=0
  local status=1

  if [[ -s $telemetry_file ]] &&
    grep -Eq '^sample_at_utc=[0-9]{4}-[0-9]{2}-[0-9]{2}T' "$telemetry_file"; then
    timestamp_ok=1
  fi
  if grep -Fxq 'gpu_observation_status=pass' "$telemetry_file" 2>/dev/null &&
    grep -Eq '^NVIDIA ' "$telemetry_file" 2>/dev/null; then
    gpu_ok=1
  fi
  if grep -Fxq 'host_memory_status=pass' "$telemetry_file" 2>/dev/null &&
    grep -Eq '^Mem:' "$telemetry_file" 2>/dev/null; then
    host_memory_ok=1
  fi
  if grep -Fxq 'container_stats_status=pass' "$telemetry_file" 2>/dev/null; then
    docker_stats_ok=1
  fi
  if grep -Fxq 'sample_complete=1' "$telemetry_file" 2>/dev/null; then
    sample_complete_ok=1
  fi
  # IDs originate from Docker. Word splitting is intentional for this local list.
  # shellcheck disable=SC2086
  for id in $container_ids; do
    if ! grep -Fq -- "${id:0:12}" "$telemetry_file" 2>/dev/null; then
      expected_containers_ok=0
    fi
  done
  if [[ $timestamp_ok == 1 && $gpu_ok == 1 && $host_memory_ok == 1 &&
    $docker_stats_ok == 1 && $expected_containers_ok == 1 &&
    $sample_complete_ok == 1 ]]; then
    status=0
  fi
  jq -n --arg status "$([[ $status == 0 ]] && printf pass || printf fail)" \
    --argjson timestamp_ok "$timestamp_ok" --argjson gpu_ok "$gpu_ok" \
    --argjson host_memory_ok "$host_memory_ok" --argjson docker_stats_ok "$docker_stats_ok" \
    --argjson expected_containers_ok "$expected_containers_ok" \
    --argjson sample_complete_ok "$sample_complete_ok" \
    --argjson expected_container_count "$(wc -w <<<"$container_ids")" '{
      status: $status,
      timestamp_observed: ($timestamp_ok == 1),
      gpu_observation_observed: ($gpu_ok == 1),
      host_memory_observed: ($host_memory_ok == 1),
      docker_stats_observed: ($docker_stats_ok == 1),
      docker_stats_observed_for_all_expected_containers: ($expected_containers_ok == 1),
      complete_sample_observed: ($sample_complete_ok == 1),
      expected_container_count: $expected_container_count,
      unified_memory_na_allowed: true
    }' >"$output" || return 1
  [[ $status == 0 ]]
}

candidate_values() {
  local candidate=$1
  case "$candidate" in
    llama)
      CANDIDATE_PROFILE=llama
      CANDIDATE_SERVICE=nim-llm-llama
      CANDIDATE_KIND=llm
      CANDIDATE_MODEL=$NIM_LLM_LLAMA_MODEL
      CANDIDATE_IMAGE=$NIM_LLM_LLAMA_IMAGE
      CANDIDATE_DIGEST=${NIM_LLM_LLAMA_IMAGE##*@}
      CANDIDATE_NIM_VERSION=2.0.6
      CANDIDATE_RUNTIME_PROFILE=unresolved-live-profile
      CANDIDATE_PRECISION=unresolved-live-precision
      CANDIDATE_PROFILE_SOURCE='runtime-output-required'
      CANDIDATE_PRECISION_SOURCE='runtime-output-required'
      CANDIDATE_MAX_LENGTH=${PHASE3_LLAMA_MAX_MODEL_LENGTH:-131072}
      CANDIDATE_MAX_LENGTH_SOURCE='declared-model-and-profile-capability-live-request-evidence-separate'
      CANDIDATE_LICENSE=llama-3.1-community-license-and-nvidia-nim-terms
      CANDIDATE_REASONING_CONTROL_MODE=llama-standard
      ;;
    nemotron)
      CANDIDATE_PROFILE=nemotron
      CANDIDATE_SERVICE=nim-llm-nemotron
      CANDIDATE_KIND=llm
      CANDIDATE_MODEL=$NIM_LLM_NEMOTRON_MODEL
      CANDIDATE_IMAGE=$NIM_LLM_NEMOTRON_IMAGE
      CANDIDATE_DIGEST=${NIM_LLM_NEMOTRON_IMAGE##*@}
      CANDIDATE_NIM_VERSION=1.0.0
      CANDIDATE_RUNTIME_PROFILE=unresolved-live-profile
      CANDIDATE_PRECISION=unresolved-live-precision
      CANDIDATE_PROFILE_SOURCE='runtime-output-required'
      CANDIDATE_PRECISION_SOURCE='runtime-output-required'
      CANDIDATE_MAX_LENGTH=${PHASE3_NEMOTRON_MAX_MODEL_LENGTH:-131072}
      CANDIDATE_MAX_LENGTH_SOURCE='declared-model-and-profile-capability-live-request-evidence-separate'
      CANDIDATE_LICENSE=nvidia-open-model-license
      CANDIDATE_REASONING_CONTROL_MODE=nemotron-no-think
      ;;
    embedding-300m)
      CANDIDATE_PROFILE=retriever
      CANDIDATE_SERVICE=nim-embedding-300m
      CANDIDATE_KIND=embedding
      CANDIDATE_MODEL=$NIM_EMBED_300M_MODEL
      CANDIDATE_IMAGE=$NIM_EMBED_300M_IMAGE
      CANDIDATE_DIGEST=${NIM_EMBED_300M_IMAGE##*@}
      CANDIDATE_NIM_VERSION=1.13.0
      CANDIDATE_RUNTIME_PROFILE=unresolved-live-profile
      CANDIDATE_PRECISION=unresolved-live-precision
      CANDIDATE_PROFILE_SOURCE='runtime-output-required'
      CANDIDATE_PRECISION_SOURCE='runtime-output-required'
      CANDIDATE_MAX_LENGTH=${PHASE3_EMBED_MAX_MODEL_LENGTH:-8192}
      CANDIDATE_MAX_LENGTH_SOURCE='embed-1.13-support-matrix-profile-capability'
      CANDIDATE_LICENSE=nvidia-open-model-license
      CANDIDATE_REASONING_CONTROL_MODE=not-applicable
      ;;
    reranking-500m)
      CANDIDATE_PROFILE=retriever
      CANDIDATE_SERVICE=nim-reranking-500m
      CANDIDATE_KIND=reranking
      CANDIDATE_MODEL=$NIM_RERANK_500M_MODEL
      CANDIDATE_IMAGE=$NIM_RERANK_500M_IMAGE
      CANDIDATE_DIGEST=${NIM_RERANK_500M_IMAGE##*@}
      CANDIDATE_NIM_VERSION=1.10.0
      CANDIDATE_RUNTIME_PROFILE=unresolved-live-profile
      CANDIDATE_PRECISION=unresolved-live-precision
      CANDIDATE_PROFILE_SOURCE='runtime-output-required'
      CANDIDATE_PRECISION_SOURCE='runtime-output-required'
      CANDIDATE_MAX_LENGTH=${PHASE3_RERANK_MAX_MODEL_LENGTH:-4096}
      CANDIDATE_MAX_LENGTH_SOURCE='rerank-1.10-conservative-runtime-limit'
      CANDIDATE_LICENSE=nvidia-community-model-license
      CANDIDATE_REASONING_CONTROL_MODE=not-applicable
      ;;
    *) return 2 ;;
  esac
}

resolve_runtime_metadata() {
  local candidate=$1
  local directory=$2
  local fp8_profile=c4789f7af56c770c1c88b73da666886365534d6980b6b922b41fd97036c77d73
  local nemotron_profile=f9db61d5a467d46be7733e90a26705798764b93d480c842143d525c1932b01e2
  local embed_profile=e28f17c9c13a99055d065f88d725bf93c23b3aab14acd68f16323de1353fc528
  local rerank_profile=f7391ddbcb95b2406853526b8e489fedf20083a2420563ca3e65358ff417b10f
  local profile configured_profile

  if [[ $candidate == llama ]]; then
    [[ ${NIM_LLM_LLAMA_PROFILE:-} == "$fp8_profile" ]] || return 1
    configured_profile=$(jq -er '.[0].Config.NIM_MODEL_PROFILE' \
      "$directory/container-inspect.json") || return 1
    [[ $configured_profile == "$fp8_profile" ]] || return 1
    grep -Eiq '(^|[^[:alnum:]])(FP8|float8)([^[:alnum:]]|$)' \
      "$directory/startup.log" 2>/dev/null || return 1
    CANDIDATE_RUNTIME_PROFILE=$fp8_profile
    CANDIDATE_PRECISION=FP8
    CANDIDATE_PROFILE_SOURCE=exact-profile-configured-and-live-fp8-confirmed
    CANDIDATE_PRECISION_SOURCE=exact-profile-configured-and-live-fp8-confirmed
    return 0
  else
    case "$candidate" in
      nemotron)
        profile=$nemotron_profile
        CANDIDATE_PRECISION=NVFP4
        ;;
      embedding-300m)
        profile=$embed_profile
        CANDIDATE_PRECISION=ONNX-FP16
        ;;
      reranking-500m)
        profile=$rerank_profile
        CANDIDATE_PRECISION=ONNX-FP16
        ;;
      *) return 2 ;;
    esac
    grep -Fq -- "$profile" "$directory/startup.log" 2>/dev/null || return 1
    CANDIDATE_RUNTIME_PROFILE=$profile
  fi
  CANDIDATE_PROFILE_SOURCE=exact-profile-id-observed-in-live-startup-log
  CANDIDATE_PRECISION_SOURCE=precision-mapped-from-reviewed-exact-profile-id
}

write_runtime_declaration() {
  local candidate=$1
  local output=$2
  local active_verified=false
  if [[ $CANDIDATE_PROFILE_SOURCE == exact-profile-id-observed-in-live-startup-log ||
    $CANDIDATE_PROFILE_SOURCE == exact-profile-configured-and-live-fp8-confirmed ]]; then
    active_verified=true
  fi
  jq -n \
    --arg candidate "$candidate" \
    --arg profile "$CANDIDATE_RUNTIME_PROFILE" \
    --arg profile_source "$CANDIDATE_PROFILE_SOURCE" \
    --arg precision "$CANDIDATE_PRECISION" \
    --arg precision_source "$CANDIDATE_PRECISION_SOURCE" \
    --arg reasoning_control_mode "$CANDIDATE_REASONING_CONTROL_MODE" \
    --argjson active_verified "$active_verified" \
    --argjson max_model_length "$CANDIDATE_MAX_LENGTH" \
    --arg max_model_length_source "$CANDIDATE_MAX_LENGTH_SOURCE" '{
      candidate: $candidate,
      reasoning_control: {
        mode: $reasoning_control_mode,
        source: "candidate_allowlist",
        system_prompt_persisted: false
      },
      active_runtime_profile: {
        value: $profile,
        evidence_source: $profile_source,
        live_runtime_verified: $active_verified
      },
      precision: {value: $precision, evidence_source: $precision_source},
      max_model_length: {
        value: $max_model_length,
        evidence_source: $max_model_length_source,
        distinction: "declared/profile capability; live request evidence is separate"
      },
      reviewed_llama_compatible_profiles: (if $candidate == "llama" then [
        {id: "c4789f7af56c770c1c88b73da666886365534d6980b6b922b41fd97036c77d73",
          backend: "vLLM", precision: "FP8"},
        {id: "092ed4213624e774d24cdaf84e3b6222839bab2008a21d3c214ab46626366f90",
          backend: "vLLM", precision: "BF16"},
        {id: "a28963301b18077db3454d5eb21f5678304936c5a425ddc552443de1f5449f2a",
          backend: "vLLM", precision: "NVFP4"}
      ] else [] end),
      compatible_profile_is_not_automatically_an_active_profile: true
    }' >"$output"
}

verify_runtime_evidence() {
  local candidate=$1
  local directory=$2

  uv run --locked --no-sync python "$ROOT_DIR/scripts/phase3_runtime_evidence.py" \
    --candidate-dir "$directory" \
    --candidate "$candidate" \
    --expected-model "$CANDIDATE_MODEL" \
    --expected-version "$CANDIDATE_NIM_VERSION" \
    --expected-profile "$CANDIDATE_RUNTIME_PROFILE" \
    --expected-precision "$CANDIDATE_PRECISION" \
    --expected-max-model-length "$CANDIDATE_MAX_LENGTH" \
    --expected-image-digest "$CANDIDATE_DIGEST" \
    --license-declaration "$CANDIDATE_LICENSE"
}

run_smoke() {
  local kind=$1
  local api_base=$2
  local model=$3
  local log_file=$4
  local reasoning_control_mode=$5
  local api_origin=${api_base%/v1}
  local api_authority=${api_origin#http://}
  local api_host=${api_authority%%:*}
  local -a environment=(
    env
    "NO_PROXY=$api_host,${NO_PROXY:-}"
    "no_proxy=$api_host,${no_proxy:-}"
    "NIM_KIND=$kind"
    "NIM_API_BASE_URL=$api_base"
    "NIM_MODEL=$model"
    "NIM_TIMEOUT_SECONDS=$REQUEST_TIMEOUT_SECONDS"
  )
  if [[ $kind == embedding ]]; then
    [[ $reasoning_control_mode == not-applicable ]] || return 2
    environment+=(NIM_EMBEDDING_DIMENSION=2048 NIM_METRICS_REQUIRED=0)
  elif [[ $kind == reranking ]]; then
    [[ $reasoning_control_mode == not-applicable ]] || return 2
    environment+=(NIM_METRICS_REQUIRED=0)
  else
    [[ $reasoning_control_mode == llama-standard ||
      $reasoning_control_mode == nemotron-no-think ]] || return 2
    environment+=(
      NIM_METRICS_REQUIRED=1
      "NIM_REASONING_CONTROL_MODE=$reasoning_control_mode"
    )
  fi
  run_logged "$log_file" "${environment[@]}" "$ROOT_DIR/scripts/nim-smoke.sh"
}

run_benchmark() {
  local candidate=$1
  local api_base=$2
  local output_dir=$3
  local measured_requests=${4:-$MEASURED_REQUESTS}
  local warmup_requests=${5:-$WARMUP_REQUESTS}
  local include_long_context=${6:-$INCLUDE_LONG_CONTEXT}
  local -a arguments=(
    uv run --locked --no-sync python "$ROOT_DIR/scripts/phase3_benchmark.py"
    --kind "$CANDIDATE_KIND"
    --base-url "$api_base"
    --model "$CANDIDATE_MODEL"
    --candidate-id "$candidate"
    --output-dir "$output_dir"
    --requests "$measured_requests"
    --warmup "$warmup_requests"
    --timeout-seconds "$REQUEST_TIMEOUT_SECONDS"
    --image-ref "$CANDIDATE_IMAGE"
    --image-digest "$CANDIDATE_DIGEST"
    --nim-version "$CANDIDATE_NIM_VERSION"
    --runtime-profile "$CANDIDATE_RUNTIME_PROFILE"
    --precision "$CANDIDATE_PRECISION"
    --max-model-length "$CANDIDATE_MAX_LENGTH"
    --license-id "$CANDIDATE_LICENSE"
  )
  if [[ $CANDIDATE_KIND == llm ]]; then
    arguments+=(
      --metrics-required
      --reasoning-control-mode "$CANDIDATE_REASONING_CONTROL_MODE"
    )
    [[ $include_long_context == 1 ]] && arguments+=(--include-long-context)
  else
    arguments+=(--metrics-optional)
  fi
  "${arguments[@]}"
}

run_quality() {
  local candidate=$1
  local api_base=$2
  local output_dir=$3
  uv run --locked --no-sync python "$ROOT_DIR/scripts/phase3_quality.py" \
    --base-url "$api_base" \
    --model "$CANDIDATE_MODEL" \
    --candidate-id "$candidate" \
    --image-ref "$CANDIDATE_IMAGE" \
    --image-digest "$CANDIDATE_DIGEST" \
    --nim-version "$CANDIDATE_NIM_VERSION" \
    --runtime-profile "$CANDIDATE_RUNTIME_PROFILE" \
    --precision "$CANDIDATE_PRECISION" \
    --max-model-length "$CANDIDATE_MAX_LENGTH" \
    --license-id "$CANDIDATE_LICENSE" \
    --reasoning-control-mode "$CANDIDATE_REASONING_CONTROL_MODE" \
    --timeout-seconds "$REQUEST_TIMEOUT_SECONDS" \
    --output-dir "$output_dir"
}

evaluate_benchmark_report() {
  local kind=$1
  local report=$2
  local output=$3
  local runner_exit_code=$4
  local expected_candidate=${5:-}
  local expected_model=${6:-}
  local expected_profile=${7:-}
  local expected_requests=${8:-$MEASURED_REQUESTS}
  local expected_warmup=${9:-$WARMUP_REQUESTS}
  local long_context_required=${10:-$INCLUDE_LONG_CONTEXT}

  [[ -s $report ]] || return 1
  if [[ $kind == llm ]]; then
    jq --argjson runner_exit_code "$runner_exit_code" \
      --arg expected_candidate "$expected_candidate" \
      --arg expected_model "$expected_model" \
      --arg expected_profile "$expected_profile" \
      --argjson expected_requests "$expected_requests" \
      --argjson expected_warmup "$expected_warmup" \
      --argjson long_context_required "$long_context_required" '
      def metric_counts_ok($summary; $count):
        all([
          "prompt_tokens_actual", "completion_tokens_actual", "total_tokens_actual",
          "ttft_seconds", "decode_duration_seconds", "decode_tokens_per_second",
          "total_latency_seconds"
        ][]; ($summary[.].observed_count? == $count));
      def input_gate_ok($summary; $spec):
        ($summary.input_token_target_check? | type) == "object" and
        $summary.input_token_target_check.status == "pass" and
        $summary.input_token_target_check.target_input_tokens == $spec.input and
        $summary.input_token_target_check.target_context_tokens == $spec.context and
        $summary.input_token_target_check.max_output_tokens == $spec.output and
        if $spec.context == null then
          $summary.input_token_target_check.required_relation ==
            "every_observed_prompt_within_target_ratio" and
          $summary.input_token_target_check.minimum_ratio == 0.8 and
          $summary.input_token_target_check.maximum_ratio == 1.2 and
          ($summary.input_token_target_check.observed_prompt_tokens_min | type) == "number" and
          ($summary.input_token_target_check.observed_prompt_tokens_max | type) == "number" and
          $summary.input_token_target_check.observed_prompt_tokens_min >= ($spec.input * 0.8) and
          $summary.input_token_target_check.observed_prompt_tokens_max <= ($spec.input * 1.2)
        else
          $summary.input_token_target_check.required_relation ==
            "every_observed_prompt_plus_max_output_within_absolute_context_window" and
          $summary.input_token_target_check.absolute_context_lower_bound ==
            ($spec.context - 512) and
          $summary.input_token_target_check.absolute_context_upper_bound == $spec.context and
          ($summary.input_token_target_check.observed_prompt_plus_max_output_min | type) ==
            "number" and
          ($summary.input_token_target_check.observed_prompt_plus_max_output_max | type) ==
            "number" and
          $summary.input_token_target_check.observed_prompt_plus_max_output_min ==
            ($summary.input_token_target_check.observed_prompt_tokens_min + $spec.output) and
          $summary.input_token_target_check.observed_prompt_plus_max_output_max ==
            ($summary.input_token_target_check.observed_prompt_tokens_max + $spec.output) and
          $summary.input_token_target_check.observed_prompt_plus_max_output_min >=
            ($spec.context - 512) and
          $summary.input_token_target_check.observed_prompt_plus_max_output_max <= $spec.context
        end;
      def output_gate_ok($summary; $spec; $requests; $warmup):
        ($summary.output_token_target_check? | type) == "object" and
        $summary.output_token_target_check.status == "pass" and
        $summary.output_token_target_check.required_relation ==
          "completion_tokens_actual_equals_max_output_tokens" and
        $summary.output_token_target_check.target_completion_tokens == $spec.output and
        $summary.output_token_target_check.fixed_request_control.ignore_eos == true and
        $summary.output_token_target_check.fixed_request_control.scope ==
          "synthetic_llm_benchmark_only" and
        $summary.output_token_target_check.measured.required_count == $requests and
        $summary.output_token_target_check.measured.observed_count == $requests and
        $summary.output_token_target_check.measured.matching_count == $requests and
        $summary.output_token_target_check.measured.observed_min == $spec.output and
        $summary.output_token_target_check.measured.observed_max == $spec.output and
        $summary.output_token_target_check.warmup.required_count == $warmup and
        $summary.output_token_target_check.warmup.observed_count == $warmup and
        $summary.output_token_target_check.warmup.matching_count == $warmup and
        (if $warmup > 0 then
          $summary.output_token_target_check.warmup.observed_min == $spec.output and
          $summary.output_token_target_check.warmup.observed_max == $spec.output
        else
          $summary.output_token_target_check.warmup.observed_min == null and
          $summary.output_token_target_check.warmup.observed_max == null
        end);
      def metric_definitions_ok($definitions):
        $definitions == {
          ttft_seconds: "client timestamp immediately before HTTP request dispatch to first non-empty streamed generated-token delta (content or reasoning_content)",
          decode_duration_seconds: "first non-empty streamed generated-token delta to last non-empty generated-token delta; content and reasoning_content are timed but never persisted",
          decode_tokens_per_second: "response-reported completion_tokens divided by decode_duration_seconds",
          total_latency_seconds: "request start to HTTP stream completion",
          token_counts: "actual response usage only; missing usage is a failed LLM measurement",
          long_context_targets: "32K/64K/128K are total-context capability targets; synthetic input reserves max output plus 256 tokens for chat-template safety",
          scope: "client-observed engine HTTP latency, measured immediately before request dispatch; not server/backend receive time and not auth/retrieval/rerank/end-to-end application latency",
          input_token_target_check: "every response-reported prompt-token count must stay within 80-120% for short/RAG scenarios; for long-context capability scenarios every observed prompt_tokens plus max_output_tokens must be between target_context_tokens minus 512 and target_context_tokens inclusive",
          output_token_target_check: "synthetic LLM benchmark requests use the fixed non-configurable ignore_eos=true control, and every warmup and measured response-reported completion_tokens count must exactly equal the scenario max_output_tokens; this control is not used by smoke or quality requests",
          prompt_uniqueness_control: "every LLM warmup and measured request uses a deterministic SHA-256 nonce derived from scenario, request phase, and request index as the first user-content line before synthetic context; warmup and measured namespaces are disjoint, full user prompts are not reused, and nonce values are never persisted"
        };
      def scenario_ok($scenarios; $spec; $requests; $warmup):
        ($scenarios | map(select(.name == $spec.name))) as $matches |
        ($matches | length) == 1 and
        ($matches[0].summary as $summary |
          ($summary | type) == "object" and
          $summary.status == "pass" and
          $summary.request_count == $requests and
          $summary.success_count == $requests and
          $summary.failure_count == 0 and
          $summary.warmup_failure_count == 0 and
          $summary.warmup_required_count == $warmup and
          $summary.concurrency == $spec.concurrency and
          $summary.target_input_tokens == $spec.input and
          $summary.target_context_tokens == $spec.context and
          $summary.max_output_tokens == $spec.output and
          metric_counts_ok($summary; $requests) and
          input_gate_ok($summary; $spec) and
          output_gate_ok($summary; $spec; $requests; $warmup));
      . as $report |
      ($report.scenarios? | if type == "array" then . else [] end) as $scenarios |
      ([
        {name: "engine-short-c1", input: 512, output: 256, concurrency: 1,
          context: null},
        {name: "rag-8k-c1", input: 8192, output: 512, concurrency: 1,
          context: null},
        {name: "rag-8k-c4", input: 8192, output: 512, concurrency: 4,
          context: null}
      ] + if $long_context_required == 1 then [
        {name: "long-32k-c1", input: 32448, output: 64, concurrency: 1,
          context: 32768},
        {name: "long-64k-c1", input: 65216, output: 64, concurrency: 1,
          context: 65536},
        {name: "long-128k-c1", input: 130752, output: 64, concurrency: 1,
          context: 131072}
      ] else [] end) as $specs |
      (([$scenarios[] | .name?] | sort) == ([$specs[].name] | sort) and
        ($scenarios | length) == ($specs | length)) as $matrix_ok |
      (all($specs[]; scenario_ok(
        $scenarios; .; $expected_requests; $expected_warmup))) as $scenarios_ok |
      (all($specs[] | select(.context == null); scenario_ok(
        $scenarios; .; $expected_requests; $expected_warmup))) as $core_ok |
      (([$specs[] | select(.context != null)] | length) == 3 and
        ([$scenarios[] | select((.name? | type) == "string") |
          select(.name | startswith("long-"))] | length) == 3) as $long_present |
      ([$scenarios[] | select((.name? | type) == "string") |
        select(.name | startswith("long-")) |
        {name, status: .summary.status,
          target_context_tokens: .summary.target_context_tokens,
          actual_to_target_p50_ratio: .summary.target_vs_actual_p50_ratio,
          input_token_target_check: .summary.input_token_target_check,
          output_token_target_check: .summary.output_token_target_check}]) as $long_results |
      (($report.schema_version? == 2) and ($report.kind? == "llm") and
        ($report.candidate.candidate_id? == $expected_candidate) and
        ($report.candidate.requested_model_id? == $expected_model) and
        ($report.runtime.served_model_id.value? == $expected_model) and
        ($report.runtime.profile.value? == $expected_profile) and
        ($report.metadata_completeness.status? == "complete") and
        ($report.metadata_completeness.unverified_or_missing_fields? == []) and
        (all([
          $report.candidate.image_ref.value?, $report.candidate.image_digest.value?,
          $report.candidate.license_id.value?, $report.runtime.nim_version.value?,
          $report.runtime.profile.value?, $report.runtime.precision.value?,
          $report.runtime.max_model_length.value?
        ][]; . != null))) as $identity_ok |
      (($report.run_config.measured_requests_per_scenario? == $expected_requests) and
        ($report.run_config.warmup_requests_per_scenario? == $expected_warmup) and
        ($report.run_config.measured_runtime_state? == "warm_after_runner_warmup") and
        ($report.run_config.long_context_opt_in? == ($long_context_required == 1)) and
        ($report.run_config.metrics_required? == true) and
        ($report.run_config.system_prompt_persisted? == false) and
        ($report.run_config.base_url_persisted? == false) and
        ($report.run_config.credentials_persisted? == false) and
        ($report.run_config.llm_prompt_uniqueness_control? == {
          status: "enabled",
          nonce_position: "first_user_content_line_before_synthetic_context",
          nonce_derivation: "sha256(scenario_name|request_phase|request_index)",
          warmup_and_measured_namespaces_disjoint: true,
          full_user_prompt_reuse_between_requests: false,
          nonce_persisted: false
        }) and
        metric_definitions_ok($report.metric_definitions?) and
        ($report.run_config.reasoning_control_mode? ==
          (if $expected_candidate == "nemotron" then "nemotron-no-think"
          else "llama-standard" end))) as $workload_ok |
      {
        runner_exit_code: $runner_exit_code,
        report_shape_valid: (
          (($report.scenarios? | type) == "array") and
          (($report.contract_check? | type) == "object")),
        evidence_identity_valid: $identity_ok,
        workload_valid: $workload_ok,
        exact_scenario_matrix_valid: $matrix_ok,
        all_scenarios_pass: $scenarios_ok,
        contract_status: ($report.contract_check.status? // "invalid"),
        core_short_and_rag_status: (if $core_ok then "pass" else "fail" end),
        long_context_matrix_present: $long_present,
        long_context_all_pass: (
          if $long_context_required == 1 then ($long_present and $scenarios_ok)
          else null end),
        long_context_required_for_this_run: ($long_context_required == 1),
        long_context_results: $long_results,
        report_overall_status: ($report.status? // "invalid"),
        failure: (if ($report.failure? | type) == "object" then $report.failure else null end)
      }
    ' "$report" >"$output" || return 1
    jq -e '
      .runner_exit_code == 0 and .report_shape_valid == true and
      .evidence_identity_valid == true and .workload_valid == true and
      .exact_scenario_matrix_valid == true and .all_scenarios_pass == true and
      .report_overall_status == "pass" and .contract_status == "pass" and
      .core_short_and_rag_status == "pass" and
      (if .long_context_required_for_this_run then
        (.long_context_matrix_present == true and .long_context_all_pass == true)
      else true end)
    ' "$output" >/dev/null
    return
  fi

  jq --argjson runner_exit_code "$runner_exit_code" \
    --arg expected_kind "$kind" \
    --arg expected_candidate "$expected_candidate" \
    --arg expected_model "$expected_model" \
    --arg expected_profile "$expected_profile" \
    --argjson expected_requests "$expected_requests" \
    --argjson expected_warmup "$expected_warmup" \
    --argjson long_context_required "$long_context_required" '
    def scenario_ok($scenarios; $spec; $requests; $warmup):
      ($scenarios | map(select(.name == $spec.name))) as $matches |
      ($matches | length) == 1 and
      ($matches[0].summary as $summary |
        ($summary | type) == "object" and $summary.status == "pass" and
        $summary.request_count == $requests and $summary.success_count == $requests and
        $summary.failure_count == 0 and $summary.warmup_failure_count == 0 and
        $summary.warmup_required_count == $warmup and $summary.concurrency == 1 and
        $summary[$spec.target_field] == $spec.target and
        $summary.total_latency_seconds.observed_count == $requests);
    . as $report |
    ($report.scenarios? | if type == "array" then . else [] end) as $scenarios |
    (if $expected_kind == "embedding" then [
      {name: "embedding-batch-1", target_field: "batch_size", target: 1},
      {name: "embedding-batch-16", target_field: "batch_size", target: 16}
    ] else [
      {name: "reranking-passages-2", target_field: "passage_count", target: 2},
      {name: "reranking-passages-16", target_field: "passage_count", target: 16}
    ] end) as $specs |
    (([$scenarios[] | .name?] | sort) == ([$specs[].name] | sort) and
      ($scenarios | length) == ($specs | length)) as $matrix_ok |
    (all($specs[]; scenario_ok(
      $scenarios; .; $expected_requests; $expected_warmup))) as $scenarios_ok |
    (($report.schema_version? == 2) and ($report.kind? == $expected_kind) and
      ($report.candidate.candidate_id? == $expected_candidate) and
      ($report.candidate.requested_model_id? == $expected_model) and
      ($report.runtime.served_model_id.value? == $expected_model) and
      ($report.runtime.profile.value? == $expected_profile) and
      ($report.metadata_completeness.status? == "complete") and
      ($report.metadata_completeness.unverified_or_missing_fields? == []) and
      (all([
        $report.candidate.image_ref.value?, $report.candidate.image_digest.value?,
        $report.candidate.license_id.value?, $report.runtime.nim_version.value?,
        $report.runtime.profile.value?, $report.runtime.precision.value?,
        $report.runtime.max_model_length.value?
      ][]; . != null))) as $identity_ok |
    (($report.run_config.measured_requests_per_scenario? == $expected_requests) and
      ($report.run_config.warmup_requests_per_scenario? == $expected_warmup) and
      ($report.run_config.long_context_opt_in? == false) and
      ($long_context_required == 0) and ($report.run_config.metrics_required? == false)) as
      $workload_ok |
    {
      runner_exit_code: $runner_exit_code,
      report_shape_valid: (
        (($report.scenarios? | type) == "array") and
        (($report.contract_check? | type) == "object") and
        (($report.semantic_check? | type) == "object")),
      evidence_identity_valid: $identity_ok,
      workload_valid: $workload_ok,
      exact_scenario_matrix_valid: $matrix_ok,
      contract_status: ($report.contract_check.status? // "invalid"),
      report_overall_status: ($report.status? // "invalid"),
      semantic_status: ($report.semantic_check.status? // "invalid"),
      all_scenarios_pass: $scenarios_ok,
      failure: (if ($report.failure? | type) == "object" then $report.failure else null end)
    }
  ' "$report" >"$output" || return 1
  jq -e '
    .runner_exit_code == 0 and .report_shape_valid == true and
    .evidence_identity_valid == true and .workload_valid == true and
    .exact_scenario_matrix_valid == true and .contract_status == "pass" and
    .report_overall_status == "pass" and .semantic_status == "pass" and
    .all_scenarios_pass == true
  ' "$output" >/dev/null
}

evaluate_quality_report() {
  local report=$1
  local output=$2

  [[ -s $report ]] || return 1
  jq '{
    report_status: .status,
    automatic_hard_gate: .automatic_hard_gate,
    human_review: {
      required: .human_review.required,
      status: .human_review.status,
      decision: .human_review.decision
    },
    candidate_selection: .candidate_selection,
    case_count: .fixture.case_count
  }' "$report" >"$output" || return 1
  jq -e '
    .report_status == "completed" and
    (.case_count >= 8 and .case_count <= 12) and
    .human_review.required == true and
    .human_review.status == "pending" and
    .human_review.decision == null and
    .candidate_selection.status == "not_decided"
  ' "$output" >/dev/null || return 1
  if jq -e '.automatic_hard_gate.status == "passed"' "$output" >/dev/null; then
    return 0
  fi
  if jq -e '.automatic_hard_gate.status == "failed"' "$output" >/dev/null; then
    return 3
  fi
  return 1
}

stop_candidate_service() {
  local profile=$1
  local service=$2
  local status=0
  local remaining

  compose --profile "$profile" stop --timeout 120 "$service" >/dev/null 2>&1 || status=1
  compose --profile "$profile" rm -f -s "$service" >/dev/null 2>&1 || status=1
  remaining=$(docker ps -aq --filter \
    "label=com.docker.compose.project=$COMPOSE_PROJECT_NAME" 2>/dev/null) || status=1
  [[ -z $remaining ]] || status=1
  CURRENT_CONTAINER_ID=
  CURRENT_SERVICE=
  [[ $status == 0 ]]
}

run_candidate() {
  local candidate=$1
  local directory=$RUN_DIR/candidates/$candidate
  local container_id ip api_base models_file
  local result=0
  local benchmark_exit_code=0
  local quality_gate_failed=0
  local quality_exit_code=0

  candidate_values "$candidate" || return 2
  CURRENT_STEP="start-$candidate"
  CURRENT_SERVICE=$CANDIDATE_SERVICE
  mkdir -p -- "$directory" || return 1
  MUTATION_STARTED=1
  if ! compose --profile "$CANDIDATE_PROFILE" up -d --no-deps --pull never \
    "$CANDIDATE_SERVICE" >"$directory/compose-up.log" 2>&1; then
    result=1
  fi
  if ((result == 0)); then
    if ! container_id=$(compose --profile "$CANDIDATE_PROFILE" ps -q \
      "$CANDIDATE_SERVICE"); then
      result=1
    elif [[ -z $container_id ]]; then
      result=1
    fi
  fi
  if ((result == 0)); then
    CURRENT_CONTAINER_ID=$container_id
    if ! wait_healthy "$container_id"; then
      result=1
    fi
  fi
  if ((result == 0)); then
    assert_no_published_ports "$container_id" || result=1
    ip=$(container_ip "$container_id") || result=1
  fi
  if ((result == 0)); then
    api_base=http://$ip:8000/v1
    models_file=$directory/models.json
    if ! curl --disable --noproxy '*' --fail --silent --show-error \
      --max-time "$REQUEST_TIMEOUT_SECONDS" "$api_base/models" >"$models_file"; then
      result=1
    elif ! jq -e --arg model "$CANDIDATE_MODEL" \
      'any(.data[]?; .id == $model)' "$models_file" >/dev/null; then
      result=1
    fi
  fi
  if ((result == 0)); then
    CURRENT_STEP="evidence-$candidate"
    capture_runtime_evidence "$candidate" "$container_id" "$api_base" \
      "$CANDIDATE_IMAGE" "$CANDIDATE_LICENSE" || result=1
    capture_logs "$container_id" "$directory/startup.log" || result=1
    resolve_runtime_metadata "$candidate" "$directory" || result=1
    write_runtime_declaration "$candidate" "$directory/runtime-declaration.json" || result=1
    if ((result == 0)); then
      verify_runtime_evidence "$candidate" "$directory" \
        >"$directory/runtime-verification-runner.log" 2>&1 || result=1
    fi
  fi
  if ((result == 0)); then
    if ! start_sampler "$container_id" "$directory/telemetry.log"; then
      result=1
    else
      CURRENT_STEP="smoke-$candidate"
      run_smoke "$CANDIDATE_KIND" "$api_base" "$CANDIDATE_MODEL" \
        "$directory/smoke.log" "$CANDIDATE_REASONING_CONTROL_MODE" || result=1
    fi
  fi
  if ((result == 0)); then
    CURRENT_STEP="benchmark-$candidate"
    if run_benchmark "$candidate" "$api_base" "$directory/benchmark" \
      >"$directory/benchmark-runner.log" 2>&1; then
      benchmark_exit_code=0
    else
      benchmark_exit_code=$?
    fi
    if ! evaluate_benchmark_report "$CANDIDATE_KIND" \
      "$directory/benchmark/report.json" "$directory/benchmark-evaluation.json" \
      "$benchmark_exit_code" "$candidate" "$CANDIDATE_MODEL" \
      "$CANDIDATE_RUNTIME_PROFILE" "$MEASURED_REQUESTS" "$WARMUP_REQUESTS" \
      "$([[ $CANDIDATE_KIND == llm ]] && printf '%s' "$INCLUDE_LONG_CONTEXT" || printf 0)"; then
      result=1
    fi
  fi
  if ((result == 0)) && [[ $CANDIDATE_KIND == llm ]]; then
    CURRENT_STEP="quality-$candidate"
    if run_quality "$candidate" "$api_base" "$directory/quality" \
      >"$directory/quality-runner.log" 2>&1; then
      quality_exit_code=0
    else
      quality_exit_code=$?
      result=1
    fi
    if ((quality_exit_code == 0)); then
      if evaluate_quality_report "$directory/quality/report.json" \
        "$directory/quality-evaluation.json"; then
        quality_gate_failed=0
      else
        quality_exit_code=$?
        if ((quality_exit_code == 3)); then
          quality_gate_failed=1
        else
          result=1
        fi
      fi
    fi
  fi
  stop_sampler
  if [[ -n ${container_id:-} ]]; then
    validate_telemetry "$container_id" "$directory/telemetry.log" \
      "$directory/telemetry-validation.json" || result=1
    capture_logs "$container_id" "$directory/runtime.log" || result=1
    docker inspect "$container_id" | jq '[.[] | {
      RestartCount,
      State: {Status: .State.Status, Running: .State.Running,
        OOMKilled: .State.OOMKilled, Health: .State.Health.Status}
    }]' >"$directory/final-container-state.json" || result=1
    if ! jq -e 'all(.[]; .RestartCount == 0 and .State.OOMKilled == false)' \
      "$directory/final-container-state.json" >/dev/null; then
      result=1
    fi
  fi
  stop_candidate_service "$CANDIDATE_PROFILE" "$CANDIDATE_SERVICE" || result=1
  if ((result == 0)); then
    if [[ $quality_gate_failed == 1 ]]; then
      record_candidate "$candidate" evaluated-quality-gate-failed \
        "candidates/$candidate" || return 1
      return 3
    else
      record_candidate "$candidate" pass "candidates/$candidate" || return 1
    fi
    return 0
  fi
  record_candidate "$candidate" fail "candidates/$candidate" || return 1
  return 1
}

run_combination() {
  local llm_candidate=$1
  local llm_profile
  local result=0
  local smoke_pass=1
  local load_pass=1
  local restart_pass=1
  local health_pass=1
  local telemetry_pass=1
  local logs_pass=1
  local cleanup_pass=1
  local directory=$RUN_DIR/combinations/$llm_candidate
  local candidate service id ip pid runner_status expected_profile remaining log_scan_status
  local concurrent_started_at concurrent_finished_at
  local -a candidates=("$llm_candidate" embedding-300m reranking-500m)
  local -a services=()
  local -a ids=()
  local -a smoke_pids=()
  local -a load_pids=()
  local -A candidate_service=()
  local -A candidate_id=()
  local -A candidate_api_base=()
  local -A pid_candidate=()
  local -A load_exit_code=()

  candidate_values "$llm_candidate" || return 2
  llm_profile=$CANDIDATE_PROFILE
  mkdir -p -- "$directory" || return 1
  CURRENT_STEP="target-combination-$llm_candidate"
  MUTATION_STARTED=1

  for candidate in "${candidates[@]}"; do
    candidate_values "$candidate" || return 2
    candidate_service[$candidate]=$CANDIDATE_SERVICE
    services+=("$CANDIDATE_SERVICE")
  done

  if ! compose --profile "$llm_profile" --profile retriever up -d --no-deps --pull never \
    "${services[@]}" >"$directory/compose-up.log" 2>&1; then
    result=1
    health_pass=0
  fi
  if ((result == 0)); then
    for candidate in "${candidates[@]}"; do
      service=${candidate_service[$candidate]}
      if ! id=$(compose --profile "$llm_profile" --profile retriever ps -q "$service") ||
        [[ -z $id ]] || ! wait_healthy "$id" || ! assert_no_published_ports "$id"; then
        result=1
        health_pass=0
        break
      fi
      if ! ip=$(container_ip "$id"); then
        result=1
        health_pass=0
        break
      fi
      candidate_id[$candidate]=$id
      candidate_api_base[$candidate]=http://$ip:8000/v1
      ids+=("$id")
    done
  fi

  if ((result == 0)); then
    if ! start_sampler "${ids[*]}" "$directory/telemetry.log"; then
      result=1
      telemetry_pass=0
    fi
  fi
  if ((result == 0)); then
    concurrent_started_at=$(date -u +%Y-%m-%dT%H:%M:%SZ)
    for candidate in "${candidates[@]}"; do
      candidate_values "$candidate" || return 2
      run_smoke "$CANDIDATE_KIND" "${candidate_api_base[$candidate]}" \
        "$CANDIDATE_MODEL" "$directory/smoke-$candidate.log" \
        "$CANDIDATE_REASONING_CONTROL_MODE" &
      pid=$!
      smoke_pids+=("$pid")
    done
    for pid in "${smoke_pids[@]}"; do
      if ! wait "$pid"; then
        smoke_pass=0
        result=1
      fi
    done
    concurrent_finished_at=$(date -u +%Y-%m-%dT%H:%M:%SZ)
    jq -n --arg started "$concurrent_started_at" --arg finished "$concurrent_finished_at" \
      --arg llm_candidate "$llm_candidate" \
      --argjson launched "${#smoke_pids[@]}" --argjson expected "${#candidates[@]}" \
      --argjson passed "$([[ $smoke_pass == 1 ]] && printf true || printf false)" '{
        concurrent: true,
        llm_candidate: $llm_candidate,
        bounded_request_count: $expected,
        launched_request_count: $launched,
        one_request_per_loaded_service: true,
        system_prompt_persisted: false,
        started_at_utc: $started,
        finished_at_utc: $finished,
        status: (if $passed and $launched == $expected then "pass" else "fail" end)
      }' >"$directory/concurrent-smoke.json" || {
        smoke_pass=0
        result=1
      }
  fi

  if ((result == 0)); then
    concurrent_started_at=$(date -u +%Y-%m-%dT%H:%M:%SZ)
    for candidate in "${candidates[@]}"; do
      (
        candidate_values "$candidate"
        CANDIDATE_RUNTIME_PROFILE=$(jq -er '.runtime.profile.value' \
          "$RUN_DIR/candidates/$candidate/benchmark/report.json")
        CANDIDATE_PRECISION=$(jq -er '.runtime.precision.value' \
          "$RUN_DIR/candidates/$candidate/benchmark/report.json")
        run_benchmark "$candidate" "${candidate_api_base[$candidate]}" \
          "$directory/load-$candidate" 4 1 0
      ) >"$directory/load-$candidate-runner.log" 2>&1 &
      pid=$!
      load_pids+=("$pid")
      pid_candidate[$pid]=$candidate
    done
    for pid in "${load_pids[@]}"; do
      candidate=${pid_candidate[$pid]}
      if wait "$pid"; then
        load_exit_code[$candidate]=0
      else
        runner_status=$?
        load_exit_code[$candidate]=$runner_status
        load_pass=0
      fi
    done
    concurrent_finished_at=$(date -u +%Y-%m-%dT%H:%M:%SZ)

    for candidate in "${candidates[@]}"; do
      candidate_values "$candidate" || return 2
      expected_profile=$(jq -er '.runtime.profile.value' \
        "$RUN_DIR/candidates/$candidate/benchmark/report.json") || {
        load_pass=0
        continue
      }
      if ! evaluate_benchmark_report "$CANDIDATE_KIND" \
        "$directory/load-$candidate/report.json" \
        "$directory/load-$candidate-evaluation.json" \
        "${load_exit_code[$candidate]:-1}" "$candidate" "$CANDIDATE_MODEL" \
        "$expected_profile" 4 1 0; then
        load_pass=0
      fi
    done
    jq -n --arg started "$concurrent_started_at" --arg finished "$concurrent_finished_at" \
      --arg llm_candidate "$llm_candidate" \
      --argjson passed "$([[ $load_pass == 1 ]] && printf true || printf false)" '{
        concurrent: true,
        llm_candidate: $llm_candidate,
        measured_requests_per_scenario: 4,
        warmup_requests_per_scenario: 1,
        workloads: ["llm-core-including-rag-8k-c4", "embedding-batches", "reranking-passages"],
        started_at_utc: $started,
        finished_at_utc: $finished,
        status: (if $passed then "pass" else "fail" end)
      }' >"$directory/concurrent-load.json" || load_pass=0
    if [[ $load_pass != 1 ]]; then
      result=1
    fi
  else
    load_pass=0
  fi

  stop_sampler
  if [[ ${#ids[@]} == "${#candidates[@]}" ]]; then
    if ! validate_telemetry "${ids[*]}" "$directory/telemetry.log" \
      "$directory/telemetry-validation.json"; then
      telemetry_pass=0
      result=1
    fi
  else
    jq -n --argjson expected "${#candidates[@]}" --argjson discovered "${#ids[@]}" '{
      status: "fail",
      expected_container_count: $expected,
      discovered_container_count: $discovered,
      docker_stats_observed_for_all_expected_containers: false,
      failure_code: "incomplete_expected_container_set",
      unified_memory_na_allowed: true
    }' >"$directory/telemetry-validation.json" || result=1
    telemetry_pass=0
    result=1
  fi

  if ! : >"$directory/container-states.jsonl"; then
    health_pass=0
    restart_pass=0
    result=1
  fi
  for candidate in "${candidates[@]}"; do
    service=${candidate_service[$candidate]}
    id=${candidate_id[$candidate]:-}
    if [[ -z $id ]]; then
      health_pass=0
      restart_pass=0
      result=1
      continue
    fi
    if ! docker inspect "$id" | jq -c --arg service "$service" --arg candidate "$candidate" \
      '.[] | {
        candidate: $candidate, service: $service, RestartCount,
        State: {Status: .State.Status, Running: .State.Running,
          OOMKilled: .State.OOMKilled, Health: (.State.Health.Status // "missing")}
      }' >>"$directory/container-states.jsonl"; then
      health_pass=0
      restart_pass=0
      result=1
      continue
    fi
    if ! capture_logs "$id" "$directory/runtime-$service.log"; then
      logs_pass=0
      result=1
    fi
  done
  if ! jq -se --argjson expected "${#services[@]}" '
    length == $expected and
    all(.[]; .State.Running == true and .State.Status == "running" and
      .State.OOMKilled == false and .State.Health == "healthy")
  ' "$directory/container-states.jsonl" >/dev/null; then
    health_pass=0
    result=1
  fi
  if ! jq -se --argjson expected "${#services[@]}" '
    length == $expected and all(.[]; .RestartCount == 0)
  ' "$directory/container-states.jsonl" >/dev/null; then
    restart_pass=0
    result=1
  fi
  if rg --quiet --ignore-case \
    'CUDA[[:space:]]+out[[:space:]]+of[[:space:]]+memory|CUDA[[:space:]]+OOM|OutOfMemoryError|OOMKilled|Killed[[:space:]]+process' \
    "$directory"/runtime-*.log 2>/dev/null; then
    log_scan_status=0
  else
    log_scan_status=$?
  fi
  if [[ $log_scan_status != 1 ]]; then
    logs_pass=0
    result=1
  fi

  if ! compose --profile "$llm_profile" --profile retriever stop --timeout 120 \
    "${services[@]}" >"$directory/compose-stop.log" 2>&1; then
    cleanup_pass=0
    result=1
  fi
  if ! compose --profile "$llm_profile" --profile retriever rm -f -s \
    "${services[@]}" >"$directory/compose-rm.log" 2>&1; then
    cleanup_pass=0
    result=1
  fi
  if ! remaining=$(docker ps -aq --filter \
    "label=com.docker.compose.project=$COMPOSE_PROJECT_NAME" 2>/dev/null); then
    cleanup_pass=0
    result=1
  elif [[ -n $remaining ]]; then
    cleanup_pass=0
    result=1
  fi
  CURRENT_CONTAINER_ID=
  CURRENT_SERVICE=

  jq -n \
    --arg llm_candidate "$llm_candidate" \
    --argjson smoke_pass "$smoke_pass" --argjson load_pass "$load_pass" \
    --argjson restart_pass "$restart_pass" --argjson health_pass "$health_pass" \
    --argjson telemetry_pass "$telemetry_pass" --argjson logs_pass "$logs_pass" \
    --argjson cleanup_pass "$cleanup_pass" --argjson result "$result" '{
      status: (if $result == 0 then "pass" else "fail" end),
      scope: {
        llm_candidate: $llm_candidate,
        candidates: [$llm_candidate, "embedding-300m", "reranking-500m"],
        concurrent_smoke: true,
        concurrent_bounded_load: true,
        llm_load_requirement: "core matrix includes rag-8k-c4 at concurrency 4",
        measured_requests_per_scenario: 4,
        warmup_requests_per_scenario: 1
      },
      checks: {
        no_oom: {status: (if $health_pass == 1 and $restart_pass == 1 and
          $logs_pass == 1 and $telemetry_pass == 1 then "pass" else "fail" end)},
        load: {status: (if $load_pass == 1 and $smoke_pass == 1 then "pass" else "fail" end)},
        restart: {status: (if $restart_pass == 1 then "pass" else "fail" end)},
        health: {status: (if $health_pass == 1 then "pass" else "fail" end)},
        telemetry: {status: (if $telemetry_pass == 1 then "pass" else "fail" end)},
        logs: {status: (if $logs_pass == 1 then "pass" else "fail" end)},
        cleanup: {status: (if $cleanup_pass == 1 then "pass" else "fail" end)}
      },
      details: {
        container_states: "container-states.jsonl",
        telemetry_validation: "telemetry-validation.json",
        concurrent_smoke: "concurrent-smoke.json",
        concurrent_load: "concurrent-load.json",
        sensitive_log_matches_persisted: false
      }
    }' >"$directory/result.json" || result=1

  if ((result == 0)); then
    record_execution "target-service-combination-$llm_candidate" pass \
      "combinations/$llm_candidate/result.json" || return 1
    return 0
  fi
  record_execution "target-service-combination-$llm_candidate" fail \
    "combinations/$llm_candidate/result.json" || return 1
  return 1
}

write_scorecard_inputs() {
  uv run --locked --no-sync python "$ROOT_DIR/scripts/phase3_scorecard.py" \
    --run-dir "$RUN_DIR" \
    --output "$RUN_DIR/scorecard.json"
}

record_phase3_acceptance() {
  if [[ $HAD_EXECUTION_FAILURE == 0 ]]; then
    record_acceptance AC-01 blocked \
      "four available candidates have health/sample/report; BGE-M3 live HTTP $BGE_LIVE_HTTP_STATUS has no exact reviewed runtime"
    if [[ $INCLUDE_LONG_CONTEXT == 1 && $WORKLOAD_CONFORMANT == 1 ]]; then
      # Reaching this branch means both LLM benchmark evaluators already proved
      # every required 32K/64K/128K scenario and its actual-token target.
      record_acceptance AC-02 blocked \
        'validated 32K/64K/128K evidence and scorecard captured; human-reviewed LLM winner not selected'
    else
      record_acceptance AC-02 fail \
        'required 32K/64K/128K long-context evidence was not run in reduced debug; context acceptance and LLM winner are not evaluated'
    fi
    if [[ $WORKLOAD_CONFORMANT == 1 ]]; then
      record_acceptance AC-03 pass \
        'client-observed request-start TTFT, decode tokens/s, total HTTP latency, p50/p95 and concurrency are explicitly scoped; backend-receive TTFT is not claimed'
    else
      record_acceptance AC-03 fail 'debug workload does not meet master-plan minimum'
      HAD_EXECUTION_FAILURE=1
    fi
    record_acceptance AC-04 blocked \
      "Embed 300M is under 1B, but DG-03 BGE-M3 comparison is incomplete (live HTTP $BGE_LIVE_HTTP_STATUS)"
    if [[ $COMBINATION_PROVEN == 1 ]]; then
      record_acceptance AC-05 pass \
        'both Llama and Nemotron provisional combinations completed concurrent smoke and bounded concurrent load with Embed 300M + Rerank 500M; all containers stayed healthy with RestartCount=0, OOMKilled=false, clean logs, and valid telemetry'
    else
      record_acceptance AC-05 fail \
        'both required LLM combinations were not proven under concurrent smoke and bounded load'
      HAD_EXECUTION_FAILURE=1
    fi
    record_acceptance AC-06 blocked \
      'available candidates have pinned image/license evidence, but BGE-M3 exact image/runtime/license evidence is unavailable'
  else
    record_acceptance AC-01 fail 'one or more available candidates failed live acceptance'
    if [[ $INCLUDE_LONG_CONTEXT == 1 && $WORKLOAD_CONFORMANT == 1 ]]; then
      record_acceptance AC-02 fail 'complete LLM context evidence/scorecard unavailable'
    else
      record_acceptance AC-02 fail \
        'required 32K/64K/128K long-context evidence was not run in reduced debug; context acceptance and LLM winner are not evaluated'
    fi
    record_acceptance AC-03 fail 'complete conforming benchmark evidence unavailable'
    record_acceptance AC-04 blocked \
      "BGE-M3 exact image/runtime missing; live scope status $BGE_LIVE_HTTP_STATUS"
    record_acceptance AC-05 fail 'target service combination was not proven healthy/no-OOM'
    record_acceptance AC-06 blocked \
      'BGE-M3 exact pinned runtime and corresponding license evidence remain unavailable'
  fi
}

phase3_failure_reason() {
  if [[ $WORKLOAD_CONFORMANT == 0 ]]; then
    printf 'reduced debug workload is required-nonconformant (measured requests=%s, warmup requests=%s, long-context enabled=%s); Phase 3 acceptance evidence is incomplete' \
      "$MEASURED_REQUESTS" "$WARMUP_REQUESTS" "$INCLUDE_LONG_CONTEXT"
  else
    printf 'one or more live Phase 3 gates failed; see candidate and execution evidence'
  fi
}

main() {
  local candidate
  local candidate_status
  local combination_status
  local bge_execution_status
  local preexisting_result

  trap on_exit EXIT
  trap 'exit 130' INT
  trap 'exit 143' TERM

  if [[ ${1:-} == --help || ${1:-} == -h ]]; then
    usage
    SUMMARY_WRITTEN=1
    return 0
  fi
  [[ $# == 0 ]] || {
    usage >&2
    return 2
  }

  CURRENT_STEP=input-validation
  validate_inputs
  for tool in docker curl jq uv free sed rg; do
    command -v "$tool" >/dev/null 2>&1 || fail "required command is unavailable: $tool"
  done

  umask 027
  mkdir -p -- "$EVIDENCE_ROOT"
  if ! mkdir -- "$RUN_DIR"; then
    fail "evidence run already exists or cannot be created: $RUN_DIR"
  fi
  EVIDENCE_CLAIMED=1
  chmod 750 "$RUN_DIR"
  : >"$EXECUTION_FILE"
  : >"$ACCEPTANCE_FILE"
  : >"$CANDIDATE_FILE"

  set -a
  # shellcheck disable=SC1090
  . "$ENV_FILE"
  set +a
  [[ ${COMPOSE_PROJECT_NAME:-} == ntc-rag-phase3 ]] ||
    fail 'Phase 3 Compose project name drifted'
  [[ ${BGE_M3_ACCESS_HTTP_STATUS:-} == 402 ]] ||
    fail 'BGE-M3 observed HTTP status evidence drifted from 402'
  [[ ${BGE_M3_ACCESS_STATE:-} == blocked-* ]] ||
    fail 'BGE-M3 access state is not the reviewed blocked state'

  CURRENT_STEP=preexisting-container-gate
  if assert_no_preexisting_containers; then
    preexisting_result=pass
  else
    preexisting_result=fail
  fi
  record_execution preexisting-container-gate "$preexisting_result" 'docker project label query'
  [[ $preexisting_result == pass ]] || return 1

  CURRENT_STEP=static-gates
  if run_logged "$RUN_DIR/compose-check.log" "$ROOT_DIR/scripts/phase3-compose-check.sh"; then
    record_execution compose-static-gate pass compose-check.log
  else
    record_execution compose-static-gate fail compose-check.log
    return 1
  fi
  if run_logged "$RUN_DIR/secret-check.log" "$ROOT_DIR/scripts/phase3-secrets.sh" check; then
    record_execution secret-gate pass secret-check.log
  else
    record_execution secret-gate fail secret-check.log
    return 1
  fi
  if run_logged "$RUN_DIR/image-check.log" "$ROOT_DIR/scripts/phase3-images.sh" check all; then
    record_execution image-gate pass image-check.log
  else
    record_execution image-gate fail image-check.log
    return 1
  fi
  CURRENT_STEP=bge-live-access-probe
  local bge_probe_result=pass
  if ! BGE_LIVE_HTTP_STATUS=$(probe_bge_access); then
    bge_probe_result=fail
  fi
  write_bge_evidence "$RUN_DIR/bge-m3-access.json" "$bge_probe_result"
  if [[ $bge_probe_result == pass ]]; then
    bge_execution_status=blocked
  else
    bge_execution_status=fail
  fi
  record_execution bge-m3-access-gate "$bge_execution_status" bge-m3-access.json
  [[ $bge_probe_result == pass ]] || return 1

  if [[ $STAGE_CACHES == 1 ]]; then
    CURRENT_STEP=cache-staging
    MUTATION_STARTED=1
    for candidate in llama nemotron retriever; do
      if "$ROOT_DIR/scripts/phase3-cache.sh" stage "$candidate" >/dev/null 2>&1; then
        record_execution "cache-stage-$candidate" pass 'persistent Compose volume'
      else
        record_execution "cache-stage-$candidate" fail 'persistent Compose volume'
        return 1
      fi
    done
  else
    record_execution cache-staging skipped 'existing staged-cache markers required by runtime wrapper'
  fi

  mkdir -p -- "$RUN_DIR/candidates"
  for candidate in llama nemotron embedding-300m reranking-500m; do
    if run_candidate "$candidate"; then
      :
    else
      candidate_status=$?
      if ((candidate_status == 3)); then
        HAD_QUALITY_GATE_FAILURE=1
      else
        HAD_EXECUTION_FAILURE=1
      fi
    fi
  done

  if [[ $HAD_EXECUTION_FAILURE == 0 ]]; then
    # No-OOM is an orthogonal resource/runtime proof. Exercise both provisional
    # LLM combinations even when an automatic supplied-context quality gate
    # failed; neither combination is called the winner.
    combination_status=0
    for candidate in llama nemotron; do
      if ! run_combination "$candidate"; then
        combination_status=1
      fi
    done
    if [[ $combination_status == 0 ]]; then
      COMBINATION_PROVEN=1
    else
      HAD_EXECUTION_FAILURE=1
    fi
    if [[ $HAD_EXECUTION_FAILURE == 0 ]]; then
      if ! write_scorecard_inputs >"$RUN_DIR/scorecard-runner.log" 2>&1; then
        HAD_EXECUTION_FAILURE=1
        record_execution scorecard fail scorecard.json
      else
        record_execution scorecard pass scorecard.json
      fi
    else
      record_execution scorecard skipped 'combination failure'
    fi
  else
    record_execution scorecard skipped 'candidate failure'
    record_execution target-service-combination-llama skipped 'candidate failure'
    record_execution target-service-combination-nemotron skipped 'candidate failure'
  fi

  CURRENT_STEP=final-cleanup
  if cleanup_runtime; then
    record_execution final-cleanup pass cleanup.json
  else
    record_execution final-cleanup fail cleanup.json
    HAD_EXECUTION_FAILURE=1
  fi

  CURRENT_STEP=artifact-secret-scan
  if scan_exact_secret_artifacts; then
    record_execution exact-secret-artifact-scan pass secret-artifact-scan.json
  else
    record_execution exact-secret-artifact-scan fail secret-artifact-scan.json
    HAD_EXECUTION_FAILURE=1
  fi

  CURRENT_STEP=acceptance-mapping
  record_phase3_acceptance

  if [[ $HAD_EXECUTION_FAILURE == 1 ]]; then
    write_summary 1 failed "$(phase3_failure_reason)"
    printf 'Phase 3 live acceptance FAILED. Evidence: %s\n' "$RUN_DIR" >&2
    return 1
  fi

  write_summary 3 blocked \
    "BGE-M3 exact pinned runtime is unavailable (live scope HTTP $BGE_LIVE_HTTP_STATUS) and final human-reviewed winners are not selected"
  printf 'Phase 3 live acceptance BLOCKED (BGE-M3 live HTTP %s). Evidence: %s\n' \
    "$BGE_LIVE_HTTP_STATUS" "$RUN_DIR" >&2
  return 3
}

if [[ ${BASH_SOURCE[0]} == "$0" ]]; then
  main "$@"
fi

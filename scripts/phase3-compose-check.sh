#!/usr/bin/env bash

set -euo pipefail

ROOT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
ENV_FILE=${PHASE3_ENV_FILE:-$ROOT_DIR/infra/compose/phase3.env}
COMPOSE_FILE=${PHASE3_COMPOSE_FILE:-$ROOT_DIR/compose.phase3.yaml}
PHASE3_NGC_API_KEY_FILE=${PHASE3_NGC_API_KEY_FILE:-$ROOT_DIR/.secrets/phase3/ngc_api_key}
PHASE3_SECRET_GID=${PHASE3_SECRET_GID:-$(id -g)}
export PHASE3_NGC_API_KEY_FILE PHASE3_SECRET_GID
CONFIG_FILE=$(mktemp)
trap 'rm -f "$CONFIG_FILE"' EXIT

for tool in docker jq; do
  command -v "$tool" >/dev/null 2>&1 || {
    printf 'Required command is unavailable: %s\n' "$tool" >&2
    exit 127
  }
done
if [[ ! -f $ENV_FILE ]]; then
  printf 'Phase 3 environment file is missing: %s\n' "$ENV_FILE" >&2
  exit 2
fi
if [[ ! -f $COMPOSE_FILE ]]; then
  printf 'Phase 3 Compose file is missing: %s\n' "$COMPOSE_FILE" >&2
  exit 2
fi
if [[ ${PHASE3_REQUIRE_SECRET:-0} == 1 ]]; then
  "$ROOT_DIR/scripts/phase3-secrets.sh" check >/dev/null
fi

set -a
# shellcheck disable=SC1090
. "$ENV_FILE"
set +a

docker compose --env-file "$ENV_FILE" --file "$COMPOSE_FILE" \
  --profile llama --profile nemotron --profile retriever \
  --profile stage-llama --profile stage-nemotron --profile stage-retriever \
  config --format json >"$CONFIG_FILE"

jq -e \
  --arg llama_image "$NIM_LLM_LLAMA_IMAGE" \
  --arg nemotron_image "$NIM_LLM_NEMOTRON_IMAGE" \
  --arg embed_image "$NIM_EMBED_300M_IMAGE" \
  --arg rerank_image "$NIM_RERANK_500M_IMAGE" \
  --arg llama_arm64 "$NIM_LLM_LLAMA_ARM64_DIGEST" \
  --arg nemotron_arm64 "$NIM_LLM_NEMOTRON_ARM64_DIGEST" \
  --arg embed_arm64 "$NIM_EMBED_300M_ARM64_DIGEST" \
  --arg rerank_arm64 "$NIM_RERANK_500M_ARM64_DIGEST" \
  --arg llama_profile "$NIM_LLM_LLAMA_PROFILE" \
  --arg nemotron_start_arg "$NIM_LLM_NEMOTRON_START_ARG" \
  --arg bge_state "$BGE_M3_ACCESS_STATE" \
  --arg bge_http "$BGE_M3_ACCESS_HTTP_STATUS" '
  . as $root |
  ["nim-llm-llama", "nim-llm-nemotron", "nim-embedding-300m",
   "nim-reranking-500m"] as $runtime |
  ["stage-nim-llm-llama", "stage-nim-llm-nemotron",
   "stage-nim-embedding-300m", "stage-nim-reranking-500m"] as $staging |
  .name == "ntc-rag-phase3" and
  ([.services | keys[]] | sort) == (($runtime + $staging) | sort) and
  (.services | has("bge-m3") | not) and
  .["x-bge-m3-access-gate"].state == "blocked" and
  .["x-bge-m3-access-gate"].model_id == "baai/bge-m3" and
  (.["x-bge-m3-access-gate"].observed_http_status | tostring) == $bge_http and
  ($bge_http == "402") and
  ($bge_state | startswith("blocked-")) and
  .["x-bge-m3-access-gate"].mutable_latest_forbidden == true and
  (.networks.runtime.internal == true) and
  ((.networks.staging.internal // false) == false) and
  ([.volumes | keys[]] | sort) == ([
    "nim_embed_300m_cache", "nim_llama_cache", "nim_nemotron_cache",
    "nim_rerank_500m_cache"
  ] | sort) and
  (.secrets.ngc_api_key.file | type == "string" and length > 0) and
  all($runtime[]; . as $name |
    ($root.services[$name].networks | keys) == ["runtime"] and
    (($root.services[$name].ports // []) | length == 0) and
    (($root.services[$name].expose // []) == ["8000"]) and
    (($root.services[$name].secrets // []) | length == 0) and
    ($root.services[$name].environment.NTC_NIM_MODE == "serve") and
    ($root.services[$name].environment.NTC_NIM_HEALTH_PATH == "/v1/health/ready") and
    ($root.services[$name].healthcheck.test == ["CMD", "/usr/local/bin/ntc-nim-healthcheck"]) and
    ($root.services[$name].healthcheck.start_period | type == "string" and length > 0) and
    ($root.services[$name].restart == "unless-stopped") and
    ($root.services[$name].platform == "linux/arm64") and
    ($root.services[$name].pull_policy == "never") and
    ($root.services[$name].gpus == [{"count": -1}]) and
    (($root.services[$name].mem_limit | tonumber) > 0) and
    (($root.services[$name].pids_limit | tonumber) > 0) and
    ($root.services[$name].security_opt | index("no-new-privileges:true") != null)
  ) and
  all($staging[]; . as $name |
    ($root.services[$name].networks | keys) == ["staging"] and
    (($root.services[$name].ports // []) | length == 0) and
    (($root.services[$name].expose // []) | length == 0) and
    ($root.services[$name].environment.NTC_NIM_MODE == "stage") and
    ($root.services[$name].restart == "no") and
    ($root.services[$name].platform == "linux/arm64") and
    ($root.services[$name].pull_policy == "never") and
    ($root.services[$name].gpus == [{"count": -1}]) and
    (($root.services[$name].mem_limit | tonumber) > 0) and
    (($root.services[$name].pids_limit | tonumber) > 0) and
    ($root.services[$name].secrets == [{
      "source": "ngc_api_key", "target": "ngc_api_key", "mode": "0440"
    }]) and
    ($root.services[$name].group_add | index(env.PHASE3_SECRET_GID) != null)
  ) and
  (.services["nim-llm-llama"].image == $llama_image) and
  (.services["stage-nim-llm-llama"].image == $llama_image) and
  (.services["nim-llm-llama"].environment.NTC_NIM_ARM64_MANIFEST_DIGEST == $llama_arm64) and
  (.services["stage-nim-llm-llama"].environment.NTC_NIM_ARM64_MANIFEST_DIGEST == $llama_arm64) and
  (.services["nim-llm-nemotron"].image == $nemotron_image) and
  (.services["stage-nim-llm-nemotron"].image == $nemotron_image) and
  (.services["nim-llm-nemotron"].environment.NTC_NIM_ARM64_MANIFEST_DIGEST == $nemotron_arm64) and
  (.services["stage-nim-llm-nemotron"].environment.NTC_NIM_ARM64_MANIFEST_DIGEST == $nemotron_arm64) and
  (.services["nim-embedding-300m"].image == $embed_image) and
  (.services["stage-nim-embedding-300m"].image == $embed_image) and
  (.services["nim-embedding-300m"].environment.NTC_NIM_ARM64_MANIFEST_DIGEST == $embed_arm64) and
  (.services["stage-nim-embedding-300m"].environment.NTC_NIM_ARM64_MANIFEST_DIGEST == $embed_arm64) and
  (.services["nim-reranking-500m"].image == $rerank_image) and
  (.services["stage-nim-reranking-500m"].image == $rerank_image) and
  (.services["nim-reranking-500m"].environment.NTC_NIM_ARM64_MANIFEST_DIGEST == $rerank_arm64) and
  (.services["stage-nim-reranking-500m"].environment.NTC_NIM_ARM64_MANIFEST_DIGEST == $rerank_arm64) and
  (.services["nim-llm-llama"].environment.NTC_NIM_CONTEXT_CAPABILITY_TEST_TARGET == "131072") and
  (.services["nim-llm-llama"].environment.NIM_MODEL_PROFILE == $llama_profile) and
  (.services["stage-nim-llm-llama"].environment.NIM_MODEL_PROFILE == $llama_profile) and
  (.services["nim-llm-llama"].environment.NTC_NIM_CACHE_KEY ==
    ("llama-3-1-8b-nim-2-0-6-profile-" + $llama_profile)) and
  (.services["stage-nim-llm-llama"].environment.NTC_NIM_CACHE_KEY ==
    ("llama-3-1-8b-nim-2-0-6-profile-" + $llama_profile)) and
  (.services["nim-llm-llama"].environment.NTC_NIM_START_ENTRYPOINT == "/opt/nim/start_server.sh") and
  (.services["nim-llm-nemotron"].environment.NTC_NIM_IMAGE_VERSION_EXPECTED == "1.0.0") and
  (.services["nim-llm-nemotron"].environment.NTC_NIM_START_ENTRYPOINT ==
    "/opt/nvidia/nvidia_entrypoint.sh") and
  (.services["nim-llm-nemotron"].environment.NTC_NIM_START_ARG ==
    $nemotron_start_arg) and
  ($nemotron_start_arg == "/usr/local/bin/start_server") and
  (.services["stage-nim-llm-nemotron"].environment.NTC_NIM_START_ENTRYPOINT ==
    "/opt/nvidia/nvidia_entrypoint.sh") and
  (.services["stage-nim-llm-nemotron"].environment.NTC_NIM_START_ARG ==
    $nemotron_start_arg) and
  (.services["nim-llm-nemotron"].environment.NTC_NIM_RUNTIME_VERSION_STATUS ==
    "verified-live-nim-1-0-0-ready-models-context-131072") and
  (.services["nim-llm-nemotron"].environment.HF_HUB_OFFLINE == "1") and
  ((.services["stage-nim-llm-nemotron"].environment // {}) |
    has("HF_HUB_OFFLINE") | not) and
  (.services["nim-embedding-300m"].environment.NTC_NIM_START_ENTRYPOINT ==
    "/opt/nvidia/nvidia_entrypoint.sh") and
  (.services["nim-embedding-300m"].environment.NTC_NIM_START_ARG ==
    "/opt/nim/start_server.sh") and
  (.services["nim-reranking-500m"].environment.NTC_NIM_IMAGE_VERSION_EXPECTED == "1.10.0") and
  (.services["nim-reranking-500m"].environment.NTC_NIM_DOCS_VERSION_LINE == "1.10.0") and
  (.services["nim-reranking-500m"].environment.NTC_NIM_START_ENTRYPOINT ==
    "/opt/nvidia/nvidia_entrypoint.sh") and
  (.services["nim-reranking-500m"].environment.NTC_NIM_START_ARG ==
    "/opt/nim/start_server.sh") and
  all(.services[];
    (.image | test(":latest") | not) and
    (.image | test(":.+@sha256:[0-9a-f]{64}$")) and
    (.privileged // false | not) and
    ((.network_mode // "") != "host") and
    ([.environment // {} | keys[] |
      select(test("^(NGC_API_KEY|NGC_CLI_API_KEY|HF_TOKEN|HUGGING_FACE_HUB_TOKEN)$"))] |
      length == 0) and
    ((.environment // {}) | has("NIM_MAX_MODEL_LEN") | not)
  ) and
  all([
    "nim-llm-nemotron", "nim-embedding-300m", "nim-reranking-500m",
    "stage-nim-llm-nemotron", "stage-nim-embedding-300m",
    "stage-nim-reranking-500m"
  ][]; . as $name |
    (($root.services[$name].environment // {}) | has("NIM_MODEL_PROFILE") | not)
  )
' "$CONFIG_FILE" >/dev/null || {
  printf 'Phase 3 Compose isolation, pinning, or security contract failed.\n' >&2
  exit 1
}

if jq -r '.. | strings' "$CONFIG_FILE" | grep -Fq '/var/run/docker.sock'; then
  printf 'Phase 3 Compose must not mount the Docker socket.\n' >&2
  exit 1
fi
if [[ -s $PHASE3_NGC_API_KEY_FILE ]]; then
  # Read the credential as a pattern file so it never appears in this shell's
  # variables or in a child process argument list visible through `ps`.
  if grep -Fq --file="$PHASE3_NGC_API_KEY_FILE" "$CONFIG_FILE"; then
    printf 'Rendered Phase 3 Compose config contains the NGC secret value.\n' >&2
    exit 1
  fi
fi

printf 'Phase 3 Compose config, egress isolation, and image pinning contract passed.\n'

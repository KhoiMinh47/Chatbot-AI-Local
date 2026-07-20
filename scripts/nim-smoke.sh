#!/usr/bin/env bash

# Minimal Phase 0 API smoke for an already-running NIM service.
# This script does not start, stop, pull, or modify any container/model.

set -euo pipefail

usage() {
  cat <<'EOF'
Usage:
  NIM_KIND=llm|embedding|reranking \
  NIM_API_BASE_URL=http://127.0.0.1:8000/v1 \
  NIM_MODEL=<exact-model-id> \
  ./scripts/nim-smoke.sh

Optional:
  NIM_BASE_URL=<origin>        Legacy alias; /v1 is appended when absent.
  NIM_API_KEY_FILE=<path>     Preferred source for a bearer token.
  NIM_API_KEY=<bearer-token>  Fallback; never placed in curl's argv.
  NIM_TIMEOUT_SECONDS=30
  NIM_METRICS_REQUIRED=0|1    Defaults to 1 for LLM and 0 for Retriever 1.x.
  NIM_REASONING_CONTROL_MODE=llama-standard|nemotron-no-think
                              Required for LLM; fixed allowlist, not prompt text.

Embedding additionally requires NIM_EMBEDDING_DIMENSION=<positive integer>.

The endpoint contract must be rechecked against the documentation for the
exact pinned NIM version before use. These paths match the version lines listed
in the Phase 0 model inventory.
EOF
}

for tool in curl jq; do
  if ! command -v "$tool" >/dev/null 2>&1; then
    printf 'Required command is unavailable: %s\n' "$tool" >&2
    exit 127
  fi
done

: "${NIM_KIND:?Set NIM_KIND to llm, embedding, or reranking}"
: "${NIM_MODEL:?Set NIM_MODEL to the exact model ID reported by the service}"

case "$NIM_KIND" in
  llm | embedding | reranking) ;;
  *)
    usage >&2
    exit 2
    ;;
esac

reasoning_control_mode=${NIM_REASONING_CONTROL_MODE:-}
reasoning_control_text=
if [[ $NIM_KIND == llm ]]; then
  case "$reasoning_control_mode" in
    llama-standard) reasoning_control_text='detailed thinking off' ;;
    nemotron-no-think) reasoning_control_text=/no_think ;;
    *)
      printf 'NIM_REASONING_CONTROL_MODE must be llama-standard or nemotron-no-think for LLM smoke.\n' >&2
      exit 2
      ;;
  esac
elif [[ -n $reasoning_control_mode ]]; then
  printf 'NIM_REASONING_CONTROL_MODE applies only to LLM smoke.\n' >&2
  exit 2
fi
unset NIM_REASONING_CONTROL_MODE

if [[ -n ${NIM_API_BASE_URL:-} && -n ${NIM_BASE_URL:-} ]]; then
  printf 'Set only NIM_API_BASE_URL or the legacy NIM_BASE_URL, not both.\n' >&2
  exit 2
fi
base_url=${NIM_API_BASE_URL:-${NIM_BASE_URL:-}}
if [[ -z $base_url ]]; then
  printf 'Set NIM_API_BASE_URL (preferred) or NIM_BASE_URL.\n' >&2
  exit 2
fi
base_url=${base_url%/}
if [[ $base_url == */v1 ]]; then
  api_base_url=$base_url
else
  api_base_url=$base_url/v1
fi
NIM_TIMEOUT_SECONDS=${NIM_TIMEOUT_SECONDS:-30}
if [[ ! $api_base_url =~ ^https?:// ]] || [[ $api_base_url =~ ^https?://[^/]*@ ]] ||
  [[ $api_base_url == *\?* || $api_base_url == *\#* ]]; then
  printf 'NIM API base URL must be HTTP(S) without userinfo, query, or fragment.\n' >&2
  exit 2
fi
if [[ ! $NIM_TIMEOUT_SECONDS =~ ^[1-9][0-9]*$ ]]; then
  printf 'NIM_TIMEOUT_SECONDS must be a positive integer.\n' >&2
  exit 2
fi
if [[ -z ${NIM_METRICS_REQUIRED:-} ]]; then
  if [[ $NIM_KIND == llm ]]; then
    NIM_METRICS_REQUIRED=1
  else
    NIM_METRICS_REQUIRED=0
  fi
fi
if [[ $NIM_METRICS_REQUIRED != 0 && $NIM_METRICS_REQUIRED != 1 ]]; then
  printf 'NIM_METRICS_REQUIRED must be 0 or 1.\n' >&2
  exit 2
fi
if [[ $NIM_KIND == embedding ]] &&
  [[ ! ${NIM_EMBEDDING_DIMENSION:-} =~ ^[1-9][0-9]*$ ]]; then
  printf 'NIM_EMBEDDING_DIMENSION must be a positive integer for embedding smoke.\n' >&2
  exit 2
fi

api_key=${NIM_API_KEY:-}
if [[ -n ${NIM_API_KEY_FILE:-} ]]; then
  if [[ ! -r $NIM_API_KEY_FILE ]]; then
    printf 'NIM_API_KEY_FILE is not readable: %s\n' "$NIM_API_KEY_FILE" >&2
    exit 2
  fi
  api_key=$(<"$NIM_API_KEY_FILE")
  if [[ -z $api_key ]]; then
    printf 'NIM_API_KEY_FILE is empty.\n' >&2
    exit 2
  fi
fi
if [[ -n $api_key && ! $api_key =~ ^[-A-Za-z0-9._~+/=]+$ ]]; then
  printf 'Bearer token contains unsupported characters.\n' >&2
  exit 2
fi
unset NIM_API_KEY NIM_API_KEY_FILE

request() (
  local method=$1
  local url=$2
  local payload=${3:-}
  local body_file
  local http_code
  local curl_status
  local -a request_args

  body_file=$(mktemp)
  trap 'rm -f "$body_file"' EXIT
  request_args=(
    --silent
    --show-error
    --max-time "$NIM_TIMEOUT_SECONDS"
    --output "$body_file"
    --write-out '%{http_code}'
    --request "$method"
    -H 'Content-Type: application/json'
    "$url"
  )
  if [[ -n $payload ]]; then
    request_args+=(--data "$payload")
  fi

  if [[ -n $api_key ]]; then
    # Supply the secret through curl's config stdin, not the process argument
    # list. --disable is curl's first argument so ~/.curlrc is never loaded.
    if http_code=$(printf 'header = "Authorization: Bearer %s"\n' "$api_key" |
      curl --disable --config - "${request_args[@]}"); then
      curl_status=0
    else
      curl_status=$?
    fi
  else
    if http_code=$(curl --disable "${request_args[@]}"); then
      curl_status=0
    else
      curl_status=$?
    fi
  fi

  if ((curl_status != 0)); then
    return "$curl_status"
  fi
  if [[ ! $http_code =~ ^2[0-9][0-9]$ ]]; then
    printf 'Unexpected HTTP status %s for %s %s; expected 2xx.\n' \
      "$http_code" "$method" "$url" >&2
    return 22
  fi

  cat "$body_file"
)

printf 'Checking documented NIM health endpoints at %s\n' "$api_base_url"
# Health response fields differ between NIM product/version lines. HTTP 2xx is
# the stable contract; request() checks the exact status class without assuming
# a `.ready` field that some Retriever releases do not return.
request GET "$api_base_url/health/live" >/dev/null
request GET "$api_base_url/health/ready" >/dev/null
request GET "$api_base_url/models" | jq -e --arg model "$NIM_MODEL" \
  'any(.data[]?; .id == $model)'

# NIM LLM 2.x documents this endpoint. Retriever 1.x versions must be checked
# against their own API contract instead of inheriting the LLM assumption.
if [[ $NIM_METRICS_REQUIRED == 1 ]]; then
  metrics=$(request GET "$api_base_url/metrics")
  [[ -n $metrics ]]
fi

case "$NIM_KIND" in
  llm)
    printf 'LLM reasoning control mode: %s\n' "$reasoning_control_mode"
    payload=$(jq -n --arg model "$NIM_MODEL" \
      --arg reasoning_control "$reasoning_control_text" '{
      model: $model,
      messages: [
        {role: "system", content: $reasoning_control},
        {role: "user", content: "Reply with exactly: OK"}
      ],
      max_tokens: 8,
      temperature: 0
    }')
    request POST "$api_base_url/chat/completions" "$payload" |
      jq -e --arg model "$NIM_MODEL" '
        ((.model? // $model) == $model) and
        (.choices[0].message.content | type == "string" and
          gsub("^[[:space:]]+|[[:space:]]+$"; "") == "OK")'
    ;;
  embedding)
    payload=$(jq -n --arg model "$NIM_MODEL" '{
      model: $model,
      input: ["Xin chào NTC"],
      input_type: "query",
      encoding_format: "float"
    }')
    request POST "$api_base_url/embeddings" "$payload" |
      jq -e --arg model "$NIM_MODEL" --argjson dimension "$NIM_EMBEDDING_DIMENSION" '
        ((.model? // $model) == $model) and
        (.data[0].embedding |
          type == "array" and length == $dimension and
          all(.[]; type == "number"))'
    ;;
  reranking)
    payload=$(jq -n --arg model "$NIM_MODEL" '{
      model: $model,
      query: {text: "Thủ đô của Việt Nam là gì?"},
      passages: [
        {text: "Hà Nội là thủ đô của Việt Nam."},
        {text: "Tokyo là thủ đô của Nhật Bản."}
      ]
    }')
    request POST "$api_base_url/ranking" "$payload" |
      jq -e --arg model "$NIM_MODEL" '
        ((.model? // $model) == $model) and
        (.rankings |
          type == "array" and length == 2 and
          all(.[]; (.index | type) == "number" and (.logit | type) == "number") and
          .[0].index == 0 and .[1].index == 1 and .[0].logit > .[1].logit)'
    ;;
esac

printf '%s smoke passed for model %s\n' "$NIM_KIND" "$NIM_MODEL"

#!/usr/bin/env bash

set -euo pipefail

ROOT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
ENV_FILE=${PHASE3_ENV_FILE:-$ROOT_DIR/infra/compose/phase3.env}
COMPOSE_FILE=${PHASE3_COMPOSE_FILE:-$ROOT_DIR/compose.phase3.yaml}
ACTION=${1:-}
TARGET=${2:-}
PHASE3_SECRET_GID=${PHASE3_SECRET_GID:-$(id -g)}
PHASE3_NGC_API_KEY_FILE=${PHASE3_NGC_API_KEY_FILE:-$ROOT_DIR/.secrets/phase3/ngc_api_key}
export PHASE3_SECRET_GID PHASE3_NGC_API_KEY_FILE

if [[ $ACTION != stage ]] || \
  [[ $TARGET != llama && $TARGET != nemotron && $TARGET != retriever ]]; then
  printf 'Usage: %s stage [llama|nemotron|retriever]\n' "${BASH_SOURCE[0]}" >&2
  exit 2
fi
if [[ ! -f $ENV_FILE ]]; then
  printf 'Phase 3 environment file is missing: %s\n' "$ENV_FILE" >&2
  exit 2
fi
command -v docker >/dev/null 2>&1 || {
  printf 'Required command is unavailable: docker\n' >&2
  exit 127
}

set -a
# shellcheck disable=SC1090
. "$ENV_FILE"
set +a

if [[ $TARGET == nemotron && $NIM_LLM_NEMOTRON_START_ENTRYPOINT != /* ]]; then
  printf 'Nemotron cache staging is blocked until the complete image entrypoint is verified.\n' \
    >&2
  exit 1
fi

"$ROOT_DIR/scripts/phase3-secrets.sh" check >/dev/null
PHASE3_REQUIRE_SECRET=1 "$ROOT_DIR/scripts/phase3-compose-check.sh" >/dev/null
"$ROOT_DIR/scripts/phase3-images.sh" check "$TARGET" >/dev/null

if [[ ! ${COMPOSE_PROJECT_NAME:-} =~ ^[a-z0-9][a-z0-9_-]*$ ]]; then
  printf 'COMPOSE_PROJECT_NAME contains unsupported characters.\n' >&2
  exit 2
fi

prepare_cache_volume() {
  local image=$1
  local volume=$2

  docker volume create "$volume" >/dev/null
  # Named volumes mounted over a path absent from an image start as root:root
  # 0755. All reviewed NIMs run as UID/GID 1000, so initialize only the cache
  # root in a networkless, short-lived container before starting the NIM.
  docker run --rm --pull never --network none --user 0:0 \
    --volume "$volume:/cache" --entrypoint /bin/sh "$image" \
    -ec 'chown 1000:1000 /cache && chmod 0775 /cache'
}

case "$TARGET" in
  llama)
    profile=stage-llama
    services=(stage-nim-llm-llama)
    prepare_cache_volume "$NIM_LLM_LLAMA_IMAGE" \
      "${COMPOSE_PROJECT_NAME}_nim_llama_cache"
    ;;
  nemotron)
    profile=stage-nemotron
    services=(stage-nim-llm-nemotron)
    prepare_cache_volume "$NIM_LLM_NEMOTRON_IMAGE" \
      "${COMPOSE_PROJECT_NAME}_nim_nemotron_cache"
    ;;
  retriever)
    profile=stage-retriever
    services=(stage-nim-embedding-300m stage-nim-reranking-500m)
    prepare_cache_volume "$NIM_EMBED_300M_IMAGE" \
      "${COMPOSE_PROJECT_NAME}_nim_embed_300m_cache"
    prepare_cache_volume "$NIM_RERANK_500M_IMAGE" \
      "${COMPOSE_PROJECT_NAME}_nim_rerank_500m_cache"
    ;;
esac

for service in "${services[@]}"; do
  docker compose --env-file "$ENV_FILE" --file "$COMPOSE_FILE" \
    --profile "$profile" run --rm --no-deps --pull never "$service"
done

printf 'Phase 3 model cache staging completed for target %s.\n' "$TARGET"

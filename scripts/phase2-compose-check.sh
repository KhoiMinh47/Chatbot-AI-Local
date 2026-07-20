#!/usr/bin/env bash

set -euo pipefail

ROOT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
ENV_FILE=${PHASE2_ENV_FILE:-$ROOT_DIR/infra/compose/phase2.env}
SECRET_DIR=${PHASE2_SECRET_DIR:-$ROOT_DIR/.secrets/phase2}
PHASE2_SECRET_GID=${PHASE2_SECRET_GID:-$(id -g)}
export PHASE2_SECRET_GID PHASE2_SECRET_DIR
PHASE2_SECRET_DIR=$SECRET_DIR
CONFIG_FILE=$(mktemp)
trap 'rm -f "$CONFIG_FILE"' EXIT

"$ROOT_DIR/scripts/phase2-secrets.sh" check >/dev/null
docker compose --env-file "$ENV_FILE" --file "$ROOT_DIR/compose.yaml" \
  --profile core --profile app --profile observability --profile dev \
  config --format json >"$CONFIG_FILE"

jq -e '
  .name == "ntc-rag-phase2" and
  ([.services | keys[]] | sort) == ([
    "api", "dcgm-exporter", "grafana", "mailpit", "minio", "postgres",
    "prometheus", "qdrant", "rabbitmq", "redis", "reverse-proxy", "web", "worker"
  ] | sort) and
  ([.services | to_entries[] | select((.value.ports // []) | length > 0) | .key] == ["reverse-proxy"]) and
  (.services["reverse-proxy"].ports | length == 1) and
  (.services["reverse-proxy"].ports[0].host_ip == "127.0.0.1") and
  ([.services | to_entries[] | select(.value.healthcheck == null) | .key] | length == 0) and
  ([.services | to_entries[] | select(.value.restart != "unless-stopped") | .key] | length == 0) and
  ([.services | to_entries[] | select((.value.mem_limit // 0) == 0) | .key] | length == 0) and
  ([.services | to_entries[] | select((.value.pids_limit // 0) == 0) | .key] | length == 0) and
  ([.services | to_entries[] | select(.value.privileged == true) | .key] | length == 0) and
  ([.services | to_entries[] | select(.value.network_mode == "host") | .key] | length == 0) and
  (.networks.internal.internal == true) and
  (.services.api.group_add | index(env.PHASE2_SECRET_GID) != null) and
  (.services.worker.group_add | index(env.PHASE2_SECRET_GID) != null) and
  (.services.grafana.group_add | index(env.PHASE2_SECRET_GID) != null) and
  ([.volumes | keys[]] | sort) == ([
    "grafana_data", "mailpit_data", "minio_data", "postgres_data",
    "prometheus_data", "qdrant_data", "rabbitmq_data", "redis_data"
  ] | sort)
' "$CONFIG_FILE" >/dev/null || {
  printf 'Phase 2 Compose security/topology contract failed.\n' >&2
  exit 1
}

while IFS= read -r image; do
  if [[ $image == ntc-rag-phase2-* ]]; then
    continue
  fi
  if [[ $image != *@sha256:* || $image == *:latest* ]]; then
    printf 'Compose contains an unpinned external image: %s\n' "$image" >&2
    exit 1
  fi
done < <(jq -r '.services[].image' "$CONFIG_FILE" | LC_ALL=C sort -u)

if jq -r '.. | strings' "$CONFIG_FILE" | grep -Fq '/var/run/docker.sock'; then
  printf 'Compose must not mount the Docker socket.\n' >&2
  exit 1
fi

for secret_file in "$SECRET_DIR"/*; do
  if grep -Fq -- "$(<"$secret_file")" "$CONFIG_FILE"; then
    printf 'Rendered Compose config contains a secret value.\n' >&2
    exit 1
  fi
done

printf 'Phase 2 Compose config and static security contract passed.\n'

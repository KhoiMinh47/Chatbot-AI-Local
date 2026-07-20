#!/usr/bin/env bash

set -euo pipefail

ROOT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
ENV_FILE=${PHASE2_ENV_FILE:-$ROOT_DIR/infra/compose/phase2.env}
PHASE2_SECRET_GID=${PHASE2_SECRET_GID:-$(id -g)}
export PHASE2_SECRET_GID
COMPOSE=(docker compose --env-file "$ENV_FILE" --file "$ROOT_DIR/compose.yaml")

set -a
# shellcheck disable=SC1090
. "$ENV_FILE"
set +a

container_id=$("${COMPOSE[@]}" --profile core ps -q postgres)
if [[ -z $container_id ]]; then
  printf 'Phase 2 PostgreSQL container is not running.\n' >&2
  exit 1
fi
health=$(docker inspect "$container_id" --format '{{.State.Health.Status}}')
if [[ $health != healthy ]]; then
  printf 'Phase 2 PostgreSQL is not healthy: %s\n' "$health" >&2
  exit 1
fi
postgres_host=$(docker inspect "$container_id" --format '{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}')
if [[ -z $postgres_host ]]; then
  printf 'Unable to resolve the internal PostgreSQL address.\n' >&2
  exit 1
fi

export PHASE2_POSTGRES_HOST=$postgres_host
export PHASE2_POSTGRES_USER=$POSTGRES_USER
export PHASE2_POSTGRES_DB=$POSTGRES_DB
export PHASE2_POSTGRES_PASSWORD_FILE=${PHASE2_SECRET_DIR:-$ROOT_DIR/.secrets/phase2}/postgres_password

cd "$ROOT_DIR"
uv run --locked --no-sync alembic upgrade head
uv run --locked --no-sync alembic current --check-heads

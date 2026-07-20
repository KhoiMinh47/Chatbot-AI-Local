#!/usr/bin/env bash
set -euo pipefail

# Restore data services from a backup directory created by backup.sh
# Usage:
#   ./restore.sh backups/2026-04-09_120000

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$PROJECT_ROOT"

COMPOSE_FILE="${COMPOSE_FILE:-docker-compose.yml}"

POSTGRES_CONTAINER="${POSTGRES_CONTAINER:-postgres}"
POSTGRES_USER="${POSTGRES_USER:-bao}"
POSTGRES_DB="${POSTGRES_DB:-multiangent_db}"
POSTGRES_CLIENT_SERVICES="${POSTGRES_CLIENT_SERVICES:-backend pgbouncer db_ui postgres_exporter}"

REDIS_SERVICE="${REDIS_SERVICE:-redis}"
REDIS_CONTAINER="${REDIS_CONTAINER:-redis}"

QDRANT_SERVICE="${QDRANT_SERVICE:-qdrant}"
MINIO_SERVICE="${MINIO_SERVICE:-minio}"

BACKUP_DIR="${1:-}"
if [[ -z "$BACKUP_DIR" ]]; then
  echo "Usage: $0 <backup_dir>"
  exit 1
fi

if [[ ! -d "$BACKUP_DIR" ]]; then
  echo "ERROR: Backup directory not found: $BACKUP_DIR"
  exit 1
fi

for required in postgres.dump redis.dump.rdb qdrant_storage.tar.gz minio_data.tar.gz; do
  if [[ ! -f "$BACKUP_DIR/$required" ]]; then
    echo "ERROR: Missing file: $BACKUP_DIR/$required"
    exit 1
  fi
done

service_exists_in_compose() {
  local svc="$1"
  docker compose -f "$COMPOSE_FILE" config --services | grep -qx "$svc"
}

stop_postgres_clients() {
  local stopped_any="false"
  for svc in $POSTGRES_CLIENT_SERVICES; do
    if service_exists_in_compose "$svc"; then
      echo "[pg] Stopping PostgreSQL client service: $svc"
      docker compose -f "$COMPOSE_FILE" stop "$svc" >/dev/null || true
      stopped_any="true"
    fi
  done
  if [[ "$stopped_any" == "false" ]]; then
    echo "[pg] No configured PostgreSQL client service found in compose."
  fi
}

echo "[1/8] Ensuring required services are up..."
docker compose -f "$COMPOSE_FILE" up -d "$POSTGRES_CONTAINER" "$REDIS_SERVICE" "$QDRANT_SERVICE" "$MINIO_SERVICE"

echo "[2/8] Stopping PostgreSQL client services (to avoid active sessions)..."
stop_postgres_clients

echo "[3/8] Restoring PostgreSQL schema+data..."
docker compose -f "$COMPOSE_FILE" exec -T "$POSTGRES_CONTAINER" \
  psql -U "$POSTGRES_USER" -d postgres -v ON_ERROR_STOP=1 -c "ALTER DATABASE \"$POSTGRES_DB\" WITH ALLOW_CONNECTIONS false;" || true
docker compose -f "$COMPOSE_FILE" exec -T "$POSTGRES_CONTAINER" \
  psql -U "$POSTGRES_USER" -d postgres -v ON_ERROR_STOP=1 -c "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = '$POSTGRES_DB' AND pid <> pg_backend_pid();"
docker compose -f "$COMPOSE_FILE" exec -T "$POSTGRES_CONTAINER" \
  psql -U "$POSTGRES_USER" -d postgres -v ON_ERROR_STOP=1 -c "DROP DATABASE IF EXISTS \"$POSTGRES_DB\" WITH (FORCE);"
docker compose -f "$COMPOSE_FILE" exec -T "$POSTGRES_CONTAINER" \
  psql -U "$POSTGRES_USER" -d postgres -v ON_ERROR_STOP=1 -c "CREATE DATABASE \"$POSTGRES_DB\";"
cat "$BACKUP_DIR/postgres.dump" | docker compose -f "$COMPOSE_FILE" exec -T "$POSTGRES_CONTAINER" \
  pg_restore -U "$POSTGRES_USER" -d "$POSTGRES_DB" --clean --if-exists

echo "[4/8] Stopping Redis/Qdrant/MinIO to restore filesystem data..."
docker compose -f "$COMPOSE_FILE" stop "$REDIS_SERVICE" "$QDRANT_SERVICE" "$MINIO_SERVICE"

echo "[5/8] Restoring Redis dump..."
mkdir -p "cache/redis_data"
if ! cp "$BACKUP_DIR/redis.dump.rdb" "cache/redis_data/dump.rdb" 2>/dev/null; then
  echo "[5/8] Local copy failed (permission). Fallback to container copy..."
  docker compose -f "$COMPOSE_FILE" cp "$BACKUP_DIR/redis.dump.rdb" "$REDIS_CONTAINER:/data/dump.rdb"
fi

echo "[6/8] Restoring Qdrant storage..."
rm -rf "cache/qdrant_storage"
tar -xzf "$BACKUP_DIR/qdrant_storage.tar.gz" -C "cache"

echo "[7/8] Restoring MinIO data..."
rm -rf "cache/minio"
tar -xzf "$BACKUP_DIR/minio_data.tar.gz" -C "cache"

echo "[8/8] Starting services again..."
docker compose -f "$COMPOSE_FILE" up -d "$REDIS_SERVICE" "$QDRANT_SERVICE" "$MINIO_SERVICE"

echo "Restore completed from: $BACKUP_DIR"

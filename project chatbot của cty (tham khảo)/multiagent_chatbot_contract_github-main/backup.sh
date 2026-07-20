#!/usr/bin/env bash
set -euo pipefail

# Backup data services for this project:
# - PostgreSQL (logical dump)
# - Redis (RDB snapshot)
# - Qdrant (filesystem archive)
# - MinIO (filesystem archive)

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$PROJECT_ROOT"

COMPOSE_FILE="${COMPOSE_FILE:-docker-compose.yml}"
BACKUP_BASE_DIR="${BACKUP_BASE_DIR:-backups}"
TIMESTAMP="$(date +%F_%H%M%S)"
BACKUP_DIR="$BACKUP_BASE_DIR/$TIMESTAMP"

# App defaults from docker-compose.yml
POSTGRES_CONTAINER="${POSTGRES_CONTAINER:-postgres}"
POSTGRES_USER="${POSTGRES_USER:-bao}"
POSTGRES_DB="${POSTGRES_DB:-multiangent_db}"

REDIS_CONTAINER="${REDIS_CONTAINER:-redis}"
REDIS_PASSWORD="${REDIS_PASSWORD:-Redis@BachViet2026}"

mkdir -p "$BACKUP_DIR"

echo "[1/6] Checking docker compose file..."
if [[ ! -f "$COMPOSE_FILE" ]]; then
  echo "ERROR: Compose file not found: $COMPOSE_FILE"
  exit 1
fi

echo "[2/6] Backing up PostgreSQL -> $BACKUP_DIR/postgres.dump"
docker compose -f "$COMPOSE_FILE" exec -T "$POSTGRES_CONTAINER" \
  pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -F c \
  > "$BACKUP_DIR/postgres.dump"

echo "[3/6] Backing up Redis -> $BACKUP_DIR/redis.dump.rdb"
docker compose -f "$COMPOSE_FILE" exec -T "$REDIS_CONTAINER" \
  redis-cli -a "$REDIS_PASSWORD" SAVE >/dev/null

# Prefer local bind-mount copy for speed; fallback to docker compose cp when file permissions block access.
if ! cp "cache/redis_data/dump.rdb" "$BACKUP_DIR/redis.dump.rdb" 2>/dev/null; then
  echo "[3/6] Local Redis dump copy failed (permission). Fallback to container copy..."
  docker compose -f "$COMPOSE_FILE" cp "$REDIS_CONTAINER:/data/dump.rdb" "$BACKUP_DIR/redis.dump.rdb"
fi

echo "[4/6] Backing up Qdrant storage -> $BACKUP_DIR/qdrant_storage.tar.gz"
tar -czf "$BACKUP_DIR/qdrant_storage.tar.gz" -C "cache" "qdrant_storage"

echo "[5/6] Backing up MinIO data -> $BACKUP_DIR/minio_data.tar.gz"
tar -czf "$BACKUP_DIR/minio_data.tar.gz" -C "cache" "minio"

echo "[6/6] Writing metadata -> $BACKUP_DIR/metadata.env"
cat > "$BACKUP_DIR/metadata.env" <<EOF
BACKUP_CREATED_AT=$TIMESTAMP
POSTGRES_USER=$POSTGRES_USER
POSTGRES_DB=$POSTGRES_DB
POSTGRES_CONTAINER=$POSTGRES_CONTAINER
REDIS_CONTAINER=$REDIS_CONTAINER
COMPOSE_FILE=$COMPOSE_FILE
EOF

echo "Backup completed: $BACKUP_DIR"

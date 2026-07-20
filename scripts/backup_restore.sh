#!/usr/bin/env bash
# Phase 11 Backup and Restore Script for PostgreSQL and Qdrant

set -euo pipefail

ROOT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
ENV_FILE=${PHASE2_ENV_FILE:-$ROOT_DIR/infra/compose/phase2.env}

if [[ -f $ENV_FILE ]]; then
  set -a
  # shellcheck disable=SC1090
  . "$ENV_FILE"
  set +a
fi

COMPOSE=(docker compose --env-file "$ENV_FILE" --file "$ROOT_DIR/compose.yaml")

usage() {
  printf "Usage: %s [backup|restore] [backup_directory]\n" "$0" >&2
  exit 1
}

if [[ $# -lt 2 ]]; then
  usage
fi

ACTION=$1
BACKUP_DIR=$2

if [[ $ACTION != "backup" && $ACTION != "restore" ]]; then
  usage
fi

# Find running containers
postgres_container=$("${COMPOSE[@]}" --profile core ps -q postgres 2>/dev/null || true)
qdrant_container=$("${COMPOSE[@]}" --profile core ps -q qdrant 2>/dev/null || true)

if [[ -z $postgres_container ]]; then
  printf "PostgreSQL container is not running. Cannot proceed.\n" >&2
  exit 1
fi

if [[ -z $qdrant_container ]]; then
  printf "Qdrant container is not running. Cannot proceed.\n" >&2
  exit 1
fi

mkdir -p "$BACKUP_DIR"

if [[ $ACTION == "backup" ]]; then
  printf "Starting Backup...\n"
  
  # 1. PostgreSQL Backup
  printf "Backing up PostgreSQL...\n"
  docker exec -i "$postgres_container" sh -c \
    'PGPASSWORD=$(cat /run/secrets/postgres_password) pg_dump -U "$POSTGRES_USER" "$POSTGRES_DB"' \
    > "$BACKUP_DIR/postgres_backup.sql"
  printf "PostgreSQL backup completed: %s/postgres_backup.sql\n" "$BACKUP_DIR"

  # 2. Qdrant Backup
  printf "Backing up Qdrant snapshots...\n"
  # Create full snapshot via Qdrant API inside container
  snapshot_resp=$(docker exec -i "$qdrant_container" curl -s -X POST http://localhost:6333/snapshots)
  printf "Qdrant Snapshot Response: %s\n" "$snapshot_resp"
  
  # Copy snapshot storage out of container
  # Snapshots by default are stored in the storage path under Qdrant
  docker cp "$qdrant_container:/qdrant/storage/snapshots" "$BACKUP_DIR/qdrant_snapshots" 2>/dev/null || {
    # If no snapshots directory, we check common folders
    docker exec -i "$qdrant_container" mkdir -p /qdrant/storage/snapshots
    docker cp "$qdrant_container:/qdrant/storage/snapshots" "$BACKUP_DIR/qdrant_snapshots"
  }
  printf "Qdrant snapshot folder copied to: %s/qdrant_snapshots\n" "$BACKUP_DIR"
  printf "Backup completed successfully.\n"

elif [[ $ACTION == "restore" ]]; then
  printf "Starting Restore...\n"

  # 1. PostgreSQL Restore
  if [[ -f "$BACKUP_DIR/postgres_backup.sql" ]]; then
    printf "Restoring PostgreSQL...\n"
    # Drop and recreate schema / tables or simply restore
    docker exec -i "$postgres_container" sh -c \
      'PGPASSWORD=$(cat /run/secrets/postgres_password) psql -U "$POSTGRES_USER" -d "$POSTGRES_DB"' \
      < "$BACKUP_DIR/postgres_backup.sql"
    printf "PostgreSQL restore completed.\n"
  else
    printf "PostgreSQL backup file not found at: %s/postgres_backup.sql\n" "$BACKUP_DIR" >&2
  fi

  # 2. Qdrant Restore
  if [[ -d "$BACKUP_DIR/qdrant_snapshots" ]]; then
    printf "Restoring Qdrant snapshots...\n"
    docker cp "$BACKUP_DIR/qdrant_snapshots/." "$qdrant_container:/qdrant/storage/snapshots/"
    printf "Qdrant snapshots restored to container storage.\n"
  else
    printf "Qdrant snapshot folder not found at: %s/qdrant_snapshots\n" "$BACKUP_DIR" >&2
  fi
  
  printf "Restore completed.\n"
fi

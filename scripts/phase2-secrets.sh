#!/usr/bin/env bash

set -euo pipefail

ROOT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
SECRET_DIR=${PHASE2_SECRET_DIR:-$ROOT_DIR/.secrets/phase2}
SECRET_GID=${PHASE2_SECRET_GID:-$(id -g)}
ACTION=${1:-check}
SECRET_NAMES=(
  postgres_password
  redis_password
  rabbitmq_password
  minio_root_password
  grafana_admin_password
)

secure_secret_directory() {
  if [[ ! -d $SECRET_DIR ]]; then
    printf 'Required Phase 2 secret directory is missing: %s\n' "$SECRET_DIR" >&2
    return 1
  fi
  chgrp "$SECRET_GID" "$SECRET_DIR"
  chmod 750 "$SECRET_DIR"
}

require_secret() {
  local name=$1
  local path=$SECRET_DIR/$name

  if [[ ! -f $path || ! -s $path ]]; then
    printf 'Required Phase 2 secret file is missing or empty: %s\n' "$path" >&2
    return 1
  fi
  chgrp "$SECRET_GID" "$path"
  chmod 640 "$path"
}

case "$ACTION" in
  init)
    command -v openssl >/dev/null 2>&1 || {
      printf 'Required command is unavailable: openssl\n' >&2
      exit 127
    }
    umask 077
    mkdir -p "$SECRET_DIR"
    secure_secret_directory
    for name in "${SECRET_NAMES[@]}"; do
      path=$SECRET_DIR/$name
      if [[ ! -e $path ]]; then
        openssl rand -hex 32 >"$path"
      fi
      require_secret "$name"
    done
    printf 'Phase 2 secret files are initialized with mode 0640 for runtime group %s.\n' \
      "$SECRET_GID"
    ;;
  check)
    secure_secret_directory
    for name in "${SECRET_NAMES[@]}"; do
      require_secret "$name"
    done
    printf 'Phase 2 secret files are present and non-empty.\n'
    ;;
  *)
    printf 'Usage: %s [init|check]\n' "${BASH_SOURCE[0]}" >&2
    exit 2
    ;;
esac

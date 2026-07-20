#!/usr/bin/env bash

set -euo pipefail

ROOT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
SECRET_DIR=${PHASE3_SECRET_DIR:-$ROOT_DIR/.secrets/phase3}
SECRET_FILE=${PHASE3_NGC_API_KEY_FILE:-$SECRET_DIR/ngc_api_key}
SECRET_GID=${PHASE3_SECRET_GID:-$(id -g)}
DOCKER_CONFIG_FILE=${PHASE3_DOCKER_CONFIG_FILE:-${DOCKER_CONFIG:-$HOME/.docker}/config.json}
ACTION=${1:-check}

check_secret() {
  local secret_value

  if [[ -L $SECRET_DIR || ! -d $SECRET_DIR ]]; then
    printf 'Required Phase 3 secret directory is missing or is a symlink: %s\n' \
      "$SECRET_DIR" >&2
    return 1
  fi
  if [[ -L $SECRET_FILE || ! -f $SECRET_FILE || ! -s $SECRET_FILE ]]; then
    printf 'Required Phase 3 NGC secret is missing, empty, or is a symlink: %s\n' \
      "$SECRET_FILE" >&2
    return 1
  fi
  if [[ $(stat -c '%u' "$SECRET_DIR") != "$(id -u)" || \
    $(stat -c '%g' "$SECRET_DIR") != "$SECRET_GID" || \
    $(stat -c '%a' "$SECRET_DIR") != 750 ]]; then
    printf 'Phase 3 secret directory must be caller-owned, runtime-group-owned, and mode 0750.\n' >&2
    return 1
  fi
  if [[ $(stat -c '%u' "$SECRET_FILE") != "$(id -u)" || \
    $(stat -c '%g' "$SECRET_FILE") != "$SECRET_GID" || \
    $(stat -c '%a' "$SECRET_FILE") != 640 ]]; then
    printf 'Phase 3 NGC secret must be caller-owned, runtime-group-owned, and mode 0640.\n' >&2
    return 1
  fi

  secret_value=$(<"$SECRET_FILE")
  if ((${#secret_value} < 20)) || [[ ! $secret_value =~ ^[-A-Za-z0-9._~+/=]+$ ]]; then
    printf 'Phase 3 NGC secret has an invalid format.\n' >&2
    unset secret_value
    return 1
  fi
  unset secret_value
}

case "$ACTION" in
  init-from-docker-auth)
    for tool in jq base64 stat; do
      command -v "$tool" >/dev/null 2>&1 || {
        printf 'Required command is unavailable: %s\n' "$tool" >&2
        exit 127
      }
    done
    if [[ ! $SECRET_GID =~ ^[0-9]+$ ]]; then
      printf 'PHASE3_SECRET_GID must be a numeric group ID.\n' >&2
      exit 2
    fi
    if [[ ! -f $DOCKER_CONFIG_FILE || ! -s $DOCKER_CONFIG_FILE ]]; then
      printf 'Docker credential configuration is missing: %s\n' "$DOCKER_CONFIG_FILE" >&2
      exit 1
    fi
    secret_parent=$(dirname -- "$SECRET_DIR")
    if [[ -L $secret_parent || -L $SECRET_DIR || \
      (-e $SECRET_DIR && ! -d $SECRET_DIR) ]]; then
      printf 'Refusing a symlinked or non-directory Phase 3 secret path.\n' >&2
      exit 1
    fi
    if [[ ! -d $secret_parent ]]; then
      mkdir -p -- "$secret_parent"
    fi
    if [[ -e $SECRET_FILE || -L $SECRET_FILE ]]; then
      printf 'Refusing to overwrite the existing Phase 3 NGC secret.\n' >&2
      exit 1
    fi

    encoded_auth=$(jq -er '.auths["nvcr.io"].auth | select(type == "string" and length > 0)' \
      "$DOCKER_CONFIG_FILE") || {
      printf 'Docker configuration has no inline nvcr.io credential.\n' >&2
      exit 1
    }
    decoded_auth=$(printf '%s' "$encoded_auth" | base64 --decode 2>/dev/null) || {
      printf 'The nvcr.io Docker credential is not valid base64.\n' >&2
      unset encoded_auth
      exit 1
    }
    unset encoded_auth
    username=${decoded_auth%%:*}
    secret_value=${decoded_auth#*:}
    if [[ $decoded_auth != *:* || $username != "\$oauthtoken" || \
      ${#secret_value} -lt 20 || ! $secret_value =~ ^[-A-Za-z0-9._~+/=]+$ ]]; then
      printf 'The nvcr.io Docker credential is not an expected NGC API credential.\n' >&2
      unset decoded_auth username secret_value
      exit 1
    fi
    unset decoded_auth username

    umask 077
    mkdir -p -- "$SECRET_DIR"
    chgrp "$SECRET_GID" -- "$SECRET_DIR"
    chmod 750 -- "$SECRET_DIR"
    secret_tmp=$(mktemp "$SECRET_DIR/.ngc-api-key.XXXXXX")
    trap 'rm -f -- "$secret_tmp"' EXIT
    printf '%s' "$secret_value" >"$secret_tmp"
    unset secret_value
    chgrp "$SECRET_GID" -- "$secret_tmp"
    chmod 640 -- "$secret_tmp"
    mv -- "$secret_tmp" "$SECRET_FILE"
    trap - EXIT
    check_secret
    printf 'Phase 3 NGC secret initialized from Docker auth without emitting its value.\n'
    ;;
  check)
    command -v stat >/dev/null 2>&1 || {
      printf 'Required command is unavailable: stat\n' >&2
      exit 127
    }
    if [[ ! $SECRET_GID =~ ^[0-9]+$ ]]; then
      printf 'PHASE3_SECRET_GID must be a numeric group ID.\n' >&2
      exit 2
    fi
    check_secret
    printf 'Phase 3 NGC secret is present with secure ownership and permissions.\n'
    ;;
  *)
    printf 'Usage: %s [check|init-from-docker-auth]\n' "${BASH_SOURCE[0]}" >&2
    exit 2
    ;;
esac

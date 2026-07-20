#!/usr/bin/env bash

# Phase 1 source-only credential gate. Matching content is never printed: a
# failure reports file names so a developer can inspect them locally.

set -euo pipefail

ROOT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
SCAN_ROOT=${SOURCE_SECRET_SCAN_ROOT:-$ROOT_DIR}
RG_BIN=${RG_BIN:-rg}

if ! command -v "$RG_BIN" >/dev/null 2>&1; then
  printf 'Required command is unavailable: %s\n' "$RG_BIN" >&2
  exit 127
fi
if [[ ! -d $SCAN_ROOT ]]; then
  printf 'Source secret scan root is not a directory: %s\n' "$SCAN_ROOT" >&2
  exit 2
fi

HIT_FILE=$(mktemp)
trap 'rm -f "$HIT_FILE"' EXIT

# The scanner itself is excluded because it necessarily contains detector
# expressions. Generated dependencies, caches, evidence, and lockfiles are not
# authored source and would add opaque third-party hashes or host inventory.
RG_ARGS=(
  --files-with-matches
  --hidden
  --ignore-case
  --no-messages
  --glob '!.git/**'
  --glob '!.secrets/**'
  --glob '!.venv/**'
  --glob '!**/node_modules/**'
  --glob '!**/.next/**'
  --glob '!**/__pycache__/**'
  --glob '!**/.pytest_cache/**'
  --glob '!**/.mypy_cache/**'
  --glob '!**/.ruff_cache/**'
  --glob '!artifacts/**'
  --glob '!compatibility/**'
  --glob '!uv.lock'
  --glob '!pnpm-lock.yaml'
  --glob '!scripts/source-secret-scan.sh'
)

KNOWN_CREDENTIAL='(nvapi-|sk-|hf_|gh[pousr]_|github_pat_|xox[baprs]-)[a-z0-9_-]{12,}|AKIA[A-Z0-9]{16}|eyJ[a-zA-Z0-9_-]{10,}\.[a-zA-Z0-9_-]{10,}\.[a-zA-Z0-9_-]{10,}'
PRIVATE_KEY='-----BEGIN ([A-Z0-9 ]+ )?PRIVATE KEY-----'
# Shell/template variables are references, not embedded credentials. Excluding
# their sigils prevents safe runtime secret expansion from tripping this
# high-confidence source scanner.
URL_CREDENTIAL='[a-z][a-z0-9+.-]*://[^$:/{}[:space:]]+:[^$@/{}[:space:]]{8,}@'
ASSIGNED_CREDENTIAL="(api[_-]?key|access[_-]?token|auth[_-]?token|client[_-]?secret|password|passwd)[[:space:]]*[=:][[:space:]]*[\"'][^\"'[:space:]]{12,}[\"']"

set +e
(
  cd "$SCAN_ROOT"
  "$RG_BIN" "${RG_ARGS[@]}" \
    --regexp "$KNOWN_CREDENTIAL" \
    --regexp "$PRIVATE_KEY" \
    --regexp "$URL_CREDENTIAL" \
    --regexp "$ASSIGNED_CREDENTIAL" .
) >"$HIT_FILE"
SCAN_STATUS=$?
set -e

if ((SCAN_STATUS == 0)); then
  printf 'Potential source credential detected in:\n' >&2
  LC_ALL=C sort -u "$HIT_FILE" >&2
  printf 'Matched values were intentionally suppressed.\n' >&2
  exit 1
fi
if ((SCAN_STATUS != 1)); then
  printf 'Source secret scan failed unexpectedly (rg status %s).\n' "$SCAN_STATUS" >&2
  exit "$SCAN_STATUS"
fi

printf 'Source secret scan passed.\n'

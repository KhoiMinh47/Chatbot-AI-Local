#!/usr/bin/env bash
set -euo pipefail

# One-shot verification for history pipeline cutover.
# Usage:
#   ./scripts/run_history_pipeline_one_shot.sh [USER_ID] [SESSION_ID] [QUERY_FLOW]
# Example:
#   ./scripts/run_history_pipeline_one_shot.sh ntcai 12 fast

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PY="${ROOT_DIR}/../.venv/bin/python"

if [[ ! -x "$PY" ]]; then
  echo "ERROR: Python executable not found at $PY"
  exit 1
fi

USER_ID="${1:-smoke}"
SESSION_ID="${2:-999999}"
QUERY_FLOW="${3:-fast}"

cd "$ROOT_DIR"

echo "[1/4] Running migration..."
"$PY" -m alembic upgrade head

echo "[2/4] Running semantic backfill..."
"$PY" scripts/backfill_semantic_history.py

echo "[3/4] Running regression scenario..."
"$PY" scripts/history_pipeline_regression.py

echo "[4/4] Running smoke context preview..."
"$PY" scripts/smoke_history_context.py \
  --user-id "$USER_ID" \
  --session-id "$SESSION_ID" \
  --query "kiểm tra lịch sử hội thoại" \
  --query-flow "$QUERY_FLOW"

echo "DONE: history pipeline one-shot checks completed"

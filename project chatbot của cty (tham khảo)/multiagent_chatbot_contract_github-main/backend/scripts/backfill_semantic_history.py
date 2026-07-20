import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

# Ensure backend/ is importable when executed directly.
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
BACKEND_DIR = os.path.dirname(CURRENT_DIR)
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

ROOT_DIR = Path(BACKEND_DIR).parent
ROOT_ENV_ALL = ROOT_DIR / ".env.all"
ROOT_ENV = ROOT_DIR / ".env"
BACKEND_ENV = Path(BACKEND_DIR) / ".env"


def _load_env_file(file_path: Path, override: bool) -> None:
    if not file_path.exists():
        return
    for line in file_path.read_text(encoding="utf-8").splitlines():
        text = line.strip()
        if not text or text.startswith("#") or "=" not in text:
            continue
        key, value = text.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if not key:
            continue
        if not override and key in os.environ:
            continue
        os.environ[key] = value


_load_env_file(ROOT_ENV_ALL, override=False)
_load_env_file(ROOT_ENV, override=True)
_load_env_file(BACKEND_ENV, override=True)

from service.history_pipeline_service import backfill_semantic_history


async def _run(session_id: int | None, default_query_flow: str) -> int:
    result = await backfill_semantic_history(
        session_id=session_id,
        default_query_flow=default_query_flow,
    )
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result.get("status") == "ok" else 1


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Backfill semantic_history from existing history_mess records"
    )
    parser.add_argument(
        "--session-id",
        type=int,
        default=None,
        help="Only backfill one session id (default: all sessions)",
    )
    parser.add_argument(
        "--default-query-flow",
        type=str,
        default="fast",
        choices=["fast", "web_search"],
        help="Task type used when old records have no flow metadata",
    )

    args = parser.parse_args()
    return asyncio.run(_run(args.session_id, args.default_query_flow))


if __name__ == "__main__":
    raise SystemExit(main())

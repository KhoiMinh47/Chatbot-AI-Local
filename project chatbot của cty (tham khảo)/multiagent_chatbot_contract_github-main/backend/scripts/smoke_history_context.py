import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
BACKEND_DIR = os.path.dirname(CURRENT_DIR)
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

ROOT_DIR = Path(BACKEND_DIR).parent


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


_load_env_file(ROOT_DIR / ".env.all", override=False)
_load_env_file(ROOT_DIR / ".env", override=True)
_load_env_file(Path(BACKEND_DIR) / ".env", override=True)

from service.history_pipeline_service import build_history_context_with_debug


async def _run(user_id: str, session_id: int, query: str, query_flow: str) -> int:
    context, debug = await build_history_context_with_debug(
        user_id=user_id,
        session_id=session_id,
        user_query=query,
        query_flow=query_flow,
        max_chars=30000,
    )
    payload = {
        "debug": debug,
        "preview": context[:1200],
        "preview_chars": min(1200, len(context)),
        "total_chars": len(context),
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Smoke test history context builder")
    parser.add_argument("--user-id", required=True)
    parser.add_argument("--session-id", required=True, type=int)
    parser.add_argument("--query", default="tóm tắt lại các ý quan trọng")
    parser.add_argument("--query-flow", default="fast", choices=["fast", "web_search"])
    args = parser.parse_args()
    return asyncio.run(_run(args.user_id, args.session_id, args.query, args.query_flow))


if __name__ == "__main__":
    raise SystemExit(main())

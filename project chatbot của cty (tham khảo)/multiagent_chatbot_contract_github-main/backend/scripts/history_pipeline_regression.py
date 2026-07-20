import asyncio
import json
import os
import sys
from pathlib import Path

from sqlalchemy import delete, select

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

from database.setup_postgres import SessionLocal
from database.table.table_postgres import session, history_mess, semantic_history
from service.history_pipeline_service import ingest_semantic_history_turn, build_history_context_with_debug


async def _setup_fixture(user_id: str, session_name: str) -> int:
    async with SessionLocal() as db:
        s = session(user_id=user_id, name=session_name, paths=[], is_pinned=False)
        db.add(s)
        await db.flush()

        m1 = history_mess(user_id=user_id, session_id=s.id, role="user", mess="Thêm điều khoản phạt chậm thanh toán 5%")
        m2 = history_mess(user_id=user_id, session_id=s.id, role="chatbot", mess="Đã thêm điều khoản phạt 5%")
        m3 = history_mess(user_id=user_id, session_id=s.id, role="user", mess="Bỏ điều khoản phạt chậm thanh toán đi")
        m4 = history_mess(user_id=user_id, session_id=s.id, role="chatbot", mess="Đã bỏ điều khoản phạt")
        db.add_all([m1, m2, m3, m4])
        await db.flush()

        await db.commit()

        # Ingest semantic theo turn user để mô phỏng runtime thực tế.
        await ingest_semantic_history_turn(
            user_id=user_id,
            session_id=s.id,
            turn_id=int(m1.id),
            query_flow="fast",
            user_text=m1.mess,
            assistant_text=m2.mess,
        )
        await ingest_semantic_history_turn(
            user_id=user_id,
            session_id=s.id,
            turn_id=int(m3.id),
            query_flow="fast",
            user_text=m3.mess,
            assistant_text=m4.mess,
        )

        return int(s.id)


async def _cleanup_fixture(user_id: str, session_id: int) -> None:
    async with SessionLocal() as db:
        await db.execute(delete(semantic_history).where(semantic_history.user_id == user_id, semantic_history.session_id == session_id))
        await db.execute(delete(history_mess).where(history_mess.user_id == user_id, history_mess.session_id == session_id))
        await db.execute(delete(session).where(session.user_id == user_id, session.id == session_id))
        await db.commit()


async def _run() -> int:
    user_id = "history_regression_user"
    session_name = "__history_regression_temp__"

    sid = await _setup_fixture(user_id, session_name)
    try:
        context, debug = await build_history_context_with_debug(
            user_id=user_id,
            session_id=sid,
            user_query="Hợp đồng này có phạt chậm thanh toán không?",
            query_flow="fast",
            max_chars=30000,
        )

        has_latest_negation = "Bỏ điều khoản phạt chậm thanh toán đi" in context or "Đã bỏ điều khoản phạt" in context
        has_old_fact = "Thêm điều khoản phạt chậm thanh toán 5%" in context

        result = {
            "session_id": sid,
            "debug": debug,
            "assertions": {
                "contains_latest_negation_signal": has_latest_negation,
                "contains_older_fact_signal": has_old_fact,
                "has_semantic_section": "Tóm tắt hội thoại liên quan:" in context,
                "has_short_term_section": "Tin nhắn gần nhất trong session:" in context,
            },
            "preview": context[:1200],
        }

        print(json.dumps(result, ensure_ascii=False, indent=2))

        if not has_latest_negation:
            return 1
        return 0
    finally:
        await _cleanup_fixture(user_id, sid)


def main() -> int:
    return asyncio.run(_run())


if __name__ == "__main__":
    raise SystemExit(main())

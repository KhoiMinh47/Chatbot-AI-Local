import logging
import math
import os
import re

import httpx
from sqlalchemy import select, desc

from database.setup_postgres import SessionLocal
from database.table.table_postgres import semantic_history, history_mess

logger = logging.getLogger(__name__)

try:
    from prometheus_client import Counter, Histogram
except Exception:  # pragma: no cover - fallback when prometheus_client is missing
    Counter = None
    Histogram = None

BGE_BASE_URL = os.getenv("BGE_BASE_URL", "").strip()
BGE_EMBED_PATH = os.getenv("BGE_EMBED_PATH", "").strip()
BGE_TIMEOUT = 8.0

HISTORY_SHORT_WINDOW_TURNS = int(os.getenv("HISTORY_SHORT_WINDOW_TURNS", "2"))
HISTORY_SEMANTIC_TOPK = int(os.getenv("HISTORY_SEMANTIC_TOPK", "6"))
HISTORY_SEMANTIC_SCAN_LIMIT = int(os.getenv("HISTORY_SEMANTIC_SCAN_LIMIT", "120"))

STOPWORDS = {
    "bạn", "ơi", "giúp", "mình", "em", "anh", "chị", "tôi", "vui", "lòng", "nhé",
    "ạ", "thì", "là", "và", "hoặc", "cho", "xin", "được", "không", "có", "này", "kia",
}


if Counter is not None:
    HISTORY_INGEST_CALLS_TOTAL = Counter(
        "history_pipeline_ingest_calls_total",
        "Total semantic history ingest calls",
        ["task_type"],
    )
    HISTORY_INGEST_INSERTED_TOTAL = Counter(
        "history_pipeline_ingest_inserted_rows_total",
        "Total inserted semantic history rows",
        ["task_type"],
    )
    HISTORY_CONTEXT_BUILD_TOTAL = Counter(
        "history_pipeline_context_build_total",
        "Total history context build calls",
        ["task_type", "status"],
    )
    HISTORY_CONTEXT_FALLBACK_TOTAL = Counter(
        "history_pipeline_context_semantic_fallback_total",
        "Total times semantic retrieval fell back to session-wide scope",
        ["task_type"],
    )
    HISTORY_CONTEXT_CHARS = Histogram(
        "history_pipeline_context_chars",
        "Built history context length (characters)",
        buckets=(0, 200, 500, 1000, 2000, 4000, 8000, 16000, 32000),
    )
else:
    HISTORY_INGEST_CALLS_TOTAL = None
    HISTORY_INGEST_INSERTED_TOTAL = None
    HISTORY_CONTEXT_BUILD_TOTAL = None
    HISTORY_CONTEXT_FALLBACK_TOTAL = None
    HISTORY_CONTEXT_CHARS = None


def _entity_bucket_key(keys: list[str] | None, turn_id: int, row_id: int) -> str:
    if not keys:
        return f"turn:{turn_id}:{row_id}"
    normalized = sorted({str(k).strip().lower() for k in keys if str(k).strip()})
    if not normalized:
        return f"turn:{turn_id}:{row_id}"
    return "|".join(normalized[:3])


def _safe_task_type(query_flow: str | None) -> str:
    return "web_search" if (query_flow or "").strip() == "web_search" else "rag_fast"


def _is_negation(text: str) -> bool:
    lower = text.lower()
    patterns = ["bỏ", "hủy", "không cần", "remove", "xóa", "không áp dụng"]
    return any(p in lower for p in patterns)


def _extract_time_scope(text: str) -> str | None:
    m = re.search(r"(hôm nay|mới nhất|quý\s*\d+|tháng\s*\d+|năm\s*\d{4}|\d{1,2}[/-]\d{1,2}[/-]\d{2,4})", text.lower())
    return m.group(1) if m else None


def _extract_entity_keys(text: str) -> list[str]:
    tokens = re.findall(r"[\w%]+", text.lower(), flags=re.UNICODE)
    out = []
    seen = set()
    for t in tokens:
        if t in STOPWORDS or len(t) <= 2:
            continue
        if re.match(r"^\d+$", t):
            continue
        if t not in seen:
            seen.add(t)
            out.append(t)
        if len(out) >= 10:
            break
    return out


def _normalize_summary(text: str) -> str:
    cleaned = re.sub(r"\s+", " ", (text or "").strip())
    if not cleaned:
        return ""

    # Ưu tiên tóm tắt theo dạng mệnh đề rõ chủ đích.
    keys = _extract_entity_keys(cleaned)
    if keys:
        return f"Yeu cau/chinh sua lien quan: {' '.join(keys)}. Noi dung: {cleaned[:600]}"
    return cleaned[:700]


async def _get_embedding(text: str) -> list[float] | None:
    if not text or not BGE_BASE_URL or not BGE_EMBED_PATH:
        return None

    url = f"{BGE_BASE_URL}{BGE_EMBED_PATH}"
    payload = {"texts": [text]}

    try:
        async with httpx.AsyncClient(timeout=BGE_TIMEOUT) as client:
            resp = await client.post(url, json=payload)
            resp.raise_for_status()
            data = resp.json()
        result = data.get("result") or []
        if not result:
            return None
        return result[0]
    except Exception as e:
        logger.warning("[HISTORY_PIPELINE] Embedding failed: %s", e)
        return None


def _cosine_similarity(a: list[float] | None, b: list[float] | None) -> float:
    if not a or not b or len(a) != len(b):
        return -1.0
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    if norm_a == 0 or norm_b == 0:
        return -1.0
    return dot / (norm_a * norm_b)


async def ingest_semantic_history_turn(
    *,
    user_id: str,
    session_id: int,
    turn_id: int,
    query_flow: str | None,
    user_text: str,
    assistant_text: str,
) -> int:
    """Ingest history turn thành semantic records để retrieval ở lượt sau."""
    if not user_id or session_id <= 0 or turn_id <= 0:
        return 0

    task_type = _safe_task_type(query_flow)
    if HISTORY_INGEST_CALLS_TOTAL is not None:
        HISTORY_INGEST_CALLS_TOTAL.labels(task_type=task_type).inc()

    records = [
        ("user", user_text or ""),
        ("chatbot", assistant_text or ""),
    ]
    inserted = 0

    try:
        async with SessionLocal() as db:
            for role, raw_text in records:
                raw_text = (raw_text or "").strip()
                if not raw_text:
                    continue

                existing = await db.execute(
                    select(semantic_history.id)
                    .where(
                        semantic_history.user_id == user_id,
                        semantic_history.session_id == session_id,
                        semantic_history.turn_id == turn_id,
                        semantic_history.role == role,
                        semantic_history.task_type == task_type,
                    )
                    .limit(1)
                )
                if existing.scalar_one_or_none() is not None:
                    continue

                summary = _normalize_summary(raw_text)
                emb = await _get_embedding(summary)

                db.add(
                    semantic_history(
                        user_id=user_id,
                        session_id=session_id,
                        turn_id=turn_id,
                        role=role,
                        task_type=task_type,
                        raw_text=raw_text[:4000],
                        summary_text=summary,
                        entity_keys=_extract_entity_keys(raw_text),
                        time_scope=_extract_time_scope(raw_text),
                        is_negation=_is_negation(raw_text),
                        supersedes_turn_id=None,
                        embedding=emb,
                    )
                )
                inserted += 1

            await db.commit()
            if HISTORY_INGEST_INSERTED_TOTAL is not None and inserted > 0:
                HISTORY_INGEST_INSERTED_TOTAL.labels(task_type=task_type).inc(inserted)
            return inserted
    except Exception as e:
        logger.exception("[HISTORY_PIPELINE] ingest_semantic_history_turn failed: %s", e)
        return 0


async def build_history_context(
    *,
    user_id: str,
    session_id: int,
    user_query: str,
    query_flow: str | None,
    max_chars: int,
) -> str:
    """Build unified history context = semantic summary + short-term raw window."""
    text, _debug = await build_history_context_with_debug(
        user_id=user_id,
        session_id=session_id,
        user_query=user_query,
        query_flow=query_flow,
        max_chars=max_chars,
    )
    return text


async def build_history_context_with_debug(
    *,
    user_id: str,
    session_id: int,
    user_query: str,
    query_flow: str | None,
    max_chars: int,
) -> tuple[str, dict]:
    """Build history context và trả thêm debug metrics cho observability."""
    if not user_id or session_id <= 0:
        return "", {
            "short_window_count": 0,
            "semantic_pool_count": 0,
            "semantic_ranked_count": 0,
            "semantic_selected_count": 0,
            "used_fallback_semantic_scope": False,
            "query_embedding_available": False,
            "context_chars": 0,
        }

    task_type = _safe_task_type(query_flow)

    short_rows = []
    semantic_rows = []
    used_fallback_semantic_scope = False

    try:
        async with SessionLocal() as db:
            # 1) Short-term: lấy một cửa sổ lượt chat gần nhất từ raw history.
            raw_limit = max(4, HISTORY_SHORT_WINDOW_TURNS * 2)
            raw_data = await db.execute(
                select(history_mess)
                .where(
                    history_mess.user_id == user_id,
                    history_mess.session_id == session_id,
                )
                .order_by(desc(history_mess.id))
                .limit(raw_limit)
            )
            short_rows = list(reversed(raw_data.scalars().all()))

            # 2) Semantic pool cho session/task hiện tại.
            sem_data = await db.execute(
                select(semantic_history)
                .where(
                    semantic_history.user_id == user_id,
                    semantic_history.session_id == session_id,
                    semantic_history.task_type == task_type,
                )
                .order_by(desc(semantic_history.turn_id), desc(semantic_history.id))
                .limit(HISTORY_SEMANTIC_SCAN_LIMIT)
            )
            semantic_rows = sem_data.scalars().all()

            # Fallback: nếu chưa có semantic record theo task hiện tại thì dùng semantic của session.
            if not semantic_rows:
                used_fallback_semantic_scope = True
                sem_data_fallback = await db.execute(
                    select(semantic_history)
                    .where(
                        semantic_history.user_id == user_id,
                        semantic_history.session_id == session_id,
                    )
                    .order_by(desc(semantic_history.turn_id), desc(semantic_history.id))
                    .limit(HISTORY_SEMANTIC_SCAN_LIMIT)
                )
                semantic_rows = sem_data_fallback.scalars().all()
    except Exception as e:
        logger.warning("[HISTORY_PIPELINE] build_history_context query failed: %s", e)
        if HISTORY_CONTEXT_BUILD_TOTAL is not None:
            HISTORY_CONTEXT_BUILD_TOTAL.labels(task_type=task_type, status="query_error").inc()
        return "", {
            "short_window_count": 0,
            "semantic_pool_count": 0,
            "semantic_ranked_count": 0,
            "semantic_selected_count": 0,
            "used_fallback_semantic_scope": used_fallback_semantic_scope,
            "query_embedding_available": False,
            "context_chars": 0,
        }

    # 3) Semantic ranking theo query embedding.
    ranked_semantic = []
    q_emb = await _get_embedding((user_query or "").strip())
    for row in semantic_rows:
        score = _cosine_similarity(q_emb, row.embedding)
        ranked_semantic.append((score, row))

    ranked_semantic.sort(key=lambda x: (x[0], x[1].turn_id, x[1].id), reverse=True)

    # 4) Conflict resolve theo entity bucket + recency.
    # Bucket trùng entity chỉ giữ record mới nhất, ưu tiên negation khi cùng turn.
    grouped: dict[str, tuple[float, semantic_history]] = {}
    for score, row in ranked_semantic:
        bucket = _entity_bucket_key(row.entity_keys or [], int(row.turn_id or 0), int(row.id or 0))
        current = grouped.get(bucket)
        if current is None:
            grouped[bucket] = (score, row)
            continue

        _, prev_row = current
        prev_key = (int(prev_row.turn_id or 0), int(prev_row.id or 0), 1 if prev_row.is_negation else 0)
        next_key = (int(row.turn_id or 0), int(row.id or 0), 1 if row.is_negation else 0)
        if next_key > prev_key:
            grouped[bucket] = (max(score, current[0]), row)

    selected_pairs = sorted(
        grouped.values(),
        key=lambda x: (x[0], int(x[1].turn_id or 0), int(x[1].id or 0)),
        reverse=True,
    )[:HISTORY_SEMANTIC_TOPK]

    selected = [row for _, row in selected_pairs]

    selected.sort(key=lambda r: (r.turn_id, r.id))

    semantic_parts = []
    for item in selected:
        role = "Người dùng" if item.role == "user" else "Trợ lý"
        note = " [NEGATION]" if item.is_negation else ""
        semantic_parts.append(f"- Turn {item.turn_id} | {role}{note}: {item.summary_text}")

    short_parts = []
    for row in short_rows:
        role = "Người dùng" if row.role == "user" else "Trợ lý"
        short_parts.append(f"- {role}: {row.mess}")

    chunks = []
    if semantic_parts:
        chunks.append("Tóm tắt hội thoại liên quan:\n" + "\n".join(semantic_parts))
    if short_parts:
        chunks.append("Tin nhắn gần nhất trong session:\n" + "\n".join(short_parts))

    text = "\n\n".join(chunks).strip()
    if len(text) > max_chars:
        text = text[:max_chars]

    if HISTORY_CONTEXT_BUILD_TOTAL is not None:
        HISTORY_CONTEXT_BUILD_TOTAL.labels(task_type=task_type, status="ok").inc()
    if HISTORY_CONTEXT_FALLBACK_TOTAL is not None and used_fallback_semantic_scope:
        HISTORY_CONTEXT_FALLBACK_TOTAL.labels(task_type=task_type).inc()
    if HISTORY_CONTEXT_CHARS is not None:
        HISTORY_CONTEXT_CHARS.observe(len(text))

    debug = {
        "short_window_count": len(short_rows),
        "semantic_pool_count": len(semantic_rows),
        "semantic_ranked_count": len(ranked_semantic),
        "semantic_selected_count": len(selected),
        "used_fallback_semantic_scope": used_fallback_semantic_scope,
        "query_embedding_available": bool(q_emb),
        "context_chars": len(text),
    }
    return text, debug


async def backfill_semantic_history(
    *,
    session_id: int | None = None,
    default_query_flow: str = "fast",
) -> dict:
    """
    Backfill semantic history từ bảng raw history hiện có.
    Idempotent: bỏ qua record đã tồn tại theo (user, session, turn, role, task).
    """
    total_rows = 0
    ingested_rows = 0

    try:
        async with SessionLocal() as db:
            query = select(history_mess)
            if session_id and session_id > 0:
                query = query.where(history_mess.session_id == session_id)

            query = query.order_by(history_mess.session_id.asc(), history_mess.id.asc())
            rows = (await db.execute(query)).scalars().all()

        if not rows:
            return {
                "status": "ok",
                "total_rows": 0,
                "ingested_rows": 0,
            }

        # Quy ước turn: ưu tiên id của user message gần nhất trong cùng session.
        last_user_turn_by_session: dict[int, int] = {}

        for row in rows:
            total_rows += 1
            sid = int(row.session_id or 0)
            if sid <= 0:
                continue

            if row.role == "user":
                turn_id = int(row.id)
                last_user_turn_by_session[sid] = turn_id
            else:
                turn_id = int(last_user_turn_by_session.get(sid) or row.id)

            inserted = await ingest_semantic_history_turn(
                user_id=str(row.user_id or ""),
                session_id=sid,
                turn_id=turn_id,
                query_flow=default_query_flow,
                user_text=(row.mess or "") if row.role == "user" else "",
                assistant_text=(row.mess or "") if row.role != "user" else "",
            )
            ingested_rows += int(inserted or 0)

        return {
            "status": "ok",
            "total_rows": total_rows,
            "ingested_rows": ingested_rows,
        }
    except Exception as e:
        logger.exception("[HISTORY_PIPELINE] backfill_semantic_history failed: %s", e)
        return {
            "status": "error",
            "message": str(e),
            "total_rows": total_rows,
            "ingested_rows": ingested_rows,
        }

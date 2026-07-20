import json
import logging
import os
import time
import urllib.parse
import uuid
from datetime import datetime, timezone

from fastapi import HTTPException, UploadFile
from fastapi.responses import FileResponse
from qdrant_client.http import models
from sqlalchemy import select, delete, desc, func
from sqlalchemy.orm.attributes import flag_modified

from agent_chatbot.graph.rag_graph import app_upload_workflow
from database.setup_postgres import get_db, SessionLocal
from database.setup_qdrant import qdrant_service, COLLECTION_NAME
from database.setup_redis import (
    redis_service,
    CACHE_TTL_SESSIONS,
    CACHE_TTL_HISTORY,
    CACHE_KEY_SESSIONS,
    CACHE_KEY_HISTORY_PREFIX,
)
from database.setup_minio import minio_service, MINIO_CONTRACT_BUCKET
from database.table.table_postgres import (
    session, history_mess, document_fulltext, contract, semantic_history,
)

from request.rag_chat_request import rag_chat_request
from agent_chatbot.graph.rag_graph import (
    app_rag_contract_fast_workflow,
    app_rag_web_search_workflow,
)
from service.history_pipeline_service import ingest_semantic_history_turn

logger = logging.getLogger(__name__)

# --- Hằng số ---
BACKEND_URL = os.getenv("BACKEND_URL")

# Số lượng points tối đa khi scroll Qdrant
QDRANT_SCROLL_LIMIT = 1000
WEB_SEARCH_RATE_LIMIT_PER_MIN = int(os.getenv("WEB_SEARCH_RATE_LIMIT_PER_MIN", "20"))
WEB_SEARCH_GLOBAL_RATE_LIMIT_PER_MIN = int(os.getenv("WEB_SEARCH_GLOBAL_RATE_LIMIT_PER_MIN", "300"))
SEARCH_LOG_ENABLED = os.getenv("SEARCH_LOG_ENABLED", "false").strip().lower() == "true"

# Thư mục lưu file contract local
FOLDER_PATH_CONTRACT = os.getenv("FOLDER_PATH_CONTRACT", "database/storage/contract")


def _utc_now():
    return datetime.now(timezone.utc)


async def _invalidate_sessions_cache(user_id: str = None):
    """Xóa cache sessions list. Nếu có user_id thì xóa đúng key, không thì xóa tất cả."""
    try:
        if user_id:
            await redis_service.client.delete(f"{CACHE_KEY_SESSIONS}:{user_id}")
        else:
            async for key in redis_service.client.scan_iter(match=f"{CACHE_KEY_SESSIONS}:*"):
                await redis_service.client.delete(key)
    except Exception as e:
        logger.warning("[CACHE] Redis invalidate sessions failed: %s", e)


async def _invalidate_history_cache(session_id: int = None, user_id: str = None):
    """
    Xóa cache history.

    - Nếu có session_id + user_id: xóa đúng 1 key.
    - Nếu chỉ có session_id: scan theo session.
    - Nếu không truyền gì: scan toàn bộ history cache.
    """
    try:
        if session_id and user_id:
            await redis_service.client.delete(
                f"{CACHE_KEY_HISTORY_PREFIX}:{session_id}:{user_id}"
            )
            return

        if session_id:
            pattern = f"{CACHE_KEY_HISTORY_PREFIX}:{session_id}:*"
        else:
            pattern = f"{CACHE_KEY_HISTORY_PREFIX}:*"

        async for key in redis_service.client.scan_iter(match=pattern):
            await redis_service.client.delete(key)
    except Exception as e:
        logger.warning("[CACHE] Redis invalidate history failed: %s", e)


async def _enforce_web_search_rate_limit(user_id: str) -> None:
    """Giới hạn số lượt web_search theo user + global trong 1 phút."""
    if not user_id:
        user_id = "anonymous"
    key = f"rate:web_search:{user_id}"
    global_key = "rate:web_search:global"
    try:
        global_current = await redis_service.client.incr(global_key)
        if global_current == 1:
            await redis_service.client.expire(global_key, 60)
        if global_current > WEB_SEARCH_GLOBAL_RATE_LIMIT_PER_MIN:
            raise HTTPException(
                status_code=429,
                detail=(
                    "Hệ thống đang quá tải web search. "
                    "Vui lòng thử lại sau khoảng 1 phút."
                ),
            )

        current = await redis_service.client.incr(key)
        if current == 1:
            await redis_service.client.expire(key, 60)
        if current > WEB_SEARCH_RATE_LIMIT_PER_MIN:
            raise HTTPException(
                status_code=429,
                detail=f"Bạn đã vượt quá giới hạn {WEB_SEARCH_RATE_LIMIT_PER_MIN} lượt web search/phút. Vui lòng thử lại sau.",
            )
    except HTTPException:
        raise
    except Exception as e:
        logger.warning("[RATE_LIMIT] Không thể kiểm tra limit web_search: %s", e)


async def upload_service(files: list[UploadFile], session_id: int = 0, user_id: str = None):
    """
    Xử lý upload danh sách file tài liệu.

    Quy trình cho mỗi file:
        1. Đọc nội dung file, chuẩn hóa tên, lưu file.
        2. Chạy LangGraph workflow (docling → chunking → embedding).
        3. Lưu fulltext vào PostgreSQL (document_fulltext).
        4. Xóa chunks cũ + lưu chunks mới vào Qdrant.

    Input:
        files (list[UploadFile]): Danh sách file tài liệu.
        session_id (int): ID session liên kết (optional).
        user_id (str): ID người dùng thực hiện (optional).

    Output:
        dict: Kết quả tổng hợp.
    """

    start_time = time.perf_counter()
    processed_count = 0

    logger.info("=" * 60)
    logger.info("[SERVICE] upload_service — Nhận %d file cho session %d", len(files), session_id)
    logger.info("=" * 60)

    # Thu thập các filenames thành công để lưu vào session
    successfully_processed_files = []

    for idx, file in enumerate(files):
        try:
            logger.info(
                "[FILE %d/%d] Bắt đầu xử lý: %s",
                idx + 1, len(files), file.filename,
            )

            # --- Bước 1: Đọc file + chuẩn hóa tên ---
            file_content = await file.read()
            normalized_filename = (
                str(file.filename).lower()
                .replace(" ", "_").replace("-", "_")
            )

            logger.info(
                "[FILE %d/%d] Tên: %s | Size: %d bytes",
                idx + 1, len(files), normalized_filename, len(file_content),
            )

            # --- Bước 1.5: Backup file gốc lên MinIO (raw-files) ---
            from database.setup_minio import minio_service, MINIO_RAW_BUCKET
            import io

            # Xóa file cũ trên MinIO nếu trùng tên (Deduplication)
            try:
                minio_service.client.stat_object(MINIO_RAW_BUCKET, normalized_filename)
                minio_service.client.remove_object(MINIO_RAW_BUCKET, normalized_filename)
                logger.info("[MINIO] Đã xóa file cũ trùng lặp: %s", normalized_filename)
            except Exception:
                pass # Bỏ qua nếu file chưa tồn tại

            # Đẩy file mới lên MinIO
            minio_service.client.put_object(
                bucket_name=MINIO_RAW_BUCKET,
                object_name=normalized_filename,
                data=io.BytesIO(file_content),
                length=len(file_content),
                content_type=file.content_type
            )
            logger.info("[MINIO] Đã upload thành công lên bucket '%s': %s", MINIO_RAW_BUCKET, normalized_filename)

            # --- Bước 2: Chạy upload workflow ---
            file_input = {
                "files": (file.filename, file_content, file.content_type)
            }

            state = {
                "input_file": file_input,
                "status": "",
                "document_path": normalized_filename,
                "docling_markdown": "",
                "document_id": 0,
                "chunks": [],
            }

            result = await app_upload_workflow.ainvoke(state)

            markdown = result.get("docling_markdown", "")
            chunks = result.get("chunks", [])

            logger.info(
                "[FILE %d/%d] Workflow xong: %d ký tự, %d chunks",
                idx + 1, len(files), len(markdown), len(chunks),
            )

            # --- Bước 3: Lưu fulltext vào PostgreSQL ---
            doc_id = await _save_document_fulltext(
                normalized_filename, markdown,
            )
            logger.info(
                "[FILE %d/%d] PostgreSQL document_id=%d",
                idx + 1, len(files), doc_id,
            )

            # --- Bước 4: Xóa chunks cũ + lưu chunks mới vào Qdrant ---
            await _delete_old_qdrant_chunks(normalized_filename)
            await _save_chunks_to_qdrant(doc_id, normalized_filename, chunks)

            logger.info(
                "[FILE %d/%d] ✓ Hoàn thành: %s | doc_id=%d | %d chunks",
                idx + 1, len(files), file.filename, doc_id, len(chunks),
            )
            successfully_processed_files.append(normalized_filename)
            processed_count += 1

        except Exception as e:
            logger.error(
                "[FILE %d/%d] ✗ Lỗi file %s: %s",
                idx + 1, len(files), file.filename, str(e),
            )
            continue

    execution_time = time.perf_counter() - start_time
    # --- Cập nhật danh sách file vào Session ---
    if processed_count > 0:
        async with SessionLocal() as db:
            # 1. Lấy hoặc tạo session
            session_obj = None
            if session_id > 0:
                query = select(session).where(session.id == session_id)
                if user_id is not None:
                    query = query.where(session.user_id == str(user_id))
                res = await db.execute(query)
                session_obj = res.scalars().first()

            if not session_obj:
                # Tạo session mới nếu không tìm thấy hoặc chưa có id
                session_name = successfully_processed_files[0] if successfully_processed_files else "Upload"
                session_obj = session(
                    user_id=str(user_id) if user_id else None,
                    name=session_name,
                    updated_at=_utc_now(),
                )
                db.add(session_obj)
                await db.commit()
                await db.refresh(session_obj)
                session_id = session_obj.id
                logger.info("[SESSION] Đã tạo session mới: %d", session_id)

            # 2. Cập nhật paths trong session
            current_paths = list(session_obj.paths) if session_obj.paths else []
            for fname in successfully_processed_files:
                if fname not in current_paths:
                    current_paths.append(fname)

            session_obj.paths = current_paths
            session_obj.updated_at = _utc_now()
            flag_modified(session_obj, "paths")
            await db.commit()
            logger.info("[SESSION] Đã cập nhật %d files vào session %d", len(successfully_processed_files), session_id)

        # 3. Invalidate cache ngay sau khi session.paths thay đổi bởi upload
        try:
            cache_user_id = str(user_id) if user_id is not None else None
            await _invalidate_sessions_cache(cache_user_id)
            await _invalidate_history_cache(session_id=session_id, user_id=cache_user_id)
            logger.debug("[CACHE] Invalidated after upload for session=%s user=%s", session_id, cache_user_id)
        except Exception as e:
            logger.warning("[CACHE] Upload invalidate failed: %s", e)

    logger.info("=" * 60)
    logger.info(
        "[SERVICE] Upload %d/%d file thành công trong %.2f giây",
        processed_count, len(files), execution_time,
    )
    logger.info("=" * 60)

    return {
        "status": "service upload complete",
        "processed_files": processed_count,
        "total_files": len(files),
        "session_id": session_id
    }


# =============================================================================
# SAVE DATABASE HELPERS
# =============================================================================


async def _save_document_fulltext(file_path, content):
    """
    Lưu hoặc cập nhật fulltext vào PostgreSQL (upsert by file_path).

    Input:
        file_path (str): Tên file chuẩn hóa đóng vai trò như đường dẫn.
        content (str): Toàn bộ markdown.

    Output:
        int: ID record trong document_fulltext.
    """

    async with SessionLocal() as db:
        # Tìm record cũ theo file_path
        query = select(document_fulltext).where(
            document_fulltext.file_path == file_path
        )
        result = await db.execute(query)
        existing = result.scalars().first()

        if existing:
            # Update content
            existing.content = content
            existing.file_path = file_path
            await db.commit()
            await db.refresh(existing)

            logger.info("[DB] Updated document_fulltext id=%d", existing.id)
            return existing.id

        # Insert mới
        new_doc = document_fulltext(
            file_path=file_path,
            content=content,
        )
        db.add(new_doc)
        await db.commit()
        await db.refresh(new_doc)

        logger.info("[DB] Inserted document_fulltext id=%d", new_doc.id)
        return new_doc.id


async def _delete_old_qdrant_chunks(file_path):
    """
    Xóa chunks cũ trong Qdrant theo file path.

    Input:
        file_path (str): Đường dẫn file (dùng làm filter).
    """

    await qdrant_service.client.delete(
        collection_name=COLLECTION_NAME,
        points_selector=models.FilterSelector(
            filter=models.Filter(
                must=[
                    models.FieldCondition(
                        key="path",
                        match=models.MatchValue(value=file_path),
                    )
                ]
            )
        ),
    )

    logger.info("[QDRANT] Đã xóa chunks cũ cho path=%s", file_path)


async def _save_chunks_to_qdrant(document_id, file_path, chunks):
    """
    Lưu chunks + embedding vào Qdrant.

    Mỗi chunk tạo 1 point với:
        - id: UUID random
        - vector: {"dense_content": embedding}
        - payload: metadata (document_id, path, chunk_index, heading, ...)

    Input:
        document_id (int): ID record PostgreSQL document_fulltext.
        file_path (str): Đường dẫn file.
        chunks (list[dict]): Chunks đã có embedding.
    """

    if not chunks:
        logger.warning("[QDRANT] Không có chunks để lưu")
        return

    points = []

    for chunk in chunks:
        embedding = chunk.get("embedding")
        if not embedding:
            logger.warning(
                "[QDRANT] Skip chunk #%d — không có embedding",
                chunk.get("chunk_index", -1),
            )
            continue

        point = models.PointStruct(
            id=str(uuid.uuid4()),
            vector={"dense_content": embedding},
            payload={
                "document_id": document_id,
                "path": file_path,
                "chunk_index": chunk["chunk_index"],
                "heading": chunk.get("heading", ""),
                "heading_group_id": chunk.get("heading_group_id", ""),
                "split_part": chunk.get("split_part", 0),
                "total_parts": chunk.get("total_parts", 1),
                "content": chunk["content"],
            },
        )
        points.append(point)

    # Upsert vào Qdrant
    await qdrant_service.client.upsert(
        collection_name=COLLECTION_NAME,
        points=points,
    )

    logger.info(
        "[QDRANT] Đã lưu %d points cho document_id=%d",
        len(points), document_id,
    )


async def load_file_service():
    """
    Lấy danh sách tên tất cả file đã upload từ Qdrant.

    Dùng scroll để duyệt toàn bộ points trong collection,
    trích xuất danh sách path duy nhất (dùng Set để loại trùng).

    Output:
        dict: {"status": 200, "result": list[str]}
    """

    unique_paths = set()
    offset = None

    # Scroll qua toàn bộ collection để lấy danh sách path
    while True:
        points, offset = await qdrant_service.client.scroll(
            collection_name=COLLECTION_NAME,
            scroll_filter=None,
            limit=QDRANT_SCROLL_LIMIT,
            with_payload=True,
            with_vectors=False,
            offset=offset,
        )

        for point in points:
            path_value = point.payload.get("path")
            if path_value:
                unique_paths.add(path_value)

        if offset is None:
            break

    return {
        "status": 200,
        "result": list(unique_paths),
    }


async def delete_file_service(file_path: str):
    """
    Xóa file tài liệu hoàn toàn khỏi PostgreSQL, Qdrant và MinIO.

    Input:
        file_path (str): Tên file chuẩn hóa đóng vai trò là path định danh.

    Output:
        dict: Kết quả xóa.
    """

    logger.info("[SERVICE] Bắt đầu xóa tài liệu: %s", file_path)

    # 1. Xóa khỏi PostgreSQL
    try:
        async with SessionLocal() as db:
            await db.execute(
                delete(document_fulltext).where(document_fulltext.file_path == file_path)
            )
            await db.commit()
            logger.info("[DB] Đã xóa record document_fulltext cho: %s", file_path)
    except Exception as e:
        logger.error("[DB] Lỗi xóa record PostgreSQL: %s", e)

    # 2. Xóa khỏi Qdrant (Dùng hàm helper đã có)
    try:
        await _delete_old_qdrant_chunks(file_path)
        logger.info("[QDRANT] Đã xóa chunks cho: %s", file_path)
    except Exception as e:
        logger.error("[QDRANT] Lỗi xóa chunks: %s", e)

    # 2.5 Xóa khỏi list paths trong tất cả các session
    try:
        async with SessionLocal() as db:
            # Lấy tất cả session để lọc trong Python (đảm bảo hoạt động với JSON type)
            res = await db.execute(select(session))
            all_sessions = res.scalars().all()
            updated_count = 0
            for s in all_sessions:
                if s.paths and file_path in s.paths:
                    new_paths = [p for p in s.paths if p != file_path]
                    s.paths = new_paths
                    flag_modified(s, "paths")
                    updated_count += 1
            if updated_count > 0:
                await db.commit()
            logger.info("[SESSION] Đã loại bỏ path khỏi %d sessions", updated_count)
    except Exception as e:
        logger.error("[SESSION] Lỗi cập nhật session paths khi xóa file: %s", e)

    # 3. Xóa khỏi MinIO
    from database.setup_minio import minio_service, MINIO_RAW_BUCKET
    try:
        # Kiểm tra tồn tại trước khi xóa
        try:
            minio_service.client.stat_object(MINIO_RAW_BUCKET, file_path)
            minio_service.client.remove_object(MINIO_RAW_BUCKET, file_path)
            logger.info("[MINIO] Đã xóa file trên bucket '%s': %s", MINIO_RAW_BUCKET, file_path)
        except Exception:
            logger.info("[MINIO] File không tồn tại trên MinIO, bỏ qua xóa: %s", file_path)
    except Exception as e:
        logger.error("[MINIO] Lỗi thao tác MinIO: %s", e)

    return {
        "status": 200,
        "result": "ok",
        "file_path": file_path
    }


async def load_sesion_service(db, user_id: str):
    """
    Lấy danh sách session RAG của user.

    Sử dụng cache-aside: check Redis trước, miss thì query PostgreSQL
    và set cache với TTL 5 phút.

    Sắp xếp: is_pinned (desc), COALESCE(updated_at, created_at) (desc), id (desc).

    Input:
        db (AsyncSession): Database session.
        user_id (str): ID người dùng từ token.

    Output:
        dict: {"status": 200, "result": list[dict]}
              Mỗi dict gồm {"id": int, "name": str, "is_pinned": bool, "paths": list}.
    """

    cache_key = f"{CACHE_KEY_SESSIONS}:{user_id}"

    # 1. Check cache Redis
    try:
        cached = await redis_service.client.get(cache_key)
        if cached:
            logger.debug("[CACHE HIT] %s", cache_key)
            return {"status": 200, "result": json.loads(cached)}
    except Exception as e:
        logger.warning("[CACHE] Redis read failed, fallback DB: %s", e)

    # 2. Cache miss → query PostgreSQL
    logger.debug("[CACHE MISS] %s", cache_key)
    result = await db.execute(
        select(session)
        .where(session.user_id == user_id)
        .order_by(
            desc(session.is_pinned),
            desc(func.coalesce(session.updated_at, session.created_at)),
            desc(session.id),
        )
    )
    rows = result.scalars().all()

    session_list = [
        {
            "id": row.id,
            "name": row.name,
            "is_pinned": row.is_pinned,
            "paths": row.paths or [],
            "created_at": row.created_at.isoformat() if row.created_at else None,
            "updated_at": row.updated_at.isoformat() if row.updated_at else None
        }
        for row in rows
    ]

    # 3. Set cache (TTL 5 phút)
    try:
        await redis_service.client.setex(
            cache_key,
            CACHE_TTL_SESSIONS,
            json.dumps(session_list, ensure_ascii=False),
        )
    except Exception as e:
        logger.warning("[CACHE] Redis write failed: %s", e)

    return {
        "status": 200,
        "result": session_list,
    }


async def delete_sesion_service(db, id: int, user_id: str):
    """
    Xóa session RAG và toàn bộ lịch sử chat + contract liên quan.

    Thứ tự xóa: contract (file + DB) → history → session.
    Sau khi xóa DB, invalidate cache Redis (sessions list + history).

    Input:
        db (AsyncSession): Database session.
        id (int): ID session cần xóa.

    Output:
        dict: {"status": 200, "result": "ok"}
    """

    # 1. Xác thực session tồn tại và thuộc về đúng user
    owned_session_rs = await db.execute(
        select(session).where(
            session.id == id,
            session.user_id == user_id,
        )
    )
    owned_session = owned_session_rs.scalars().first()
    if not owned_session:
        raise HTTPException(status_code=404, detail="Session không tồn tại")

    # 2. Lấy danh sách contract liên quan để xóa file
    related = await db.execute(select(contract).where(contract.session_id == id))
    related_contracts = related.scalars().all()

    # 3. Xóa file local + MinIO của từng contract
    for c in related_contracts:
        if c.name:
            local_path = os.path.join(FOLDER_PATH_CONTRACT, c.name)
            if os.path.isfile(local_path):
                os.remove(local_path)
            try:
                minio_service.client.remove_object(MINIO_CONTRACT_BUCKET, c.name)
            except Exception as e:
                logger.warning("Không xóa được file contract MinIO '%s': %s", c.name, e)

    # 4. Xóa DB records theo thứ tự phụ thuộc FK
    try:
        await db.execute(delete(contract).where(contract.session_id == id))
        await db.execute(delete(history_mess).where(history_mess.session_id == id))
        await db.execute(delete(semantic_history).where(semantic_history.session_id == id))
        await db.execute(delete(session).where(session.id == id, session.user_id == user_id))
        await db.commit()
    except Exception:
        await db.rollback()
        raise

    # 5. Invalidate cache
    try:
        await _invalidate_sessions_cache(user_id=user_id)
        # Scan và xóa tất cả history cache liên quan session này
        async for key in redis_service.client.scan_iter(
            match=f"{CACHE_KEY_HISTORY_PREFIX}:{id}:*"
        ):
            await redis_service.client.delete(key)
        logger.debug("[CACHE] Invalidated session %d", id)
    except Exception as e:
        logger.warning("[CACHE] Redis invalidate failed: %s", e)

    return {
        "status": 200,
        "result": "ok",
    }

async def rename_sesion_service(db, session_id: int, new_name: str):
    """
    Đổi tên session RAG.

    Input:
        db (AsyncSession): Database session.
        session_id (int): ID session cần đổi tên.
        new_name (str): Tên mới của session.

    Output:
        dict: {"status": 200, "result": "ok"}
    """
    result = await db.execute(select(session).where(session.id == session_id))
    record = result.scalars().first()

    if not record:
        raise HTTPException(status_code=404, detail="Session không tồn tại")

    record.name = new_name
    record.updated_at = _utc_now()
    await db.commit()

    # Invalidate sessions list cache (tên đã thay đổi)
    await _invalidate_sessions_cache()

    return {
        "status": 200,
        "result": "ok",
    }


async def add_path_to_session_service(db, session_id: int, file_path: str):
    """Thêm một file_path vào session."""
    res = await db.execute(select(session).where(session.id == session_id))
    s = res.scalars().first()
    if not s:
        raise HTTPException(status_code=404, detail="Session không tồn tại")

    current_paths = list(s.paths) if s.paths else []
    if file_path not in current_paths:
        current_paths.append(file_path)
        s.paths = current_paths
        s.updated_at = _utc_now()
        flag_modified(s, "paths")
        await db.commit()
        await _invalidate_sessions_cache()

    return {"status": 200, "result": "ok"}


async def remove_path_from_session_service(db, session_id: int, file_path: str):
    """Xóa một file_path khỏi session."""
    res = await db.execute(select(session).where(session.id == session_id))
    s = res.scalars().first()
    if not s:
        raise HTTPException(status_code=404, detail="Session không tồn tại")

    if s.paths and file_path in s.paths:
        new_paths = [p for p in s.paths if p != file_path]
        s.paths = new_paths
        s.updated_at = _utc_now()
        flag_modified(s, "paths")
        await db.commit()
        await _invalidate_sessions_cache()

    return {"status": 200, "result": "ok"}


async def pin_session_service(db, session_id: int, pin: bool = True):
    """Ghim hoặc bỏ ghim session."""
    res = await db.execute(select(session).where(session.id == session_id))
    s = res.scalars().first()
    if not s:
        raise HTTPException(status_code=404, detail="Session không tồn tại")

    s.is_pinned = pin
    s.updated_at = _utc_now()
    await db.commit()
    await _invalidate_sessions_cache()

    return {"status": 200, "result": "ok"}


async def load_history_service(request_history, db, user_id: str):
    """
    Lấy lịch sử chat RAG theo session, sắp xếp theo thứ tự thời gian.

    Sử dụng cache-aside: check Redis trước, miss thì query PostgreSQL
    và set cache với TTL 30 phút. Serialize ORM objects thành dict
    để lưu JSON vào Redis.

    Input:
        request_history: Request chứa session_id.
        db (AsyncSession): Database session.
        user_id (str): ID người dùng từ token.

    Output:
        dict: {"status": 200, "result": list[dict]}
    """

    cache_key = (
        f"{CACHE_KEY_HISTORY_PREFIX}"
        f":{request_history.session_id}"
        f":{user_id}"
    )

    # 1. Check cache Redis
    try:
        cached = await redis_service.client.get(cache_key)
        if cached:
            logger.debug("[CACHE HIT] %s", cache_key)
            return {"status": 200, "result": json.loads(cached)}
    except Exception as e:
        logger.warning("[CACHE] Redis read failed, fallback DB: %s", e)

    # 2. Cache miss → query PostgreSQL
    logger.debug("[CACHE MISS] %s", cache_key)
    query = select(history_mess).where(
        history_mess.session_id == request_history.session_id,
        history_mess.user_id == user_id,
    ).order_by(
        history_mess.id.asc()
    )

    data = await db.execute(query)
    rows = data.scalars().all()

    # 3. Serialize ORM objects → dict để lưu cache và trả về
    history_list = [
        {
            "id": row.id,
            "user_id": row.user_id,
            "session_id": row.session_id,
            "role": row.role,
            "mess": row.mess,
            "created_at": row.created_at.isoformat()
            if row.created_at else None,
        }
        for row in rows
    ]

    # 4. Set cache (TTL 30 phút)
    try:
        await redis_service.client.setex(
            cache_key,
            CACHE_TTL_HISTORY,
            json.dumps(history_list, ensure_ascii=False),
        )
    except Exception as e:
        logger.warning("[CACHE] Redis write failed: %s", e)

    return {
        "status": 200,
        "result": history_list,
    }


# =============================================================================
# HÀM NỘI BỘ (PRIVATE HELPERS)
# =============================================================================


async def _get_or_create_rag_session(result, request, db, user_id: str):
    """
    Lấy session RAG hiện tại hoặc tạo mới nếu chưa tồn tại.

    Input:
        result (dict): Kết quả từ query workflow.
        request: Request chứa session_id, user_input.
        db (AsyncSession): Database session.
        user_id (str): ID người dùng từ token.

    Output:
        session: Session record từ database.
    """

    if request.session_id and request.session_id > 0:
        session_query = await db.execute(
            select(session).where(
                session.id == request.session_id,
                session.user_id == user_id,
            )
        )
        existing_session = session_query.scalars().first()

        if existing_session is not None:
            logger.debug("Sử dụng session cũ: %s", existing_session.id)
            return existing_session

    # Tạo session mới — lấy tối đa 20 ký tự đầu của user_input làm tên
    session_name = (request.user_input or "")[:20].strip() or "Untitled"
    new_session = session(user_id=user_id, name=session_name, updated_at=_utc_now())
    db.add(new_session)
    await db.commit()
    await db.refresh(new_session)

    logger.info("Đã tạo session mới: id=%s, name='%s'", new_session.id, new_session.name)

    return new_session


async def create_sesion_service(db, user_id: str, name: str):
    """
    Tạo một session RAG mới với tên cho trước.

    Input:
    db: Database session.
    user_id: ID người dùng.
    name: Tên session.
    """
    new_session = session(user_id=user_id, name=name, updated_at=_utc_now())
    db.add(new_session)
    await db.commit()
    await db.refresh(new_session)

    # Invalidate cache list session của user
    await _invalidate_sessions_cache(user_id)

    logger.info("[SERVICE] Đã tạo session mới: id=%d, name='%s'", new_session.id, new_session.name)
    return {
        "status": 200,
        "result": {
            "id": new_session.id,
            "name": new_session.name,
            "is_pinned": new_session.is_pinned,
            "paths": new_session.paths or []
        }
    }


async def rag_contract_fast_service(request: rag_chat_request, user_id: str):
    """
    Truy vấn RAG Contract Fast — SSE streaming.

    Trả về async generator để StreamingResponse yield SSE events.
    Mỗi event gồm: user_id, session_id, title, mess, end.

    path_list được lấy tự động từ session.paths trong DB (nếu session tồn tại).
    user_id được lấy từ token xác thực.
    """
    import asyncio
    import json

    if (request.query_flow or "fast") == "web_search":
        await _enforce_web_search_rate_limit(user_id)

    queue = asyncio.Queue()

    # Lấy path_list từ session trong DB
    path_list = []
    if request.session_id and request.session_id > 0:
        try:
            async with SessionLocal() as local_db:
                result = await local_db.execute(
                    select(session.paths).where(
                        session.id == request.session_id,
                        session.user_id == user_id,
                    )
                )
                session_paths = result.scalars().first()
                if session_paths:
                    path_list = list(session_paths)
                    logger.info("[SERVICE] Lấy %d paths từ session %d", len(path_list), request.session_id)
        except Exception as e:
            logger.warning("[SERVICE] Lỗi lấy paths từ session: %s", e)

    initial_state = {
        "user_id": user_id,
        "session_id": request.session_id,
        "user_input": request.user_input,
        "model_name": request.model_name,
        "query_flow": request.query_flow,
        "web_urls": request.web_urls,
        "web_mode": request.web_mode,
        "path_list": path_list,
        "search_results": [],
        "filtered_paths": [],
        "context_with_path": [],
        "assistant_response": "",
        "sse_queue": queue,
    }

    chosen_flow = request.query_flow or "fast"
    chosen_workflow = (
        app_rag_web_search_workflow
        if chosen_flow == "web_search"
        else app_rag_contract_fast_workflow
    )

    if chosen_flow != "web_search" or SEARCH_LOG_ENABLED:
        logger.info(
            "[SERVICE] Bắt đầu workflow RAG query (flow=%s, sse): %s",
            chosen_flow,
            request.user_input,
        )

    async def _run_workflow():
        """Chạy workflow background, cuối cùng push event end=true."""
        try:
            result = await chosen_workflow.ainvoke(initial_state)

            if SEARCH_LOG_ENABLED:
                history_debug = result.get("history_pipeline_debug") or {}
                logger.debug(
                    "[HISTORY_PIPELINE_AUDIT] flow=%s user=%s session=%s short=%s semantic_pool=%s selected=%s fallback=%s chars=%s",
                    chosen_flow,
                    user_id,
                    request.session_id,
                    history_debug.get("short_window_count", 0),
                    history_debug.get("semantic_pool_count", 0),
                    history_debug.get("semantic_selected_count", 0),
                    history_debug.get("used_fallback_semantic_scope", False),
                    history_debug.get("context_chars", 0),
                )

            if chosen_flow == "web_search" and SEARCH_LOG_ENABLED:
                logger.info(
                    "[WEB_AUDIT] user=%s session=%s selected_urls=%s evidence_count=%s confidence=%s",
                    user_id,
                    request.session_id,
                    result.get("selected_urls") or [],
                    len(result.get("reranked_evidence") or []),
                    result.get("confidence") or "n/a",
                )

            # Lưu session + history sau khi workflow xong
            actual_session_id = request.session_id
            turn_id_to_pass = 0

            async with SessionLocal() as local_db:
                session_obj = await _get_or_create_rag_session(result, request, local_db, user_id)
                actual_session_id = session_obj.id

                user_mess = history_mess(
                    user_id=user_id,
                    session_id=actual_session_id,
                    role="user",
                    mess=request.user_input,
                )

                bot_mess = history_mess(
                    user_id=user_id,
                    session_id=actual_session_id,
                    role="chatbot",
                    mess=result.get("assistant_response", ""),
                )

                # Touch session để đảm bảo thứ tự "mới nhất lên đầu" nhất quán.
                session_obj.updated_at = _utc_now()
                local_db.add_all([user_mess, bot_mess])
                await local_db.commit()
                await local_db.refresh(user_mess)
                turn_id_to_pass = int(user_mess.id or bot_mess.id or 0)

            # Ingest semantic history bất đồng bộ để không tăng độ trễ trả SSE.
            async def _ingest_history_background(t_id, sid):
                await ingest_semantic_history_turn(
                    user_id=user_id,
                    session_id=sid,
                    turn_id=t_id,
                    query_flow=chosen_flow,
                    user_text=request.user_input,
                    assistant_text=result.get("assistant_response", ""),
                )

            asyncio.create_task(_ingest_history_background(turn_id_to_pass, actual_session_id))

            # Invalidate cache: sessions list + history cho session này
            try:
                await _invalidate_sessions_cache(user_id)
                await redis_service.client.delete(
                    f"{CACHE_KEY_HISTORY_PREFIX}"
                    f":{actual_session_id}"
                    f":{user_id}"
                )
            except Exception as e:
                logger.warning("[CACHE] Redis invalidate failed: %s", e)

            # Push event kết thúc
            await queue.put({
                "user_id": user_id,
                "session_id": actual_session_id,
                "title": "",
                "mess": "",
                "end": True,
            })

        except Exception as e:
            logger.error(f"[SERVICE] Workflow error: {e}")
            await queue.put({
                "user_id": user_id,
                "session_id": request.session_id,
                "title": "Lỗi",
                "mess": str(e),
                "end": True,
            })

    async def event_generator():
        """Async generator yield SSE events từ queue."""
        task = asyncio.create_task(_run_workflow())

        try:
            while True:
                event = await queue.get()
                yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"

                if event.get("end"):
                    break
        finally:
            # Đảm bảo task hoàn thành
            if not task.done():
                await task

    return event_generator()

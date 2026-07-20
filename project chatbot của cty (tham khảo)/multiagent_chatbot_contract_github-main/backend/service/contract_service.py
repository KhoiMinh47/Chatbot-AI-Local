"""Service xử lý business logic cho hợp đồng (Contract).

Bao gồm các hàm chính:
    - upload_template: Upload và parse template hợp đồng (.docx) qua workflow.
    - create_contract: Gọi LLM trả lời dựa trên template và tạo file Word.
    - load_template_name: Lấy danh sách template.
    - delete_template_service: Xóa template.
"""

import asyncio
import json
import logging
import os
import re
import urllib.parse
from datetime import datetime

from fastapi import UploadFile, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy import select, delete

from agent_chatbot.graph.contract_graph import (
    upload_template_workflow,
    create_contract_workflow,
    create_contract_fast_workflow,
    create_contract_reasoning_workflow,
)
from database.setup_minio import minio_service, MINIO_CONTRACT_BUCKET, MINIO_BUCKET
from database.setup_postgres import SessionLocal
from database.table.table_postgres import contract_template, contract, session, history_mess
from database.setup_redis import redis_service

logger = logging.getLogger(__name__)

# --- Hằng số đường dẫn ---
FOLDER_PATH_CONTRACT = os.getenv("FOLDER_PATH_CONTRACT", "database/storage/contract")
FOLDER_PATH_TEMPLATE = os.getenv("FOLDER_PATH_TEMPLATE", "database/storage/template")

# --- Cấu hình Redis Cache ---
CACHE_KEY_SESSIONS = "sessions:all"
CACHE_KEY_HISTORY_PREFIX = "history"
CACHE_TTL_SESSIONS = 300   # 5 phút
CACHE_TTL_HISTORY = 1800   # 30 phút


def build_contract_download_url(path_name: str) -> str:
    """Tạo public download URL theo reverse proxy hiện tại, không khóa cứng host."""
    if not path_name:
        return ""
    encoded_path = urllib.parse.quote(path_name, safe="/")
    return f"/api/v1/contracts/download-contract/{encoded_path}"


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



# =============================================================================
# 2 HÀM CHÍNH: upload_template & create_contract
# =============================================================================


async def upload_template_service(file: UploadFile, db):
    """
    Upload file template hợp đồng (.docx) lên server qua upload_template_workflow.

    Quy trình:
        1. Kiểm tra trùng tên file trong database.
        2. Gọi upload_template_workflow để validate, lưu file, quét schema.
        3. Lưu thông tin template vào database.

    Input:
        file (UploadFile): File DOCX template hợp đồng.
        db (AsyncSession): Database session.

    Output:
        dict: {"status_code": 200, "description": "ok"} nếu thành công.

    Raises:
        HTTPException 400: Nếu file trùng tên hoặc workflow trả lỗi.
    """

    filename = file.filename

    # Kiểm tra trùng tên file trong database
    file_db = await db.execute(
        select(contract_template).where(contract_template.name == filename)
    )
    file_db = file_db.scalars().all()

    if len(file_db) > 0:
        raise HTTPException(status_code=400, detail="file đã tồn tại.")

    # Đọc nội dung file
    file_content = await file.read()

    # Gọi upload_template_workflow
    state = {
        "filename": filename,
        "file_content": file_content,
        "file_path": "",
        "minio_path": "",
        "status": "",
        "mess": "",
        "parsed_content": "",
    }

    result = await upload_template_workflow.ainvoke(state)

    if result.get("status") == "error":
        raise HTTPException(status_code=400, detail=result.get("mess"))

    logger.info("Upload template thành công: %s", filename)

    # Lưu thông tin template vào database
    new_template = contract_template(
        name=filename,
        content=result.get("parsed_content"),
        path=result.get("minio_path"),
    )
    db.add(new_template)
    await db.commit()

    return {
        "status_code": 200,
        "description": "ok",
    }

async def create_contract_templated_service(request, db, user_id: str):
    """
    Streaming version của create_contract_service.
    Flow:
        1. Tạo hợp đồng Word hoàn chỉnh (không stream từng token)
        2. Lưu DB + upload MinIO
        3. Stream tóm tắt ngắn từ LLM kèm link download

    SSE event format:
        {user_id, session_id, title, mess, end, path_name, download_url}
        - title: node đang chạy (hiển thị thông báo trạng thái)
        - mess: token tóm tắt (chỉ ở bước cuối)
        - end: True khi hoàn thành
    """
    from agent_chatbot.node.util.contract_create_util import stream_contract_summary

    # 1. Xử lý session
    session_id = None
    if request.session_id > 0:
        existing = await db.execute(
            select(session).where(
                session.id == request.session_id,
                session.user_id == user_id,
            )
        )
        if existing.scalars().first():
            session_id = request.session_id

    if session_id is None:
        session_name = (request.user_input or "")[:20].strip() or "Untitled"
        new_session = session(user_id=user_id, name=session_name)
        db.add(new_session)
        await db.flush()
        await db.commit()
        session_id = new_session.id

    # 2. Load template
    stmt = select(contract_template).where(contract_template.id == request.template_id)
    result = await db.execute(stmt)
    template = result.scalars().first()

    if not template or not template.content:
        async def _error_gen():
            yield f"data: {json.dumps({'title': 'Lỗi', 'mess': 'Template không tồn tại hoặc chưa có nội dung.', 'end': True})}\\n\\n"
        return _error_gen()

    # 3. Tạo tên hợp đồng
    template_base = os.path.splitext(template.name)[0]
    clean_name = re.sub(r'[^\w\s.-]', '', template_base).strip()
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    contract_name = f"{clean_name}_{timestamp}"

    # 4. State cho workflow (không cần sse_queue vì không stream khi tạo)
    workflow_state = {
        "user_id": user_id,
        "session_id": session_id,
        "user_input": request.user_input,
        "template_content": template.content,
        "contract_name": contract_name,
        "model_name": request.model_name or "",
        "llm_response": "",
        "mess": "",
        "status": "",
        "path_name": "",
        "sse_queue": None,
    }

    async def _stream_generator():
        # --- Bước 1: Chạy workflow tạo hợp đồng (background task) ---
        workflow_task = asyncio.create_task(
            create_contract_workflow.ainvoke(workflow_state)
        )

        # Gửi event trạng thái ban đầu
        yield f"data: {json.dumps({'user_id': user_id, 'session_id': session_id, 'title': 'Đang tạo hợp đồng...', 'mess': '', 'end': False}, ensure_ascii=False)}\n\n"

        # Heartbeat mỗi 3s để frontend biết đang xử lý
        heartbeat_interval = 3.0
        elapsed = 0.0
        while not workflow_task.done():
            await asyncio.sleep(0.5)
            elapsed += 0.5
            if elapsed >= heartbeat_interval:
                elapsed = 0.0
                yield f"data: {json.dumps({'user_id': user_id, 'session_id': session_id, 'title': 'Đang tạo hợp đồng...', 'mess': '', 'end': False}, ensure_ascii=False)}\n\n"

        # Kiểm tra lỗi workflow
        exc = workflow_task.exception()
        if exc:
            logger.error("Workflow lỗi: %s", exc)
            yield f"data: {json.dumps({'user_id': user_id, 'session_id': session_id, 'title': 'Lỗi', 'mess': str(exc), 'end': True}, ensure_ascii=False)}\n\n"
            return

        workflow_result = workflow_task.result()
        path_name = workflow_result.get("path_name", "")
        llm_response = workflow_result.get("llm_response", "")
        status = workflow_result.get("status", "")

        if status == "error":
            yield f"data: {json.dumps({'user_id': user_id, 'session_id': session_id, 'title': 'Lỗi', 'mess': workflow_result.get('mess', ''), 'end': True}, ensure_ascii=False)}\n\n"
            return

                        # --- Bước 2: Lưu DB + MinIO ---
        yield f"data: {json.dumps({'user_id': user_id, 'session_id': session_id, 'title': 'Đang lưu hợp đồng...', 'mess': '', 'end': False}, ensure_ascii=False)}\n\n"
        try:
            async with SessionLocal() as new_db:
                minio_path = f"{MINIO_CONTRACT_BUCKET}/{path_name}" if path_name else ""
                contract_record = contract(
                    template_id=request.template_id,
                    user_id=user_id,
                    session_id=session_id,
                    name=path_name,
                    content=llm_response,
                    path=minio_path,
                )
                user_mess = history_mess(
                    user_id=user_id, session_id=session_id,
                    role="user", mess=request.user_input,
                )
                new_db.add_all([contract_record, user_mess])
                await new_db.commit()
                logger.info("Đã lưu Fast contract + user history vào DB")

            try:
                await _invalidate_sessions_cache(user_id)
                await redis_service.client.delete(
                    f"{CACHE_KEY_HISTORY_PREFIX}:{session_id}:{user_id}"
                )
            except Exception as e:
                logger.warning("[CACHE] Redis invalidate failed on fast create: %s", e)

            if path_name:
                file_path = os.path.join(FOLDER_PATH_CONTRACT, path_name)
                if os.path.isfile(file_path):
                    minio_service.client.fput_object(
                        bucket_name=MINIO_CONTRACT_BUCKET,
                        object_name=path_name,
                        file_path=file_path,
                        content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                    )
                    logger.info("Đã upload Fast hợp đồng lên MinIO: %s", path_name)

        except Exception as e:
            logger.error("Lỗi lưu DB/MinIO (Fast): %s", e)

        # --- Bước 3: Stream tóm tắt ---
        download_url = build_contract_download_url(path_name)
        yield f"data: {json.dumps({'user_id': user_id, 'session_id': session_id, 'title': 'Đang tóm tắt...', 'mess': '', 'end': False}, ensure_ascii=False)}\n\n"

        summary_text = ""
        summary_queue = asyncio.Queue()
        summary_task = asyncio.create_task(
            stream_contract_summary(
                llm_response,
                summary_queue,
                user_id=user_id,
                session_id=session_id,
                model_name=request.model_name,
            )
        )

        while True:
            event = await summary_queue.get()
            if event is None: break
            if "mess" in event:
                summary_text += event["mess"]
            yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"

        await summary_task
        
        # Ghi Summary + Link tải vào DB chatbot history
        if download_url:
            summary_text += f"\n\n[📄 Tải hợp đồng ({path_name})]({download_url})"
            
        try:
            async with SessionLocal() as new_db:
                bot_mess = history_mess(
                    user_id=user_id, session_id=session_id,
                    role="bot", mess=summary_text,
                )
                new_db.add(bot_mess)
                await new_db.commit()
                
                await redis_service.client.delete(f"{CACHE_KEY_HISTORY_PREFIX}:{session_id}:{user_id}")
        except Exception as e:
            logger.error("Lỗi lưu bot_mess: %s", e)
            
        yield f"data: {json.dumps({'user_id': user_id, 'session_id': session_id, 'title': 'Hoàn thành', 'mess': '', 'path_name': path_name, 'download_url': download_url, 'end': True}, ensure_ascii=False)}\n\n"

    return _stream_generator()


async def create_contract_fast_service(request, db, user_id: str):
    """
    Luồng 2: Tạo hợp đồng siêu nhanh không cần template.
    """
    from agent_chatbot.node.util.contract_create_util import stream_contract_summary

    # 1. Xử lý session
    session_id = None
    if request.session_id > 0:
        existing = await db.execute(
            select(session).where(
                session.id == request.session_id,
                session.user_id == user_id,
            )
        )
        if existing.scalars().first():
            session_id = request.session_id

    if session_id is None:
        session_name = (request.user_input or "")[:20].strip() or "Untitled"
        new_session = session(user_id=user_id, name=session_name)
        db.add(new_session)
        await db.flush()
        await db.commit()
        session_id = new_session.id

    # 3. Tạo tên hợp đồng
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    contract_name = f"AIFast_Contract_{timestamp}"

    # 4. State cho workflow
    workflow_state = {
        "user_id": user_id,
        "session_id": session_id,
        "user_input": request.user_input,
        "template_content": "", # Không cần cho luồng Fast
        "contract_name": contract_name,
        "model_name": request.model_name or "",
        "llm_response": "",
        "mess": "",
        "status": "",
        "path_name": "",
        "sse_queue": None,
    }

    async def _stream_generator():
        # --- Bước 1: Chạy workflow tạo hợp đồng Fast ---
        workflow_task = asyncio.create_task(
            create_contract_fast_workflow.ainvoke(workflow_state)
        )

        yield f"data: {json.dumps({'user_id': user_id, 'session_id': session_id, 'title': 'Đang phác thảo hợp đồng...', 'mess': '', 'end': False}, ensure_ascii=False)}\n\n"

        heartbeat_interval = 3.0
        elapsed = 0.0
        while not workflow_task.done():
            await asyncio.sleep(0.5)
            elapsed += 0.5
            if elapsed >= heartbeat_interval:
                elapsed = 0.0
                yield f"data: {json.dumps({'user_id': user_id, 'session_id': session_id, 'title': 'Đang phác thảo hợp đồng...', 'mess': '', 'end': False}, ensure_ascii=False)}\n\n"

        exc = workflow_task.exception()
        if exc:
            logger.error("Fast Workflow lỗi: %s", exc)
            yield f"data: {json.dumps({'user_id': user_id, 'session_id': session_id, 'title': 'Lỗi', 'mess': str(exc), 'end': True}, ensure_ascii=False)}\n\n"
            return

        workflow_result = workflow_task.result()
        path_name = workflow_result.get("path_name", "")
        llm_response = workflow_result.get("llm_response", "")
        status = workflow_result.get("status", "")

        if status == "error":
            yield f"data: {json.dumps({'user_id': user_id, 'session_id': session_id, 'title': 'Lỗi', 'mess': workflow_result.get('mess', ''), 'end': True}, ensure_ascii=False)}\n\n"
            return

        yield f"data: {json.dumps({'user_id': user_id, 'session_id': session_id, 'title': 'Đang lưu hợp đồng...', 'mess': '', 'end': False}, ensure_ascii=False)}\n\n"
        try:
            async with SessionLocal() as new_db:
                minio_path = f"{MINIO_CONTRACT_BUCKET}/{path_name}" if path_name else ""
                contract_record = contract(
                    template_id=None,
                    user_id=user_id,
                    session_id=session_id,
                    name=path_name,
                    content=llm_response,
                    path=minio_path,
                )
                new_db.add(contract_record)
                user_mess = history_mess(
                    user_id=user_id, session_id=session_id,
                    role="user", mess=request.user_input,
                )
                new_db.add(user_mess)
                await new_db.commit()
                logger.info("Đã lưu Fast contract + user history vào DB")

            try:
                await _invalidate_sessions_cache(user_id)
                await redis_service.client.delete(
                    f"{CACHE_KEY_HISTORY_PREFIX}:{session_id}:{user_id}"
                )
            except Exception as e:
                logger.warning("[CACHE] Redis invalidate failed on fast create: %s", e)

            if path_name:
                file_path = os.path.join(FOLDER_PATH_CONTRACT, path_name)
                if os.path.isfile(file_path):
                    minio_service.client.fput_object(
                        bucket_name=MINIO_CONTRACT_BUCKET,
                        object_name=path_name,
                        file_path=file_path,
                        content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                    )
                    logger.info("Đã upload Fast hợp đồng lên MinIO: %s", path_name)

        except Exception as e:
            logger.error("Lỗi lưu DB/MinIO (Fast): %s", e)

        # --- Bước 3: Stream tóm tắt ---
        download_url = build_contract_download_url(path_name)
        yield f"data: {json.dumps({'user_id': user_id, 'session_id': session_id, 'title': 'Đang tóm tắt...', 'mess': '', 'end': False}, ensure_ascii=False)}\n\n"

        summary_text = ""
        summary_queue = asyncio.Queue()
        summary_task = asyncio.create_task(
            stream_contract_summary(
                llm_response,
                summary_queue,
                user_id=user_id,
                session_id=session_id,
                model_name=request.model_name,
            )
        )

        while True:
            event = await summary_queue.get()
            if event is None: break
            if "mess" in event:
                summary_text += event["mess"]
            yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"

        await summary_task
        
        # Ghi Summary + Link tải vào DB chatbot history
        if download_url:
            summary_text += f"\n\n[📄 Tải hợp đồng ({path_name})]({download_url})"
            
        try:
            async with SessionLocal() as new_db:
                bot_mess = history_mess(
                    user_id=user_id, session_id=session_id,
                    role="bot", mess=summary_text,
                )
                new_db.add(bot_mess)
                await new_db.commit()
                
                await redis_service.client.delete(f"{CACHE_KEY_HISTORY_PREFIX}:{session_id}:{user_id}")
        except Exception as e:
            logger.error("Lỗi lưu bot_mess luồng Fast: %s", e)

        yield f"data: {json.dumps({'user_id': user_id, 'session_id': session_id, 'title': 'Hoàn thành', 'mess': '', 'path_name': path_name, 'download_url': download_url, 'end': True}, ensure_ascii=False)}\n\n"

    return _stream_generator()


async def create_contract_reasoning_service(request, db, user_id: str):
    """
    Luồng 3: Multi-Agent AI tạo hợp đồng chặt chẽ qua cơ chế kiểm duyệt.
    """
    from agent_chatbot.node.util.contract_create_util import stream_contract_summary
    async def _stream_generator():
        # 1. Xử lý session
        session_id = None
        if request.session_id > 0:
            existing = await db.execute(
                select(session).where(
                    session.id == request.session_id,
                    session.user_id == user_id,
                )
            )
            if existing.scalars().first():
                session_id = request.session_id

        if session_id is None:
            session_name = (request.user_input or "")[:20].strip() or "Untitled"
            new_session = session(user_id=user_id, name=session_name)
            db.add(new_session)
            await db.flush()
            await db.commit()
            session_id = new_session.id

        # 2. State ban đầu cho workflow
        workflow_state = {
            "user_id": user_id,
            "session_id": session_id,
            "user_input": request.user_input,
            "model_name": request.model_name or "",
            "current_draft": "",
            "critic_feedback": "",
            "is_passed": False,
            "revision_count": 0,
            "path_name": "",
            "status": "",
            "mess": ""
        }

        # 3. Kích hoạt Workflow ngầm
        workflow_task = asyncio.create_task(
            create_contract_reasoning_workflow.ainvoke(workflow_state)
        )

        yield f"data: {json.dumps({'user_id': user_id, 'session_id': session_id, 'title': 'Multi-Agent đang hội ý tạo hợp đồng...', 'mess': '', 'end': False}, ensure_ascii=False)}\\n\\n"

        heartbeat_interval = 2.0
        elapsed = 0.0
        while not workflow_task.done():
            await asyncio.sleep(0.5)
            elapsed += 0.5
            if elapsed >= heartbeat_interval:
                elapsed = 0.0
                yield f"data: {json.dumps({'user_id': user_id, 'session_id': session_id, 'title': 'Hệ thống AI đang tranh luận...', 'mess': '', 'end': False}, ensure_ascii=False)}\\n\\n"

        exc = workflow_task.exception()
        if exc:
            logger.error("Reasoning Workflow lỗi: %s", exc)
            yield f"data: {json.dumps({'user_id': user_id, 'session_id': session_id, 'title': 'Lỗi', 'mess': str(exc), 'end': True}, ensure_ascii=False)}\\n\\n"
            return

        workflow_result = workflow_task.result()
        path_name = workflow_result.get("path_name", "")
        final_draft = workflow_result.get("current_draft", "")
        status = workflow_result.get("status", "")

        if status == "error":
            yield f"data: {json.dumps({'user_id': user_id, 'session_id': session_id, 'title': 'Lỗi', 'mess': workflow_result.get('mess', ''), 'end': True}, ensure_ascii=False)}\\n\\n"
            return

                # --- Lưu DB + MinIO ---
        yield f"data: {json.dumps({'user_id': user_id, 'session_id': session_id, 'title': 'Đang lưu hợp đồng...', 'mess': '', 'end': False}, ensure_ascii=False)}\n\n"
        try:
            async with SessionLocal() as new_db:
                minio_path = f"{MINIO_CONTRACT_BUCKET}/{path_name}" if path_name else ""
                contract_record = contract(
                    template_id=None,
                    user_id=user_id,
                    session_id=session_id,
                    name=path_name,
                    content=final_draft,
                    path=minio_path,
                )
                user_mess = history_mess(
                    user_id=user_id, session_id=session_id,
                    role="user", mess=request.user_input,
                )
                new_db.add_all([contract_record, user_mess])
                await new_db.commit()
                logger.info("[Reasoning] Đã lưu contract + user history vào DB")

            try:
                await _invalidate_sessions_cache(user_id)
                await redis_service.client.delete(
                    f"{CACHE_KEY_HISTORY_PREFIX}:{session_id}:{user_id}"
                )
            except Exception as e:
                logger.warning("[CACHE] Redis invalidate failed on reasoning create: %s", e)

            if path_name:
                file_path = os.path.join(FOLDER_PATH_CONTRACT, path_name)
                if os.path.isfile(file_path):
                    minio_service.client.fput_object(
                        bucket_name=MINIO_CONTRACT_BUCKET,
                        object_name=path_name,
                        file_path=file_path,
                        content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                    )
                    logger.info("[Reasoning] Đã upload hợp đồng lên MinIO: %s", path_name)

        except Exception as e:
            logger.error("Lỗi lưu DB/MinIO luồng Reasoning: %s", e)

        # --- Stream tóm tắt ---
        download_url = build_contract_download_url(path_name)
        yield f"data: {json.dumps({'user_id': user_id, 'session_id': session_id, 'title': 'Đang tóm tắt...', 'mess': '', 'end': False}, ensure_ascii=False)}\n\n"

        summary_text = ""
        summary_queue = asyncio.Queue()
        summary_task = asyncio.create_task(
            stream_contract_summary(
                final_draft,
                summary_queue,
                user_id=user_id,
                session_id=session_id,
                model_name=request.model_name,
            )
        )

        while True:
            event = await summary_queue.get()
            if event is None: break
            if "mess" in event:
                summary_text += event["mess"]
            yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"

        await summary_task
        
        # Ghi Summary + Link tải vào DB chatbot history
        if download_url:
            summary_text += f"\n\n[📄 Tải hợp đồng ({path_name})]({download_url})"
            
        try:
            async with SessionLocal() as new_db:
                bot_mess = history_mess(
                    user_id=user_id, session_id=session_id,
                    role="bot", mess=summary_text,
                )
                new_db.add(bot_mess)
                await new_db.commit()
                
                await redis_service.client.delete(f"{CACHE_KEY_HISTORY_PREFIX}:{session_id}:{user_id}")
        except Exception as e:
            logger.error("Lỗi lưu bot_mess: %s", e)

        # --- Event kết thúc ---
        yield f"data: {json.dumps({'user_id': user_id, 'session_id': session_id, 'title': 'Hoàn thành', 'mess': '', 'path_name': path_name, 'download_url': download_url, 'end': True}, ensure_ascii=False)}\n\n"

    return _stream_generator()


# =============================================================================
# CÁC HÀM PHỤ (CRUD)
# =============================================================================


def download_contract(filename):
    """Download file hợp đồng đã tạo theo tên file."""

    filename = urllib.parse.unquote(filename)
    filename = filename.strip('"').strip("'")

    if "/" in filename:
        filename = filename.split("/")[-1]

    file_path = os.path.join(FOLDER_PATH_CONTRACT, filename)

    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail=f"File không tồn tại: {filename}")

    return FileResponse(
        path=file_path,
        filename=filename,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    )


async def load_template_name(db):
    """Lấy danh sách template hợp đồng (id + name)."""

    result = await db.execute(
        select(contract_template.id, contract_template.name)
    )
    rows = result.all()

    return {
        "status": 200,
        "result": [{"id": r.id, "name": r.name} for r in rows],
    }

async def load_contract_list(db, user_id: str):
    """Lấy danh sách tất cả hợp đồng đã tạo của user."""

    result = await db.execute(
        select(contract).where(contract.user_id == user_id).order_by(contract.id.desc())
    )
    contracts = result.scalars().all()

    return {
        "status": 200,
        "result": [
            {
                "id": c.id, 
                "name": c.name, 
                "created_at": c.created_at.isoformat() if c.created_at else None
            } 
            for c in contracts
        ],
    }

async def delete_template_service(db, id_template):
    """Xóa template hợp đồng theo ID: xóa DB + local + MinIO."""

    # Lấy record để biết tên file
    result = await db.execute(
        select(contract_template).where(contract_template.id == id_template)
    )
    record = result.scalars().first()

    if not record:
        raise HTTPException(status_code=404, detail="Template không tồn tại")

    filename = record.name

    # Lấy danh sách contract liên quan trước khi xóa
    related = await db.execute(
        select(contract).where(contract.template_id == id_template)
    )
    related_contracts = related.scalars().all()

    # Xóa file local + MinIO của từng contract liên quan
    deleted_contracts = []
    for c in related_contracts:
        if c.name:
            deleted_contracts.append(c.name)
            local_path = os.path.join(FOLDER_PATH_CONTRACT, c.name)
            if os.path.isfile(local_path):
                os.remove(local_path)
            try:
                minio_service.client.remove_object(MINIO_CONTRACT_BUCKET, c.name)
            except Exception as e:
                logger.warning("Không xóa được file contract MinIO '%s': %s", c.name, e)

    # Xóa các contract liên quan trong DB
    await db.execute(delete(contract).where(contract.template_id == id_template))
    await db.commit()

    # Xóa record template
    await db.execute(delete(contract_template).where(contract_template.id == id_template))
    await db.commit()

    # Xóa file local
    if filename:
        file_path = os.path.join(FOLDER_PATH_TEMPLATE, filename)
        if os.path.isfile(file_path):
            os.remove(file_path)

        # Xóa file trên MinIO
        try:
            minio_service.client.remove_object(MINIO_BUCKET, filename)
        except Exception as e:
            logger.warning("Không xóa được file MinIO '%s': %s", filename, e)

    return {
        "status": 200,
        "result": "ok",
        "deleted_contracts": deleted_contracts,
    }

async def delete_contract_service(db, contract_id: int):
    """Xóa hợp đồng theo ID: xóa DB, local, MinIO."""

    # Lấy record để biết path
    result = await db.execute(
        select(contract).where(contract.id == contract_id)
    )
    record = result.scalars().first()

    if not record:
        raise HTTPException(status_code=404, detail="Contract không tồn tại")

    filename = record.name

    # Xóa record trong PostgreSQL
    await db.execute(delete(contract).where(contract.id == contract_id))
    await db.commit()

    # Xóa file local
    if filename:
        local_path = os.path.join(FOLDER_PATH_CONTRACT, filename)
        if os.path.isfile(local_path):
            os.remove(local_path)

        # Xóa file trên MinIO
        try:
            minio_service.client.remove_object(MINIO_CONTRACT_BUCKET, filename)
        except Exception as e:
            logger.warning("Không xóa được file MinIO '%s': %s", filename, e)

    return {
        "status": 200,
        "result": "ok",
    }


# =============================================================================
# SESSION APIs
# =============================================================================





async def add_contract_session_path_service(session_id: int, file_path: str, user_id: str) -> dict:
    """
    Ghim (ghi đè) template_path vào bảng session của hợp đồng.
    Chỉ cho phép 1 đường dẫn duy nhất tại 1 thời điểm.
    """
    async with SessionLocal() as db:
        result = await db.execute(
            select(session).where(
                session.id == session_id,
                session.user_id == user_id,
            )
        )
        session_obj = result.scalars().first()
        if not session_obj:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Không tìm thấy session",
            )

        session_obj.template_path = file_path
        await db.commit()
    
    # Xoá cache Redis danh sách session
    await redis_service.client.delete(f"{CACHE_KEY_SESSIONS}:{user_id}")
    return {"message": "Đã ghim template vào session"}


async def delete_contract_session_path_service(session_id: int, file_path: str, user_id: str) -> dict:
    """
    Gỡ ghim template_path khỏi bảng session của hợp đồng.
    """
    async with SessionLocal() as db:
        result = await db.execute(
            select(session).where(
                session.id == session_id,
                session.user_id == user_id,
            )
        )
        session_obj = result.scalars().first()
        if not session_obj:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Không tìm thấy session",
            )
        
        # Chỉ xoá nếu path trùng khớp với path đang ghim
        if session_obj.template_path == file_path:
            session_obj.template_path = None
            await db.commit()
            
    # Xoá cache Redis danh sách session
    await redis_service.client.delete(f"{CACHE_KEY_SESSIONS}:{user_id}")
    return {"message": "Đã gỡ template khỏi session"}




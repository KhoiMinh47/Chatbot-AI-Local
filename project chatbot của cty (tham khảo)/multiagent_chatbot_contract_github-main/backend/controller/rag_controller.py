"""
Controller xử lý các API endpoint liên quan đến RAG (Retrieval-Augmented Generation).

Bao gồm các chức năng:
    - Upload file tài liệu vào hệ thống RAG.
    - Truy vấn RAG để tìm kiếm và trả lời.
    - Download file tài liệu.
    - Quản lý session và lịch sử truy vấn.
    - Cập nhật payload field trong Qdrant.
"""

import logging

from fastapi import APIRouter, Depends, HTTPException, Query, Form, File, UploadFile
import os
from fastapi.responses import HTMLResponse, StreamingResponse
from sqlalchemy.orm import Session
from unidecode import unidecode

from auth.auth_middleware import require_roles, require_vllm_ready
from database.setup_postgres import get_db
from database.setup_qdrant import qdrant_service
from database.table.table_postgres import Account
from request.history_request import history_request, SessionRenameRequest, SessionCreateRequest
from request.rag_chat_request import rag_chat_request
from service.rag_service import (
    upload_service,
    # query_service,
    # download,
    load_file_service,
    load_sesion_service,
    delete_sesion_service,
    load_history_service,
    rag_contract_fast_service,
    rename_sesion_service,
    delete_file_service,
    pin_session_service,
    add_path_to_session_service,
    remove_path_from_session_service,
    create_sesion_service,
)

logger = logging.getLogger(__name__)

router = APIRouter()

# Tên collection Qdrant — dùng từ setup_qdrant để đảm bảo nhất quán với .env
from database.setup_qdrant import COLLECTION_NAME as QDRANT_COLLECTION_NAME


@router.get("/check")
async def check_rag_service():
    """
    Health check cho RAG service.

    Output:
        dict: {"status": "ok"}
    """

    return {"status": "ok"}


@router.get("/models")
async def get_models():
    """Lấy danh sách các model vLLM và API bên ngoài khả dụng."""
    from service.runtime_config_service import list_active_llm_model_items
    items = await list_active_llm_model_items()
    return {"status": 200, "models": items}


@router.post("/rag-contract")
async def rag_query_controller(
    request: rag_chat_request,
    db: Session = Depends(get_db),
    current_user: Account = Depends(require_roles(["rag"])),
):
    """
    Truy vấn RAG - tìm kiếm tài liệu liên quan và tạo câu trả lời.

    Input:
        request (rag_input_request): Chứa query, id_user, session_id.
        db (Session): Database session (inject qua Depends).

    Output:
        dict: Kết quả truy vấn (status, session, mess).
    """

    return await query_service(request, db)


@router.post("/rag-contract-fast")
async def rag_contract_fast_controller(
    request: rag_chat_request,
    current_user: Account = Depends(require_roles(["rag"])),
    _vllm: None = Depends(require_vllm_ready),
):
    """
    Truy vấn RAG Contract Fast — SSE streaming.

    Trả về Server-Sent Events stream, mỗi event là JSON:
    {"user_id", "session_id", "title", "mess", "end"}
    """
    generator = await rag_contract_fast_service(request, user_id=str(current_user.id))
    return StreamingResponse(generator, media_type="text/event-stream")


@router.get("/test-upload", response_class=HTMLResponse)
async def test_upload_html():
    """
    Endpoint trả về trang HTML để test upload nhiều file.
    """
    return """
    <!DOCTYPE html>
    <html lang="vi">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Test RAG Upload - Premium</title>
        <link href="https://fonts.googleapis.com/css2?family=Roboto:wght@300;400;500;700&display=swap" rel="stylesheet">
        <style>
            body { 
                font-family: 'Roboto', sans-serif; 
                background: linear-gradient(135deg, #1a1a2e 0%, #16213e 100%); 
                color: #e94560; 
                display: flex; 
                justify-content: center; 
                align-items: center; 
                min-height: 100vh; 
                margin: 0;
            }
            .container { 
                background: rgba(255, 255, 255, 0.05); 
                backdrop-filter: blur(10px); 
                padding: 40px; 
                border-radius: 20px; 
                box-shadow: 0 15px 35px rgba(0,0,0,0.5); 
                width: 450px; 
                border: 1px solid rgba(255,255,255,0.1);
            }
            h2 { text-align: center; color: #00d2ff; margin-bottom: 30px; font-weight: 300; letter-spacing: 2px; }
            .form-group { margin-bottom: 20px; }
            label { display: block; margin-bottom: 8px; color: #aaa; font-size: 0.9em; }
            input[type="number"], input[type="file"] { 
                width: 100%; 
                padding: 12px; 
                background: rgba(0,0,0,0.2); 
                border: 1px solid #333; 
                border-radius: 8px; 
                color: #fff; 
                box-sizing: border-box;
                transition: border-color 0.3s;
            }
            input:focus { border-color: #00d2ff; outline: none; }
            button { 
                width: 100%; 
                padding: 15px; 
                background: linear-gradient(45deg, #00d2ff, #3a7bd5); 
                border: none; 
                border-radius: 8px; 
                color: white; 
                font-size: 16px; 
                font-weight: 600; 
                cursor: pointer; 
                transition: transform 0.2s, box-shadow 0.2s;
                margin-top: 10px;
            }
            button:hover { transform: translateY(-2px); box-shadow: 0 5px 15px rgba(0,210,255,0.4); }
            #status { 
                margin-top: 25px; 
                padding: 15px; 
                border-radius: 8px; 
                display: none; 
                font-size: 0.9em;
                word-wrap: break-word;
                background: rgba(0,0,0,0.3);
                border: 1px solid #444;
            }
        </style>
    </head>
    <body>
        <div class="container">
            <h2>RAG UPLOAD TEST</h2>
            <div class="form-group">
                <label for="session_id">Session ID (0 = New)</label>
                <input type="number" id="session_id" value="0">
            </div>
            <div class="form-group">
                <label for="files">Chọn Files (Cần truyền key 'files')</label>
                <input type="file" id="files" multiple>
            </div>
            <button onclick="uploadFiles()">Bắt đầu Upload</button>
            <div id="status"></div>
        </div>

        <script>
            async function uploadFiles() {
                const filesInput = document.getElementById('files');
                const sessionId = document.getElementById('session_id').value;
                const statusDiv = document.getElementById('status');
                
                if (filesInput.files.length === 0) {
                    alert('Vui lòng chọn ít nhất 1 file');
                    return;
                }

                const formData = new FormData();
                formData.append('session_id', sessionId);
                for (let i = 0; i < filesInput.files.length; i++) {
                    formData.append('files', filesInput.files[i]);
                }

                statusDiv.style.display = 'block';
                statusDiv.innerHTML = '<span style="color: #00d2ff">Đang upload...</span>';
                statusDiv.style.borderColor = '#00d2ff';

                try {
                    const response = await fetch('/api/v1/rags/rag-upload', {
                        method: 'POST',
                        body: formData
                    });
                    const result = await response.json();
                    
                    if (response.ok) {
                        statusDiv.innerHTML = '<span style="color: #00ff88">✓ Thành công:</span><br><pre>' + JSON.stringify(result, null, 2) + '</pre>';
                        statusDiv.style.borderColor = '#00ff88';
                    } else {
                        statusDiv.innerHTML = '<span style="color: #ff4d4d">✗ Thất bại:</span><br><pre>' + JSON.stringify(result, null, 2) + '</pre>';
                        statusDiv.style.borderColor = '#ff4d4d';
                    }
                } catch (error) {
                    statusDiv.innerHTML = '<span style="color: #ff4d4d">✗ Lỗi kết nối: ' + error.message + '</span>';
                    statusDiv.style.borderColor = '#ff4d4d';
                }
            }
        </script>
    </body>
    </html>
    """


@router.get("/test-rag-contract-fast", response_class=HTMLResponse)
async def test_rag_contract_fast_html():
    """
    Endpoint trả về trang HTML để test SSE streaming của rag-contract-fast.
    """
    return """
    <!DOCTYPE html>
    <html lang="vi">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Test RAG Contract Fast - SSE Stream</title>
        <link href="https://fonts.googleapis.com/css2?family=Roboto+Mono:wght@300;400;500&family=Roboto:wght@300;400;500;700&display=swap" rel="stylesheet">
        <style>
            * { box-sizing: border-box; margin: 0; padding: 0; }
            body {
                font-family: 'Roboto', sans-serif;
                background: linear-gradient(135deg, #0f0c29 0%, #302b63 50%, #24243e 100%);
                color: #e0e0e0;
                min-height: 100vh;
                padding: 30px;
            }
            .container {
                max-width: 900px;
                margin: 0 auto;
            }
            h2 {
                text-align: center;
                color: #00d2ff;
                margin-bottom: 25px;
                font-weight: 300;
                letter-spacing: 2px;
                font-size: 1.5em;
            }
            .card {
                background: rgba(255, 255, 255, 0.05);
                backdrop-filter: blur(10px);
                border-radius: 16px;
                border: 1px solid rgba(255, 255, 255, 0.1);
                padding: 25px;
                margin-bottom: 20px;
            }
            .form-row {
                display: flex;
                gap: 15px;
                margin-bottom: 15px;
                flex-wrap: wrap;
            }
            .form-group {
                flex: 1;
                min-width: 200px;
            }
            label {
                display: block;
                margin-bottom: 6px;
                color: #aaa;
                font-size: 0.85em;
                font-weight: 500;
            }
            input, textarea {
                width: 100%;
                padding: 10px 12px;
                background: rgba(0, 0, 0, 0.3);
                border: 1px solid #444;
                border-radius: 8px;
                color: #fff;
                font-family: 'Roboto', sans-serif;
                font-size: 0.95em;
                transition: border-color 0.3s;
            }
            input:focus, textarea:focus {
                border-color: #00d2ff;
                outline: none;
            }
            textarea {
                resize: vertical;
                min-height: 60px;
            }
            .btn-row {
                display: flex;
                gap: 10px;
            }
            button {
                flex: 1;
                padding: 12px 20px;
                border: none;
                border-radius: 8px;
                font-size: 14px;
                font-weight: 600;
                cursor: pointer;
                transition: transform 0.2s, box-shadow 0.2s;
            }
            button:hover { transform: translateY(-1px); }
            .btn-send {
                background: linear-gradient(45deg, #00d2ff, #3a7bd5);
                color: white;
            }
            .btn-send:hover { box-shadow: 0 4px 15px rgba(0, 210, 255, 0.4); }
            .btn-stop {
                background: linear-gradient(45deg, #ff4d4d, #ff6b6b);
                color: white;
                flex: 0.3;
            }
            .btn-clear {
                background: rgba(255, 255, 255, 0.1);
                color: #aaa;
                border: 1px solid #555;
                flex: 0.3;
            }

            /* SSE Progress Steps */
            .progress-area {
                margin-bottom: 15px;
            }
            .progress-area h4 {
                color: #00d2ff;
                font-weight: 400;
                margin-bottom: 10px;
                font-size: 0.9em;
            }
            .step-list {
                list-style: none;
                padding: 0;
            }
            .step-list li {
                padding: 8px 12px;
                margin-bottom: 4px;
                border-radius: 6px;
                font-size: 0.85em;
                display: flex;
                align-items: flex-start;
                gap: 8px;
                background: rgba(0, 210, 255, 0.05);
                border-left: 3px solid #00d2ff;
                animation: fadeIn 0.3s ease;
            }
            .step-list li .step-icon { flex-shrink: 0; }
            .step-list li .step-title { font-weight: 500; color: #00d2ff; }
            .step-list li .step-mess { color: #999; margin-left: 4px; }

            /* LLM Streaming Area */
            .response-area {
                background: rgba(0, 0, 0, 0.3);
                border: 1px solid #333;
                border-radius: 10px;
                padding: 15px;
                min-height: 150px;
                max-height: 500px;
                overflow-y: auto;
                font-family: 'Roboto', sans-serif;
                font-size: 0.95em;
                line-height: 1.7;
                white-space: pre-wrap;
                word-wrap: break-word;
            }
            .response-area .cursor-blink {
                display: inline-block;
                width: 2px;
                height: 1em;
                background: #00d2ff;
                animation: blink 0.8s infinite;
                vertical-align: text-bottom;
            }

            /* Raw Events */
            .raw-toggle {
                margin-top: 10px;
                color: #666;
                font-size: 0.8em;
                cursor: pointer;
                user-select: none;
            }
            .raw-toggle:hover { color: #aaa; }
            .raw-events {
                display: none;
                margin-top: 8px;
                background: rgba(0, 0, 0, 0.4);
                border-radius: 8px;
                padding: 10px;
                max-height: 300px;
                overflow-y: auto;
                font-family: 'Roboto Mono', monospace;
                font-size: 0.75em;
                color: #888;
                line-height: 1.5;
            }

            .status-badge {
                display: inline-block;
                padding: 3px 10px;
                border-radius: 12px;
                font-size: 0.8em;
                font-weight: 500;
            }
            .status-idle { background: rgba(255,255,255,0.1); color: #888; }
            .status-streaming { background: rgba(0,210,255,0.2); color: #00d2ff; }
            .status-done { background: rgba(0,255,136,0.2); color: #00ff88; }
            .status-error { background: rgba(255,77,77,0.2); color: #ff4d4d; }

            @keyframes fadeIn { from { opacity: 0; transform: translateX(-10px); } to { opacity: 1; transform: translateX(0); } }
            @keyframes blink { 0%, 100% { opacity: 1; } 50% { opacity: 0; } }
        </style>
    </head>
    <body>
        <div class="container">
            <h2>&#x26A1; RAG CONTRACT FAST &mdash; SSE STREAM TEST</h2>

            <!-- Input Form -->
            <div class="card">
                <div class="form-row">
                    <div class="form-group">
                        <label>Session ID (-1 = m&#7899;i)</label>
                        <input type="number" id="session_id" value="-1">
                    </div>
                </div>
                <div class="form-group" style="margin-bottom:15px;">
                    <label>C&acirc;u h&#7887;i</label>
                    <textarea id="user_input" rows="2" placeholder="Nh&#7853;p c&acirc;u h&#7887;i c&#7911;a b&#7841;n...">T&igrave;m h&#7907;p &#273;&#7891;ng mua b&aacute;n thi&#7871;t b&#7883; v&#259;n ph&ograve;ng</textarea>
                </div>
                <div class="form-group" style="margin-bottom:15px;">
                    <label>File paths (m&#7895;i d&ograve;ng 1 path, &#273;&#7875; tr&#7889;ng n&#7871;u t&#7921; &#273;&#7897;ng)</label>
                    <textarea id="file_paths" rows="2" placeholder="raw-files/file1.pdf&#10;raw-files/file2.pdf"></textarea>
                </div>
                <div class="form-group" style="margin-bottom:15px;">
                    <label>Authorization Token (Bearer)</label>
                    <input type="text" id="auth_token" placeholder="Paste JWT token t&#7841;i &#273;&acirc;y...">
                </div>
                <div class="btn-row">
                    <button class="btn-send" id="btnSend" onclick="startStream()">G&#7917;i &amp; Stream</button>
                    <button class="btn-stop" id="btnStop" onclick="stopStream()" disabled>D&#7915;ng</button>
                    <button class="btn-clear" onclick="clearAll()">X&oacute;a</button>
                </div>
            </div>

            <!-- Output -->
            <div class="card">
                <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:12px;">
                    <h4 style="color:#00d2ff; font-weight:400;">K&#7871;t qu&#7843;</h4>
                    <span class="status-badge status-idle" id="statusBadge">Ch&#432;a g&#7917;i</span>
                </div>

                <div class="progress-area" id="progressArea">
                    <h4>&#128640; Ti&#7871;n tr&igrave;nh x&#7917; l&yacute;</h4>
                    <ul class="step-list" id="stepList"></ul>
                </div>

                <div class="response-area" id="responseArea">
                    <span style="color:#666;">C&acirc;u tr&#7843; l&#7901;i s&#7869; xu&#7845;t hi&#7879;n t&#7841;i &#273;&acirc;y...</span>
                </div>

                <div class="raw-toggle" onclick="toggleRaw()">&#9660; Hi&#7879;n raw SSE events</div>
                <div class="raw-events" id="rawEvents"></div>
            </div>
        </div>

        <script>
            let abortController = null;
            let isStreaming = false;
            let responseStarted = false;

            function setStatus(type, text) {
                const badge = document.getElementById('statusBadge');
                badge.className = 'status-badge status-' + type;
                badge.textContent = text;
            }

            function addStep(title, mess) {
                const li = document.createElement('li');
                li.innerHTML = '<span class="step-icon">&#9679;</span>'
                    + '<span class="step-title">' + escapeHtml(title) + '</span>'
                    + (mess ? '<span class="step-mess">&mdash; ' + escapeHtml(mess) + '</span>' : '');
                document.getElementById('stepList').appendChild(li);
            }

            function appendRaw(text) {
                const el = document.getElementById('rawEvents');
                el.textContent += text + '\\n';
                el.scrollTop = el.scrollHeight;
            }

            function toggleRaw() {
                const el = document.getElementById('rawEvents');
                el.style.display = el.style.display === 'none' ? 'block' : 'none';
            }

            function escapeHtml(str) {
                const div = document.createElement('div');
                div.appendChild(document.createTextNode(str));
                return div.innerHTML;
            }

            function clearAll() {
                document.getElementById('stepList').innerHTML = '';
                document.getElementById('responseArea').innerHTML = '<span style="color:#666;">C&acirc;u tr&#7843; l&#7901;i s&#7869; xu&#7845;t hi&#7879;n t&#7841;i &#273;&acirc;y...</span>';
                document.getElementById('rawEvents').textContent = '';
                setStatus('idle', 'Ch\\u01b0a g\\u1eedi');
                responseStarted = false;
            }

            async function startStream() {
                if (isStreaming) return;

                // Clear previous
                document.getElementById('stepList').innerHTML = '';
                document.getElementById('responseArea').innerHTML = '';
                document.getElementById('rawEvents').textContent = '';
                responseStarted = false;

                const sessionId = parseInt(document.getElementById('session_id').value);
                const userInput = document.getElementById('user_input').value.trim();
                const authToken = document.getElementById('auth_token').value.trim();
                const filePathsRaw = document.getElementById('file_paths').value.trim();
                const filePaths = filePathsRaw ? filePathsRaw.split('\\n').map(s => s.trim()).filter(Boolean) : [];

                if (!userInput) { alert('Vui l\\u00f2ng nh\\u1eadp c\\u00e2u h\\u1ecfi'); return; }
                if (!authToken) { alert('Vui l\\u00f2ng nh\\u1eadp token x\\u00e1c th\\u1ef1c'); return; }

                const body = {
                    session_id: sessionId,
                    user_input: userInput,
                };

                abortController = new AbortController();
                isStreaming = true;
                document.getElementById('btnSend').disabled = true;
                document.getElementById('btnStop').disabled = false;
                setStatus('streaming', '\\u0110ang stream...');

                try {
                    const resp = await fetch('/api/v1/rags/rag-contract-fast', {
                        method: 'POST',
                        headers: {
                            'Content-Type': 'application/json',
                            'Authorization': 'Bearer ' + authToken,
                        },
                        body: JSON.stringify(body),
                        signal: abortController.signal,
                    });

                    if (!resp.ok) {
                        const errText = await resp.text();
                        setStatus('error', 'L\\u1ed7i ' + resp.status);
                        document.getElementById('responseArea').innerHTML =
                            '<span style="color:#ff4d4d;">HTTP ' + resp.status + ': ' + escapeHtml(errText) + '</span>';
                        return;
                    }

                    const reader = resp.body.getReader();
                    const decoder = new TextDecoder();
                    let buffer = '';

                    while (true) {
                        const { done, value } = await reader.read();
                        if (done) break;

                        buffer += decoder.decode(value, { stream: true });
                        const lines = buffer.split('\\n');
                        buffer = lines.pop(); // keep incomplete line

                        for (const line of lines) {
                            if (!line.startsWith('data: ')) continue;
                            const jsonStr = line.slice(6);
                            appendRaw(jsonStr);

                            try {
                                const event = JSON.parse(jsonStr);

                                if (event.end) {
                                    // Update session_id if returned
                                    if (event.session_id && event.session_id > 0) {
                                        document.getElementById('session_id').value = event.session_id;
                                    }
                                    setStatus('done', 'Ho\\u00e0n th\\u00e0nh');
                                    // Remove cursor
                                    const cursor = document.querySelector('.cursor-blink');
                                    if (cursor) cursor.remove();
                                    break;
                                }

                                const title = event.title || '';
                                const mess = event.mess || '';

                                if (title === '\\u0110ang tr\\u1ea3 l\\u1eddi...' && mess) {
                                    // LLM token streaming
                                    if (!responseStarted) {
                                        document.getElementById('responseArea').innerHTML = '';
                                        responseStarted = true;
                                    }
                                    // Remove old cursor, append token, add cursor
                                    const cursor = document.querySelector('.cursor-blink');
                                    if (cursor) cursor.remove();
                                    const responseArea = document.getElementById('responseArea');
                                    responseArea.insertAdjacentText('beforeend', mess);
                                    responseArea.insertAdjacentHTML('beforeend', '<span class="cursor-blink"></span>');
                                    responseArea.scrollTop = responseArea.scrollHeight;

                                } else if (title) {
                                    // Progress step
                                    addStep(title, mess);
                                }

                            } catch (e) {
                                appendRaw('[PARSE ERROR] ' + e.message);
                            }
                        }
                    }

                } catch (e) {
                    if (e.name === 'AbortError') {
                        setStatus('idle', '\\u0110\\u00e3 d\\u1eebng');
                    } else {
                        setStatus('error', 'L\\u1ed7i k\\u1ebft n\\u1ed1i');
                        document.getElementById('responseArea').innerHTML =
                            '<span style="color:#ff4d4d;">L\\u1ed7i: ' + escapeHtml(e.message) + '</span>';
                    }
                } finally {
                    isStreaming = false;
                    document.getElementById('btnSend').disabled = false;
                    document.getElementById('btnStop').disabled = true;
                }
            }

            function stopStream() {
                if (abortController) {
                    abortController.abort();
                    abortController = null;
                }
            }
        </script>
    </body>
    </html>
    """


@router.post("/rag-upload")
async def rag_upload_controller(
    files: list[UploadFile],
    session_id: int = Form(0),
    db: Session = Depends(get_db),
    current_user: Account = Depends(require_roles(["root", "upload"])),
):
    """
    Upload nhiều file tài liệu vào hệ thống RAG (PDF, DOCX, TXT...).

    Input:
        files (list[UploadFile]): Danh sách file tài liệu (PDF, DOCX, ...). Mặc định là mảng rỗng để chặn lỗi 422 từ FastAPI.

    Output:
        dict: Kết quả upload. Trả về status 400 nếu không có file nào được đính kèm.
    """

    if not files or len(files) == 0:
        return {
            "status": 400,
            "mess": "Dữ liệu upload không hợp lệ. Vui lòng gửi ít nhất một file với thuộc tính 'files'."
        }

    # --- Kiểm tra extension hợp lệ cho RAG ---
    ALLOWED_EXTENSIONS = {".pdf", ".docx", ".doc", ".pptx", ".ppt", ".csv", ".jpg", ".jpeg", ".png", ".bmp", ".tiff", ".webp"}
    for f in files:
        ext = "." + f.filename.rsplit(".", 1)[-1].lower() if "." in f.filename else ""
        if ext not in ALLOWED_EXTENSIONS:
            return {
                "status": 400,
                "mess": f"Định dạng tệp {f.filename} không được hỗ trợ. Chỉ cho phép các định dạng: PDF, MS Office (Word, PPT), CSV và hình ảnh."
            }

    # --- Kiểm tra giới hạn dung lượng cho user RAG (không phải upload/root) ---
    user_roles = [ar.role.name for ar in current_user.account_roles if ar.role]
    is_admin = any(r in ["root", "upload"] for r in user_roles)

    if not is_admin:
        max_size_mb = int(os.getenv("RAG_UPLOAD_MAX_SIZE_MB", "10"))
        max_size_bytes = max_size_mb * 1024 * 1024
        
        for f in files:
            # Starlette UploadFile có .size (nếu không có thì f.file.seek(0, 2) sau đó tell())
            file_size = f.size if hasattr(f, "size") and f.size is not None else 0
            
            if file_size > max_size_bytes:
                raise HTTPException(
                    status_code=413, 
                    detail=f"Dung lượng file {f.filename} vượt quá giới hạn {max_size_mb}MB đối với tài khoản RAG."
                )

    return await upload_service(files, session_id=session_id, user_id=current_user.id)


@router.get("/file")
async def load_file(
    current_user: Account = Depends(require_roles(["rag"])),
):
    """
    Lấy danh sách tất cả file tài liệu đã upload.

    Output:
        dict: Danh sách file (status, result).
    """

    return await load_file_service()


@router.delete("/file")
async def delete_file(
    path: str,
    current_user: Account = Depends(require_roles(["upload"])),
):
    """
    Xóa một file tài liệu đã upload (Postgres, Qdrant, MinIO).

    Input:
        path (str): Tên file cần xóa.
    """

    return await delete_file_service(path)


@router.get("/sesion")
async def get_rag_sessions(
    db: Session = Depends(get_db),
    current_user: Account = Depends(require_roles(["rag"])),
):
    """
    Lấy danh sách tất cả session RAG.

    Input:
        db (Session): Database session (inject qua Depends).

    Output:
        dict: Danh sách session (status, result).
    """

    return await load_sesion_service(db, user_id=str(current_user.id))


@router.delete("/sesion/{id}")
async def delete_rag_session(
    id: int,
    db: Session = Depends(get_db),
    current_user: Account = Depends(require_roles(["rag"])),
):
    """
    Xóa session RAG và toàn bộ lịch sử liên quan.

    Input:
        id (int): ID session cần xóa.
        db (Session): Database session (inject qua Depends).

    Output:
        dict: Kết quả xóa (status, result).
    """

    return await delete_sesion_service(db, id=id, user_id=str(current_user.id))


@router.post("/session/pin/{id}")
async def pin_rag_session(
    id: int,
    db: Session = Depends(get_db),
    current_user: Account = Depends(require_roles(["rag"])),
):
    """Ghim một session RAG."""
    return await pin_session_service(db, id, pin=True)


@router.delete("/session/pin/{id}")
async def unpin_rag_session(
    id: int,
    db: Session = Depends(get_db),
    current_user: Account = Depends(require_roles(["rag"])),
):
    """Bỏ ghim một session RAG."""
    return await pin_session_service(db, id, pin=False)


@router.post("/session/path")
async def add_path_to_session(
    session_id: int = Form(...),
    path: str = Form(...),
    db: Session = Depends(get_db),
    current_user: Account = Depends(require_roles(["rag"])),
):
    """Thêm một file_path vào session."""
    return await add_path_to_session_service(db, session_id, path)


@router.delete("/session/path")
async def remove_path_from_session(
    session_id: int = Form(...),
    path: str = Form(...),
    db: Session = Depends(get_db),
    current_user: Account = Depends(require_roles(["rag"])),
):
    """Xóa một file_path khỏi session."""
    return await remove_path_from_session_service(db, session_id, path)


@router.put("/session/rename")
async def rename_rag_session(
    request: SessionRenameRequest,
    db: Session = Depends(get_db),
    current_user: Account = Depends(require_roles(["rag"])),
):
    """Đổi tên một session RAG."""
    return await rename_sesion_service(db, request.session_id, request.new_name)


@router.post("/session")
async def create_rag_session(
    request: SessionCreateRequest,
    db: Session = Depends(get_db),
    current_user: Account = Depends(require_roles(["rag"])),
):
    """
    Tạo một session RAG mới.
    """
    return await create_sesion_service(db, user_id=str(current_user.id), name=request.name)


@router.post("/history")
async def load_rag_history(
    request: history_request,
    db: Session = Depends(get_db),
    current_user: Account = Depends(require_roles(["rag"])),
):
    """
    Lấy lịch sử chat RAG theo session.

    Input:
        request (history_reques): Chứa session_id và user_id.
        db (Session): Database session (inject qua Depends).

    Output:
        dict: Danh sách tin nhắn trong session (status, result).
    """

    return await load_history_service(request, db, user_id=str(current_user.id))
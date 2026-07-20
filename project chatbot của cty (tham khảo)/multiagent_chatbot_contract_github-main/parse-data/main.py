"""
Entry point cho Parse-Data FastAPI server.

Server chuyên parse PDF sang markdown sử dụng Docling,
cấu hình GPU (CUDA) để tối ưu hiệu năng production.
"""

import logging
import os
from pathlib import Path

from dotenv import load_dotenv

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
import uvicorn

from src.router.parse_router import router as parse_router


ROOT_DIR = Path(__file__).resolve().parent.parent
ROOT_ENV_ALL_PATH = ROOT_DIR / ".env.all"
ROOT_ENV_PATH = ROOT_DIR / ".env"

# Env tập trung ở project root. Frontend là service duy nhất giữ env riêng.
if ROOT_ENV_ALL_PATH.exists():
    load_dotenv(ROOT_ENV_ALL_PATH, override=False)
if ROOT_ENV_PATH.exists():
    load_dotenv(ROOT_ENV_PATH, override=True)

SERVER_HOST = os.getenv("PARSER_SERVER_HOST", "0.0.0.0")
SERVER_PORT = int(os.getenv("PARSER_SERVER_PORT", "8005"))
SERVER_RELOAD = os.getenv("PARSER_SERVER_RELOAD", "true").strip().lower() == "true"


# --- Cấu hình logging chuẩn production ---
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)

logger = logging.getLogger(__name__)


# --- Khởi tạo FastAPI app ---
app = FastAPI(
    title="Parse-Data Service",
    description="API parse PDF sang markdown bằng Docling (GPU acceleration)",
    version="1.0.0"
)


# --- CORS middleware cho phép frontend gọi API ---
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# --- Gắn router ---
app.include_router(parse_router, prefix="/api/v1", tags=["parse"])

# Export metrics cho Prometheus
try:
    from prometheus_fastapi_instrumentator import Instrumentator
    Instrumentator().instrument(app).expose(app, include_in_schema=False)
    logger.info("Prometheus Instrumentator initialized at /metrics")
except ImportError:
    logger.warning("prometheus_fastapi_instrumentator not installed, /metrics disabled")

# --- Health check endpoint ---
@app.get("/health")
def health_check():
    """
    Kiểm tra server đang hoạt động.

    Input: Không có
    Output: dict - Trạng thái server
    """

    return {"status": "ok", "message": "Parse-Data service is running"}


# --- Trang test upload file (thay thế Swagger UI cho multi-file upload) ---
@app.get("/test", response_class=HTMLResponse)
def test_upload_page():
    """
    Trang HTML test upload nhiều file PDF.

    Input: Không có
    Output: HTMLResponse - Form upload file
    """

    return """
    <!DOCTYPE html>
    <html lang="vi">
    <head>
        <meta charset="UTF-8">
        <title>Parse-Data Test</title>
        <style>
            * { box-sizing: border-box; margin: 0; padding: 0; }
            body { font-family: 'Segoe UI', sans-serif; background: #0f172a; color: #e2e8f0; min-height: 100vh; display: flex; align-items: center; justify-content: center; }
            .container { background: #1e293b; border-radius: 16px; padding: 40px; max-width: 600px; width: 90%; box-shadow: 0 25px 50px rgba(0,0,0,0.4); }
            h1 { font-size: 24px; margin-bottom: 8px; background: linear-gradient(135deg, #38bdf8, #818cf8); -webkit-background-clip: text; -webkit-text-fill-color: transparent; }
            p.sub { color: #94a3b8; margin-bottom: 24px; font-size: 14px; }
            .upload-area { border: 2px dashed #334155; border-radius: 12px; padding: 32px; text-align: center; cursor: pointer; transition: all 0.3s; margin-bottom: 20px; }
            .upload-area:hover { border-color: #38bdf8; background: #1e293b; }
            .upload-area.dragover { border-color: #818cf8; background: rgba(129,140,248,0.1); }
            .upload-area input { display: none; }
            .upload-area .icon { font-size: 40px; margin-bottom: 8px; }
            .file-list { margin-bottom: 20px; }
            .file-item { background: #334155; border-radius: 8px; padding: 10px 14px; margin-bottom: 6px; display: flex; justify-content: space-between; align-items: center; font-size: 13px; }
            .file-item .name { color: #e2e8f0; } .file-item .size { color: #64748b; }
            .file-item .remove { color: #f87171; cursor: pointer; font-weight: bold; }
            button { width: 100%; padding: 14px; background: linear-gradient(135deg, #38bdf8, #818cf8); color: #fff; border: none; border-radius: 10px; font-size: 16px; font-weight: 600; cursor: pointer; transition: opacity 0.2s; }
            button:hover { opacity: 0.9; } button:disabled { opacity: 0.5; cursor: not-allowed; }
            .result { margin-top: 24px; background: #0f172a; border-radius: 10px; padding: 16px; max-height: 400px; overflow-y: auto; font-size: 13px; white-space: pre-wrap; word-break: break-word; display: none; }
            .result.show { display: block; }
            .loader { display: none; text-align: center; margin-top: 16px; color: #38bdf8; }
            .loader.show { display: block; }
        </style>
    </head>
    <body>
        <div class="container">
            <h1>📄 Parse Documents & Images</h1>
            <p class="sub">Upload tối đa 10 file (PDF, DOCX, PPTX, CSV, ảnh) — Docling + GPU + EasyOCR</p>

            <div class="upload-area" id="dropZone" onclick="document.getElementById('fileInput').click()">
                <div class="icon">📁</div>
                <div>Click hoặc kéo thả file vào đây</div>
                <input type="file" id="fileInput" multiple accept=".pdf,.docx,.doc,.pptx,.ppt,.csv,.jpg,.jpeg,.png,.bmp,.tiff,.webp">
            </div>

            <div class="file-list" id="fileList"></div>

            <button id="submitBtn" onclick="submitFiles()" disabled>🚀 Parse Files</button>

            <div class="loader" id="loader">⏳ Đang parse... (có thể mất vài phút)</div>
            <pre class="result" id="result"></pre>
        </div>

        <script>
            let selectedFiles = [];
            const fileInput = document.getElementById('fileInput');
            const fileList = document.getElementById('fileList');
            const submitBtn = document.getElementById('submitBtn');
            const dropZone = document.getElementById('dropZone');

            fileInput.addEventListener('change', (e) => addFiles(e.target.files));

            dropZone.addEventListener('dragover', (e) => { e.preventDefault(); dropZone.classList.add('dragover'); });
            dropZone.addEventListener('dragleave', () => dropZone.classList.remove('dragover'));
            dropZone.addEventListener('drop', (e) => { e.preventDefault(); dropZone.classList.remove('dragover'); addFiles(e.dataTransfer.files); });

            function addFiles(files) {
                for (const f of files) {
                    if (selectedFiles.length >= 10) break;
                    const ext = f.name.split('.').pop().toLowerCase();
                    const allowed = ['pdf','docx','doc','pptx','ppt','csv','jpg','jpeg','png','bmp','tiff','webp'];
                    if (!allowed.includes(ext)) { alert(f.name + ' — định dạng không hỗ trợ'); continue; }
                    selectedFiles.push(f);
                }
                renderFileList();
            }

            function removeFile(idx) { selectedFiles.splice(idx, 1); renderFileList(); }

            function renderFileList() {
                fileList.innerHTML = selectedFiles.map((f, i) =>
                    `<div class="file-item"><span class="name">${f.name}</span><span class="size">${(f.size/1024).toFixed(0)} KB</span><span class="remove" onclick="removeFile(${i})">✕</span></div>`
                ).join('');
                submitBtn.disabled = selectedFiles.length === 0;
            }

            async function submitFiles() {
                const fd = new FormData();
                selectedFiles.forEach(f => fd.append('files', f));
                submitBtn.disabled = true;
                document.getElementById('loader').classList.add('show');
                document.getElementById('result').classList.remove('show');
                try {
                    const res = await fetch('/api/v1/parse', { method: 'POST', body: fd });
                    const data = await res.json();
                    document.getElementById('result').textContent = JSON.stringify(data, null, 2);
                    document.getElementById('result').classList.add('show');
                } catch (err) {
                    document.getElementById('result').textContent = 'Error: ' + err.message;
                    document.getElementById('result').classList.add('show');
                }
                document.getElementById('loader').classList.remove('show');
                submitBtn.disabled = false;
            }
        </script>
    </div></body>
    </html>
    """


# --- Chạy server ---
if __name__ == "__main__":
    logger.info("=" * 50)
    logger.info("Parse-Data service đang khởi động...")
    logger.info("=" * 50)

    uvicorn.run(
        "main:app",
        host=SERVER_HOST,
        port=SERVER_PORT,
        reload=SERVER_RELOAD
    )

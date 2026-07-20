"""
Entry point cho Embedding FastAPI server.

Server cung cấp 2 endpoint:
- /api/v1/embed: tạo embedding vectors (Qwen3-Embedding-0.6B)
- /api/v1/rerank: xếp hạng documents (bge-reranker-v2-m3)

Cả 2 model chạy trên GPU với fp16 để tối ưu hiệu năng.
"""

import logging
import os
from pathlib import Path

from dotenv import load_dotenv

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import uvicorn

from src.router.embedding_router import router as embedding_router


ROOT_DIR = Path(__file__).resolve().parent.parent
ROOT_ENV_ALL_PATH = ROOT_DIR / ".env.all"
ROOT_ENV_PATH = ROOT_DIR / ".env"

# Env tập trung ở project root. Frontend là service duy nhất giữ env riêng.
if ROOT_ENV_ALL_PATH.exists():
    load_dotenv(ROOT_ENV_ALL_PATH, override=False)
if ROOT_ENV_PATH.exists():
    load_dotenv(ROOT_ENV_PATH, override=True)

SERVER_HOST = os.getenv("EMBEDDING_SERVER_HOST", "0.0.0.0")
SERVER_PORT = int(os.getenv("EMBEDDING_SERVER_PORT", "8006"))
SERVER_RELOAD = os.getenv("EMBEDDING_SERVER_RELOAD", "false").strip().lower() == "true"


# --- Cấu hình logging chuẩn production ---
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)

logger = logging.getLogger(__name__)


# --- Khởi tạo FastAPI app ---
app = FastAPI(
    title="Embedding & Reranking Service",
    description="API embedding (Qwen3) và reranking (BGE) trên GPU",
    version="1.0.0"
)


# --- CORS middleware ---
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# --- Gắn router ---
app.include_router(embedding_router, prefix="/api/v1", tags=["embedding"])

# Export metrics cho Prometheus
try:
    from prometheus_fastapi_instrumentator import Instrumentator
    Instrumentator().instrument(app).expose(app, include_in_schema=False)
    logger.info("Prometheus Instrumentator initialized at /metrics")
except ImportError:
    logger.warning("prometheus_fastapi_instrumentator not installed, /metrics disabled")

# --- Health check ---
@app.get("/health")
def health_check():
    """
    Kiểm tra server đang hoạt động.

    Input: Không có
    Output: dict - Trạng thái server
    """

    return {"status": "ok", "message": "Embedding service is running"}


# --- Chạy server ---
if __name__ == "__main__":
    logger.info("=" * 50)
    logger.info("Embedding service đang khởi động...")
    logger.info("=" * 50)

    uvicorn.run(
        "main:app",
        host=SERVER_HOST,
        port=SERVER_PORT,
        reload=SERVER_RELOAD
    )

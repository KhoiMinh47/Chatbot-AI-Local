import uvicorn
import logging
import os
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI
from src.controller.metrics_controller import router as metrics_router


ROOT_DIR = Path(__file__).resolve().parent.parent
ROOT_ENV_ALL_PATH = ROOT_DIR / ".env.all"
ROOT_ENV_PATH = ROOT_DIR / ".env"

# Env tập trung ở project root. Frontend là service duy nhất giữ env riêng.
if ROOT_ENV_ALL_PATH.exists():
    load_dotenv(ROOT_ENV_ALL_PATH, override=False)
if ROOT_ENV_PATH.exists():
    load_dotenv(ROOT_ENV_PATH, override=True)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="Prometheus Collector Service",
    description="Dedicated microservice for fetching and caching system metrics from Prometheus",
    version="1.0.0"
)

# Include metrics router with /api/v1 prefix
app.include_router(metrics_router, prefix="/api/v1")

@app.get("/")
async def root():
    return {"message": "Prometheus Collector Service is running", "status": "ok"}

if __name__ == "__main__":
    # Internal port for collector, e.g., 9005
    host = os.getenv("PROM_COLLECTOR_SERVER_HOST", "0.0.0.0")
    port = int(os.getenv("PROM_COLLECTOR_SERVER_PORT", "9005"))
    reload_mode = os.getenv("PROM_COLLECTOR_SERVER_RELOAD", "true").strip().lower() == "true"
    uvicorn.run("main:app", host=host, port=port, reload=reload_mode)

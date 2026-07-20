import httpx
import logging
import os
from pathlib import Path
from dotenv import load_dotenv

ROOT_ENV_ALL_PATH = Path(__file__).resolve().parents[2] / ".env.all"
ROOT_ENV_PATH = Path(__file__).resolve().parents[2] / ".env"

# Env tập trung ở project root. Frontend là service duy nhất giữ env riêng.
if ROOT_ENV_ALL_PATH.exists():
    load_dotenv(ROOT_ENV_ALL_PATH, override=False)
if ROOT_ENV_PATH.exists():
    load_dotenv(ROOT_ENV_PATH, override=True)

logger = logging.getLogger(__name__)

# URL of our dedicated prometheus-collector microservice
PROMETHEUS_COLLECTOR_URL = os.getenv("PROMETHEUS_COLLECTOR_URL")

async def get_system_metrics():
    """
    Calls the dedicated Prometheus Collector service to fetch all metrics.
    The collector handles parallel fetching and caching.
    """
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.get(PROMETHEUS_COLLECTOR_URL)
            response.raise_for_status()
            data = response.json()
            
            if data.get("success") and "metrics" in data:
                return data["metrics"]
            return {}
    except Exception as e:
        logger.error(f"Error calling Prometheus Collector service: {e}")
        return {}

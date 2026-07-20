from fastapi import APIRouter, HTTPException
import logging
from src.service.prometheus_service import get_system_metrics

logger = logging.getLogger(__name__)

router = APIRouter()

@router.get("/metrics")
async def get_metrics():
    """
    Endpoint to fetch all system metrics from Prometheus.
    """
    try:
        metrics = await get_system_metrics()
        return {
            "metrics": metrics,
            "success": True
        }
    except Exception as e:
        logger.error(f"Error in metrics controller: {e}")
        raise HTTPException(status_code=500, detail="Internal server error while fetching metrics")

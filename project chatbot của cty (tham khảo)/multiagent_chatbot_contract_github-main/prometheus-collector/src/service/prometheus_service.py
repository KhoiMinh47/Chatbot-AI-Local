import httpx
import logging
import os
import asyncio
import time
from pathlib import Path
from dotenv import load_dotenv

ROOT_ENV_ALL_PATH = Path(__file__).resolve().parents[3] / ".env.all"
ROOT_ENV_PATH = Path(__file__).resolve().parents[3] / ".env"

# Env tập trung ở project root. Frontend là service duy nhất giữ env riêng.
if ROOT_ENV_ALL_PATH.exists():
    load_dotenv(ROOT_ENV_ALL_PATH, override=False)
if ROOT_ENV_PATH.exists():
    load_dotenv(ROOT_ENV_PATH, override=True)

logger = logging.getLogger(__name__)

# Prometheus URL from host perspective
PROMETHEUS_URL = os.getenv("PROMETHEUS_URL")

# Simple TTL Cache
_cache = {
    "data": None,
    "expiry": 0
}
CACHE_TTL = 10  # seconds

async def query_prometheus(client: httpx.AsyncClient, query: str):
    """
    Query Prometheus API for a single metric value.
    """
    try:
        response = await client.get(f"{PROMETHEUS_URL}/api/v1/query", params={"query": query})
        response.raise_for_status()
        data = response.json()
        
        if data["status"] == "success" and data["data"]["result"]:
            return data["data"]["result"]
        return []
    except Exception as e:
        logger.error(f"Error querying Prometheus for {query}: {e}")
        return []

async def get_system_metrics():
    """
    Fetches 15+ metrics corresponding to the native dashboard panels.
    Uses parallel fetching and simple caching.
    """
    global _cache
    
    # Check cache
    now = time.time()
    if _cache["data"] and now < _cache["expiry"]:
        logger.info("Returning metrics from cache")
        return _cache["data"]

    queries = {
        "core_services": 'max by (job) (up{job=~"fastapi-backend|fastapi-parser|fastapi-embedding|qdrant|minio|postgres|redis|vllm"})',
        "cpu_usage": '100 - (avg(rate(node_cpu_seconds_total{mode="idle"}[5m])) * 100)',
        "ram_usage": '(node_memory_MemTotal_bytes - node_memory_MemAvailable_bytes) / node_memory_MemTotal_bytes * 100',
        "disk_used": '100 - ((node_filesystem_avail_bytes{mountpoint="/", fstype=~"ext4|xfs|btrfs"} * 100) / node_filesystem_size_bytes{mountpoint="/", fstype=~"ext4|xfs|btrfs"})',
        "gpu_temp": 'max(DCGM_FI_DEV_GPU_TEMP)',
        "gpu_util": 'max(DCGM_FI_DEV_GPU_UTIL)',
        "vram_usage": '(max(DCGM_FI_DEV_FB_USED) / max(DCGM_FI_DEV_FB_FREE + DCGM_FI_DEV_FB_USED)) * 100',
        "kv_cache": 'max(vllm:gpu_cache_usage_perc) * 100',
        "vllm_running": 'sum(vllm:num_requests_running)',
        "vllm_waiting": 'sum(vllm:num_requests_waiting)',
        "token_gen": 'sum(rate(vllm:generation_tokens_total[1m]))',
        "token_prompt": 'sum(rate(vllm:prompt_tokens_total[1m]))',
        "api_traffic": 'sum by (job) (rate(http_requests_total{job=~"fastapi-backend|fastapi-parser|fastapi-embedding"}[1m]))',
        "api_latency": 'sum by (job) (rate(http_request_duration_seconds_sum{job=~"fastapi-backend|fastapi-parser|fastapi-embedding"}[1m])) / sum by (job) (rate(http_request_duration_seconds_count{job=~"fastapi-backend|fastapi-parser|fastapi-embedding"}[1m]))',
        "api_errors": 'sum by (job) (rate(http_requests_total{job=~"fastapi-backend|fastapi-parser|fastapi-embedding", status=~"4..|5.."}[1m]))',
        "qdrant_vectors": 'collections_vector_total',
        "postgres_conns": 'sum(pg_stat_database_numbackends)',
        "redis_mem": 'redis_memory_used_bytes',
        "minio_storage": 'minio_cluster_usage_total_bytes'
    }

    results = {}
    async with httpx.AsyncClient(timeout=10.0) as client:
        # Create tasks for all queries
        tasks = {key: query_prometheus(client, q) for key, q in queries.items()}
        
        # Execute in parallel
        query_results = await asyncio.gather(*tasks.values())
        
        # Map back to keys
        map_results = dict(zip(tasks.keys(), query_results))

        for key, res in map_results.items():
            if not res:
                results[key] = 0
                continue
                
            if key in ["core_services", "api_traffic", "api_latency", "api_errors"]:
                results[key] = {item["metric"].get("job", "unknown"): float(item["value"][1]) for item in res}
            else:
                try:
                    results[key] = float(res[0]["value"][1])
                except (IndexError, ValueError, TypeError):
                    results[key] = 0
            
    # Update cache
    _cache["data"] = results
    _cache["expiry"] = now + CACHE_TTL
    
    return results

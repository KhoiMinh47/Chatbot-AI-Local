import asyncio
import hashlib
import json
import logging
import os
import random
import time
from dataclasses import dataclass
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

import httpx

from database.setup_redis import redis_service

logger = logging.getLogger(__name__)


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return str(raw).strip().lower() in {"1", "true", "yes", "on"}


def _env_csv(name: str, default: str = "") -> list[str]:
    raw = os.getenv(name, default)
    if not raw:
        return []
    return [x.strip().lower() for x in raw.split(",") if x and x.strip()]


@dataclass
class SearchBrokerResult:
    urls: list[str]
    provider: str
    provider_trace: list[dict]
    cache_hit: bool


class SearchBrokerService:
    """Provider broker cho web search: cache, failover, circuit breaker, global throttling."""

    def __init__(self) -> None:
        self.enabled = _env_bool("WEB_SEARCH_BROKER_ENABLED", True)
        self.provider_priority = _env_csv(
            "WEB_SEARCH_PROVIDER_PRIORITY",
            default="brave,bing,searxng",
        )

        self.web_timeout_sec = float(os.getenv("WEB_SEARCH_TIMEOUT_SEC", "8"))
        self.retry_max = max(0, int(os.getenv("WEB_SEARCH_RETRY_MAX", "2")))
        self.retry_base_ms = max(50, int(os.getenv("WEB_SEARCH_RETRY_BASE_MS", "200")))

        self.cache_ttl_sec = max(0, int(os.getenv("WEB_SEARCH_CACHE_TTL_SEC", "600")))
        self.cb_fail_threshold = max(1, int(os.getenv("WEB_SEARCH_CB_FAIL_THRESHOLD", "5")))
        self.cb_open_sec = max(5, int(os.getenv("WEB_SEARCH_CB_OPEN_SEC", "60")))

        self.global_concurrency = max(1, int(os.getenv("WEB_SEARCH_GLOBAL_CONCURRENCY", "8")))
        self.global_rps = max(0.5, float(os.getenv("WEB_SEARCH_GLOBAL_RPS", "6")))
        self._global_sem = asyncio.Semaphore(self.global_concurrency)
        self._bucket_tokens = self.global_rps
        self._bucket_last_refill = time.monotonic()
        self._bucket_lock = asyncio.Lock()

        # Provider config
        self.searxng_base = os.getenv("SEARXNG_BASE_URL", "").strip().rstrip("/")
        self.searxng_engines = os.getenv("SEARXNG_ENGINES", "").strip()

        self.brave_key = os.getenv("BRAVE_SEARCH_API_KEY", "").strip()
        self.brave_base = os.getenv("BRAVE_SEARCH_BASE_URL", "https://api.search.brave.com").strip().rstrip("/")

        self.bing_key = os.getenv("BING_SEARCH_API_KEY", "").strip()
        self.bing_base = os.getenv("BING_SEARCH_BASE_URL", "https://api.bing.microsoft.com/v7.0").strip().rstrip("/")

        # Optional egress proxy (for isolated gateway)
        self.egress_proxy_url = os.getenv("WEB_SEARCH_EGRESS_PROXY_URL", "").strip()

    async def _token_bucket_wait(self) -> None:
        while True:
            async with self._bucket_lock:
                now = time.monotonic()
                elapsed = max(0.0, now - self._bucket_last_refill)
                self._bucket_last_refill = now
                self._bucket_tokens = min(self.global_rps, self._bucket_tokens + (elapsed * self.global_rps))
                if self._bucket_tokens >= 1.0:
                    self._bucket_tokens -= 1.0
                    return
                wait_for = max(0.01, (1.0 - self._bucket_tokens) / self.global_rps)
            await asyncio.sleep(wait_for)

    def _cache_key(self, query: str, topk: int, allowed_domains: list[str] | None) -> str:
        payload = {
            "q": query,
            "k": topk,
            "domains": sorted([d.lower().strip() for d in (allowed_domains or []) if d]),
            "providers": self.provider_priority,
            "engines": self.searxng_engines,
        }
        digest = hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()
        return f"web:search:broker:cache:{digest}"

    async def _get_cache(self, key: str) -> SearchBrokerResult | None:
        if self.cache_ttl_sec <= 0:
            return None
        try:
            client = redis_service.client
            if not client:
                return None
            raw = await client.get(key)
            if not raw:
                return None
            data = json.loads(raw)
            urls = data.get("urls") if isinstance(data, dict) else []
            provider = str((data or {}).get("provider") or "cache")
            trace = list((data or {}).get("provider_trace") or [])
            if isinstance(urls, list) and urls:
                return SearchBrokerResult(urls=[str(u) for u in urls], provider=provider, provider_trace=trace, cache_hit=True)
            return None
        except Exception as e:
            logger.debug("[SEARCH_BROKER] Cache read fail: %s", e)
            return None

    async def _set_cache(self, key: str, result: SearchBrokerResult) -> None:
        if self.cache_ttl_sec <= 0 or not result.urls:
            return
        try:
            client = redis_service.client
            if not client:
                return
            payload = {
                "urls": result.urls,
                "provider": result.provider,
                "provider_trace": result.provider_trace,
            }
            await client.setex(key, self.cache_ttl_sec, json.dumps(payload, ensure_ascii=False))
        except Exception as e:
            logger.debug("[SEARCH_BROKER] Cache write fail: %s", e)

    async def _cb_is_open(self, provider: str) -> bool:
        try:
            client = redis_service.client
            if not client:
                return False
            raw = await client.get(f"web:search:cb:open_until:{provider}")
            if not raw:
                return False
            return float(raw) > time.time()
        except Exception:
            return False

    async def _cb_record_failure(self, provider: str) -> None:
        try:
            client = redis_service.client
            if not client:
                return
            fail_key = f"web:search:cb:fail:{provider}"
            current = await client.incr(fail_key)
            if current == 1:
                await client.expire(fail_key, max(30, self.cb_open_sec * 2))
            if current >= self.cb_fail_threshold:
                await client.setex(
                    f"web:search:cb:open_until:{provider}",
                    self.cb_open_sec,
                    str(time.time() + self.cb_open_sec),
                )
                await client.delete(fail_key)
        except Exception:
            return

    async def _cb_record_success(self, provider: str) -> None:
        try:
            client = redis_service.client
            if not client:
                return
            await client.delete(f"web:search:cb:fail:{provider}")
            await client.delete(f"web:search:cb:open_until:{provider}")
        except Exception:
            return

    @staticmethod
    def _normalize_url(url: str) -> str:
        try:
            parsed = urlparse((url or "").strip())
            if parsed.scheme not in {"http", "https"}:
                return ""
            path = parsed.path or "/"
            query_pairs = parse_qsl(parsed.query, keep_blank_values=False)
            kept_pairs = []
            for key, value in query_pairs:
                lowered = key.lower()
                if lowered.startswith("utm_") or lowered in {"gclid", "fbclid", "ref", "ref_src", "spm"}:
                    continue
                kept_pairs.append((key, value))
            new_query = urlencode(kept_pairs, doseq=True)
            normalized = parsed._replace(fragment="", query=new_query, path=path)
            return urlunparse(normalized)
        except Exception:
            return ""

    @staticmethod
    def _extract_domain(url: str) -> str:
        try:
            host = (urlparse(url).hostname or "").lower()
            return host[4:] if host.startswith("www.") else host
        except Exception:
            return ""

    @staticmethod
    def _domain_allowed(domain: str, allowed_domains: list[str]) -> bool:
        if not allowed_domains:
            return True
        d = (domain or "").lower()
        for a in allowed_domains:
            aa = (a or "").lower()
            if d == aa or d.endswith(f".{aa}"):
                return True
        return False

    def _provider_configured(self, provider: str) -> bool:
        if provider == "brave":
            return bool(self.brave_key)
        if provider == "bing":
            return bool(self.bing_key)
        if provider == "searxng":
            return bool(self.searxng_base)
        return False

    def configured_providers(self) -> list[str]:
        """Return providers that are both in priority order and configured."""
        return [p for p in (self.provider_priority or []) if self._provider_configured(p)]

    async def _request_with_retry(self, provider: str, request_fn):
        attempts = self.retry_max + 1
        last_err = None
        for attempt in range(attempts):
            try:
                return await request_fn()
            except Exception as e:
                last_err = e
                if attempt >= attempts - 1:
                    break
                sleep_ms = self.retry_base_ms * (2 ** attempt)
                jitter = random.randint(0, max(20, self.retry_base_ms // 2))
                await asyncio.sleep((sleep_ms + jitter) / 1000.0)
        raise last_err if last_err else RuntimeError(f"{provider} request failed")

    async def _provider_searxng(self, query: str, topk: int) -> list[str]:
        if not self.searxng_base:
            raise RuntimeError("searxng_not_configured")

        params = {"q": query, "format": "json", "safesearch": 0}
        if self.searxng_engines:
            params["engines"] = self.searxng_engines

        timeout = httpx.Timeout(self.web_timeout_sec)
        proxies = self.egress_proxy_url or None

        async def _do_request():
            async with httpx.AsyncClient(timeout=timeout, follow_redirects=True, proxy=proxies) as client:
                resp = await client.get(f"{self.searxng_base}/search", params=params)
                resp.raise_for_status()
                data = resp.json()
            results = data.get("results") if isinstance(data, dict) else []
            urls: list[str] = []
            seen = set()
            for item in results if isinstance(results, list) else []:
                raw = item.get("url") if isinstance(item, dict) else ""
                norm = self._normalize_url(str(raw or ""))
                if not norm or norm in seen:
                    continue
                seen.add(norm)
                urls.append(norm)
                if len(urls) >= topk:
                    break
            return urls

        return await self._request_with_retry("searxng", _do_request)

    async def _provider_brave(self, query: str, topk: int) -> list[str]:
        if not self.brave_key:
            raise RuntimeError("brave_not_configured")
        timeout = httpx.Timeout(self.web_timeout_sec)
        proxies = self.egress_proxy_url or None

        params = {"q": query, "count": max(1, min(topk, 20))}
        headers = {
            "Accept": "application/json",
            "X-Subscription-Token": self.brave_key,
        }

        async def _do_request():
            async with httpx.AsyncClient(timeout=timeout, follow_redirects=True, proxy=proxies) as client:
                resp = await client.get(f"{self.brave_base}/res/v1/web/search", params=params, headers=headers)
                resp.raise_for_status()
                data = resp.json()
            web = data.get("web") if isinstance(data, dict) else {}
            results = web.get("results") if isinstance(web, dict) else []
            urls: list[str] = []
            seen = set()
            for item in results if isinstance(results, list) else []:
                raw = item.get("url") if isinstance(item, dict) else ""
                norm = self._normalize_url(str(raw or ""))
                if not norm or norm in seen:
                    continue
                seen.add(norm)
                urls.append(norm)
                if len(urls) >= topk:
                    break
            return urls

        return await self._request_with_retry("brave", _do_request)

    async def _provider_bing(self, query: str, topk: int) -> list[str]:
        if not self.bing_key:
            raise RuntimeError("bing_not_configured")
        timeout = httpx.Timeout(self.web_timeout_sec)
        proxies = self.egress_proxy_url or None

        params = {
            "q": query,
            "count": max(1, min(topk, 50)),
            "textDecorations": False,
            "textFormat": "Raw",
        }
        headers = {
            "Ocp-Apim-Subscription-Key": self.bing_key,
            "Accept": "application/json",
        }

        async def _do_request():
            async with httpx.AsyncClient(timeout=timeout, follow_redirects=True, proxy=proxies) as client:
                resp = await client.get(f"{self.bing_base}/search", params=params, headers=headers)
                resp.raise_for_status()
                data = resp.json()
            web_pages = data.get("webPages") if isinstance(data, dict) else {}
            values = web_pages.get("value") if isinstance(web_pages, dict) else []
            urls: list[str] = []
            seen = set()
            for item in values if isinstance(values, list) else []:
                raw = item.get("url") if isinstance(item, dict) else ""
                norm = self._normalize_url(str(raw or ""))
                if not norm or norm in seen:
                    continue
                seen.add(norm)
                urls.append(norm)
                if len(urls) >= topk:
                    break
            return urls

        return await self._request_with_retry("bing", _do_request)

    async def search_urls(
        self,
        query: str,
        *,
        topk: int,
        allowed_domains: list[str] | None = None,
    ) -> SearchBrokerResult:
        query = (query or "").strip()
        if not query:
            return SearchBrokerResult(urls=[], provider="none", provider_trace=[], cache_hit=False)

        normalized_domains = [d.lower().strip() for d in (allowed_domains or []) if d and d.strip()]
        cache_key = self._cache_key(query, topk, normalized_domains)
        cached = await self._get_cache(cache_key)
        if cached:
            return cached

        if not self.enabled:
            urls = await self._provider_searxng(query, topk)
            return SearchBrokerResult(urls=urls, provider="searxng", provider_trace=[], cache_hit=False)

        provider_trace: list[dict] = []
        providers = self.provider_priority or ["searxng"]

        async with self._global_sem:
            await self._token_bucket_wait()

            for provider in providers:
                if not self._provider_configured(provider):
                    provider_trace.append({"provider": provider, "status": "unconfigured"})
                    continue
                if await self._cb_is_open(provider):
                    provider_trace.append({"provider": provider, "status": "cb_open"})
                    continue

                start = time.perf_counter()
                try:
                    if provider == "brave":
                        urls = await self._provider_brave(query, topk)
                    elif provider == "bing":
                        urls = await self._provider_bing(query, topk)
                    elif provider == "searxng":
                        urls = await self._provider_searxng(query, topk)
                    else:
                        provider_trace.append({"provider": provider, "status": "unsupported"})
                        continue

                    filtered: list[str] = []
                    seen = set()
                    for u in urls:
                        norm = self._normalize_url(u)
                        if not norm or norm in seen:
                            continue
                        if normalized_domains:
                            domain = self._extract_domain(norm)
                            if not self._domain_allowed(domain, normalized_domains):
                                continue
                        seen.add(norm)
                        filtered.append(norm)
                        if len(filtered) >= topk:
                            break

                    await self._cb_record_success(provider)
                    duration_ms = int((time.perf_counter() - start) * 1000)
                    provider_trace.append(
                        {"provider": provider, "status": "ok", "duration_ms": duration_ms, "results": len(filtered)}
                    )

                    result = SearchBrokerResult(
                        urls=filtered,
                        provider=provider,
                        provider_trace=provider_trace,
                        cache_hit=False,
                    )
                    await self._set_cache(cache_key, result)
                    return result
                except Exception as e:
                    duration_ms = int((time.perf_counter() - start) * 1000)
                    provider_trace.append(
                        {
                            "provider": provider,
                            "status": "error",
                            "duration_ms": duration_ms,
                            "error": str(e)[:160],
                        }
                    )
                    await self._cb_record_failure(provider)
                    logger.warning("[SEARCH_BROKER] provider=%s failed: %s", provider, e)

        return SearchBrokerResult(urls=[], provider="none", provider_trace=provider_trace, cache_hit=False)


search_broker_service = SearchBrokerService()

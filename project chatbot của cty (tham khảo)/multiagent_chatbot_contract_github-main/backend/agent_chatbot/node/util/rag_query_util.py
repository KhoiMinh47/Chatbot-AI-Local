"""
Module tiện ích cho pipeline truy vấn RAG Fast Contract.

Bao gồm các chức năng chính:
    - _get_embedding: Nhúng câu hỏi thành vector.
    - _rerank_documents: Rerank danh sách documents song song.
    - _sigmoid: Chuẩn hoá score về 0-1.
    - _process_single_path: Xử lý 1 path (query heading, lọc, rerank, ghép text).
    - node_search_logic: Tìm paths liên quan từ Qdrant + Rerank.
    - node_seach_with_path_logic: Lấy context chi tiết theo từng path.
    - node_asisstant_logic: Gọi vLLM trả lời cuối cùng.
    - node_search_path_user_chose_logic: Xử lý khi user chọn sẵn danh sách file paths.
"""

import os
import logging
import asyncio
import math
import json
import re
import html
import random
import ipaddress
import socket
from datetime import datetime, timezone
from urllib.parse import urlparse, urljoin, urlunparse, parse_qsl, urlencode

import httpx
from qdrant_client.http import models
from database.setup_qdrant import qdrant_service, COLLECTION_NAME
from service.search_broker_service import search_broker_service

logger = logging.getLogger(__name__)


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return str(raw).strip().lower() in {"1", "true", "yes", "on"}


def _env_csv(name: str) -> list[str]:
    raw = os.getenv(name, "")
    if not raw:
        return []
    return [item.strip() for item in raw.split(",") if item and item.strip()]


def _env_int(name: str, default: int, minimum: int | None = None) -> int:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        value = int(str(raw).strip())
    except (TypeError, ValueError):
        logger.warning("Env %s không hợp lệ: %r, dùng mặc định %d", name, raw, default)
        return default
    if minimum is not None and value < minimum:
        logger.warning("Env %s=%d thấp hơn ngưỡng %d, dùng %d", name, value, minimum, minimum)
        return minimum
    return value


def _env_float(name: str, default: float, minimum: float | None = None) -> float:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        value = float(str(raw).strip())
    except (TypeError, ValueError):
        logger.warning("Env %s không hợp lệ: %r, dùng mặc định %.2f", name, raw, default)
        return default
    if minimum is not None and value < minimum:
        logger.warning("Env %s=%.2f thấp hơn ngưỡng %.2f, dùng %.2f", name, value, minimum, minimum)
        return minimum
    return value


def _token_budget_to_chars(token_budget: int) -> int:
    return max(1, int(token_budget * RAG_CHARS_PER_TOKEN))


async def _push_sse(state: dict, title: str, mess: str = "", end: bool = False, list_file: list = None):
    """Helper: push SSE event vào queue nếu có."""
    queue = state.get("sse_queue")
    if queue:
        event = {
            "user_id": state.get("user_id", ""),
            "session_id": state.get("session_id", -1),
            "title": title,
            "mess": mess,
            "end": end,
        }
        if list_file is not None:
            event["list_file"] = list_file
        await queue.put(event)


_REASONING_LEADERS = (
    "• analyze",
    "- analyze",
    "analyze the request",
    "scan context",
    "locate relevant",
    "extract details",
    "the user",
    "i need to",
    "i should",
    "we need",
    "here's a thinking process",
    "here is a thinking process",
    "let's craft",
    "plan:",
)


def _strip_model_reasoning(text: str) -> str:
    """Remove Gemma/Qwen-style reasoning fragments from final text."""
    if not text:
        return ""

    cleaned = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL | re.IGNORECASE)
    cleaned = re.sub(
        r"<\|channel>thought\s*.*?<channel\|>",
        "",
        cleaned,
        flags=re.DOTALL | re.IGNORECASE,
    )

    # vLLM Gemma4 streaming can expose only the closing marker in content.
    if "<channel|>" in cleaned:
        cleaned = cleaned.split("<channel|>")[-1]

    cleaned = cleaned.replace("<|channel>thought", "")
    cleaned = cleaned.replace("<|channel>", "")
    cleaned = cleaned.replace("<channel|>", "")

    if _looks_like_reasoning_prefix(cleaned):
        final_markers = [
            r"\n\s*(?:Final answer|Answer|Response)\s*:\s*",
            r"\n\s*(?:Câu trả lời|Trả lời)\s*:\s*",
            r"\n\s*(?=Trong\s+)",
            r"\n\s*(?=Theo\s+)",
            r"\n\s*(?=Dựa\s+)",
            r"\n\s*(?=Chào\s+)",
            r"\n\s*(?=Mình\s+)",
            r"\n\s*(?=Tôi\s+)",
        ]
        for marker in final_markers:
            match = re.search(marker, cleaned, flags=re.IGNORECASE)
            if match:
                cleaned = cleaned[match.end():]
                break

    return cleaned.strip()


def _looks_like_reasoning_prefix(text: str) -> bool:
    compact = re.sub(r"\s+", " ", text or "").strip().lower()
    compact = compact.lstrip("-*•0123456789. )")
    if not compact:
        return True
    return any(compact.startswith(prefix) for prefix in _REASONING_LEADERS)


class _ReasoningStreamFilter:
    """
    Suppress reasoning tokens before they reach SSE.

    Gemma4's reasoning parser separates reasoning for non-stream responses, but
    streaming chunks can still put reasoning text in delta.content. This filter
    buffers the prefix until it can decide whether the model is producing a
    normal answer or a thought block.
    """

    def __init__(self) -> None:
        self._buffer = ""
        self._mode = "pending"
        self.emitted_any = False
        self.last_reasoning = ""

    def push(self, token: str) -> str:
        self.last_reasoning = ""
        if not token:
            return ""

        if self._mode == "answer":
            self.emitted_any = True
            return token

        if self._mode == "reasoning":
            self._buffer += token
            self.last_reasoning = token
            return self._release_after_channel_marker()

        self._buffer += token
        released = self._release_after_channel_marker()
        if released:
            return released

        if _looks_like_reasoning_prefix(self._buffer):
            self._mode = "reasoning"
            self.last_reasoning = self._buffer
            self._buffer = ""
            return ""

        # Wait for a small prefix before deciding this is ordinary answer text.
        if len(self._buffer) < 80 and "\n" not in self._buffer:
            return ""

        self._mode = "answer"
        released = self._buffer
        self._buffer = ""
        self.emitted_any = bool(released)
        return released

    def flush(self) -> str:
        if self._mode == "answer" and self._buffer:
            released = self._buffer
            self._buffer = ""
            self.emitted_any = True
            return released
        return ""

    def _release_after_channel_marker(self) -> str:
        marker = "<channel|>"
        marker_index = self._buffer.find(marker)
        if marker_index == -1:
            return ""

        released = self._buffer[marker_index + len(marker):]
        self._buffer = ""
        self._mode = "answer"
        self.last_reasoning = ""
        released = _strip_model_reasoning(released)
        if released:
            self.emitted_any = True
        return released


def _disable_model_thinking_extra_body() -> dict:
    return {"chat_template_kwargs": {"enable_thinking": False}}


# --- Hằng số cấu hình ---
BGE_BASE_URL = os.getenv("BGE_BASE_URL") # Replace if env absent
BGE_EMBED_PATH = os.getenv("BGE_EMBED_PATH")
BGE_RERANK_PATH = os.getenv("BGE_RERANK_PATH")
BGE_TIMEOUT = 2000

# Ngưỡng score rerank
NODE_SEARCH_RERANK_THRESHOLD = 0.2
NODE_SEARCH_RERANK_PATH_THRESHOLD = 0.6
NODE_SEARCH_EMBED_THRESHOLD = 0.05
RAG_INPUT_TOKEN_BUDGET = _env_int("RAG_INPUT_TOKEN_BUDGET", 50000, minimum=1000)
RAG_OUTPUT_TOKEN_BUDGET = _env_int("RAG_OUTPUT_TOKEN_BUDGET", 10000, minimum=256)
RAG_FILE_CONTEXT_TOKEN_BUDGET = _env_int("RAG_FILE_CONTEXT_TOKEN_BUDGET", 40000, minimum=1000)
RAG_HISTORY_TOKEN_BUDGET = _env_int("RAG_HISTORY_TOKEN_BUDGET", 10000, minimum=0)
RAG_SELECTED_PATH_TOKEN_BUDGET = _env_int("RAG_SELECTED_PATH_TOKEN_BUDGET", 50000, minimum=1000)
RAG_CHARS_PER_TOKEN = _env_float("RAG_CHARS_PER_TOKEN", 2.5, minimum=1.0)
MAX_FILE_CONTEXT = _token_budget_to_chars(RAG_FILE_CONTEXT_TOKEN_BUDGET)
MAX_HISTORY_CONTEXT = _token_budget_to_chars(RAG_HISTORY_TOKEN_BUDGET)
MAX_TOKEN_OUTPUT = RAG_OUTPUT_TOKEN_BUDGET
QDRANT_LIMIT_PATH = 10
QDRANT_GROUP_SIZE = 3
MAX_HEADINGS_PER_PATH = 10
HEADING_GROUP_SIZE = 20
MAX_USER_PATHS_PER_QUERY = 10

# --- Cấu hình Web Search ---
WEB_SEARCH_TIMEOUT_SEC = float(os.getenv("WEB_SEARCH_TIMEOUT_SEC", "8"))
WEB_FETCH_TIMEOUT_SEC = float(os.getenv("WEB_FETCH_TIMEOUT_SEC", "8"))
WEB_FETCH_MAX_CONCURRENCY = max(1, int(os.getenv("WEB_FETCH_MAX_CONCURRENCY", "6")))
WEB_FETCH_RETRY_MAX = max(0, int(os.getenv("WEB_FETCH_RETRY_MAX", "2")))
WEB_FETCH_RETRY_BASE_MS = max(50, int(os.getenv("WEB_FETCH_RETRY_BASE_MS", "200")))
WEB_MAX_URLS_PER_QUERY = int(os.getenv("WEB_MAX_URLS_PER_QUERY", "5"))
WEB_MAX_CANDIDATE_URLS = int(os.getenv("WEB_MAX_CANDIDATE_URLS", "50"))
WEB_URL_SELECTOR_PREFETCH_MULTIPLIER = int(os.getenv("WEB_URL_SELECTOR_PREFETCH_MULTIPLIER", "4"))
WEB_TITLE_FETCH_TIMEOUT_SEC = float(os.getenv("WEB_TITLE_FETCH_TIMEOUT_SEC", "4"))
WEB_LISTING_EXPAND_MAX_PAGES = int(os.getenv("WEB_LISTING_EXPAND_MAX_PAGES", "3"))
WEB_LISTING_EXPAND_LINK_LIMIT = int(os.getenv("WEB_LISTING_EXPAND_LINK_LIMIT", "20"))
SEARXNG_BASE_URL = os.getenv("SEARXNG_BASE_URL", "").strip().rstrip("/")
SEARXNG_ENGINES = os.getenv("SEARXNG_ENGINES", "bing,duckduckgo,startpage").strip()
WEB_SEARXNG_TOPK = int(os.getenv("WEB_SEARXNG_TOPK", "30"))
WEB_MAX_CONTENT_CHARS_PER_URL = int(os.getenv("WEB_MAX_CONTENT_CHARS_PER_URL", "6000"))
WEB_MIN_CONTENT_CHARS_PER_URL = int(os.getenv("WEB_MIN_CONTENT_CHARS_PER_URL", "140"))
WEB_MAX_TOTAL_CONTEXT = int(os.getenv("WEB_MAX_TOTAL_WEB_CONTEXT", "24000"))
WEB_DOMAIN_MAP_TTL_SEC = int(os.getenv("WEB_DOMAIN_MAP_TTL_SEC", "1800"))
WEB_SOURCE_POLICY_CACHE_KEY = "web:source_policy:active"
WEB_SEARCH_LOG_ENABLED = _env_bool("WEB_SEARCH_LOG_ENABLED", default=False)
WEB_QUERY_DECOMPOSITION_ENABLED = _env_bool("WEB_QUERY_DECOMPOSITION_ENABLED", default=True)
WEB_QUERY_DECOMPOSITION_MAX_SUBQUERIES = int(os.getenv("WEB_QUERY_DECOMPOSITION_MAX_SUBQUERIES", "6"))
WEB_QUERY_PLANNER_LLM_ENABLED = _env_bool("WEB_QUERY_PLANNER_LLM_ENABLED", default=True)
WEB_BROAD_SEARCH_ENABLED = _env_bool("WEB_BROAD_SEARCH_ENABLED", default=True)
WEB_SEARCH_STRICT_SOURCE_FILTER = _env_bool("WEB_SEARCH_STRICT_SOURCE_FILTER", default=False)
WEB_SEARCH_ALLOWED_DOMAINS = [d.lower() for d in _env_csv("WEB_SEARCH_ALLOWED_DOMAINS")]
WEB_SEARCH_BLOCKED_DOMAINS = [d.lower() for d in _env_csv("WEB_SEARCH_BLOCKED_DOMAINS")]
WEB_SEARCH_ALLOWED_URL_PREFIXES = [p.strip() for p in _env_csv("WEB_SEARCH_ALLOWED_URL_PREFIXES")]
WEB_SEARCH_BLOCKED_URL_PREFIXES = [p.strip() for p in _env_csv("WEB_SEARCH_BLOCKED_URL_PREFIXES")]
WEB_PREFERRED_DOMAIN_SEARCH_MAX = max(0, int(os.getenv("WEB_PREFERRED_DOMAIN_SEARCH_MAX", "5")))
WEB_ADAPTIVE_BUDGET_ENABLED = _env_bool("WEB_ADAPTIVE_BUDGET_ENABLED", default=True)
WEB_ADAPTIVE_LOW_RERANK_THRESHOLD = float(os.getenv("WEB_ADAPTIVE_LOW_RERANK_THRESHOLD", "0.62"))
WEB_ADAPTIVE_EXTRA_FETCH_URLS = int(os.getenv("WEB_ADAPTIVE_EXTRA_FETCH_URLS", "3"))
WEB_MAX_EVIDENCE_PER_DOMAIN = max(1, int(os.getenv("WEB_MAX_EVIDENCE_PER_DOMAIN", "2")))
WEB_CITATION_VALIDATION_ENABLED = _env_bool("WEB_CITATION_VALIDATION_ENABLED", default=True)
WEB_EVIDENCE_SUMMARIZER_ENABLED = _env_bool("WEB_EVIDENCE_SUMMARIZER_ENABLED", default=True)
WEB_SUMMARIZER_MIN_SCORE = float(os.getenv("WEB_SUMMARIZER_MIN_SCORE", "0.48"))
WEB_SEARCH_EVALUATOR_LOOP_ENABLED = _env_bool("WEB_SEARCH_EVALUATOR_LOOP_ENABLED", default=True)
WEB_SEARCH_MAX_RESEARCH_LOOPS = max(1, int(os.getenv("WEB_SEARCH_MAX_RESEARCH_LOOPS", "2")))
WEB_EVALUATOR_MIN_EVIDENCE = max(1, int(os.getenv("WEB_EVALUATOR_MIN_EVIDENCE", "3")))
WEB_EVALUATOR_MIN_DOMAINS = max(1, int(os.getenv("WEB_EVALUATOR_MIN_DOMAINS", "2")))
WEB_EVALUATOR_MIN_TOP_SCORE = float(os.getenv("WEB_EVALUATOR_MIN_TOP_SCORE", "0.65"))
HISTORY_PIPELINE_LOG_ENABLED = _env_bool("HISTORY_PIPELINE_LOG_ENABLED", default=False)
WEB_EXPLICIT_DOMAIN_PROBE_PATHS = [
    "/",
    "/about/",
    "/about-us/",
    "/gioi-thieu/",
    "/ve-chung-toi/",
    "/company/",
]

_WEB_FETCH_SEMAPHORE = asyncio.Semaphore(WEB_FETCH_MAX_CONCURRENCY)

PROMPT_FEATURE_WEB_SEARCH_COORDINATOR = "web_search_coordinator"
PROMPT_FEATURE_WEB_SEARCH_SYNTHESIZER = "web_search_synthesizer"
PROMPT_FEATURE_WEB_SEARCH_VERIFIER = "web_search_verifier"

WEB_COORDINATOR_SYSTEM_PROMPT = (
    "Bạn là Web Research Coordinator trong hệ thống trợ lý doanh nghiệp. "
    "Mục tiêu: phân tích yêu cầu thành các câu hỏi nghiên cứu nhỏ, xác định thực thể/bên liên quan, "
    "ràng buộc thời gian/địa lý/chỉ số quan trọng và tạo truy vấn web bao phủ cả nguồn chính thức lẫn nguồn độc lập. "
    "Nếu hệ thống có allowlist nguồn web, xem đó là khóa nguồn bắt buộc và không đề xuất nguồn ngoài allowlist. "
    "Ưu tiên query ngắn, giàu từ khóa, có tín hiệu official/source/report/news/comparison khi phù hợp. "
    "Trả về kế hoạch JSON ngắn gọn, không tự tạo câu trả lời cuối cùng thay cho synthesizer."
)

WEB_SYNTHESIZER_SYSTEM_PROMPT = (
    "Bạn là Senior Web Evidence Synthesizer. "
    "Nhiệm vụ: tạo câu trả lời tiếng Việt chính xác, dễ hiểu, thân thiện và chuyên nghiệp từ evidence đã cung cấp. "
    "Nguyên tắc bắt buộc: ưu tiên phần tóm tắt sạch của evidence, chỉ dùng dữ liệu trong evidence, không suy diễn ngoài nguồn, không bịa số liệu. "
    "Mỗi luận điểm chính phải có citation theo nhãn [Sx] tương ứng (có thể nhiều nhãn như [S1][S3]). "
    "Với câu hỏi về một tổ chức/sản phẩm cụ thể, nguồn chính thức có thể đủ để mô tả ngắn gọn; nêu giới hạn nếu chỉ có một nguồn. "
    "Bố cục ưu tiên: (1) Trả lời ngắn gọn trực diện, (2) Chi tiết quan trọng theo ý, (3) Lưu ý/giới hạn nếu có, (4) Nguồn tham khảo. "
    "Mục 'Nguồn tham khảo' phải liệt kê rõ Sx -> URL. "
    "Nếu bằng chứng mâu thuẫn hoặc chưa đủ mạnh, nêu rõ mức độ chắc chắn và đề xuất cách truy vấn tiếp theo để người dùng hành động được ngay."
)

WEB_VERIFIER_SYSTEM_PROMPT = (
    "Bạn là Web Evidence Verifier. "
    "Đánh giá chất lượng câu trả lời web_search theo các tiêu chí: độ liên quan, tính nhất quán giữa nguồn, độ độc lập của nguồn, "
    "mức độ cập nhật và mức độ hỗ trợ trực tiếp cho kết luận. "
    "Phân loại mức tin cậy high/medium/low và nêu ngắn gọn lý do theo evidence, tránh nhận định mơ hồ."
)

VI_QUERY_STOPWORDS = {
    "là", "gì", "ai", "ở", "đâu", "nào", "bao", "bao_nhiêu", "nhiêu", "mấy", "vì", "sao",
    "như", "thế", "này", "kia", "đó", "được", "không", "có", "cho", "về", "với", "và",
    "hoặc", "trong", "ngoài", "khi", "thì", "để", "nên", "đi", "lại", "rồi", "hãy", "giúp",
    "mình", "em", "anh", "chị", "tôi", "ta", "bạn", "xin", "vui", "lòng", "cho_biết",
    "thông_tin", "hỏi", "cho_hỏi", "câu", "này", "nhé", "nhỉ", "ạ",
}

VI_TIME_HINTS = {
    "hôm", "nay", "hôm_nay", "mới", "nhất", "mới_nhất", "gần", "đây", "gần_đây",
    "tháng", "năm", "quý", "tuần", "ngày", "trước", "sau", "hiện_tại",
}


def _default_source_policy() -> dict:
    return {
        "strict_source_filter": WEB_SEARCH_STRICT_SOURCE_FILTER,
        "allow_domains": WEB_SEARCH_ALLOWED_DOMAINS,
        "allow_url_prefixes": WEB_SEARCH_ALLOWED_URL_PREFIXES,
        "block_domains": WEB_SEARCH_BLOCKED_DOMAINS,
        "block_url_prefixes": WEB_SEARCH_BLOCKED_URL_PREFIXES,
    }


def _extract_time_terms(query: str) -> list[str]:
    tokens = [t.lower() for t in re.findall(r"[0-9]+(?:[./-][0-9]+)*|[^\W_]+", query or "", flags=re.UNICODE)]
    picked: list[str] = []
    seen = set()

    for token in tokens:
        if token in VI_TIME_HINTS or re.match(r"^(19|20)\d{2}$", token) or re.match(r"^\d{1,2}[/-]\d{1,2}([/-]\d{2,4})?$", token):
            if token not in seen:
                seen.add(token)
                picked.append(token)
    return picked[:4]


def _remove_time_terms(query: str) -> str:
    terms = _extract_time_terms(query)
    if not terms:
        return query
    pattern = r"\b(?:" + "|".join(re.escape(t) for t in terms) + r")\b"
    cleaned = re.sub(pattern, " ", query, flags=re.IGNORECASE)
    return re.sub(r"\s+", " ", cleaned).strip()


def _extract_domains_from_query(query: str) -> list[str]:
    """
    Trích xuất domain người dùng chỉ định trực tiếp trong câu hỏi.
    Hỗ trợ cả dạng `site:example.com` và URL/domain thuần.
    """
    text = str(query or "").strip().lower()
    if not text:
        return []

    candidates: list[str] = []
    seen: set[str] = set()

    def _push(domain: str):
        d = str(domain or "").strip().lower().strip(".")
        if not d:
            return
        parts = [p for p in d.split(".") if p]
        if len(parts) < 2:
            return
        tld = parts[-1]
        if len(tld) < 2 or not re.match(r"^[a-z]+$", tld):
            return
        if d not in seen:
            seen.add(d)
            candidates.append(d)

    for m in re.finditer(r"\bsite:([a-z0-9-]+(?:\.[a-z0-9-]+)+)\b", text):
        _push(m.group(1))

    for m in re.finditer(r"\bhttps?://([^\s/]+)", text):
        host = (m.group(1) or "").split(":")[0]
        if host.startswith("www."):
            host = host[4:]
        _push(host)

    for m in re.finditer(r"\b([a-z0-9-]+(?:\.[a-z0-9-]+)+)\b", text):
        token = m.group(1)
        if token.startswith("www."):
            token = token[4:]
        _push(token)

    return candidates[:10]


def _build_subqueries(user_query: str, rewritten_query: str, max_subqueries: int = 3) -> list[str]:
    max_subqueries = max(1, max_subqueries)
    base_query = (rewritten_query or user_query or "").strip()
    if not base_query:
        return []

    candidates: list[str] = []

    def _add(q: str):
        q = re.sub(r"\s+", " ", (q or "").strip())
        if not q:
            return
        if q.lower() in {x.lower() for x in candidates}:
            return
        candidates.append(q)

    _add(base_query)

    # 1) Decompose theo mệnh đề khi câu hỏi có nhiều vế.
    raw_parts = re.split(r"\s*(?:;|\||,|\bvà\b|\bhoặc\b|\bso với\b|\bvs\b)\s*", user_query or "", flags=re.IGNORECASE)
    for part in raw_parts:
        if len(candidates) >= max_subqueries:
            break
        normalized = _rewrite_query_keywords(part)
        if len(normalized.split()) >= 3:
            _add(normalized)

    # 2) Entity-focused query (giảm bias từ cụm thời gian).
    if len(candidates) < max_subqueries:
        entity_query = _remove_time_terms(base_query)
        if entity_query and entity_query.lower() != base_query.lower():
            _add(entity_query)

    # 3) Time-focused query giữ thực thể + cụm thời gian để bắt kết quả mới.
    if len(candidates) < max_subqueries:
        time_terms = _extract_time_terms(user_query or base_query)
        entity = _remove_time_terms(base_query) or base_query
        if time_terms:
            _add(f"{entity} {' '.join(time_terms)}")

    return candidates[:max_subqueries]


def _extract_json_object(text: str) -> dict:
    """Parse JSON object từ LLM response, chấp nhận cả fenced code block."""
    raw = (text or "").strip()
    if not raw:
        return {}

    raw = re.sub(r"^```(?:json)?\s*", "", raw, flags=re.IGNORECASE)
    raw = re.sub(r"\s*```$", "", raw)

    try:
        parsed = json.loads(raw)
        return parsed if isinstance(parsed, dict) else {}
    except Exception:
        pass

    start = raw.find("{")
    end = raw.rfind("}")
    if start >= 0 and end > start:
        try:
            parsed = json.loads(raw[start:end + 1])
            return parsed if isinstance(parsed, dict) else {}
        except Exception:
            return {}
    return {}


def _clean_query_list(items: list, max_items: int) -> list[str]:
    cleaned: list[str] = []
    seen: set[str] = set()
    for item in items or []:
        q = re.sub(r"\s+", " ", str(item or "").strip())
        if not q:
            continue
        key = q.lower()
        if key in seen:
            continue
        seen.add(key)
        cleaned.append(q[:180])
        if len(cleaned) >= max_items:
            break
    return cleaned


def _pick_preferred_domains(query: str, configured_domains: list[str], limit: int) -> list[str]:
    if limit <= 0 or not configured_domains:
        return []

    query_terms = {
        t.lower().replace("-", "")
        for t in re.findall(r"[a-zA-Z0-9À-ỹ]{3,}", query or "", flags=re.UNICODE)
        if t.lower() not in VI_QUERY_STOPWORDS
    }

    matched: list[str] = []
    remaining: list[str] = []
    seen: set[str] = set()
    for domain in configured_domains:
        d = str(domain or "").lower().strip()
        if not d or d in seen:
            continue
        seen.add(d)
        labels = [label.replace("-", "") for label in d.split(".") if label]
        if any(label in query_terms for label in labels):
            matched.append(d)
        else:
            remaining.append(d)

    return (matched + remaining)[:limit]


def _build_retry_subqueries(query: str, plan: dict, retry_reasons: list[str], max_items: int) -> list[str]:
    base = (plan.get("keyword_query") or query or "").strip()
    previous = _clean_query_list(plan.get("sub_queries") or [], max_items)
    additions = []
    reason_text = " ".join(retry_reasons or [])

    if base:
        additions.extend([
            f"{base} official source",
            f"{base} report analysis",
            f"{base} latest news",
        ])
    if "citation" in reason_text or "low_score" in reason_text:
        additions.append(f"{query} evidence source")
    if "missing_questions" in reason_text:
        research_questions = plan.get("research_questions") or []
        additions.extend(str(q) for q in research_questions)

    return _clean_query_list(previous + additions, max_items)


async def _llm_plan_web_queries(
    state: dict,
    query: str,
    fallback_rewritten_query: str,
    fallback_subqueries: list[str],
    source_policy: dict,
) -> dict:
    if not WEB_QUERY_PLANNER_LLM_ENABLED or not query.strip():
        return {}

    try:
        from service.runtime_config_service import (
            get_required_active_prompt_content,
            resolve_model_runtime,
        )

        model_selector = state.get("model_name")
        client, resolved_model, _meta = await resolve_model_runtime(model_selector)
        system_prompt = await get_required_active_prompt_content(
            PROMPT_FEATURE_WEB_SEARCH_COORDINATOR
        )

        retry_reasons = state.get("web_retry_reasons") or []
        retry_hint = (
            f"\nLý do vòng trước chưa đạt: {', '.join(retry_reasons)}\n"
            if retry_reasons else ""
        )
        user_content = (
            "Hãy lập kế hoạch web research cho câu hỏi sau.\n"
            f"Câu hỏi gốc: {query}\n"
            f"Keyword fallback: {fallback_rewritten_query}\n"
            f"Sub-query fallback: {fallback_subqueries}\n"
            f"Strict source filter: {bool(source_policy.get('strict_source_filter'))}\n"
            f"{retry_hint}\n"
            "Trả về DUY NHẤT JSON object hợp lệ, không markdown, schema:\n"
            "{\n"
            '  "rewritten_query": "keyword query ngắn",\n'
            '  "research_questions": ["câu hỏi con cần trả lời"],\n'
            '  "search_queries": ["truy vấn web ngắn, có cả biến thể official/source và biến thể open-web nếu phù hợp"],\n'
            '  "must_cover": ["thực thể/bên/chỉ số/thời gian bắt buộc"],\n'
            '  "freshness_required": true,\n'
            '  "notes": "ghi chú ngắn cho summarizer"\n'
            "}\n"
            "Giới hạn search_queries tối đa theo cấu hình, tránh câu quá dài. "
            "Không thêm toán tử site: trừ khi câu hỏi gốc đã chỉ định domain."
        )

        resp = await client.chat.completions.create(
            model=resolved_model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_content},
            ],
            temperature=0.1,
            max_tokens=800,
            extra_body=_disable_model_thinking_extra_body(),
            stream=False,
        )
        content = (
            _strip_model_reasoning(resp.choices[0].message.content)
            if resp and resp.choices and resp.choices[0].message
            else ""
        )
        parsed = _extract_json_object(content or "")
        return parsed
    except Exception as e:
        logger.debug("[WEB_PLANNER] LLM planner fallback: %s", e)
        return {}


def _rewrite_query_keywords(user_query: str, max_terms: int = 14) -> str:
    """Rút gọn câu hỏi người dùng thành keyword query để tăng hiệu quả web search."""
    text = re.sub(r"\s+", " ", (user_query or "").strip())
    if not text:
        return ""

    quoted_phrases = [
        m.group(1).strip()
        for m in re.finditer(r'"([^"]{2,80})"', text)
        if m.group(1).strip()
    ]

    raw_tokens = re.findall(r"[0-9]+(?:[./-][0-9]+)*|[^\W_]+", text, flags=re.UNICODE)
    keywords: list[str] = []
    seen = set()

    def _push(term: str):
        key = term.lower().strip()
        if not key or key in seen:
            return
        seen.add(key)
        keywords.append(term.strip())

    for phrase in quoted_phrases:
        _push(phrase)

    for token in raw_tokens:
        t = token.strip()
        if not t:
            continue
        lower = t.lower()
        if lower in VI_QUERY_STOPWORDS:
            continue
        if len(lower) <= 1 and not re.match(r"^[0-9]+$", lower):
            continue
        _push(t)
        if len(keywords) >= max_terms:
            break

    if not keywords:
        return text

    return " ".join(keywords[:max_terms])


def _sigmoid(x: float) -> float:
    """Hàm Sigmoid đưa score về thang 0 -> 1"""
    try:
        return 1 / (1 + math.exp(-x))
    except OverflowError:
        return 0.0 if x < 0 else 1.0

async def _get_embedding(query_input: str) -> list[float]:
    """Gọi BGE embedding API để tạo vector embedding từ query."""
    bge_embed_url = f"{BGE_BASE_URL}{BGE_EMBED_PATH}"
    payload = {"texts": [query_input]}

    async with httpx.AsyncClient(timeout=BGE_TIMEOUT) as client:
        resp = await client.post(bge_embed_url, json=payload)
        resp.raise_for_status()
        data = resp.json()

    return data["result"][0]


async def _rerank_documents(query_input: str, documents: list[str]) -> list[dict]:
    """
    Gọi BGE rerank API để xếp hạng documents theo relevance với query.
    Sử dụng asyncio.gather để chia nhỏ batch rải request song song nhằm tối ưu performance.
    """
    # Không chia quá nhỏ để GPU còn gánh được batch
    BATCH_SIZE = 10
    bge_rerank_url = f"{BGE_BASE_URL}{BGE_RERANK_PATH}"

    async def _fetch_rerank_batch(batch_docs: list[str], start_idx: int, client: httpx.AsyncClient) -> list[dict]:
        payload = {"query": query_input, "documents": batch_docs}
        try:
            resp = await client.post(bge_rerank_url, json=payload)
            resp.raise_for_status()
            data = resp.json()
            
            # Khôi phục index thực tế
            batch_result = data.get("result", [])
            for item in batch_result:
                item["index"] += start_idx 
            return batch_result
        except Exception as e:
            logger.error(f"Lỗi khi gọi bge rerank batch: {e}")
            return []

    # Chia chunks thành các batch nhỏ
    batches = [documents[i:i + BATCH_SIZE] for i in range(0, len(documents), BATCH_SIZE)]
    
    async with httpx.AsyncClient(timeout=BGE_TIMEOUT) as client:
        tasks = []
        for i, batch in enumerate(batches):
            start_idx = i * BATCH_SIZE
            tasks.append(_fetch_rerank_batch(batch, start_idx, client))
        
        # Chạy song song tất cả các batch
        batch_results = await asyncio.gather(*tasks)

    # Gộp list of lists thành list
    results = [item for batch in batch_results for item in batch]
    return sorted(results, key=lambda x: x["score"], reverse=True)


async def node_search_logic(state: dict) -> dict:
    """
    Node search:
    - Stage 1: Embedding câu hỏi user, search Qdrant limit 30 paths, 3 chunks/path. Lọc embeddings score > 0.6.
    - Stage 2: Rerank các chunks vượt qua Stage 1 bằng BGE Reranker.
    - Chọn lọc các path có ít nhất 1 chunk đạt rerank score > 0.8.
    
    Tối ưu: Ưu tiên các file đã được upload hoặc gắn vào session hiện tại.
    """
    from database.setup_postgres import SessionLocal
    from database.table.table_postgres import session
    from sqlalchemy import select
    logger.info("=== Bắt đầu Node Search Logic ===")
    query = state.get("user_input", "")
    if not query:
        logger.warning("Không tìm thấy user_input trong state.")
        state["search_results"] = []
        return state

    # 1. Tạo vector embedding từ câu hỏi
    await _push_sse(state, title="Đang tạo vector embedding cho câu hỏi...")
    embedding = await _get_embedding(query)

    # 2. Vector Search_groups trên Qdrant (Limit 30 paths, mỗi path 3 chunks/hits)
    await _push_sse(state, title=f"Đang tìm kiếm vector trong cơ sở dữ liệu (top {QDRANT_LIMIT_PATH} paths)...")
    search_result = await qdrant_service.client.query_points_groups(
        collection_name=COLLECTION_NAME,
        query=embedding,
        group_by="path",
        limit=QDRANT_LIMIT_PATH,
        group_size=QDRANT_GROUP_SIZE,
        using="dense_content",
        with_payload=True,
    )

    # 3. Ưu tiên các file trong Session (nếu có context session_id)
    session_id = state.get("session_id", 0)
    session_paths = []
    if session_id > 0:
        try:
            async with SessionLocal() as db:
                res = await db.execute(select(session.paths).where(session.id == session_id))
                paths_data = res.scalars().first()
                if paths_data:
                    session_paths = list(paths_data)
                    logger.info("[PRIORITY] Session %d có các paths ưu tiên: %s", session_id, session_paths)
        except Exception as e:
            logger.warning("[PRIORITY] Lỗi lấy session paths: %s", e)

    # 4. Nếu có session_paths, thực hiện thêm một query nhắm mục tiêu (Targeted Search)
    # Gộp kết quả từ General Search và Targeted Search
    targeted_hits = []
    if session_paths:
        await _push_sse(state, title=f"Đang ưu tiên tìm kiếm trong {len(session_paths)} file của session...")
        targeted_result = await qdrant_service.client.query_points(
            collection_name=COLLECTION_NAME,
            query=embedding,
            query_filter=models.Filter(
                must=[
                    models.Filter(
                        should=[
                            models.FieldCondition(key="path", match=models.MatchValue(value=p))
                            for p in session_paths
                        ]
                    )
                ]
            ),
            limit=20, # Lấy nhiều chunks từ các file ưu tiên
            using="dense_content",
            with_payload=True
        )
        targeted_hits = targeted_result.points
        logger.info("[PRIORITY] Tìm thấy %d chunks từ targeted session paths", len(targeted_hits))

    # 5. Lọc embeddings & Thu thập tài liệu để Rerank
    documents_to_rerank = []
    chunk_metadata = []

    # Gộp hits từ General search (groups) và Targeted search (points)
    # Lưu ý: group search return groups, qdrant_result.points return points
    
    # Xử lý General Search Groups
    for group in search_result.groups:
        path = group.id
        for hit in group.hits:
            score = getattr(hit, 'score', 0)
            if score >= NODE_SEARCH_EMBED_THRESHOLD:
                content = hit.payload.get("content", "") if hit.payload else ""
                if content:
                    documents_to_rerank.append(content)
                    chunk_metadata.append(path)

    # Xử lý Targeted Search Hits (Points) - Tăng điểm ảo hoặc ưu tiên slot
    for hit in targeted_hits:
        path = hit.payload.get("path")
        score = getattr(hit, 'score', 0)
        # Ưu tiên: Thậm chí nếu score hơi thấp cũng rerank thử
        if score >= (NODE_SEARCH_EMBED_THRESHOLD * 0.5): 
            content = hit.payload.get("content", "")
            if content:
                # Tránh trùng lặp nếu đã có từ general search
                # Ở đây chúng ta cứ add vào, rerank sẽ xử lý, filter sau
                documents_to_rerank.append(content)
                chunk_metadata.append(path)

    if not documents_to_rerank:
        logger.warning(f"Không có text chunk nào vượt qua vector search threshold {NODE_SEARCH_EMBED_THRESHOLD}")
        await _push_sse(state, title="Không tìm thấy đoạn văn nào liên quan trong cơ sở dữ liệu.")
        state["search_results"] = []
        return state

    # 4. Rerank toàn bộ các chunks (Stage 2)
    await _push_sse(state, title=f"Tìm thấy {len(documents_to_rerank)} đoạn văn, đang xếp hạng lại (reranking)...")
    rerank_results = await _rerank_documents(query, documents_to_rerank)
    
    # 5. Phân giải điểm số vào từng path và lọc ngưỡng > NODE_SEARCH_RERANK_PATH_THRESHOLD
    # rerank_results trả về mảng dict có [{'index': i, 'document': doc, 'score': score}, ...]
    path_max_scores = {}
    path_top_chunks = {}
    
    for result in rerank_results:
        idx = result["index"]
        raw_score = result["score"]
        doc_content = result.get("document", "")
        
        # Áp dụng hàm sigmoid đã có để chuyển điểm về 0 -> 1
        normalized_score = _sigmoid(raw_score)
        
        assigned_path = chunk_metadata[idx]
        
        # Chỉ lưu max score và chunk content tương ứng của từng path
        if assigned_path not in path_max_scores or normalized_score > path_max_scores[assigned_path]:
            path_max_scores[assigned_path] = normalized_score
            path_top_chunks[assigned_path] = doc_content

    # Lọc path nào có max score > NODE_SEARCH_RERANK_PATH_THRESHOLD


    filtered_paths = []
    for path, max_score in path_max_scores.items():
        if max_score > NODE_SEARCH_RERANK_PATH_THRESHOLD:
            filtered_paths.append({
                "path": path,
                "score": max_score,
                "top_chunk": path_top_chunks[path]
            })
            
    # Fallback: nếu không có path nào vượt ngưỡng → lấy top-1 path
    # để LLM tự quyết định có liên quan hay không
    if not filtered_paths and path_max_scores:
        best_path = max(path_max_scores, key=path_max_scores.get)
        filtered_paths.append({
            "path": best_path,
            "score": path_max_scores[best_path],
            "top_chunk": path_top_chunks[best_path],
        })
        logger.info(
            "Fallback: lấy top-1 path '%s' (score=%.3f)",
            best_path, path_max_scores[best_path]
        )

    # Sort paths giảm dần theo rerank score
    filtered_paths.sort(key=lambda x: x["score"], reverse=True)
    # Hard-cap số lượng path trả về để đảm bảo không vượt cấu hình top-k
    filtered_paths = filtered_paths[:QDRANT_LIMIT_PATH]

    state["search_results"] = [
        {"path": p["path"], "score": p["score"]} for p in filtered_paths
    ]

    # SSE: thông báo kết quả tìm kiếm chi tiết
    path_names = [os.path.basename(p["path"]) for p in filtered_paths]
    if filtered_paths:
        await _push_sse(
            state,
            title=f"Đã chọn {len(filtered_paths)} tài liệu phù hợp nhất",
            list_file=path_names,
        )
    else:
        await _push_sse(state, title="Không tìm thấy tài liệu nào đạt ngưỡng rerank.")

    logger.info(
        f"Node Search: {len(filtered_paths)} paths được chọn "
        f"(threshold={NODE_SEARCH_RERANK_PATH_THRESHOLD}): "
        f"{[p['path'] for p in filtered_paths]}"
    )
    
    return state



async def _process_single_path(
    path: str,
    query: str,
    embedding: list[float]
) -> str | None:
    """
    Xử lý 1 path: truy vấn Qdrant theo heading, lọc embed + rerank,
    lấy nguyên heading nếu có chunk đạt ngưỡng, ghép text.

    Args:
        path: Đường dẫn tài liệu trong Qdrant.
        query: Câu hỏi gốc của user.
        embedding: Vector embedding của câu hỏi.

    Returns:
        Chuỗi text context của path, hoặc None nếu không có chunk đạt ngưỡng.
    """

    # 1. Query Qdrant: group_by heading_group_id, filter path
    search_result = await qdrant_service.client.query_points_groups(
        collection_name=COLLECTION_NAME,
        query=embedding,
        group_by="heading_group_id",
        query_filter=models.Filter(
            must=[
                models.FieldCondition(
                    key="path",
                    match=models.MatchValue(value=path)
                )
            ]
        ),
        limit=MAX_HEADINGS_PER_PATH,
        group_size=HEADING_GROUP_SIZE,
        using="dense_content",
        with_payload=True,
    )

    if not search_result.groups:
        return None

    # 2. Thu thập chunks theo heading
    # heading_chunks lưu TẤT CẢ chunks của heading (kể cả embed score thấp)
    # để khi heading đạt ngưỡng rerank → lấy nguyên heading hoàn chỉnh
    heading_chunks = {}
    chunks_to_rerank = []
    chunk_heading_map = []

    for group in search_result.groups:
        heading_id = group.id
        for hit in group.hits:
            payload = hit.payload or {}
            content = payload.get("content", "")
            if not content:
                continue

            # Luôn lưu payload vào heading_chunks (lấy nguyên heading)
            if heading_id not in heading_chunks:
                heading_chunks[heading_id] = []
            heading_chunks[heading_id].append(payload)

            # Chỉ gửi rerank chunks có embed score đủ cao
            score = getattr(hit, "score", 0)
            if score >= NODE_SEARCH_EMBED_THRESHOLD:
                chunks_to_rerank.append(content)
                chunk_heading_map.append(heading_id)

    if not chunks_to_rerank:
        return None

    # 3. Rerank tất cả chunks của path này
    rerank_results = await _rerank_documents(query, chunks_to_rerank)

    # 4. Xác định heading nào có ít nhất 1 chunk đạt ngưỡng rerank
    qualified_headings = set()
    for result in rerank_results:
        idx = result["index"]
        normalized_score = _sigmoid(result["score"])
        if normalized_score > NODE_SEARCH_RERANK_THRESHOLD:
            qualified_headings.add(chunk_heading_map[idx])

    if not qualified_headings:
        return None

    # 5. Lấy toàn bộ chunks của các heading đạt ngưỡng, sắp xếp
    selected_chunks = []
    for heading_id in qualified_headings:
        if heading_id in heading_chunks:
            selected_chunks.extend(heading_chunks[heading_id])

    # Sắp xếp: chunk_index (vị trí trong tài liệu), split_part (vị trí trong heading)
    selected_chunks.sort(
        key=lambda c: (c.get("chunk_index", 0), c.get("split_part", 0))
    )

    # 6. Ghép text + header tên file
    file_name = os.path.basename(path)
    text_parts = [f"=== Tài liệu: {file_name} ==="]
    for chunk in selected_chunks:
        text_parts.append(chunk.get("content", ""))

    return "\n\n".join(text_parts)


async def node_seach_with_path_logic(state: dict) -> dict:
    """
    Với mỗi path từ node_search, truy vấn chi tiết Qdrant theo heading,
    lọc embed + rerank, lấy nguyên heading nếu đạt ngưỡng,
    ghép thành context text cho LLM.

    Input state keys:
        - search_results: List[Dict] từ node_search_logic
        - user_input: Câu hỏi user

    Output state keys:
        - context_with_path: Chuỗi text context ghép từ tất cả paths
    """

    logger.info("=== Bắt đầu Node Search With Path ===")

    search_results = state.get("search_results", [])
    query = state.get("user_input", "")

    if not search_results or not query:
        logger.warning("Không có search_results hoặc user_input.")
        state["context_with_path"] = ""
        return state

    # 1. Tạo embedding cho query (dùng chung cho tất cả paths)
    await _push_sse(state, title="Đang tạo embedding cho truy vấn chi tiết...")
    embedding = await _get_embedding(query)

    # 2. Xử lý song song tất cả paths
    path_names = [os.path.basename(item["path"]) for item in search_results]
    await _push_sse(
        state,
        title=f"Đang trích xuất context từ {len(search_results)} tài liệu song song...",
        list_file=path_names,
    )
    tasks = [
        _process_single_path(item["path"], query, embedding)
        for item in search_results
    ]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    # 3. Lọc kết quả hợp lệ (bỏ None và exceptions)
    context_texts = []
    for i, result in enumerate(results):
        if isinstance(result, Exception):
            path = search_results[i]["path"]
            logger.error(f"Lỗi xử lý path {path}: {result}")
            continue
        if result:
            context_texts.append(result)

    # 4. Ghép tất cả thành 1 chuỗi context
    state["context_with_path"] = "\n\n".join(context_texts)

    ctx_len = len(state["context_with_path"])
    await _push_sse(
        state,
        title=f"Trích xuất hoàn tất: {len(context_texts)}/{len(search_results)} tài liệu có nội dung phù hợp",
        mess=f"Tổng {ctx_len:,} ký tự context",
    )

    logger.info(
        f"Node Search With Path: {len(context_texts)}/{len(search_results)} "
        f"paths có context"
    )

    return state


# =====================================================================
# NODE ASSISTANT — Gọi vLLM trả lời cuối cùng
# =====================================================================

LLM_TEMPERATURE = 0.3

# System prompt chuẩn production cho tra cứu hợp đồng / báo giá
SYSTEM_PROMPT = (
    "Bạn là trợ lý tra cứu hồ sơ dự án/hợp đồng. Hãy tuân thủ các quy tắc sau:"

    "1. TRẢ LỜI CÓ NGUỒN: Chỉ dùng Context được cung cấp. Phải trích dẫn tên tài liệu."
    "2. TRẢ LỜI TỰ DO: Nếu câu hỏi là xã giao hoặc kiến thức chung (không yêu cầu tra cứu), phải tự suy luận và trả lời câu hỏi đó sau đó thêm ghi chú: 'Phản hồi này dựa trên kiến thức chung, không thuộc tài liệu nội bộ'."
    "3. KHI THIẾU THÔNG TIN: Tuyệt đối không nói 'Không tìm thấy'. Hãy phản hồi:\n"
    "   - 'Hiện tại thông tin này chưa rõ ràng trong dữ liệu hiện có.'\n"
    "   - Hướng dẫn user cung cấp thêm các từ khóa định danh để tăng độ chính xác như:\n"
    "   Tên bên tham gia, địa chỉ dự án, tên đầy đủ gói thầu/đồ án/hạng mục, giá trị hợp đồng hoặc năm ký kết.\n"
    "4. ĐỊNH DẠNG: Tiếng Việt, súc tích, rõ ràng đúng trọng tâm không dư thừa, trả lời thẳng vào vấn đề."
)


async def node_fetch_history_logic(state: dict) -> dict:
    """
    Node lấy lịch sử trò chuyện (chat history) từ DB.
    Giới hạn nội dung lấy về trong khoảng 30,000 ký tự.
    Output state object.chat_history: chuỗi text chứa lịch sử.
    """
    from service.history_pipeline_service import build_history_context_with_debug

    if HISTORY_PIPELINE_LOG_ENABLED:
        logger.debug("[HISTORY_PIPELINE] Start node_fetch_history")
    user_id = state.get("user_id", "")
    session_id = state.get("session_id", -1)

    if session_id <= 0 or not user_id:
        if HISTORY_PIPELINE_LOG_ENABLED:
            logger.debug("[HISTORY_PIPELINE] Skip fetch because session_id/user_id is invalid")
        state["chat_history"] = ""
        return state

    try:
        built_history, history_debug = await build_history_context_with_debug(
            user_id=user_id,
            session_id=session_id,
            user_query=state.get("user_input", ""),
            query_flow=state.get("query_flow"),
            max_chars=MAX_HISTORY_CONTEXT,
        )
        state["chat_history"] = built_history
        state["history_pipeline_debug"] = history_debug
        if HISTORY_PIPELINE_LOG_ENABLED:
            logger.debug("[HISTORY_PIPELINE] Built history context chars=%d debug=%s", len(built_history), history_debug)
    except Exception as e:
        logger.error("[HISTORY_PIPELINE] Build context failed: %s", e)
        state["chat_history"] = ""
        state["history_pipeline_debug"] = {
            "short_window_count": 0,
            "semantic_pool_count": 0,
            "semantic_ranked_count": 0,
            "semantic_selected_count": 0,
            "used_fallback_semantic_scope": False,
            "query_embedding_available": False,
            "context_chars": 0,
            "error": str(e),
        }

    return state


async def node_asisstant_logic(state: dict) -> dict:
    """
    Gọi vLLM để sinh câu trả lời cuối cùng từ context đã thu thập.
    Hỗ trợ streaming tokens qua SSE queue nếu có.

    Input state keys:
        - user_input: Câu hỏi user
        - context_with_path: Context text từ node_seach_with_path_logic
        - model_name: Tên model LLM (optional override)
        - sse_queue: asyncio.Queue (optional) để stream tokens

    Output state keys:
        - assistant_response: Câu trả lời từ LLM
    """

    logger.info("=== Bắt đầu Node Assistant ===")

    query = state.get("user_input", "")
    context = state.get("context_with_path", "")
    queue = state.get("sse_queue")

    # Edge case: không có context → trả thông báo ngay, không gọi LLM
    if not context:
        context = "Không có tài liệu nội bộ nào liên quan câu hỏi."
        await _push_sse(state, title="Không tìm thấy tài liệu liên quan, AI sẽ trả lời dựa trên kiến thức chung...")
    else:
        await _push_sse(
            state,
            title=f"Đang chuẩn bị prompt cho mô hình AI ({len(context):,} ký tự context)...",
        )

    logger.info(
        "[RAG_BUDGET] input_tokens=%d file_tokens=%d history_tokens=%d output_tokens=%d "
        "file_chars=%d history_chars=%d",
        RAG_INPUT_TOKEN_BUDGET,
        RAG_FILE_CONTEXT_TOKEN_BUDGET,
        RAG_HISTORY_TOKEN_BUDGET,
        MAX_TOKEN_OUTPUT,
        MAX_FILE_CONTEXT,
        MAX_HISTORY_CONTEXT,
    )

    # Nếu context từ file quá dài theo budget env, cắt đi.
    if len(context) > MAX_FILE_CONTEXT:
        context = context[:MAX_FILE_CONTEXT] + "\n...(Bị cắt gọn do quá giới hạn độ dài)..."

    chat_history = state.get("chat_history", "")
    history_prompt = ""
    if chat_history:
        history_prompt = f"\nNGỮ CẢNH LỊCH SỬ LIÊN QUAN:\n{chat_history}\n"

    # Xây dựng user prompt theo thứ tự tối ưu cache: context chính -> history -> câu hỏi mới.
    user_content = (
        f"\nTÀI LIỆU THAM KHẢO:\n{context}\n"
        f"{history_prompt}\n"
        f"CÂU HỎI CỦA NGƯỜI DÙNG:\n{query}"
    )

    # Chọn model và system prompt theo cấu hình runtime trong DB
    from service.runtime_config_service import (
        get_required_active_prompt_content,
        resolve_model_runtime,
        PROMPT_FEATURE_RAG_ASSISTANT,
    )

    model_selector = state.get("model_name")
    client, resolved_model, meta = await resolve_model_runtime(model_selector)
    current_system_prompt = await get_required_active_prompt_content(
        PROMPT_FEATURE_RAG_ASSISTANT
    )

    try:
        # Streaming mode: gửi từng token qua SSE queue
        stream = await client.chat.completions.create(
            model=resolved_model,
            messages=[
                {"role": "system", "content": current_system_prompt},
                {"role": "user", "content": user_content},
            ],
            temperature=LLM_TEMPERATURE,
            max_tokens=MAX_TOKEN_OUTPUT,
            extra_body=_disable_model_thinking_extra_body(),
            stream=True,
        )

        full_response = ""
        stream_filter = _ReasoningStreamFilter()

        async for chunk in stream:
            if (
                chunk.choices
                and chunk.choices[0].delta
                and chunk.choices[0].delta.content
            ):
                token = chunk.choices[0].delta.content
                full_response += token
                display_token = stream_filter.push(token)

                if queue and stream_filter.last_reasoning:
                    await queue.put({
                        "user_id": state.get("user_id", ""),
                        "session_id": state.get("session_id", -1),
                        "title": "Đang suy luận...",
                        "mess": "",
                        "reasoning_mess": stream_filter.last_reasoning,
                        "end": False,
                    })

                # Push từng token qua SSE queue
                if queue and display_token:
                    await queue.put({
                        "user_id": state.get("user_id", ""),
                        "session_id": state.get("session_id", -1),
                        "title": "Đang trả lời...",
                        "mess": display_token,
                        "end": False,
                    })

        tail_token = stream_filter.flush()
        if queue and tail_token:
            await queue.put({
                "user_id": state.get("user_id", ""),
                "session_id": state.get("session_id", -1),
                "title": "Đang trả lời...",
                "mess": tail_token,
                "end": False,
            })

        final_response = _strip_model_reasoning(full_response)
        if queue and final_response and not stream_filter.emitted_any:
            await queue.put({
                "user_id": state.get("user_id", ""),
                "session_id": state.get("session_id", -1),
                "title": "Đang trả lời...",
                "mess": final_response,
                "end": False,
            })

        state["assistant_response"] = final_response
        logger.info("Node Assistant: Đã stream xong phản hồi từ LLM.")

    except Exception as e:
        logger.error(f"Lỗi khi gọi vLLM: {e}")
        error_msg = "Hệ thống tạm thời không thể xử lý. Vui lòng thử lại."
        state["assistant_response"] = error_msg

        if queue:
            await queue.put({
                "user_id": state.get("user_id", ""),
                "session_id": state.get("session_id", -1),
                "title": "Lỗi",
                "mess": error_msg,
                "end": False,
            })

    return state


# =====================================================================
# NODE SEARCH PATH USER CHOSE — Xử lý khi user chọn sẵn file paths
# =====================================================================

# Tổng token budget cho context từ file khi user chọn path, cấu hình từ env.
_TOKEN_BUDGET = RAG_SELECTED_PATH_TOKEN_BUDGET
# Ước lượng trung bình 1 chunk ~ 600 tokens
_AVG_TOKENS_PER_CHUNK = _env_int("RAG_AVG_TOKENS_PER_CHUNK", 600, minimum=1)
# Giới hạn chunks mỗi path khi vector search cho >10 files
_VECTOR_SEARCH_LIMIT_PER_PATH = 2000


async def _load_full_document_by_path(path: str) -> str | None:
    """
    Load nguyên nội dung markdown của 1 file từ PostgreSQL (document_fulltext).

    Args:
        path: file_path trong bảng document_fulltext.

    Returns:
        Chuỗi text context có header tên file, hoặc None nếu không tìm thấy.
    """
    from database.setup_postgres import SessionLocal
    from database.table.table_postgres import document_fulltext
    from sqlalchemy import select

    async with SessionLocal() as db:
        result = await db.execute(
            select(document_fulltext.content).where(
                document_fulltext.file_path == path
            )
        )
        content = result.scalars().first()

    if not content:
        logger.warning("[LOAD_FULL] Không tìm thấy document_fulltext cho path=%s", path)
        return None

    file_name = os.path.basename(path)
    return f"=== Tài liệu: {file_name} ===\n\n{content}"


def _select_chunks_with_heading_integrity(
    rerank_results: list[dict],
    all_chunks: list[dict],
    chunk_index_map: list[int],
    max_chunks: int,
) -> list[dict]:
    """
    Chọn top chunks sau rerank, đảm bảo trọn vẹn heading (heading_group_id).

    Logic:
        1. Duyệt rerank_results (đã sort giảm dần theo score).
        2. Với mỗi chunk có score cao → đánh dấu heading_group_id của nó là "qualified".
        3. Lấy TẤT CẢ chunks thuộc heading qualified (trọn vẹn heading).
        4. Dừng khi tổng chunks >= max_chunks.
        5. Sắp xếp theo chunk_index → split_part.

    Args:
        rerank_results: Kết quả rerank đã sort desc theo score.
        all_chunks: Tất cả chunks payload gốc (từ Qdrant).
        chunk_index_map: Map index trong rerank_results → index trong all_chunks.
        max_chunks: Số chunk tối đa cho phép.

    Returns:
        Danh sách chunks đã chọn, sắp xếp theo chunk_index + split_part.
    """
    # Build lookup: heading_group_id → list of chunk payloads
    heading_to_chunks = {}
    for chunk in all_chunks:
        hg_id = chunk.get("heading_group_id", "")
        if hg_id not in heading_to_chunks:
            heading_to_chunks[hg_id] = []
        heading_to_chunks[hg_id].append(chunk)

    qualified_headings = []
    seen_headings = set()
    total_selected = 0

    for result in rerank_results:
        idx = result["index"]
        original_idx = chunk_index_map[idx]
        chunk_payload = all_chunks[original_idx]
        hg_id = chunk_payload.get("heading_group_id", "")

        if hg_id in seen_headings:
            continue

        heading_chunks = heading_to_chunks.get(hg_id, [])
        heading_chunk_count = len(heading_chunks)

        # Kiểm tra nếu thêm heading này vẫn trong budget
        if total_selected + heading_chunk_count > max_chunks and total_selected > 0:
            continue

        seen_headings.add(hg_id)
        qualified_headings.append(hg_id)
        total_selected += heading_chunk_count

        if total_selected >= max_chunks:
            break

    # Thu thập tất cả chunks của các heading qualified
    selected_chunks = []
    for hg_id in qualified_headings:
        selected_chunks.extend(heading_to_chunks.get(hg_id, []))

    # Sắp xếp theo chunk_index → split_part
    selected_chunks.sort(
        key=lambda c: (c.get("chunk_index", 0), c.get("split_part", 0))
    )

    return selected_chunks


async def _search_rerank_single_path_full(
    path: str,
    query: str,
    embedding: list[float],
    max_chunks: int,
) -> str | None:
    """
    Xử lý 1 path cho trường hợp 2-10 files:
    Search hết chunks theo path, rerank toàn bộ từng chunk,
    lấy top chunks đảm bảo trọn vẹn heading, sắp xếp theo index.

    Args:
        path: File path trong Qdrant.
        query: Câu hỏi user.
        embedding: Vector embedding câu hỏi.
        max_chunks: Số chunk tối đa cho path này.

    Returns:
        Chuỗi text context hoặc None.
    """
    # 1. Scroll lấy hết chunks của path
    all_chunks = []
    offset = None
    while True:
        points, offset = await qdrant_service.client.scroll(
            collection_name=COLLECTION_NAME,
            scroll_filter=models.Filter(
                must=[
                    models.FieldCondition(
                        key="path",
                        match=models.MatchValue(value=path)
                    )
                ]
            ),
            limit=500,
            with_payload=True,
            with_vectors=False,
            offset=offset,
        )
        for point in points:
            if point.payload and point.payload.get("content"):
                all_chunks.append(point.payload)
        if offset is None:
            break

    if not all_chunks:
        return None

    # 2. Rerank toàn bộ chunks
    documents = [c["content"] for c in all_chunks]
    chunk_index_map = list(range(len(all_chunks)))
    rerank_results = await _rerank_documents(query, documents)

    if not rerank_results:
        return None

    # 3. Chọn chunks với heading integrity
    selected = _select_chunks_with_heading_integrity(
        rerank_results, all_chunks, chunk_index_map, max_chunks
    )

    if not selected:
        return None

    # 4. Ghép text
    file_name = os.path.basename(path)
    text_parts = [f"=== Tài liệu: {file_name} ==="]
    for chunk in selected:
        text_parts.append(chunk.get("content", ""))

    return "\n\n".join(text_parts)


async def _search_rerank_single_path_vector(
    path: str,
    query: str,
    embedding: list[float],
    max_chunks: int,
) -> str | None:
    """
    Xử lý 1 path cho trường hợp >10 files:
    Vector search theo path chỉ lấy chunks > NODE_SEARCH_EMBED_THRESHOLD (max 2000),
    rerank để xác định headings quan trọng, sau đó scroll lấy trọn vẹn heading.

    Args:
        path: File path trong Qdrant.
        query: Câu hỏi user.
        embedding: Vector embedding câu hỏi.
        max_chunks: Số chunk tối đa cho path này.

    Returns:
        Chuỗi text context hoặc None.
    """
    # 1. Vector search filter by path, limit 2000
    search_result = await qdrant_service.client.query_points(
        collection_name=COLLECTION_NAME,
        query=embedding,
        query_filter=models.Filter(
            must=[
                models.FieldCondition(
                    key="path",
                    match=models.MatchValue(value=path)
                )
            ]
        ),
        limit=_VECTOR_SEARCH_LIMIT_PER_PATH,
        using="dense_content",
        with_payload=True,
        score_threshold=NODE_SEARCH_EMBED_THRESHOLD,
    )

    if not search_result.points:
        return None

    # 2. Thu thập chunks đạt ngưỡng embedding (chỉ dùng để rerank, chưa phải kết quả cuối)
    candidate_chunks = []
    for hit in search_result.points:
        payload = hit.payload or {}
        if payload.get("content"):
            candidate_chunks.append(payload)

    if not candidate_chunks:
        return None

    # 3. Rerank toàn bộ candidates
    documents = [c["content"] for c in candidate_chunks]
    rerank_results = await _rerank_documents(query, documents)

    if not rerank_results:
        return None

    # 4. Xác định thứ tự heading qualified theo rerank score
    qualified_hg_ids = []
    seen_hg = set()
    for result in rerank_results:
        idx = result["index"]
        hg_id = candidate_chunks[idx].get("heading_group_id", "")
        if hg_id not in seen_hg:
            seen_hg.add(hg_id)
            qualified_hg_ids.append(hg_id)

    if not qualified_hg_ids:
        return None

    # 5. Scroll Qdrant lấy TẤT CẢ chunks của các heading qualified (trọn vẹn heading)
    heading_filter_conditions = [
        models.FieldCondition(
            key="heading_group_id",
            match=models.MatchValue(value=hg_id)
        )
        for hg_id in qualified_hg_ids
    ]

    all_heading_chunks = {}  # hg_id → [chunk_payloads]
    offset = None
    while True:
        points, offset = await qdrant_service.client.scroll(
            collection_name=COLLECTION_NAME,
            scroll_filter=models.Filter(
                must=[
                    models.FieldCondition(
                        key="path",
                        match=models.MatchValue(value=path)
                    ),
                    models.Filter(should=heading_filter_conditions),
                ]
            ),
            limit=500,
            with_payload=True,
            with_vectors=False,
            offset=offset,
        )
        for point in points:
            if point.payload and point.payload.get("content"):
                hg_id = point.payload.get("heading_group_id", "")
                all_heading_chunks.setdefault(hg_id, []).append(point.payload)
        if offset is None:
            break

    # 6. Chọn headings trong budget (theo thứ tự rerank score, đếm chunk không đếm heading)
    selected_chunks = []
    total = 0
    for hg_id in qualified_hg_ids:
        heading_chunks = all_heading_chunks.get(hg_id, [])
        if not heading_chunks:
            continue
        heading_chunk_count = len(heading_chunks)
        if total + heading_chunk_count > max_chunks and total > 0:
            continue
        selected_chunks.extend(heading_chunks)
        total += heading_chunk_count
        if total >= max_chunks:
            break

    if not selected_chunks:
        return None

    # 7. Sắp xếp theo chunk_index → split_part
    selected_chunks.sort(
        key=lambda c: (c.get("chunk_index", 0), c.get("split_part", 0))
    )

    # 8. Ghép text
    file_name = os.path.basename(path)
    text_parts = [f"=== Tài liệu: {file_name} ==="]
    for chunk in selected_chunks:
        text_parts.append(chunk.get("content", ""))

    return "\n\n".join(text_parts)


async def node_search_path_user_chose_logic(state: dict) -> dict:
    """
    Node xử lý khi user đã chọn sẵn danh sách file paths.

    3 trường hợp:
        - 1 file: Load nguyên document từ PostgreSQL.
        - 2-10 files: Search hết chunks per path → rerank → heading integrity → ghép.
        - >10 files: Vector search > threshold per path (max 2000) → rerank → ghép.

    Input state keys:
        - path_list: List[str] danh sách file paths user chọn.
        - user_input: Câu hỏi user.

    Output state keys:
        - context_with_path: Chuỗi text context ghép.
    """
    logger.info("=== Bắt đầu Node Search Path User Chose ===")

    raw_path_list = state.get("path_list", [])
    # Loại trùng nhưng giữ thứ tự.
    path_list = list(dict.fromkeys(raw_path_list))
    query = state.get("user_input", "")

    if not path_list or not query:
        logger.warning("path_list rỗng hoặc không có user_input.")
        state["context_with_path"] = ""
        return state

    # Hard-cap số file xử lý mỗi lượt query để tránh quét quá nhiều tài liệu.
    if len(path_list) > MAX_USER_PATHS_PER_QUERY:
        original_count = len(path_list)
        path_list = path_list[:MAX_USER_PATHS_PER_QUERY]
        logger.info(
            "[USER_PATH] Cắt path_list từ %d xuống %d (MAX_USER_PATHS_PER_QUERY)",
            original_count, MAX_USER_PATHS_PER_QUERY
        )
        await _push_sse(
            state,
            title=f"Giới hạn truy vấn tối đa {MAX_USER_PATHS_PER_QUERY} file/lần",
            mess=f"Nhận {original_count} file, hệ thống sẽ dùng {MAX_USER_PATHS_PER_QUERY} file đầu tiên.",
        )

    num_paths = len(path_list)
    path_names = [os.path.basename(p) for p in path_list]
    logger.info("[USER_PATH] Số paths: %d, paths: %s", num_paths, path_list)

    await _push_sse(
        state,
        title=f"Nhận {num_paths} file từ người dùng",
        list_file=path_names,
    )

    # --- Trường hợp 1: Chỉ có 1 file → load nguyên document từ PostgreSQL ---
    if num_paths == 1:
        logger.info("[USER_PATH] 1 file → load full document từ PostgreSQL")
        await _push_sse(state, title=f"Đang tải toàn bộ nội dung '{path_names[0]}'...")
        content = await _load_full_document_by_path(path_list[0])
        state["context_with_path"] = content or ""
        if content:
            await _push_sse(
                state,
                title=f"Đã tải xong '{path_names[0]}'",
                mess=f"{len(content):,} ký tự",
            )
        else:
            await _push_sse(state, title=f"Không tìm thấy nội dung cho '{path_names[0]}'.")
        return state

    # --- Tính max chunks per path ---
    max_chunks_per_path = max(1, _TOKEN_BUDGET // (num_paths * _AVG_TOKENS_PER_CHUNK))
    logger.info("[USER_PATH] max_chunks_per_path = %d", max_chunks_per_path)

    # --- Tạo embedding để dùng chung ---
    await _push_sse(state, title="Đang tạo embedding câu hỏi...")
    embedding = await _get_embedding(query)

    # --- Trường hợp 2: 2-10 files → search hết + rerank per path ---
    if num_paths <= 10:
        logger.info("[USER_PATH] 2-10 files → search full + rerank per path")
        await _push_sse(
            state,
            title=f"Đang tìm kiếm toàn bộ và xếp hạng nội dung trong {num_paths} file...",
            mess=f"Mỗi file tối đa {max_chunks_per_path} đoạn",
        )
        tasks = [
            _search_rerank_single_path_full(p, query, embedding, max_chunks_per_path)
            for p in path_list
        ]
    # --- Trường hợp 3: >10 files → vector search + rerank per path ---
    else:
        logger.info("[USER_PATH] >10 files → vector search + rerank per path")
        await _push_sse(
            state,
            title=f"Đang tìm kiếm vector và xếp hạng trong {num_paths} file...",
            mess=f"Mỗi file tối đa {max_chunks_per_path} đoạn (chế độ vector search)",
        )
        tasks = [
            _search_rerank_single_path_vector(p, query, embedding, max_chunks_per_path)
            for p in path_list
        ]

    results = await asyncio.gather(*tasks, return_exceptions=True)

    # Lọc kết quả hợp lệ
    context_texts = []
    for i, result in enumerate(results):
        if isinstance(result, Exception):
            logger.error("[USER_PATH] Lỗi xử lý path %s: %s", path_list[i], result)
            continue
        if result:
            context_texts.append(result)

    state["context_with_path"] = "\n\n".join(context_texts)

    ctx_len = len(state["context_with_path"])
    await _push_sse(
        state,
        title=f"Hoàn thành: {len(context_texts)}/{num_paths} file có nội dung liên quan",
        mess=f"Tổng {ctx_len:,} ký tự context",
    )

    logger.info(
        "[USER_PATH] Hoàn thành: %d/%d paths có context",
        len(context_texts), num_paths
    )

    return state


# =====================================================================
# WEB SEARCH PIPELINE LOGIC
# =====================================================================


def _normalize_url(raw: str) -> str:
    url = (raw or "").strip()
    if not url:
        return ""
    if not url.startswith(("http://", "https://")):
        url = f"https://{url}"

    try:
        parsed = urlparse(url)
        scheme = parsed.scheme.lower() or "https"
        netloc = (parsed.netloc or "").lower()

        path = parsed.path or "/"
        path = re.sub(r"/\./", "/", path)
        path = re.sub(r"//+", "/", path)
        if not path.startswith("/"):
            path = f"/{path}"

        # Loại tracking params phổ biến để giảm duplicate URL.
        filtered_qs = []
        for k, v in parse_qsl(parsed.query, keep_blank_values=False):
            key = (k or "").lower()
            if key.startswith("utm_") or key in {"fbclid", "gclid", "ref", "source"}:
                continue
            filtered_qs.append((k, v))
        query = urlencode(filtered_qs, doseq=True)

        return urlunparse((scheme, netloc, path, "", query, ""))
    except Exception:
        return url


def _is_probably_content_url(url: str) -> bool:
    path = (urlparse(url).path or "").lower()

    # Loại static assets và feed/endpoints không phải bài viết.
    if re.search(r"\.(css|js|json|xml|rss|atom|ico|png|jpe?g|gif|webp|svg|woff2?|ttf|eot|mp4|mp3|zip|rar|7z|tar|gz)(?:$|\?)", path):
        return False
    if re.search(r"/(feed|comments/feed|wp-content|wp-includes|wp-json)(?:/|$)", path):
        return False

    return True


def _is_listing_url(url: str) -> bool:
    path = (urlparse(url).path or "").lower().strip("/")
    if not path:
        return False
    if re.search(r"(^|/)(blog|news|tin-tuc|bai-viet|posts?|articles?|category)(/|$)", f"/{path}/"):
        return True
    return False


def _extract_domain(url: str) -> str:
    try:
        return (urlparse(url).hostname or "").lower()
    except Exception:
        return ""


def _normalize_url_prefix(raw_prefix: str) -> str:
    normalized = _normalize_url(raw_prefix)
    return normalized.rstrip("/").lower()


def _url_matches_any_prefix(url: str, prefixes: list[str]) -> bool:
    if not prefixes:
        return False
    normalized_url = _normalize_url(url).lower()
    if not normalized_url:
        return False
    target = normalized_url.rstrip("/")
    for raw_prefix in prefixes:
        prefix = _normalize_url_prefix(raw_prefix)
        if not prefix:
            continue
        if target == prefix or target.startswith(f"{prefix}/"):
            return True
    return False


def _domain_blocked(domain: str, blocked_domains: list[str]) -> bool:
    if not domain:
        return True
    for blocked in blocked_domains:
        blocked = blocked.lower().strip()
        if not blocked:
            continue
        if domain == blocked or domain.endswith(f".{blocked}"):
            return True
    return False


def _domain_allowed(domain: str, allowed_domains: list[str]) -> bool:
    if not domain:
        return False
    if not allowed_domains:
        return True
    for allowed in allowed_domains:
        allowed = allowed.lower().strip()
        if not allowed:
            continue
        if domain == allowed or domain.endswith(f".{allowed}"):
            return True
    return False


def _is_source_allowed(url: str, source_policy: dict | None = None) -> bool:
    policy = source_policy or _default_source_policy()
    blocked_domains = [str(x).lower().strip() for x in (policy.get("block_domains") or []) if str(x).strip()]
    blocked_url_prefixes = [str(x).strip() for x in (policy.get("block_url_prefixes") or []) if str(x).strip()]
    allowed_domains = [str(x).lower().strip() for x in (policy.get("allow_domains") or []) if str(x).strip()]
    allowed_url_prefixes = [str(x).strip() for x in (policy.get("allow_url_prefixes") or []) if str(x).strip()]
    strict_filter = bool(policy.get("strict_source_filter"))

    domain = _extract_domain(url)
    if _domain_blocked(domain, blocked_domains):
        return False

    if _url_matches_any_prefix(url, blocked_url_prefixes):
        return False

    has_allow_scope = bool(allowed_domains or allowed_url_prefixes)
    if not has_allow_scope:
        return True

    if _domain_allowed(domain, allowed_domains):
        return True

    if _url_matches_any_prefix(url, allowed_url_prefixes):
        return True

    return False


def _is_private_or_local_host(hostname: str) -> bool:
    if not hostname:
        return True

    lowered = hostname.lower()
    if lowered in {"localhost", "127.0.0.1", "::1"}:
        return True

    try:
        infos = socket.getaddrinfo(hostname, None)
    except Exception:
        return True

    for info in infos:
        ip_str = info[4][0]
        try:
            ip_obj = ipaddress.ip_address(ip_str)
            if (
                ip_obj.is_private
                or ip_obj.is_loopback
                or ip_obj.is_link_local
                or ip_obj.is_reserved
                or ip_obj.is_multicast
            ):
                return True
        except Exception:
            return True

    return False


def _is_url_safe(url: str) -> bool:
    try:
        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"}:
            return False
        host = (parsed.hostname or "").lower()
        if not host:
            return False
        if host.endswith(".internal"):
            return False
        if _is_private_or_local_host(host):
            return False
        return True
    except Exception:
        return False


def _strip_html_to_text(html_content: str) -> str:
    text = re.sub(r"(?is)<script.*?>.*?</script>", " ", html_content)
    text = re.sub(r"(?is)<style.*?>.*?</style>", " ", text)
    text = re.sub(r"(?is)<noscript.*?>.*?</noscript>", " ", text)
    text = re.sub(r"(?is)<!--.*?-->", " ", text)
    text = re.sub(r"(?is)<[^>]+>", " ", text)
    text = html.unescape(text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _extract_main_content_text(html_content: str) -> str:
    """
    Ưu tiên lấy nội dung trong article/main/section trước khi fallback strip full body.
    Giảm trường hợp chỉ lấy menu/header/footer dẫn tới model chỉ trả URL/title.
    """
    cleaned = re.sub(r"(?is)<script.*?>.*?</script>", " ", html_content)
    cleaned = re.sub(r"(?is)<style.*?>.*?</style>", " ", cleaned)
    cleaned = re.sub(r"(?is)<noscript.*?>.*?</noscript>", " ", cleaned)
    cleaned = re.sub(r"(?is)<!--.*?-->", " ", cleaned)

    # Ưu tiên extractor chuyên dụng trước để lấy nội dung "main body" tốt hơn.
    try:
        import trafilatura

        extracted = trafilatura.extract(
            cleaned,
            output_format="txt",
            include_links=False,
            include_tables=False,
            favor_recall=True,
        )
        extracted_text = re.sub(r"\s+", " ", str(extracted or "")).strip()
        if len(extracted_text) >= WEB_MIN_CONTENT_CHARS_PER_URL:
            return extracted_text
    except Exception:
        pass

    # Fallback 2: readability-lxml khi trafilatura không hiệu quả.
    try:
        from readability import Document

        doc = Document(cleaned)
        summary_html = doc.summary(html_partial=True)
        readability_text = _strip_html_to_text(summary_html)
        if len(readability_text) >= WEB_MIN_CONTENT_CHARS_PER_URL:
            return readability_text
    except Exception:
        pass

    candidate_blocks: list[str] = []

    for pattern in [
        r"(?is)<article[^>]*>(.*?)</article>",
        r"(?is)<main[^>]*>(.*?)</main>",
        r"(?is)<section[^>]*>(.*?)</section>",
    ]:
        candidate_blocks.extend(re.findall(pattern, cleaned))

    # Nếu không bắt được main/article thì thử lấy tập paragraph để tránh text menu.
    if not candidate_blocks:
        paragraphs = re.findall(r"(?is)<p[^>]*>(.*?)</p>", cleaned)
        if paragraphs:
            candidate_blocks.append(" ".join(paragraphs))

    best = ""
    for block in candidate_blocks:
        text = _strip_html_to_text(block)
        if len(text) > len(best):
            best = text

    # Fallback cuối cùng: strip toàn trang
    if len(best) < WEB_MIN_CONTENT_CHARS_PER_URL:
        best = _strip_html_to_text(cleaned)

    # Loại các trang yêu cầu JS/challenge thường không có nội dung thật.
    lowered = best.lower()
    if (
        "enable javascript" in lowered
        or "access denied" in lowered
        or "cf-chl" in lowered
        or "checking your browser" in lowered
    ):
        return ""

    return re.sub(r"\s+", " ", best).strip()


def _extract_links_from_html(base_url: str, html_content: str) -> list[str]:
    links: list[str] = []
    for match in re.finditer(r'href=["\']([^"\']+)["\']', html_content, flags=re.IGNORECASE):
        href = (match.group(1) or "").strip()
        if not href or href.startswith(("#", "javascript:", "mailto:")):
            continue
        abs_url = urljoin(base_url, href)
        abs_url = _normalize_url(abs_url)
        parsed = urlparse(abs_url)
        if parsed.scheme not in {"http", "https"}:
            continue
        links.append(abs_url)
    return list(dict.fromkeys(links))


async def _search_urls_with_searxng(
    query: str,
    *,
    topk: int,
    allowed_domains: list[str] | None = None,
    strict_domain_filter: bool = False,
    source_policy: dict | None = None,
) -> tuple[list[str], dict]:
    if not query.strip():
        return [], {"provider": "none", "provider_trace": [], "cache_hit": False}

    try:
        broker_result = await search_broker_service.search_urls(
            query,
            topk=max(1, topk),
            allowed_domains=allowed_domains if strict_domain_filter else None,
        )

        urls: list[str] = []
        seen = set()
        domains = allowed_domains or []
        for raw_url in broker_result.urls:
            normalized = _normalize_url(str(raw_url or ""))
            if not normalized or normalized in seen:
                continue
            if not _is_url_safe(normalized) or not _is_probably_content_url(normalized):
                continue
            if not _is_source_allowed(normalized, source_policy=source_policy):
                continue

            host = _extract_domain(normalized)
            if strict_domain_filter and domains and not _domain_allowed(host, domains):
                continue

            seen.add(normalized)
            urls.append(normalized)
            if len(urls) >= topk:
                break

        debug_meta = {
            "provider": broker_result.provider,
            "provider_trace": broker_result.provider_trace,
            "cache_hit": bool(broker_result.cache_hit),
        }
        return urls, debug_meta
    except Exception as e:
        if WEB_SEARCH_LOG_ENABLED:
            logger.warning("[WEB_SEARCH] Broker search failed: %s", e)
        return [], {"provider": "none", "provider_trace": [], "cache_hit": False, "error": str(e)}


async def _fetch_url_html(url: str, timeout_sec: float) -> tuple[str, str]:
    timeout = httpx.Timeout(timeout_sec)
    headers = {
        "User-Agent": "Mozilla/5.0 (compatible; RAG-WebSearch/1.0)",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    }
    proxy_url = os.getenv("WEB_FETCH_EGRESS_PROXY_URL", "").strip() or None
    attempts = WEB_FETCH_RETRY_MAX + 1
    last_err: Exception | None = None

    for attempt in range(attempts):
        try:
            async with _WEB_FETCH_SEMAPHORE:
                async with httpx.AsyncClient(
                    timeout=timeout,
                    follow_redirects=True,
                    headers=headers,
                    proxy=proxy_url,
                ) as client:
                    resp = await client.get(url)
                    resp.raise_for_status()
                    content_type = (resp.headers.get("content-type") or "").lower()
                    if (
                        "text/html" not in content_type
                        and "application/xml" not in content_type
                        and "text/xml" not in content_type
                    ):
                        return "", content_type
                    return resp.text or "", content_type
        except Exception as e:
            last_err = e
            if attempt >= attempts - 1:
                break
            backoff_ms = WEB_FETCH_RETRY_BASE_MS * (2 ** attempt)
            jitter_ms = random.randint(0, max(1, int(backoff_ms * 0.3)))
            await asyncio.sleep((backoff_ms + jitter_ms) / 1000.0)

    raise last_err if last_err else RuntimeError("fetch_failed")


async def _fetch_url_title(url: str, timeout_sec: float = WEB_TITLE_FETCH_TIMEOUT_SEC) -> str:
    """
    Fetch nhanh title để phục vụ URL selector theo semantic title match.
    """
    try:
        html_text, _content_type = await _fetch_url_html(url, timeout_sec)
        if not html_text:
            return ""

        title_match = re.search(
            r"<title[^>]*>(.*?)</title>",
            html_text,
            flags=re.IGNORECASE | re.DOTALL,
        )
        if not title_match:
            return ""

        title = re.sub(r"\s+", " ", title_match.group(1)).strip()
        return title
    except Exception:
        return ""


async def _discover_urls_from_domain(domain: str, max_urls: int) -> list[str]:
    candidate_urls: list[str] = []
    base_url = f"https://{domain}"

    def _extract_locs(xml_text: str) -> list[str]:
        return re.findall(r"<loc>(.*?)</loc>", xml_text, flags=re.IGNORECASE)

    # 1) Ưu tiên sitemap.xml
    sitemap_url = f"{base_url}/sitemap.xml"
    try:
        xml_text, _ = await _fetch_url_html(sitemap_url, WEB_SEARCH_TIMEOUT_SEC)
        if xml_text:
            locs = _extract_locs(xml_text)
            for loc in locs:
                u = _normalize_url(loc)
                if not u or not _extract_domain(u).endswith(domain):
                    continue

                # Hỗ trợ sitemap index -> đọc thêm child sitemap để lấy link sâu.
                if u.lower().endswith(".xml"):
                    try:
                        child_xml, _ = await _fetch_url_html(u, WEB_SEARCH_TIMEOUT_SEC)
                        child_locs = _extract_locs(child_xml) if child_xml else []
                        for child_loc in child_locs:
                            child_u = _normalize_url(child_loc)
                            if child_u and _extract_domain(child_u).endswith(domain):
                                candidate_urls.append(child_u)
                            if len(candidate_urls) >= max_urls:
                                break
                    except Exception:
                        pass
                else:
                    candidate_urls.append(u)

                if len(candidate_urls) >= max_urls:
                    break
    except Exception:
        pass

    # 2) Fallback: homepage links
    if len(candidate_urls) < max_urls:
        try:
            home_html, _ = await _fetch_url_html(base_url, WEB_SEARCH_TIMEOUT_SEC)
            home_links = _extract_links_from_html(base_url, home_html)
            listing_pages: list[str] = []
            for link in home_links:
                if _extract_domain(link).endswith(domain):
                    candidate_urls.append(link)
                    if _is_listing_url(link):
                        listing_pages.append(link)
                if len(candidate_urls) >= max_urls:
                    break

            # Đọc sâu thêm từ các trang listing để lấy link bài viết cụ thể.
            for listing_url in list(dict.fromkeys(listing_pages))[:WEB_LISTING_EXPAND_MAX_PAGES]:
                try:
                    listing_html, _ = await _fetch_url_html(listing_url, WEB_SEARCH_TIMEOUT_SEC)
                    deep_links = _extract_links_from_html(listing_url, listing_html)
                    added = 0
                    for deep_link in deep_links:
                        if _extract_domain(deep_link).endswith(domain):
                            candidate_urls.append(deep_link)
                            added += 1
                        if added >= WEB_LISTING_EXPAND_LINK_LIMIT or len(candidate_urls) >= max_urls:
                            break
                    if len(candidate_urls) >= max_urls:
                        break
                except Exception:
                    continue
        except Exception:
            pass

    # 3) Clean + dedup
    cleaned: list[str] = []
    seen = set()
    for url in candidate_urls:
        normalized = _normalize_url(url)
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        if _is_url_safe(normalized) and _is_probably_content_url(normalized):
            cleaned.append(normalized)
        if len(cleaned) >= max_urls:
            break

    return cleaned


def _url_relevance_score(url: str, query: str) -> float:
    host = (_extract_domain(url) or "").lower()
    path = (urlparse(url).path or "").lower()
    terms = [t.lower() for t in re.findall(r"[\wÀ-ỹ]{3,}", query or "")]
    score = 0.0
    host_hit = False
    for term in terms:
        if term in host:
            host_hit = True
            score += 0.9
        if term in path:
            score += 1.0

    # Heuristic freshness by path keywords
    if re.search(r"/(blog|news|tin-tuc|bai-viet)/", path):
        score += 0.5
    if re.search(r"/(tag|category|author)/", path):
        score -= 0.25

    # Ưu tiên URL sâu hơn (thường là bài viết cụ thể), giảm điểm listing/feed/static.
    depth = len([seg for seg in path.split("/") if seg])
    if depth >= 3:
        score += 0.6
    elif depth <= 1:
        score += 0.3 if host_hit else -0.8

    if re.search(r"/(feed|comments/feed|wp-content|wp-includes|wp-json)(?:/|$)", path):
        score -= 3.0
    if not _is_probably_content_url(url):
        score -= 3.0

    return score


def _source_priority_score(url: str, query: str, plan: dict | None = None) -> float:
    """
    Score nguồn bổ trợ cho semantic rerank.

    Mục tiêu là ưu tiên nguồn chính thức/đúng domain khi entity trong query khớp domain,
    nhưng vẫn giữ open-web rộng khi không có tín hiệu domain rõ.
    """
    plan = plan or {}
    domain = _extract_domain(url)
    if not domain:
        return 0.0

    query_terms = {
        t.lower()
        for t in re.findall(r"[a-zA-Z0-9À-ỹ]{3,}", query or "", flags=re.UNICODE)
        if t.lower() not in VI_QUERY_STOPWORDS
    }
    preferred_domains = [str(d).lower().strip() for d in (plan.get("preferred_domains") or []) if str(d).strip()]
    target_domains = [str(d).lower().strip() for d in (plan.get("target_domains") or []) if str(d).strip()]

    score = 0.0

    for scoped_domain in target_domains:
        if _domain_allowed(domain, [scoped_domain]):
            score += 0.55
            break

    for preferred_domain in preferred_domains:
        if not _domain_allowed(domain, [preferred_domain]):
            continue
        score += 0.25
        root_token = preferred_domain.split(".")[0].replace("-", "")
        compact_terms = {term.replace("-", "") for term in query_terms}
        if root_token and root_token in compact_terms:
            score += 0.45
        break

    path = (urlparse(url).path or "/").lower().strip("/")
    if path in {"", "about", "about-us", "gioi-thieu", "ve-chung-toi", "company"}:
        score += 0.15

    return min(score, 1.0)


def _redis_domain_map_key(domain: str) -> str:
    return f"web:domain_map:{domain}"


def _filter_urls_by_domain(urls: list[str], domain: str, limit: int) -> list[str]:
    cleaned: list[str] = []
    seen = set()
    target = (domain or "").strip().lower()

    for raw_url in urls:
        normalized = _normalize_url(str(raw_url or ""))
        if not normalized or normalized in seen:
            continue
        if not _is_url_safe(normalized):
            continue
        if not _is_probably_content_url(normalized):
            continue
        url_domain = _extract_domain(normalized)
        if target and not (url_domain == target or url_domain.endswith(f".{target}")):
            continue
        seen.add(normalized)
        cleaned.append(normalized)
        if len(cleaned) >= limit:
            break
    return cleaned


async def _load_cached_domain_urls(domain: str, limit: int) -> list[str]:
    from database.setup_redis import redis_service

    key = _redis_domain_map_key(domain)
    try:
        raw = await redis_service.client.get(key)
        if not raw:
            return []
        payload = json.loads(raw)
        urls = payload.get("urls") if isinstance(payload, dict) else payload
        if not isinstance(urls, list):
            return []
        return _filter_urls_by_domain(urls, domain, limit)
    except Exception as e:
        logger.debug("[WEB_MAP_CACHE] Load cache fail domain=%s err=%s", domain, e)
        return []


async def _set_cached_domain_urls(domain: str, urls: list[str]) -> None:
    from database.setup_redis import redis_service

    key = _redis_domain_map_key(domain)
    safe_urls = _filter_urls_by_domain(urls, domain, WEB_MAX_CANDIDATE_URLS)
    payload = {
        "domain": domain,
        "urls": safe_urls,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    try:
        await redis_service.client.set(key, json.dumps(payload, ensure_ascii=False), ex=WEB_DOMAIN_MAP_TTL_SEC)
    except Exception as e:
        logger.debug("[WEB_MAP_CACHE] Set cache fail domain=%s err=%s", domain, e)


async def _load_source_policy_from_db() -> dict:
    policy = _default_source_policy()

    # Cache-aside: ưu tiên Redis để tránh query DB lặp lại ở mỗi câu hỏi.
    try:
        from database.setup_redis import redis_service

        client = redis_service.client
        if client:
            cached_raw = await client.get(WEB_SOURCE_POLICY_CACHE_KEY)
            if cached_raw:
                cached = json.loads(cached_raw)
                if isinstance(cached, dict):
                    return {
                        "strict_source_filter": bool(cached.get("strict_source_filter", policy["strict_source_filter"])),
                        "allow_domains": list(cached.get("allow_domains") or []),
                        "allow_url_prefixes": list(cached.get("allow_url_prefixes") or []),
                        "block_domains": list(cached.get("block_domains") or []),
                        "block_url_prefixes": list(cached.get("block_url_prefixes") or []),
                    }
    except Exception as e:
        logger.debug("[WEB_SOURCE_POLICY] Read cache fail: %s", e)

    try:
        from sqlalchemy import select
        from database.setup_postgres import SessionLocal
        from database.table.table_postgres import WebSourceRule

        async with SessionLocal() as db:
            result = await db.execute(
                select(WebSourceRule).where(WebSourceRule.is_active.is_(True))
            )
            rows = result.scalars().all()

        allow_domains = set(policy["allow_domains"])
        allow_prefixes = set(policy["allow_url_prefixes"])
        block_domains = set(policy["block_domains"])
        block_prefixes = set(policy["block_url_prefixes"])

        for row in rows:
            rule_type = str(row.rule_type or "").strip().lower()
            match_type = str(row.match_type or "").strip().lower()
            value = str(row.value or "").strip()
            if not rule_type or not match_type or not value:
                continue

            if match_type == "domain":
                normalized = value.lower().strip().strip(".")
                if not normalized:
                    continue
                if rule_type == "allow":
                    allow_domains.add(normalized)
                elif rule_type == "block":
                    block_domains.add(normalized)
            elif match_type == "url_prefix":
                normalized = _normalize_url_prefix(value)
                if not normalized:
                    continue
                if rule_type == "allow":
                    allow_prefixes.add(normalized)
                elif rule_type == "block":
                    block_prefixes.add(normalized)

        policy["allow_domains"] = sorted(allow_domains)
        policy["allow_url_prefixes"] = sorted(allow_prefixes)
        policy["block_domains"] = sorted(block_domains)
        policy["block_url_prefixes"] = sorted(block_prefixes)

        try:
            from database.setup_redis import redis_service

            client = redis_service.client
            if client:
                await client.set(WEB_SOURCE_POLICY_CACHE_KEY, json.dumps(policy, ensure_ascii=False))
        except Exception as cache_e:
            logger.debug("[WEB_SOURCE_POLICY] Write cache fail: %s", cache_e)
    except Exception as e:
        logger.debug("[WEB_SOURCE_POLICY] Load DB rules fail: %s", e)

    return policy


async def invalidate_web_source_policy_cache() -> None:
    try:
        from database.setup_redis import redis_service

        client = redis_service.client
        if client:
            await client.delete(WEB_SOURCE_POLICY_CACHE_KEY)
    except Exception as e:
        logger.warning("[WEB_SOURCE_POLICY] Invalidate cache fail: %s", e)


async def warmup_web_source_policy_cache() -> None:
    """
    Warmup policy cache sau khi backend startup.
    """
    await _load_source_policy_from_db()


async def _load_indexed_domain_urls(domain: str, query: str, limit: int) -> list[str]:
    from sqlalchemy import select, desc
    from database.setup_postgres import SessionLocal
    from database.table.table_postgres import DomainUrlIndex

    try:
        async with SessionLocal() as db:
            result = await db.execute(
                select(DomainUrlIndex)
                .where(DomainUrlIndex.domain == domain)
                .order_by(
                    desc(DomainUrlIndex.quality_score),
                    desc(DomainUrlIndex.last_seen),
                    desc(DomainUrlIndex.id),
                )
                .limit(max(10, limit * 3))
            )
            rows = result.scalars().all()

        if not rows:
            return []

        ranked: list[tuple[str, float]] = []
        for row in rows:
            url = _normalize_url(row.url)
            if not url:
                continue
            score = float(row.quality_score or 0.0) + _url_relevance_score(url, query)
            ranked.append((url, score))

        ranked.sort(key=lambda x: x[1], reverse=True)
        return _filter_urls_by_domain([u for u, _ in ranked], domain, limit)
    except Exception as e:
        logger.debug("[WEB_MAP_DB] Load index fail domain=%s err=%s", domain, e)
        return []


async def _upsert_domain_url_index(domain: str, urls: list[str], query: str) -> None:
    from sqlalchemy import select
    from database.setup_postgres import SessionLocal
    from database.table.table_postgres import DomainUrlIndex

    safe_urls = _filter_urls_by_domain(urls, domain, WEB_MAX_CANDIDATE_URLS)
    if not safe_urls:
        return

    try:
        now = datetime.now(timezone.utc)
        async with SessionLocal() as db:
            existing_result = await db.execute(
                select(DomainUrlIndex).where(
                    DomainUrlIndex.domain == domain,
                    DomainUrlIndex.url.in_(safe_urls),
                )
            )
            existing_rows = existing_result.scalars().all()
            existing_by_url = {row.url: row for row in existing_rows}

            for url in safe_urls:
                score = max(_url_relevance_score(url, query), 0.0)
                existing = existing_by_url.get(url)
                if existing:
                    existing.last_seen = now
                    existing.fetch_status = "ok"
                    existing.quality_score = max(float(existing.quality_score or 0.0), score)
                    continue

                db.add(
                    DomainUrlIndex(
                        domain=domain,
                        url=url,
                        title=None,
                        path_type=(urlparse(url).path or "/"),
                        quality_score=score,
                        fetch_status="ok",
                        last_seen=now,
                    )
                )

            await db.commit()
    except Exception as e:
        logger.debug("[WEB_MAP_DB] Upsert index fail domain=%s err=%s", domain, e)


async def node_web_coordinator_logic(state: dict) -> dict:
    query = (state.get("user_input") or "").strip()
    loop_iteration = int(state.get("web_loop_iteration") or 0)
    rewritten_query = _rewrite_query_keywords(query)
    sub_queries = _build_subqueries(
        query,
        rewritten_query,
        max_subqueries=WEB_QUERY_DECOMPOSITION_MAX_SUBQUERIES,
    ) if WEB_QUERY_DECOMPOSITION_ENABLED else [rewritten_query or query]
    web_mode = "open_web"
    raw_web_urls = state.get("web_urls") or []
    source_policy = await _load_source_policy_from_db()

    planner_payload = await _llm_plan_web_queries(
        state,
        query,
        rewritten_query or query,
        sub_queries,
        source_policy,
    )
    planner_rewritten = str(planner_payload.get("rewritten_query") or "").strip()
    planner_research_questions = _clean_query_list(
        planner_payload.get("research_questions") or [],
        WEB_QUERY_DECOMPOSITION_MAX_SUBQUERIES,
    )
    planner_search_queries = _clean_query_list(
        planner_payload.get("search_queries") or [],
        WEB_QUERY_DECOMPOSITION_MAX_SUBQUERIES,
    )

    if planner_rewritten:
        rewritten_query = planner_rewritten
    if planner_search_queries:
        sub_queries = _clean_query_list(
            [rewritten_query or query] + planner_search_queries,
            WEB_QUERY_DECOMPOSITION_MAX_SUBQUERIES,
        )

    if loop_iteration > 0:
        sub_queries = _build_retry_subqueries(
            query,
            state.get("search_plan") or {"sub_queries": sub_queries, "keyword_query": rewritten_query or query},
            state.get("web_retry_reasons") or [],
            WEB_QUERY_DECOMPOSITION_MAX_SUBQUERIES,
        )

    normalized_urls = []
    for raw in raw_web_urls:
        url = _normalize_url(str(raw))
        if url and _is_url_safe(url):
            normalized_urls.append(url)

    normalized_urls = list(dict.fromkeys(normalized_urls))[:WEB_MAX_CANDIDATE_URLS]

    query_domains = _extract_domains_from_query(query)
    configured_allow_domains = list(dict.fromkeys([d.lower().strip() for d in (source_policy.get("allow_domains") or []) if d]))
    strict_source_filter = bool(source_policy.get("strict_source_filter"))
    has_allow_scope = bool(
        configured_allow_domains
        or (source_policy.get("allow_url_prefixes") or [])
    )

    # Rule điều phối domain:
    # - Nếu có allowlist active -> coi là khóa nguồn bắt buộc, không search nguồn ngoài.
    # - Nếu query chỉ định domain -> chỉ search domain đó nếu domain nằm trong allowlist
    #   hoặc không có allowlist.
    # - Nếu không có domain scope và broad search bật -> search open-web rộng rồi lọc blocklist ở bước sau.
    preferred_domains: list[str] = []
    restrict_to_target_domains = False
    if query_domains:
        if configured_allow_domains:
            target_domains = [
                domain for domain in query_domains
                if _domain_allowed(domain, configured_allow_domains)
            ]
            domain_policy_mode = "query_explicit_allowed" if target_domains else "query_explicit_blocked_by_allowlist"
        else:
            target_domains = query_domains
            domain_policy_mode = "query_explicit"
        restrict_to_target_domains = True
    elif configured_allow_domains:
        target_domains = configured_allow_domains
        domain_policy_mode = "configured_allowlist"
        restrict_to_target_domains = True
    elif has_allow_scope and WEB_BROAD_SEARCH_ENABLED:
        target_domains = []
        preferred_domains = _pick_preferred_domains(
            query,
            configured_allow_domains,
            WEB_PREFERRED_DOMAIN_SEARCH_MAX,
        )
        domain_policy_mode = "configured_url_prefix_allowlist"
    elif WEB_BROAD_SEARCH_ENABLED:
        target_domains = []
        domain_policy_mode = "open_web_broad"
    else:
        target_domains = []
        domain_policy_mode = "no_domain_scope"

    candidate_seed_urls = normalized_urls

    state["rewritten_query"] = rewritten_query or query
    state["search_plan"] = {
        "mode": web_mode,
        "keyword_query": rewritten_query or query,
        "sub_queries": sub_queries,
        "research_questions": planner_research_questions or sub_queries,
        "must_cover": _clean_query_list(planner_payload.get("must_cover") or [], 10),
        "planner_notes": str(planner_payload.get("notes") or "").strip()[:500],
        "freshness_required": bool(planner_payload.get("freshness_required")),
        "user_urls": normalized_urls,
        "query_domains": query_domains,
        "target_domains": target_domains,
        "preferred_domains": preferred_domains,
        "domain_policy_mode": domain_policy_mode,
        "restrict_to_target_domains": restrict_to_target_domains,
        "source_policy": source_policy,
        "max_candidate_urls": WEB_MAX_CANDIDATE_URLS,
        "max_selected_urls": WEB_MAX_URLS_PER_QUERY,
        "loop_iteration": loop_iteration,
    }
    state["candidate_urls"] = candidate_seed_urls
    state["selected_urls"] = []
    state["web_documents"] = []
    state["reranked_evidence"] = []
    state["assistant_response"] = ""
    state["web_should_retry"] = False
    state["web_answer_streamed"] = False

    await _push_sse(
        state,
        title="Coordinator đã tạo kế hoạch tra cứu web",
        mess=(
            f"mode={web_mode}, urls_user={len(normalized_urls)}, "
            f"domains_scope={len(target_domains)}, preferred_domains={len(preferred_domains)}, policy={domain_policy_mode}, "
            f"sub_queries={len(sub_queries)}, research_questions={len(planner_research_questions or sub_queries)}, "
            f"loop={loop_iteration + 1}/{WEB_SEARCH_MAX_RESEARCH_LOOPS}, "
            f"strict_source_filter={strict_source_filter}, "
            f"query_rewrite='{(rewritten_query or query)[:120]}'"
        ),
    )

    return state


async def node_web_domain_mapper_logic(state: dict) -> dict:
    plan = state.get("search_plan") or {}
    query = state.get("rewritten_query") or state.get("user_input") or ""
    sub_queries = list(dict.fromkeys([str(x).strip() for x in (plan.get("sub_queries") or []) if str(x).strip()]))
    if not sub_queries and query:
        sub_queries = [query]
    candidate_urls = list(state.get("candidate_urls") or [])
    target_domains = list(dict.fromkeys(plan.get("target_domains") or []))
    preferred_domains = list(dict.fromkeys(plan.get("preferred_domains") or []))
    restrict_to_target_domains = bool(plan.get("restrict_to_target_domains"))
    domain_policy_mode = str(plan.get("domain_policy_mode") or "unknown")
    source_policy = plan.get("source_policy") or _default_source_policy()
    cache_hit_urls = 0
    db_hit_urls = 0
    discovered_urls = 0
    searx_urls = 0
    search_issue = ""
    provider_trace: list[dict] = []
    provider_cache_hits = 0
    provider_name_counts: dict[str, int] = {}
    open_search_fallback_used = False
    open_search_urls = 0
    preferred_search_urls = 0
    direct_probe_urls = 0
    has_search_provider = bool(
        search_broker_service.configured_providers()
        or SEARXNG_BASE_URL
        or os.getenv("BRAVE_SEARCH_API_KEY")
        or os.getenv("BING_SEARCH_API_KEY")
    )

    def _merge_search_meta(search_meta: dict | None) -> None:
        nonlocal provider_cache_hits
        provider = str((search_meta or {}).get("provider") or "unknown")
        provider_name_counts[provider] = provider_name_counts.get(provider, 0) + 1
        if (search_meta or {}).get("cache_hit"):
            provider_cache_hits += 1
        traces = (search_meta or {}).get("provider_trace") or []
        if traces:
            provider_trace.extend(traces)

    # Chỉ retrieval qua broker/SearxNG/official APIs; không fallback crawl sitemap/homepage tự code.
    if not sub_queries:
        search_issue = "empty_query"
    elif not target_domains and domain_policy_mode == "no_domain_scope":
        candidate_urls = []
        search_issue = "no_domain_scope"
    elif sub_queries:
        if not has_search_provider:
            search_issue = "search_provider_not_configured"
        elif target_domains:
            total_jobs = max(1, len(sub_queries) * len(target_domains))
            per_job_topk = max(3, min(WEB_SEARXNG_TOPK, WEB_MAX_CANDIDATE_URLS) // total_jobs)

            for sub_query in sub_queries:
                for domain in target_domains:
                    scoped_query = f"site:{domain} {sub_query}".strip()
                    searx_candidates, search_meta = await _search_urls_with_searxng(
                        scoped_query,
                        topk=min(WEB_MAX_CANDIDATE_URLS, per_job_topk + 2),
                        allowed_domains=[domain],
                        strict_domain_filter=True,
                        source_policy=source_policy,
                    )
                    _merge_search_meta(search_meta)
                    if searx_candidates:
                        candidate_urls.extend(searx_candidates)
                        searx_urls += len(searx_candidates)

            # Một số provider trả empty cho `site:` query. Vẫn thử open query nhưng giữ
            # strict domain filter để không vượt khóa nguồn.
            if searx_urls == 0 and target_domains:
                open_search_fallback_used = True
                for sub_query in sub_queries:
                    fallback_candidates, fallback_meta = await _search_urls_with_searxng(
                        sub_query,
                        topk=min(WEB_MAX_CANDIDATE_URLS, max(6, WEB_SEARXNG_TOPK)),
                        allowed_domains=target_domains,
                        strict_domain_filter=True,
                        source_policy=source_policy,
                    )
                    _merge_search_meta(fallback_meta)
                    if fallback_candidates:
                        candidate_urls.extend(fallback_candidates)
                        open_search_urls += len(fallback_candidates)

            if searx_urls == 0 and open_search_urls == 0 and domain_policy_mode.startswith("query_explicit"):
                for domain in target_domains:
                    for path in WEB_EXPLICIT_DOMAIN_PROBE_PATHS:
                        probe_url = _normalize_url(f"https://{domain}{path}")
                        if not probe_url:
                            continue
                        if not _is_url_safe(probe_url) or not _is_source_allowed(probe_url, source_policy=source_policy):
                            continue
                        candidate_urls.append(probe_url)
                        direct_probe_urls += 1
                        if direct_probe_urls >= WEB_MAX_URLS_PER_QUERY:
                            break
                    if direct_probe_urls >= WEB_MAX_URLS_PER_QUERY:
                        break
        else:
            if preferred_domains:
                total_jobs = max(1, len(sub_queries) * len(preferred_domains))
                per_job_topk = max(2, min(WEB_SEARXNG_TOPK, WEB_MAX_CANDIDATE_URLS) // max(1, total_jobs))
                for sub_query in sub_queries:
                    for domain in preferred_domains:
                        preferred_query = f"site:{domain} {sub_query}".strip()
                        preferred_candidates, preferred_meta = await _search_urls_with_searxng(
                            preferred_query,
                            topk=min(WEB_MAX_CANDIDATE_URLS, per_job_topk + 1),
                            allowed_domains=[domain],
                            strict_domain_filter=True,
                            source_policy=source_policy,
                        )
                        _merge_search_meta(preferred_meta)
                        if preferred_candidates:
                            candidate_urls.extend(preferred_candidates)
                            preferred_search_urls += len(preferred_candidates)

            open_search_fallback_used = True
            per_query_topk = max(6, min(WEB_SEARXNG_TOPK, WEB_MAX_CANDIDATE_URLS) // max(1, len(sub_queries)))
            for sub_query in sub_queries:
                fallback_candidates, fallback_meta = await _search_urls_with_searxng(
                    sub_query,
                    topk=min(WEB_MAX_CANDIDATE_URLS, per_query_topk + 4),
                    allowed_domains=None,
                    strict_domain_filter=False,
                    source_policy=source_policy,
                )
                _merge_search_meta(fallback_meta)
                if fallback_candidates:
                    candidate_urls.extend(fallback_candidates)
                    open_search_urls += len(fallback_candidates)

        if searx_urls == 0 and open_search_urls == 0 and not search_issue:
            search_issue = "searxng_no_results_or_blocked"
        elif not search_issue:
            search_issue = "none"

    dedup_urls = []
    seen = set()
    for u in candidate_urls:
        if u in seen:
            continue
        seen.add(u)
        if _is_url_safe(u):
            if restrict_to_target_domains and target_domains and not _domain_allowed(_extract_domain(u), target_domains):
                continue
            if _is_source_allowed(u, source_policy=source_policy):
                dedup_urls.append(u)
        if len(dedup_urls) >= WEB_MAX_CANDIDATE_URLS:
            break

    state["candidate_urls"] = dedup_urls
    state["web_search_debug"] = {
        "query": query,
        "candidate_count": len(dedup_urls),
        "sub_queries": sub_queries,
        "target_domains": target_domains,
        "preferred_domains": preferred_domains,
        "restrict_to_target_domains": restrict_to_target_domains,
        "domain_policy_mode": domain_policy_mode,
        "searx_urls": searx_urls,
        "preferred_search_urls": preferred_search_urls,
        "direct_probe_urls": direct_probe_urls,
        "open_search_fallback_used": open_search_fallback_used,
        "open_search_urls": open_search_urls,
        "cache_hit_urls": cache_hit_urls,
        "db_hit_urls": db_hit_urls,
        "discovered_urls": discovered_urls,
        "strict_source_filter": bool(source_policy.get("strict_source_filter")),
        "allowed_domains_count": len(source_policy.get("allow_domains") or []),
        "allowed_url_prefixes_count": len(source_policy.get("allow_url_prefixes") or []),
        "blocked_domains_count": len(source_policy.get("block_domains") or []),
        "blocked_url_prefixes_count": len(source_policy.get("block_url_prefixes") or []),
        "provider_name_counts": provider_name_counts,
        "provider_cache_hits": provider_cache_hits,
        "provider_trace": provider_trace[-20:],
        "search_issue": search_issue,
    }

    await _push_sse(
        state,
        title=f"Domain mapper thu thập {len(dedup_urls)} URL candidates",
        mess=(
            f"searx={searx_urls}, cache={cache_hit_urls}, "
            f"preferred={preferred_search_urls}, direct_probe={direct_probe_urls}, index={db_hit_urls}, discover={discovered_urls}, "
            f"domain_policy={domain_policy_mode}, restricted={restrict_to_target_domains}, issue={search_issue or 'none'}"
        ),
    )

    return state


async def node_web_url_selector_logic(state: dict) -> dict:
    query = state.get("rewritten_query") or state.get("user_input") or ""
    candidate_urls = state.get("candidate_urls") or []
    plan = state.get("search_plan") or {}

    scored: list[tuple[str, float]] = []
    for url in candidate_urls:
        score = _url_relevance_score(url, query) + _source_priority_score(url, query, plan)
        scored.append((url, score))

    scored.sort(key=lambda x: x[1], reverse=True)

    # Stage 1: heuristic shortlist theo path/url.
    prefetch_size = max(
        WEB_MAX_URLS_PER_QUERY,
        WEB_MAX_URLS_PER_QUERY * max(1, WEB_URL_SELECTOR_PREFETCH_MULTIPLIER),
    )
    shortlist = [u for u, _ in scored[:prefetch_size]]

    # Stage 2: title-aware rerank để bắt đúng bài khi query gần tiêu đề trang.
    title_docs: list[str] = []
    title_meta: list[tuple[str, str, float]] = []
    if shortlist:
        title_tasks = [_fetch_url_title(url) for url in shortlist]
        title_results = await asyncio.gather(*title_tasks, return_exceptions=True)
        base_score_map = {u: s for u, s in scored}

        for idx, result in enumerate(title_results):
            if isinstance(result, Exception):
                continue
            title = str(result or "").strip()
            if not title:
                continue
            url = shortlist[idx]
            base_score = float(base_score_map.get(url, 0.0))
            title_docs.append(title)
            title_meta.append((url, title, base_score))

    selected_urls: list[str] = []
    selected_titles: dict[str, str] = {}

    if len(title_docs) >= 2:
        try:
            rerank_titles = await _rerank_documents(query, title_docs)
            blended: list[tuple[str, float, str]] = []
            for item in rerank_titles:
                idx = item.get("index", -1)
                if idx < 0 or idx >= len(title_meta):
                    continue
                url, title, base_score = title_meta[idx]
                title_score = _sigmoid(float(item.get("score", 0.0)))
                # Blend score: ưu tiên semantic title match, vẫn giữ heuristic path.
                final_score = (0.75 * title_score) + (0.25 * max(base_score, 0.0))
                blended.append((url, final_score, title))

            blended.sort(key=lambda x: x[1], reverse=True)
            for url, _score, title in blended[:WEB_MAX_URLS_PER_QUERY]:
                selected_urls.append(url)
                selected_titles[url] = title
        except Exception as e:
            logger.debug("[WEB_SELECTOR] title rerank fail: %s", e)

    if not selected_urls:
        selected_urls = [u for u, _ in scored[:WEB_MAX_URLS_PER_QUERY]]

    # Giới hạn số URL mỗi domain để tăng đa dạng nguồn ngay từ selector stage.
    domain_used: dict[str, int] = {}
    diversified_urls: list[str] = []
    for url in selected_urls:
        domain = _extract_domain(url)
        if not domain:
            continue
        current = domain_used.get(domain, 0)
        if current >= WEB_MAX_EVIDENCE_PER_DOMAIN:
            continue
        domain_used[domain] = current + 1
        diversified_urls.append(url)
    if diversified_urls:
        selected_urls = diversified_urls

    if len(selected_urls) < WEB_MAX_URLS_PER_QUERY:
        selected_set = set(selected_urls)
        for url, _score in scored:
            if url in selected_set:
                continue
            domain = _extract_domain(url)
            if not domain:
                continue
            current = domain_used.get(domain, 0)
            if current >= WEB_MAX_EVIDENCE_PER_DOMAIN:
                continue
            domain_used[domain] = current + 1
            selected_urls.append(url)
            selected_set.add(url)
            if len(selected_urls) >= WEB_MAX_URLS_PER_QUERY:
                break

    # Ghi ngược selected URLs vào index/cache để lần sau map nhanh hơn.
    by_domain: dict[str, list[str]] = {}
    for url in selected_urls:
        domain = _extract_domain(url)
        if not domain:
            continue
        by_domain.setdefault(domain, []).append(url)

    for domain, urls in by_domain.items():
        await _set_cached_domain_urls(domain, urls)
        await _upsert_domain_url_index(domain, urls, query)

    state["selected_urls"] = selected_urls
    if selected_titles:
        state["selected_url_titles"] = selected_titles

    sse_message = f"title_rerank_candidates={len(title_docs)}"
    await _push_sse(
        state,
        title=f"Đã chọn {len(selected_urls)} URL để đọc sâu",
        mess=sse_message,
        list_file=selected_urls,
    )
    return state


async def _fetch_and_clean_single_url(url: str) -> dict:
    try:
        html_text, content_type = await _fetch_url_html(url, WEB_FETCH_TIMEOUT_SEC)
        if not html_text:
            return {"url": url, "title": url, "content": "", "ok": False, "reason": "empty"}

        title_match = re.search(r"<title[^>]*>(.*?)</title>", html_text, flags=re.IGNORECASE | re.DOTALL)
        title = re.sub(r"\s+", " ", title_match.group(1)).strip() if title_match else url

        content = _extract_main_content_text(html_text)
        if len(content) < WEB_MIN_CONTENT_CHARS_PER_URL:
            return {
                "url": url,
                "title": title,
                "content": "",
                "ok": False,
                "reason": "content_too_short",
                "content_type": content_type,
            }

        if len(content) > WEB_MAX_CONTENT_CHARS_PER_URL:
            content = content[:WEB_MAX_CONTENT_CHARS_PER_URL]

        return {
            "url": url,
            "title": title,
            "content": content,
            "ok": True,
            "content_type": content_type,
        }
    except Exception as e:
        return {"url": url, "title": url, "content": "", "ok": False, "reason": str(e)}


async def node_web_fetch_clean_logic(state: dict) -> dict:
    selected_urls = state.get("selected_urls") or []
    if not selected_urls:
        state["web_documents"] = []
        await _push_sse(state, title="Không có URL hợp lệ để fetch")
        return state

    tasks = [_fetch_and_clean_single_url(url) for url in selected_urls]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    docs = []
    failed_count = 0
    reason_counts: dict[str, int] = {}
    for rs in results:
        if isinstance(rs, Exception):
            failed_count += 1
            reason_counts["exception"] = reason_counts.get("exception", 0) + 1
            continue
        if rs.get("ok") and rs.get("content"):
            docs.append(rs)
        else:
            failed_count += 1
            reason = str(rs.get("reason") or "unknown")
            reason_counts[reason] = reason_counts.get(reason, 0) + 1

    state["web_documents"] = docs
    state["web_fetch_debug"] = {
        "selected_urls": len(selected_urls),
        "success_docs": len(docs),
        "failed_docs": failed_count,
        "reason_counts": reason_counts,
    }
    await _push_sse(
        state,
        title=f"Fetch/Clean hoàn tất: {len(docs)}/{len(selected_urls)} URL có nội dung",
        mess=f"failed_or_low_content={failed_count}, reasons={reason_counts}",
    )
    return state


async def node_web_rerank_logic(state: dict) -> dict:
    query = state.get("rewritten_query") or state.get("user_input") or ""
    plan = state.get("search_plan") or {}
    docs = state.get("web_documents") or []
    selected_urls = list(state.get("selected_urls") or [])
    candidate_urls = list(state.get("candidate_urls") or [])

    adaptive_debug = {
        "adaptive_enabled": WEB_ADAPTIVE_BUDGET_ENABLED,
        "triggered": False,
        "reason": "",
        "extra_fetch_urls": 0,
        "top_score_before": 0.0,
        "top_score_after": 0.0,
    }

    def _compute_rerank(current_docs: list[dict]) -> list[dict]:
        return [d for d in current_docs if (d.get("content") or "").strip()]

    filtered_docs = _compute_rerank(docs)
    rerank = []
    top_score_before = 0.0

    if filtered_docs:
        documents = [d.get("content", "") for d in filtered_docs]
        rerank = await _rerank_documents(query, documents)
        if rerank:
            top_score_before = _sigmoid(float(rerank[0].get("score", 0.0)))
    adaptive_debug["top_score_before"] = top_score_before

    should_expand = (
        WEB_ADAPTIVE_BUDGET_ENABLED
        and WEB_ADAPTIVE_EXTRA_FETCH_URLS > 0
        and (
            (not filtered_docs)
            or (top_score_before < WEB_ADAPTIVE_LOW_RERANK_THRESHOLD)
        )
    )

    if should_expand:
        extra_pool = [u for u in candidate_urls if u and u not in set(selected_urls)]
        scored_pool = sorted(
            [(u, _url_relevance_score(u, query)) for u in extra_pool],
            key=lambda x: x[1],
            reverse=True,
        )
        extra_urls = [u for u, _ in scored_pool[:WEB_ADAPTIVE_EXTRA_FETCH_URLS]]

        if extra_urls:
            adaptive_debug["triggered"] = True
            adaptive_debug["reason"] = "low_rerank_or_empty_docs"
            adaptive_debug["extra_fetch_urls"] = len(extra_urls)

            extra_results = await asyncio.gather(
                *[_fetch_and_clean_single_url(url) for url in extra_urls],
                return_exceptions=True,
            )

            appended_docs: list[dict] = []
            for item in extra_results:
                if isinstance(item, Exception):
                    continue
                if item.get("ok") and item.get("content"):
                    appended_docs.append(item)

            if appended_docs:
                docs.extend(appended_docs)
                filtered_docs = _compute_rerank(docs)
                documents = [d.get("content", "") for d in filtered_docs]
                rerank = await _rerank_documents(query, documents)
                selected_urls.extend([d.get("url") for d in appended_docs if d.get("url")])
                state["selected_urls"] = list(dict.fromkeys(selected_urls))

    if not filtered_docs:
        state["reranked_evidence"] = []
        state["web_adaptive_debug"] = adaptive_debug
        return state

    if rerank:
        adaptive_debug["top_score_after"] = _sigmoid(float(rerank[0].get("score", 0.0)))

    evidence = []
    evidence_domain_count: dict[str, int] = {}
    scored_evidence_items: list[tuple[float, dict]] = []
    for item in rerank:
        idx = item.get("index", 0)
        if idx < 0 or idx >= len(filtered_docs):
            continue
        semantic_score = _sigmoid(item.get("score", 0.0))
        doc = filtered_docs[idx]
        source_score = _source_priority_score(str(doc.get("url") or ""), query, plan)
        score = min(1.0, (0.78 * semantic_score) + (0.22 * source_score))
        scored_evidence_items.append((score, {**doc, "_semantic_score": semantic_score, "_source_score": source_score}))

    scored_evidence_items.sort(key=lambda x: x[0], reverse=True)

    for score, doc in scored_evidence_items:
        doc_url = doc.get("url")
        doc_domain = _extract_domain(str(doc_url or ""))
        if doc_domain:
            current = evidence_domain_count.get(doc_domain, 0)
            if current >= WEB_MAX_EVIDENCE_PER_DOMAIN:
                continue
            evidence_domain_count[doc_domain] = current + 1
        evidence.append({
            "url": doc_url,
            "title": doc.get("title"),
            "score": score,
            "semantic_score": doc.get("_semantic_score"),
            "source_score": doc.get("_source_score"),
            "snippet": (doc.get("content") or "")[:2200],
        })
        if len(evidence) >= WEB_MAX_URLS_PER_QUERY:
            break

    if not evidence:
        # fallback khi rerank lỗi/empty
        fallback_domain_count: dict[str, int] = {}
        for doc in filtered_docs[:WEB_MAX_URLS_PER_QUERY]:
            doc_url = doc.get("url")
            doc_domain = _extract_domain(str(doc_url or ""))
            if doc_domain:
                current = fallback_domain_count.get(doc_domain, 0)
                if current >= WEB_MAX_EVIDENCE_PER_DOMAIN:
                    continue
                fallback_domain_count[doc_domain] = current + 1
            evidence.append({
                "url": doc_url,
                "title": doc.get("title"),
                "score": 0.5,
                "snippet": (doc.get("content") or "")[:2200],
            })
            if len(evidence) >= WEB_MAX_URLS_PER_QUERY:
                break

    state["reranked_evidence"] = evidence
    state["web_documents"] = docs
    state["web_adaptive_debug"] = adaptive_debug
    await _push_sse(state, title=f"Rerank hoàn tất: {len(evidence)} evidence")
    return state


def _heuristic_summarize_evidence(evidence: list[dict], research_questions: list[str]) -> list[dict]:
    question_terms = set()
    for question in research_questions or []:
        for token in re.findall(r"[0-9]+(?:[./-][0-9]+)*|[^\W_]{3,}", question.lower(), flags=re.UNICODE):
            if token not in VI_QUERY_STOPWORDS:
                question_terms.add(token)

    summarized: list[dict] = []
    for idx, ev in enumerate(evidence, 1):
        snippet = re.sub(r"\s+", " ", str(ev.get("snippet") or "")).strip()
        if not snippet:
            continue
        score = float(ev.get("score") or 0.0)
        lowered = snippet.lower()
        term_hits = sum(1 for term in question_terms if term in lowered)
        keep = score >= WEB_SUMMARIZER_MIN_SCORE or term_hits >= 2 or idx <= 2
        if not keep:
            continue

        sentences = re.split(r"(?<=[.!?])\s+", snippet)
        picked = []
        for sentence in sentences:
            s = sentence.strip()
            if not s:
                continue
            if not question_terms or any(term in s.lower() for term in question_terms):
                picked.append(s)
            if len(" ".join(picked)) >= 650:
                break
        if not picked:
            picked = sentences[:3]

        enriched = dict(ev)
        enriched["source_id"] = idx
        enriched["summary"] = " ".join(picked)[:900]
        enriched["covered_questions"] = research_questions[:3]
        enriched["summary_confidence"] = "medium" if score >= WEB_SUMMARIZER_MIN_SCORE else "low"
        summarized.append(enriched)

    return summarized or evidence


async def node_web_summarize_logic(state: dict) -> dict:
    evidence = state.get("reranked_evidence") or []
    plan = state.get("search_plan") or {}
    research_questions = _clean_query_list(plan.get("research_questions") or plan.get("sub_queries") or [], 8)
    query = state.get("user_input") or ""

    if not evidence:
        state["web_summary_debug"] = {
            "enabled": WEB_EVIDENCE_SUMMARIZER_ENABLED,
            "kept_evidence": 0,
            "missing_questions": research_questions,
            "mode": "empty",
        }
        return state

    if not WEB_EVIDENCE_SUMMARIZER_ENABLED:
        state["reranked_evidence"] = _heuristic_summarize_evidence(evidence, research_questions)
        state["web_summary_debug"] = {
            "enabled": False,
            "kept_evidence": len(state["reranked_evidence"]),
            "missing_questions": [],
            "mode": "heuristic_disabled",
        }
        return state

    evidence_blocks = []
    for idx, ev in enumerate(evidence, 1):
        evidence_blocks.append(
            f"[S{idx}] URL: {ev.get('url')}\n"
            f"Title: {ev.get('title')}\n"
            f"Score: {float(ev.get('score') or 0.0):.3f}\n"
            f"Snippet: {str(ev.get('snippet') or '')[:1800]}"
        )

    try:
        from service.runtime_config_service import resolve_model_runtime

        model_selector = state.get("model_name")
        client, resolved_model, _meta = await resolve_model_runtime(model_selector)
        user_content = (
            "Bạn là evidence summarizer/filter cho web research. "
            "Hãy lọc nhiễu và giữ lại thông tin sạch phục vụ đúng câu hỏi, không trả lời cuối cùng.\n"
            f"Câu hỏi gốc: {query}\n"
            f"Câu hỏi nghiên cứu cần cover: {research_questions}\n"
            f"Must cover: {plan.get('must_cover') or []}\n"
            f"Ghi chú planner: {plan.get('planner_notes') or ''}\n\n"
            "EVIDENCE:\n"
            + "\n\n".join(evidence_blocks)
            + "\n\nTrả về DUY NHẤT JSON object hợp lệ, schema:\n"
            "{\n"
            '  "clean_evidence": [\n'
            '    {"source_id": 1, "keep": true, "clean_facts": ["fact ngắn, bám snippet"], "covered_questions": ["..."], "confidence": "high|medium|low"}\n'
            "  ],\n"
            '  "missing_questions": ["câu hỏi con còn thiếu bằng chứng"],\n'
            '  "conflicts": ["mâu thuẫn giữa nguồn nếu có"]\n'
            "}"
        )
        resp = await client.chat.completions.create(
            model=resolved_model,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "Chỉ tóm tắt/lọc evidence đã cho. Không bịa fact, không dùng kiến thức ngoài. "
                        "Nếu source không liên quan, đánh keep=false."
                    ),
                },
                {"role": "user", "content": user_content},
            ],
            temperature=0.1,
            max_tokens=1000,
            extra_body=_disable_model_thinking_extra_body(),
            stream=False,
        )
        content = (
            _strip_model_reasoning(resp.choices[0].message.content)
            if resp and resp.choices and resp.choices[0].message
            else ""
        )
        parsed = _extract_json_object(content or "")
        clean_items = parsed.get("clean_evidence") if isinstance(parsed, dict) else []
        by_sid = {idx: ev for idx, ev in enumerate(evidence, 1)}
        summarized: list[dict] = []

        if isinstance(clean_items, list):
            for item in clean_items:
                if not isinstance(item, dict) or item.get("keep") is False:
                    continue
                try:
                    sid = int(item.get("source_id") or 0)
                except Exception:
                    continue
                ev = by_sid.get(sid)
                if not ev:
                    continue
                facts = [str(x).strip() for x in (item.get("clean_facts") or []) if str(x).strip()]
                if not facts:
                    continue
                enriched = dict(ev)
                enriched["source_id"] = sid
                enriched["summary"] = " ".join(f"- {fact}" for fact in facts)[:1200]
                enriched["covered_questions"] = _clean_query_list(item.get("covered_questions") or [], 5)
                enriched["summary_confidence"] = str(item.get("confidence") or "medium")
                summarized.append(enriched)

        if not summarized:
            summarized = _heuristic_summarize_evidence(evidence, research_questions)

        # Giữ thứ tự theo source_id để citation [Sx] vẫn trỏ đúng evidence sau khi lọc.
        summarized.sort(key=lambda ev: int(ev.get("source_id") or 999))
        state["reranked_evidence"] = summarized[:WEB_MAX_URLS_PER_QUERY]
        state["web_summary_debug"] = {
            "enabled": True,
            "kept_evidence": len(state["reranked_evidence"]),
            "missing_questions": _clean_query_list(parsed.get("missing_questions") or [], 8),
            "conflicts": _clean_query_list(parsed.get("conflicts") or [], 6),
            "mode": "llm",
        }
    except Exception as e:
        logger.debug("[WEB_SUMMARY] LLM summarizer fallback: %s", e)
        state["reranked_evidence"] = _heuristic_summarize_evidence(evidence, research_questions)
        state["web_summary_debug"] = {
            "enabled": True,
            "kept_evidence": len(state["reranked_evidence"]),
            "missing_questions": [],
            "mode": "heuristic_fallback",
        }

    await _push_sse(
        state,
        title=f"Đã lọc còn {len(state.get('reranked_evidence') or [])} evidence sạch",
        mess=f"mode={(state.get('web_summary_debug') or {}).get('mode')}",
    )
    return state


def _build_web_context(evidence: list[dict]) -> str:
    parts = []
    total_len = 0
    for i, ev in enumerate(evidence, 1):
        clean_summary = str(ev.get("summary") or "").strip()
        raw_snippet = str(ev.get("snippet") or "").strip()
        content = clean_summary or raw_snippet
        if clean_summary and raw_snippet:
            content = f"Tóm tắt sạch:\n{clean_summary}\n\nTrích đoạn gốc rút gọn:\n{raw_snippet[:900]}"
        block = (
            f"[S{i}] URL: {ev.get('url')}\n"
            f"Tiêu đề: {ev.get('title')}\n"
            f"Điểm: {ev.get('score', 0):.3f}\n"
            f"Câu hỏi con liên quan: {ev.get('covered_questions') or []}\n"
            f"Nội dung: {content}\n"
        )
        if total_len + len(block) > WEB_MAX_TOTAL_CONTEXT:
            break
        parts.append(block)
        total_len += len(block)
    return "\n".join(parts)


def _is_history_recap_query(query: str) -> bool:
    text = (query or "").strip().lower()
    if not text:
        return False
    patterns = [
        "tôi vừa hỏi",
        "toi vua hoi",
        "mình vừa hỏi",
        "minh vua hoi",
        "lịch sử",
        "lich su",
        "vừa nói",
        "vua noi",
        "trước đó",
        "truoc do",
        "nhắc lại",
        "nhac lai",
        "tóm tắt đoạn chat",
        "tom tat doan chat",
    ]
    return any(p in text for p in patterns)


def _extract_recent_user_questions_from_history(chat_history: str, limit: int = 5) -> list[str]:
    questions: list[str] = []
    for line in (chat_history or "").splitlines():
        text = line.strip()
        if not text.startswith("- Người dùng:"):
            continue
        content = text.replace("- Người dùng:", "", 1).strip()
        if not content:
            continue
        questions.append(content)
    return questions[-limit:]


def _build_history_recap_answer(query: str, chat_history: str) -> str | None:
    recent_questions = _extract_recent_user_questions_from_history(chat_history, limit=6)
    if not recent_questions:
        return None

    lines = ["Trong session hiện tại, bạn vừa hỏi các ý sau:"]
    for idx, q in enumerate(recent_questions, 1):
        lines.append(f"{idx}. {q}")

    lines.append("Nếu bạn muốn, mình có thể trả lời tiếp ngay câu gần nhất mà bạn đang quan tâm.")
    return "\n".join(lines)


def _extract_citation_ids(text: str) -> list[int]:
    ids = []
    for m in re.finditer(r"\[S(\d+)\]", text or "", flags=re.IGNORECASE):
        try:
            ids.append(int(m.group(1)))
        except Exception:
            continue
    return ids


def _validate_web_citations(answer: str, evidence: list[dict]) -> tuple[bool, str]:
    if not evidence:
        return True, "no_evidence"

    citation_ids = _extract_citation_ids(answer)
    if not citation_ids:
        return False, "missing_citations"

    max_sid = len(evidence)
    for sid in citation_ids:
        if sid < 1 or sid > max_sid:
            return False, f"invalid_source_id:S{sid}"

    # Mục nguồn tham khảo là bắt buộc khi có evidence.
    lowered = (answer or "").lower()
    if "nguồn tham khảo" not in lowered and "nguon tham khao" not in lowered:
        return False, "missing_reference_section"

    return True, "ok"


async def node_web_synthesize_logic(state: dict) -> dict:
    query = state.get("user_input", "")
    evidence = state.get("reranked_evidence") or []
    queue = state.get("sse_queue")
    loop_iteration = int(state.get("web_loop_iteration") or 0)
    should_hold_draft = (
        WEB_CITATION_VALIDATION_ENABLED
        or (
            WEB_SEARCH_EVALUATOR_LOOP_ENABLED
            and loop_iteration < WEB_SEARCH_MAX_RESEARCH_LOOPS - 1
        )
    )
    state["web_answer_streamed"] = False

    from service.runtime_config_service import (
        get_required_active_prompt_content,
        resolve_model_runtime,
    )

    model_selector = state.get("model_name")
    client, resolved_model, _meta = await resolve_model_runtime(model_selector)
    current_system_prompt = await get_required_active_prompt_content(
        PROMPT_FEATURE_WEB_SEARCH_SYNTHESIZER
    )

    chat_history = state.get("chat_history", "")
    is_history_recap = _is_history_recap_query(query)

    # Trường hợp user chỉ hỏi lại lịch sử hội thoại: trả lời trực tiếp theo session history,
    # không ép gán citation web để tránh câu trả lời gượng/không tự nhiên.
    if is_history_recap and chat_history:
        recap_answer = _build_history_recap_answer(query, chat_history)
        if recap_answer:
            state["assistant_response"] = recap_answer
            state["web_answer_streamed"] = False
            return state

    web_context = _build_web_context(evidence)
    if not evidence:
        debug = state.get("web_search_debug") or {}
        fetch_debug = state.get("web_fetch_debug") or {}
        issue = (debug.get("search_issue") or "").strip()
        reason_counts = fetch_debug.get("reason_counts") or {}

        if issue in {"searxng_not_configured", "search_provider_not_configured"}:
            suffix = (
                "Hệ thống hiện chưa cấu hình provider tìm kiếm web (SearxNG/Brave/Bing). "
                "Vui lòng cấu hình ít nhất một provider để bật chức năng web_search."
            )
        elif issue == "searxng_no_results_or_blocked":
            suffix = (
                "Không thu được kết quả phù hợp từ công cụ tìm kiếm ở thời điểm hiện tại. "
                "Bạn có thể thêm ngữ cảnh như khu vực/thời gian (ví dụ: 'giá xăng RON95 hôm nay tại Việt Nam') "
                "hoặc cung cấp URL nguồn chính thống để mình phân tích trực tiếp."
            )
        elif reason_counts.get("content_too_short", 0) > 0:
            suffix = (
                "Hệ thống đã tìm thấy trang nhưng nội dung trích xuất quá ngắn hoặc không đủ dữ liệu định lượng. "
                "Bạn có thể cung cấp URL bài gốc hoặc truy vấn chi tiết hơn theo loại xăng và khu vực."
            )
        else:
            suffix = "Bạn có thể thử thêm từ khóa cụ thể hơn hoặc gửi trực tiếp URL cần phân tích để tăng độ chính xác."

        # Nếu không có evidence nhưng có lịch sử và user đang hỏi theo mạch hội thoại,
        # ưu tiên trả lời theo history thay vì trả template fallback cứng.
        if chat_history and is_history_recap:
            recap_answer = _build_history_recap_answer(query, chat_history)
            if recap_answer:
                state["assistant_response"] = recap_answer
                return state

        state["assistant_response"] = (
            "Mình chưa thu thập được bằng chứng web đủ tin cậy cho câu hỏi này. "
            f"{suffix}"
        )
        state["web_answer_streamed"] = False
        return state

    history_prompt = f"\nNGỮ CẢNH LỊCH SỬ LIÊN QUAN:\n{chat_history}\n" if chat_history else ""
    summary_debug = state.get("web_summary_debug") or {}

    user_content = (
        f"EVIDENCE WEB (CÓ THỂ TRÍCH DẪN):\n{web_context}\n"
        f"\nCÂU HỎI NGHIÊN CỨU ĐÃ PHÂN TÁCH:\n{(state.get('search_plan') or {}).get('research_questions') or []}\n"
        f"CÂU HỎI CÒN THIẾU BẰNG CHỨNG THEO SUMMARIZER:\n{summary_debug.get('missing_questions') or []}\n"
        f"{history_prompt}\n"
        f"YÊU CẦU: {query}\n"
        "Hãy trả lời tiếng Việt, mạch lạc, tự nhiên và thân thiện. "
        "Chỉ gắn nhãn [Sx] cho các ý thực sự lấy từ EVIDENCE WEB. "
        "Nếu một ý chỉ dựa vào lịch sử hội thoại thì không cần gắn [Sx] và không đưa vào 'Nguồn tham khảo'. "
        "Sau phần trả lời, thêm mục 'Nguồn tham khảo' và chỉ liệt kê Sx -> URL đã trích trong phần nội dung web. "
        "Bắt buộc dựa vào phần 'Nội dung' của evidence; không được chỉ liệt kê URL/Tiêu đề."
    )

    try:
        messages = [
            {"role": "system", "content": current_system_prompt},
            {"role": "user", "content": user_content},
        ]
        if should_hold_draft:
            resp = await client.chat.completions.create(
                model=resolved_model,
                messages=messages,
                temperature=0.2,
                max_tokens=1200,
                extra_body=_disable_model_thinking_extra_body(),
                stream=False,
            )
            final_response = (
                _strip_model_reasoning(resp.choices[0].message.content)
                if resp and resp.choices and resp.choices[0].message
                else ""
            )
            state["web_answer_streamed"] = False
        else:
            stream = await client.chat.completions.create(
                model=resolved_model,
                messages=messages,
                temperature=0.2,
                max_tokens=1200,
                extra_body=_disable_model_thinking_extra_body(),
                stream=True,
            )

            full_response = ""
            stream_filter = _ReasoningStreamFilter()
            async for chunk in stream:
                if (
                    chunk.choices
                    and chunk.choices[0].delta
                    and chunk.choices[0].delta.content
                ):
                    token = chunk.choices[0].delta.content
                    full_response += token
                    display_token = stream_filter.push(token)
                    if queue and stream_filter.last_reasoning:
                        await queue.put({
                            "user_id": state.get("user_id", ""),
                            "session_id": state.get("session_id", -1),
                            "title": "Đang suy luận...",
                            "mess": "",
                            "reasoning_mess": stream_filter.last_reasoning,
                            "end": False,
                        })
                    if queue and display_token:
                        await queue.put({
                            "user_id": state.get("user_id", ""),
                            "session_id": state.get("session_id", -1),
                            "title": "Đang trả lời...",
                            "mess": display_token,
                            "end": False,
                        })

            tail_token = stream_filter.flush()
            if queue and tail_token:
                await queue.put({
                    "user_id": state.get("user_id", ""),
                    "session_id": state.get("session_id", -1),
                    "title": "Đang trả lời...",
                    "mess": tail_token,
                    "end": False,
                })

            final_response = _strip_model_reasoning(full_response)
            if queue and final_response and not stream_filter.emitted_any:
                await queue.put({
                    "user_id": state.get("user_id", ""),
                    "session_id": state.get("session_id", -1),
                    "title": "Đang trả lời...",
                    "mess": final_response,
                    "end": False,
                })
            state["web_answer_streamed"] = True

        if WEB_CITATION_VALIDATION_ENABLED:
            valid, reason = _validate_web_citations(final_response, evidence)
            if not valid:
                fix_instruction = (
                    "Hãy sửa lại câu trả lời để citation hợp lệ. "
                    "Quy tắc bắt buộc: chỉ dùng [S1]..[S{max_sid}], không dùng source id ngoài phạm vi, "
                    "và phải có mục 'Nguồn tham khảo' map đúng Sx -> URL."
                ).format(max_sid=len(evidence))
                try:
                    fix_resp = await client.chat.completions.create(
                        model=resolved_model,
                        messages=[
                            {"role": "system", "content": current_system_prompt},
                            {"role": "user", "content": user_content},
                            {"role": "assistant", "content": final_response},
                            {"role": "user", "content": f"{fix_instruction}\nLỗi hiện tại: {reason}"},
                        ],
                        temperature=0.1,
                        max_tokens=1200,
                        extra_body=_disable_model_thinking_extra_body(),
                        stream=False,
                    )
                    fixed_text = (
                        _strip_model_reasoning(fix_resp.choices[0].message.content)
                        if fix_resp and fix_resp.choices and fix_resp.choices[0].message
                        else final_response
                    )
                    fixed_valid, _ = _validate_web_citations(fixed_text, evidence)
                    if fixed_valid:
                        final_response = fixed_text
                        state["web_answer_streamed"] = False
                except Exception as fix_e:
                    logger.warning("[WEB_SYNTH] Citation fix retry failed: %s", fix_e)

        state["assistant_response"] = final_response
    except Exception as e:
        logger.error("[WEB_SYNTH] Lỗi gọi model: %s", e)
        state["assistant_response"] = "Hệ thống web search tạm thời lỗi, vui lòng thử lại."

    return state


async def node_web_verify_logic(state: dict) -> dict:
    evidence = state.get("reranked_evidence") or []
    answer = state.get("assistant_response") or ""
    confidence = "low"
    diversity_domains = len(set(_extract_domain(str(e.get("url") or "")) for e in evidence if e.get("url")))
    citation_ok, citation_reason = _validate_web_citations(answer, evidence)
    top_score = max([float(e.get("score", 0.0)) for e in evidence]) if evidence else 0.0
    plan = state.get("search_plan") or {}
    restricted_scope = bool(plan.get("restrict_to_target_domains") or plan.get("query_domains"))
    strong_official_source = any(float(e.get("source_score") or 0.0) >= 0.70 for e in evidence)
    adaptive_single_source_ok = restricted_scope or strong_official_source
    required_evidence = 1 if adaptive_single_source_ok else WEB_EVALUATOR_MIN_EVIDENCE
    required_domains = 1 if adaptive_single_source_ok else WEB_EVALUATOR_MIN_DOMAINS
    if evidence:
        if top_score >= 0.85 and len(evidence) >= required_evidence and diversity_domains >= required_domains and citation_ok:
            confidence = "high"
        elif top_score >= 0.65 and citation_ok and len(evidence) >= min(required_evidence, len(evidence)):
            confidence = "medium"

    summary_debug = state.get("web_summary_debug") or {}
    missing_questions = summary_debug.get("missing_questions") or []
    loop_iteration = int(state.get("web_loop_iteration") or 0)
    retry_reasons: list[str] = []

    if WEB_SEARCH_EVALUATOR_LOOP_ENABLED:
        if not evidence:
            retry_reasons.append("no_evidence")
        if len(evidence) < required_evidence:
            retry_reasons.append(f"low_evidence_count:{len(evidence)}")
        if diversity_domains < required_domains:
            retry_reasons.append(f"low_domain_diversity:{diversity_domains}")
        if top_score < WEB_EVALUATOR_MIN_TOP_SCORE:
            retry_reasons.append(f"low_top_score:{top_score:.3f}")
        if not citation_ok:
            retry_reasons.append(f"citation:{citation_reason}")
        if missing_questions:
            retry_reasons.append("missing_questions")

    can_retry = (
        WEB_SEARCH_EVALUATOR_LOOP_ENABLED
        and bool(retry_reasons)
        and loop_iteration < WEB_SEARCH_MAX_RESEARCH_LOOPS - 1
    )

    state["web_should_retry"] = can_retry
    state["web_retry_reasons"] = retry_reasons
    if can_retry:
        state["web_loop_iteration"] = loop_iteration + 1
        state["assistant_response"] = ""
        await _push_sse(
            state,
            title="Verifier yêu cầu tìm thêm nguồn",
            mess=f"reasons={retry_reasons}, next_loop={loop_iteration + 2}/{WEB_SEARCH_MAX_RESEARCH_LOOPS}",
        )
    elif answer and not state.get("web_answer_streamed"):
        queue = state.get("sse_queue")
        if queue:
            await queue.put({
                "user_id": state.get("user_id", ""),
                "session_id": state.get("session_id", -1),
                "title": "Đang trả lời...",
                "mess": answer,
                "end": False,
            })
        state["web_answer_streamed"] = True

    state["confidence"] = confidence
    state["web_verify_debug"] = {
        "top_score": top_score,
        "evidence_count": len(evidence),
        "diversity_domains": diversity_domains,
        "citation_ok": citation_ok,
        "citation_reason": citation_reason,
        "retry_reasons": retry_reasons,
        "should_retry": can_retry,
        "loop_iteration": loop_iteration,
        "max_loops": WEB_SEARCH_MAX_RESEARCH_LOOPS,
        "restricted_scope": restricted_scope,
        "strong_official_source": strong_official_source,
        "required_evidence": required_evidence,
        "required_domains": required_domains,
    }

    await _push_sse(
        state,
        title=f"Kiểm định hoàn tất (confidence={confidence})",
        mess=f"retry={can_retry}, reasons={retry_reasons}",
    )
    return state

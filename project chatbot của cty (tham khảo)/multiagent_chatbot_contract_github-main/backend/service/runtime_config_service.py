import logging
import os
from typing import Any

from openai import AsyncOpenAI
from sqlalchemy import select

from database.setup_postgres import SessionLocal
from database.setup_redis import redis_service
from database.table.table_postgres import LLMProviderConfig, PromptConfig

logger = logging.getLogger(__name__)

MODEL_SELECTOR_SEPARATOR = "::"
PROMPT_CACHE_KEY_PREFIX = "prompt:active:feature"
PROMPT_CACHE_TTL_SEC = int(os.getenv("PROMPT_CACHE_TTL_SEC", "0"))

PROMPT_FEATURE_RAG_ASSISTANT = "rag_assistant"
PROMPT_FEATURE_CONTRACT_TEMPLATE = "contract_template_drafter"
PROMPT_FEATURE_CONTRACT_FAST = "contract_fast_drafter"
PROMPT_FEATURE_CONTRACT_SUMMARY = "contract_summary"
PROMPT_FEATURE_CONTRACT_REASONING_DRAFTER = "contract_reasoning_drafter"
PROMPT_FEATURE_CONTRACT_REASONING_CRITIC = "contract_reasoning_critic"
PROMPT_FEATURE_CONTRACT_REASONING_REVISER = "contract_reasoning_reviser"
PROMPT_FEATURE_WEB_SEARCH_COORDINATOR = "web_search_coordinator"
PROMPT_FEATURE_WEB_SEARCH_SYNTHESIZER = "web_search_synthesizer"
PROMPT_FEATURE_WEB_SEARCH_VERIFIER = "web_search_verifier"
PROMPT_FEATURE_CUSTOM = "custom"

PROMPT_FEATURE_DEFINITIONS = [
    {
        "feature_key": PROMPT_FEATURE_RAG_ASSISTANT,
        "label": "RAG Assistant",
        "description": "Prompt hệ thống cho chatbot tra cứu tài liệu RAG.",
    },
    {
        "feature_key": PROMPT_FEATURE_CONTRACT_TEMPLATE,
        "label": "Contract Templated",
        "description": "Prompt tạo hợp đồng theo template có sẵn.",
    },
    {
        "feature_key": PROMPT_FEATURE_CONTRACT_FAST,
        "label": "Contract Fast",
        "description": "Prompt tạo hợp đồng nhanh không cần template.",
    },
    {
        "feature_key": PROMPT_FEATURE_CONTRACT_SUMMARY,
        "label": "Contract Summary",
        "description": "Prompt tóm tắt hợp đồng sau khi tạo xong.",
    },
    {
        "feature_key": PROMPT_FEATURE_CONTRACT_REASONING_DRAFTER,
        "label": "Reasoning Drafter",
        "description": "Prompt cho tác tử soạn thảo bản nháp ban đầu.",
    },
    {
        "feature_key": PROMPT_FEATURE_CONTRACT_REASONING_CRITIC,
        "label": "Reasoning Critic",
        "description": "Prompt cho tác tử kiểm duyệt và góp ý.",
    },
    {
        "feature_key": PROMPT_FEATURE_CONTRACT_REASONING_REVISER,
        "label": "Reasoning Reviser",
        "description": "Prompt cho tác tử chỉnh sửa bản nháp theo góp ý.",
    },
    {
        "feature_key": PROMPT_FEATURE_WEB_SEARCH_COORDINATOR,
        "label": "Web Search Coordinator",
        "description": "Prompt điều phối kế hoạch tra cứu web.",
    },
    {
        "feature_key": PROMPT_FEATURE_WEB_SEARCH_SYNTHESIZER,
        "label": "Web Search Synthesizer",
        "description": "Prompt tổng hợp câu trả lời từ bằng chứng web.",
    },
    {
        "feature_key": PROMPT_FEATURE_WEB_SEARCH_VERIFIER,
        "label": "Web Search Verifier",
        "description": "Prompt kiểm định nhanh độ tin cậy web search.",
    },
    {
        "feature_key": PROMPT_FEATURE_CUSTOM,
        "label": "Custom",
        "description": "Prompt tự định nghĩa cho chức năng mở rộng.",
    },
]


def _normalize_models(raw_models: Any) -> list[str]:
    """Chuẩn hoá models về list[str], bỏ trùng và phần tử rỗng."""
    items: list[str]

    if raw_models is None:
        items = []
    elif isinstance(raw_models, list):
        items = [str(x).strip() for x in raw_models]
    elif isinstance(raw_models, str):
        items = [x.strip() for x in raw_models.split(",")]
    else:
        items = [str(raw_models).strip()]

    deduped: list[str] = []
    seen = set()
    for item in items:
        if not item:
            continue
        if item in seen:
            continue
        seen.add(item)
        deduped.append(item)
    return deduped


def build_model_selector(provider_id: int, model_name: str) -> str:
    return f"{provider_id}{MODEL_SELECTOR_SEPARATOR}{model_name}"


def parse_model_selector(model_selector: str | None) -> tuple[int | None, str | None]:
    """
    Parse chuỗi model selector:
    - Định dạng mới: "<provider_id>::<model_name>"
    - Tương thích cũ: "<model_name>"
    """
    if not model_selector:
        return None, None

    selector = str(model_selector).strip()
    if not selector:
        return None, None

    if MODEL_SELECTOR_SEPARATOR in selector:
        provider_part, model_part = selector.split(MODEL_SELECTOR_SEPARATOR, 1)
        provider_part = provider_part.strip()
        model_part = model_part.strip()
        if provider_part.isdigit():
            return int(provider_part), (model_part or None)
        # Format lạ -> coi như model_name raw
        return None, selector

    return None, selector


def _fallback_env_provider() -> dict[str, Any]:
    models = _normalize_models(os.getenv("VLLM_MODELS_LIST", ""))
    default_model = os.getenv("VLLM_MODEL_NAME", "khazarai/Qwen3-4B-Qwen3.6-plus-Reasoning-Distilled")
    if not models:
        models = [default_model]

    return {
        "id": 0,
        "name": "Local vLLM (ENV)",
        "provider_type": "local_vllm",
        "base_url": os.getenv("VLLM_BASE_URL", "http://127.0.0.1:8000/v1"),
        "api_key": os.getenv("VLLM_API_KEY", ""),
        "models": models,
        "description": "Fallback từ biến môi trường",
        "is_default": True,
        "is_active": True,
    }


def _provider_source(provider_type: str) -> tuple[str, str]:
    if provider_type == "local_vllm":
        return "local", "Local vLLM"
    return "api", "External API"


def list_prompt_features() -> list[dict[str, str]]:
    return PROMPT_FEATURE_DEFINITIONS


def _prompt_cache_key(feature_key: str) -> str:
    return f"{PROMPT_CACHE_KEY_PREFIX}:{feature_key}"


async def _get_prompt_content_from_cache(feature_key: str) -> str | None:
    client = redis_service.client
    if not client:
        return None

    try:
        cached = await client.get(_prompt_cache_key(feature_key))
        if cached:
            return str(cached)
    except Exception as e:
        logger.warning("[PROMPT_CACHE] Redis get failed for feature '%s': %s", feature_key, e)

    return None


async def _set_prompt_content_to_cache(feature_key: str, content: str) -> None:
    client = redis_service.client
    if not client:
        return

    key = _prompt_cache_key(feature_key)
    try:
        if PROMPT_CACHE_TTL_SEC > 0:
            await client.setex(key, PROMPT_CACHE_TTL_SEC, content)
        else:
            await client.set(key, content)
    except Exception as e:
        logger.warning("[PROMPT_CACHE] Redis set failed for feature '%s': %s", feature_key, e)


async def invalidate_prompt_cache(feature_key: str | None = None) -> None:
    client = redis_service.client
    if not client:
        return

    try:
        if feature_key:
            await client.delete(_prompt_cache_key(feature_key))
            return

        async for key in client.scan_iter(match=f"{PROMPT_CACHE_KEY_PREFIX}:*"):
            await client.delete(key)
    except Exception as e:
        logger.warning("[PROMPT_CACHE] Redis invalidate failed (feature=%s): %s", feature_key, e)


async def warmup_active_prompt_cache() -> int:
    """
    Nạp toàn bộ prompt active vào Redis sau startup.
    Trả về số feature prompt đã được cache.
    """
    try:
        async with SessionLocal() as db:
            rs = await db.execute(
                select(PromptConfig.feature_key, PromptConfig.content)
                .where(PromptConfig.is_active.is_(True))
                .order_by(PromptConfig.feature_key.asc(), PromptConfig.id.desc())
            )
            rows = rs.all()

        picked: dict[str, str] = {}
        for feature, content in rows:
            f = str(feature or "").strip()
            c = str(content or "")
            if not f or f in picked:
                continue
            if c:
                picked[f] = c

        for feature, content in picked.items():
            await _set_prompt_content_to_cache(feature, content)

        return len(picked)
    except Exception as e:
        logger.warning("[PROMPT_CACHE] Warmup failed: %s", e)
        return 0


async def get_active_prompt_content(feature_key: str, fallback: str) -> str:
    """Lấy prompt active theo feature_key từ DB, fallback nếu chưa có."""
    cached = await _get_prompt_content_from_cache(feature_key)
    if cached:
        return cached

    try:
        async with SessionLocal() as db:
            rs = await db.execute(
                select(PromptConfig.content)
                .where(
                    PromptConfig.feature_key == feature_key,
                    PromptConfig.is_active.is_(True),
                )
                .order_by(PromptConfig.id.desc())
                .limit(1)
            )
            content = rs.scalar_one_or_none()
            if content:
                await _set_prompt_content_to_cache(feature_key, content)
                return content
    except Exception as e:
        logger.warning("[PROMPT] Không lấy được prompt feature '%s' từ DB: %s", feature_key, e)

    return fallback


async def get_required_active_prompt_content(feature_key: str) -> str:
    """
    Lấy prompt active theo feature_key (Redis cache trước, DB sau).

    Raises:
        RuntimeError: Nếu không tìm thấy prompt active cho feature.
    """
    cached = await _get_prompt_content_from_cache(feature_key)
    if cached:
        return cached

    try:
        async with SessionLocal() as db:
            rs = await db.execute(
                select(PromptConfig.content)
                .where(
                    PromptConfig.feature_key == feature_key,
                    PromptConfig.is_active.is_(True),
                )
                .order_by(PromptConfig.id.desc())
                .limit(1)
            )
            content = rs.scalar_one_or_none()
            if content:
                await _set_prompt_content_to_cache(feature_key, content)
                return content
    except Exception as e:
        logger.error("[PROMPT] Lỗi đọc prompt feature '%s' từ DB: %s", feature_key, e)
        raise RuntimeError(f"Không thể tải prompt cho feature '{feature_key}' từ DB") from e

    raise RuntimeError(
        f"Không tìm thấy prompt active trong DB cho feature '{feature_key}'. "
        "Vui lòng cấu hình prompt trong Admin Settings."
    )


async def _load_active_providers() -> list[dict[str, Any]]:
    """Đọc providers active từ DB, fallback ENV nếu DB trống."""
    providers: list[dict[str, Any]] = []

    try:
        async with SessionLocal() as db:
            rs = await db.execute(
                select(LLMProviderConfig)
                .where(LLMProviderConfig.is_active.is_(True))
                .order_by(LLMProviderConfig.is_default.desc(), LLMProviderConfig.id.asc())
            )
            rows = rs.scalars().all()
            for row in rows:
                providers.append(
                    {
                        "id": row.id,
                        "name": row.name,
                        "provider_type": row.provider_type,
                        "base_url": row.base_url,
                        "api_key": row.api_key,
                        "models": _normalize_models(row.models),
                        "description": row.description,
                        "is_default": row.is_default,
                        "is_active": row.is_active,
                    }
                )
    except Exception as e:
        logger.warning("[LLM_PROVIDER] Không đọc được provider từ DB, fallback ENV: %s", e)

    if not providers:
        providers = [_fallback_env_provider()]

    return providers


async def list_active_llm_model_items() -> list[dict[str, Any]]:
    """Danh sách model khả dụng để frontend render dropdown."""
    providers = await _load_active_providers()
    items: list[dict[str, Any]] = []

    for provider in providers:
        source, source_label = _provider_source(provider["provider_type"])
        models = _normalize_models(provider.get("models"))
        if not models:
            fallback_models = [os.getenv("VLLM_MODEL_NAME", "google/gemma-4-E4B-it")]
            models = [fallback_models[0]]

        for model_name in models:
            selector = build_model_selector(int(provider["id"]), model_name)
            display_name = model_name.split("/")[-1] if "/" in model_name else model_name
            items.append(
                {
                    "id": selector,
                    "model_name": model_name,
                    "display_name": display_name,
                    "provider_id": provider["id"],
                    "provider_name": provider["name"],
                    "provider_type": provider["provider_type"],
                    "source": source,
                    "source_label": source_label,
                    "is_default_provider": bool(provider.get("is_default")),
                    "base_url": provider["base_url"],
                }
            )

    return items


async def resolve_model_runtime(
    model_selector: str | None,
    fallback_model: str | None = None,
) -> tuple[AsyncOpenAI, str, dict[str, Any]]:
    """
    Resolve model selector -> provider + model + AsyncOpenAI client.

    model_selector hỗ trợ:
    - "<provider_id>::<model_name>" (mới)
    - "<model_name>" (legacy)
    - None (auto default provider/model)
    """
    providers = await _load_active_providers()
    provider_id, requested_model = parse_model_selector(model_selector)

    selected_provider = None

    if provider_id is not None:
        for provider in providers:
            if int(provider["id"]) == provider_id:
                selected_provider = provider
                break

    if selected_provider is None and requested_model:
        # Legacy mode: chọn provider đầu tiên có model này.
        for provider in providers:
            if requested_model in _normalize_models(provider.get("models")):
                selected_provider = provider
                break

    if selected_provider is None:
        selected_provider = providers[0]

    provider_models = _normalize_models(selected_provider.get("models"))

    resolved_model = requested_model
    if not resolved_model:
        resolved_model = provider_models[0] if provider_models else None

    if not resolved_model:
        resolved_model = fallback_model or os.getenv("VLLM_MODEL_NAME", "khazarai/Qwen3-4B-Qwen3.6-plus-Reasoning-Distilled")

    base_url = selected_provider.get("base_url") or os.getenv("VLLM_BASE_URL", "http://127.0.0.1:8000/v1")

    api_key = str(selected_provider.get("api_key") or "").strip()
    if not api_key:
        api_key = "not-needed"

    # Init client
    client = AsyncOpenAI(base_url=base_url, api_key=api_key)

    source, source_label = _provider_source(selected_provider.get("provider_type", "openai_compatible"))
    meta = {
        "provider_id": selected_provider.get("id"),
        "provider_name": selected_provider.get("name"),
        "provider_type": selected_provider.get("provider_type"),
        "source": source,
        "source_label": source_label,
        "base_url": base_url,
        "selected_model": resolved_model,
        "selector": build_model_selector(int(selected_provider.get("id", 0)), resolved_model),
    }

    return client, resolved_model, meta

import logging
from urllib.parse import urlparse

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from database.table.table_postgres import (
    LLMProviderConfig,
    MailServerConfig,
    PromptConfig,
    TelegramBotConfig,
    TelegramRecipientConfig,
    WebSourceRule,
)
from request.admin_request import (
    LLMProviderCreate,
    LLMProviderUpdate,
    MailServerCreate,
    MailServerUpdate,
    TelegramBotCreate,
    TelegramBotUpdate,
    TelegramRecipientCreate,
    TelegramRecipientUpdate,
    PromptCreate,
    PromptUpdate,
    WebSourceRuleCreate,
    WebSourceRuleUpdate,
)
from service.runtime_config_service import invalidate_prompt_cache

logger = logging.getLogger(__name__)


import os

# --- Shared helpers ---
def _normalize_models(models: list[str] | None) -> list[str]:
    if not models:
        return []

    result: list[str] = []
    seen = set()
    for model in models:
        value = str(model).strip()
        if not value or value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result

def _resolve_api_key(raw_key: str | None) -> str | None:
    if not raw_key:
        return raw_key
    raw_key = str(raw_key).strip()
    env_val = os.getenv(raw_key)
    if env_val:
        return env_val
    return raw_key

def _get_default_env_key(provider_name: str) -> str:
    name = (provider_name or "").lower()
    if "nvidia" in name:
        return os.getenv("NVIDIA_API_KEY", "")
    if "openrouter" in name:
        return os.getenv("OPENROUTER_API_KEY", "")
    if "groq" in name:
        return os.getenv("GROQ_API_KEY", "")
    if "local vllm" in name:
        return os.getenv("VLLM_API_KEY", "")
    return ""

def _normalize_feature_key(value: str | None) -> str:
    return str(value or "custom").strip() or "custom"


def _normalize_web_source_value(match_type: str, raw_value: str | None) -> str:
    value = str(raw_value or "").strip()
    if not value:
        return ""

    if match_type == "domain":
        # Cho phép user nhập URL, hệ thống tự rút về hostname.
        candidate = value
        if "://" in candidate:
            candidate = urlparse(candidate).hostname or ""
        candidate = candidate.strip().lower().strip(".")
        return candidate

    # url_prefix
    prefix = value
    if not prefix.startswith(("http://", "https://")):
        prefix = f"https://{prefix}"
    parsed = urlparse(prefix)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return ""
    normalized = f"{parsed.scheme.lower()}://{parsed.netloc.lower()}{parsed.path or '/'}"
    return normalized.rstrip("/")


async def _invalidate_web_source_policy_cache() -> None:
    try:
        from agent_chatbot.node.util.rag_query_util import invalidate_web_source_policy_cache

        await invalidate_web_source_policy_cache()
    except Exception as e:
        logger.warning("[WEB_SOURCE_POLICY] Invalidate cache hook failed: %s", e)


# --- Mail Server Config Services ---
async def list_mail_configs(db: Session):
    result = await db.execute(
        select(MailServerConfig).order_by(MailServerConfig.id.desc())
    )
    return result.scalars().all()


async def create_mail_config(data: MailServerCreate, db: Session):
    # Nếu đây là config đầu tiên, auto active để hệ thống gửi mail dùng ngay.
    has_config = await db.execute(select(MailServerConfig.id).limit(1))
    is_first_config = has_config.scalar_one_or_none() is None

    payload = data.model_dump()
    should_activate = payload.get("is_active", False) or is_first_config
    payload["is_active"] = should_activate

    if should_activate:
        await db.execute(update(MailServerConfig).values(is_active=False))

    new_config = MailServerConfig(**payload)
    db.add(new_config)
    await db.commit()
    await db.refresh(new_config)
    return new_config


async def update_mail_config(config_id: int, data: MailServerUpdate, db: Session):
    config = await db.get(MailServerConfig, config_id)
    if not config:
        return {"status": 404, "message": "Không tìm thấy cấu hình"}

    update_data = data.model_dump(exclude_unset=True)

    # Không cho ghi đè password thành rỗng khi frontend gửi field trống.
    if "password" in update_data and not str(update_data["password"]).strip():
        update_data.pop("password")

    # Bật active cho config này -> tắt active các config còn lại.
    if update_data.get("is_active") is True:
        await db.execute(
            update(MailServerConfig)
            .where(MailServerConfig.id != config_id)
            .values(is_active=False)
        )

    # Không cho tắt active nếu đây là config active cuối cùng.
    if update_data.get("is_active") is False and config.is_active:
        other_active = await db.execute(
            select(MailServerConfig.id)
            .where(
                MailServerConfig.id != config_id,
                MailServerConfig.is_active.is_(True),
            )
            .limit(1)
        )
        if other_active.scalar_one_or_none() is None:
            return {
                "status": 400,
                "message": "Phải có ít nhất một cấu hình mail active.",
            }

    for key, value in update_data.items():
        setattr(config, key, value)

    await db.commit()
    await db.refresh(config)
    return config


async def delete_mail_config(config_id: int, db: Session):
    config = await db.get(MailServerConfig, config_id)
    if not config:
        return {"status": 404, "message": "Không tìm thấy cấu hình"}

    if config.is_active:
        other_active = await db.execute(
            select(MailServerConfig.id)
            .where(
                MailServerConfig.id != config_id,
                MailServerConfig.is_active.is_(True),
            )
            .limit(1)
        )
        if other_active.scalar_one_or_none() is None:
            return {
                "status": 400,
                "message": "Không thể xóa cấu hình mail active cuối cùng.",
            }

    await db.delete(config)
    await db.commit()
    return {"status": 200, "message": "Đã xóa cấu hình"}


# --- Telegram Bot Config Services ---
async def list_telegram_bots(db: Session):
    result = await db.execute(
        select(TelegramBotConfig).order_by(TelegramBotConfig.id.desc())
    )
    return result.scalars().all()


async def create_telegram_bot(data: TelegramBotCreate, db: Session):
    has_config = await db.execute(select(TelegramBotConfig.id).limit(1))
    is_first_config = has_config.scalar_one_or_none() is None

    payload = data.model_dump()
    should_activate = payload.get("is_active", False) or is_first_config
    payload["is_active"] = should_activate

    if should_activate:
        await db.execute(update(TelegramBotConfig).values(is_active=False))

    new_config = TelegramBotConfig(**payload)
    db.add(new_config)
    await db.commit()
    await db.refresh(new_config)
    return new_config


async def update_telegram_bot(config_id: int, data: TelegramBotUpdate, db: Session):
    config = await db.get(TelegramBotConfig, config_id)
    if not config:
        return {"status": 404, "message": "Không tìm thấy bot Telegram"}

    update_data = data.model_dump(exclude_unset=True)

    if "bot_token" in update_data and not str(update_data["bot_token"]).strip():
        update_data.pop("bot_token")

    if update_data.get("is_active") is True:
        await db.execute(
            update(TelegramBotConfig)
            .where(TelegramBotConfig.id != config_id)
            .values(is_active=False)
        )

    if update_data.get("is_active") is False and config.is_active:
        other_active = await db.execute(
            select(TelegramBotConfig.id)
            .where(
                TelegramBotConfig.id != config_id,
                TelegramBotConfig.is_active.is_(True),
            )
            .limit(1)
        )
        if other_active.scalar_one_or_none() is None:
            return {
                "status": 400,
                "message": "Phải có ít nhất một bot Telegram active.",
            }

    for key, value in update_data.items():
        setattr(config, key, value)

    await db.commit()
    await db.refresh(config)
    return config


async def delete_telegram_bot(config_id: int, db: Session):
    config = await db.get(TelegramBotConfig, config_id)
    if not config:
        return {"status": 404, "message": "Không tìm thấy bot Telegram"}

    if config.is_active:
        other_active = await db.execute(
            select(TelegramBotConfig.id)
            .where(
                TelegramBotConfig.id != config_id,
                TelegramBotConfig.is_active.is_(True),
            )
            .limit(1)
        )
        if other_active.scalar_one_or_none() is None:
            return {
                "status": 400,
                "message": "Không thể xóa bot Telegram active cuối cùng.",
            }

    await db.delete(config)
    await db.commit()
    return {"status": 200, "message": "Đã xóa bot Telegram"}


# --- Telegram Recipient Config Services ---
async def list_telegram_recipients(db: Session):
    result = await db.execute(
        select(TelegramRecipientConfig).order_by(TelegramRecipientConfig.id.desc())
    )
    return result.scalars().all()


async def create_telegram_recipient(data: TelegramRecipientCreate, db: Session):
    payload = data.model_dump()
    new_recipient = TelegramRecipientConfig(**payload)
    db.add(new_recipient)
    await db.commit()
    await db.refresh(new_recipient)
    return new_recipient


async def update_telegram_recipient(config_id: int, data: TelegramRecipientUpdate, db: Session):
    config = await db.get(TelegramRecipientConfig, config_id)
    if not config:
        return {"status": 404, "message": "Không tìm thấy người nhận Telegram"}

    update_data = data.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(config, key, value)

    await db.commit()
    await db.refresh(config)
    return config


async def delete_telegram_recipient(config_id: int, db: Session):
    config = await db.get(TelegramRecipientConfig, config_id)
    if not config:
        return {"status": 404, "message": "Không tìm thấy người nhận Telegram"}

    await db.delete(config)
    await db.commit()
    return {"status": 200, "message": "Đã xóa người nhận Telegram"}


# --- Prompt Config Services ---
async def list_prompts(db: Session):
    result = await db.execute(
        select(PromptConfig).order_by(PromptConfig.feature_key.asc(), PromptConfig.id.desc())
    )
    return result.scalars().all()


async def create_prompt(data: PromptCreate, db: Session):
    payload = data.model_dump()
    payload["feature_key"] = _normalize_feature_key(payload.get("feature_key"))

    has_same_feature = await db.execute(
        select(PromptConfig.id)
        .where(PromptConfig.feature_key == payload["feature_key"])
        .limit(1)
    )
    is_first_in_feature = has_same_feature.scalar_one_or_none() is None

    should_activate = bool(payload.get("is_active")) or is_first_in_feature
    payload["is_active"] = should_activate

    if should_activate:
        await db.execute(
            update(PromptConfig)
            .where(PromptConfig.feature_key == payload["feature_key"])
            .values(is_active=False)
        )

    new_prompt = PromptConfig(**payload)
    db.add(new_prompt)
    await db.commit()
    await db.refresh(new_prompt)
    await invalidate_prompt_cache(payload["feature_key"])
    return new_prompt


async def update_prompt(prompt_id: int, data: PromptUpdate, db: Session):
    prompt = await db.get(PromptConfig, prompt_id)
    if not prompt:
        return {"status": 404, "message": "Không tìm thấy prompt"}

    previous_feature_key = str(prompt.feature_key or "").strip() or "custom"
    update_data = data.model_dump(exclude_unset=True)
    next_feature_key = _normalize_feature_key(update_data.get("feature_key") or prompt.feature_key)

    # Nếu prompt đang active và chuyển feature_key, đảm bảo feature mới không có active trùng.
    if prompt.is_active and next_feature_key != prompt.feature_key:
        await db.execute(
            update(PromptConfig)
            .where(PromptConfig.feature_key == next_feature_key, PromptConfig.id != prompt_id)
            .values(is_active=False)
        )

    if update_data.get("is_active") is True:
        await db.execute(
            update(PromptConfig)
            .where(PromptConfig.feature_key == next_feature_key, PromptConfig.id != prompt_id)
            .values(is_active=False)
        )

    if update_data.get("is_active") is False and prompt.is_active:
        other_active = await db.execute(
            select(PromptConfig.id)
            .where(
                PromptConfig.feature_key == prompt.feature_key,
                PromptConfig.id != prompt_id,
                PromptConfig.is_active.is_(True),
            )
            .limit(1)
        )
        if other_active.scalar_one_or_none() is None:
            return {
                "status": 400,
                "message": "Phải có ít nhất một prompt active cho chức năng này.",
            }

    update_data["feature_key"] = next_feature_key
    for key, value in update_data.items():
        setattr(prompt, key, value)

    await db.commit()
    await db.refresh(prompt)
    await invalidate_prompt_cache(previous_feature_key)
    if next_feature_key != previous_feature_key:
        await invalidate_prompt_cache(next_feature_key)
    return prompt


async def delete_prompt(prompt_id: int, db: Session):
    prompt = await db.get(PromptConfig, prompt_id)
    if not prompt:
        return {"status": 404, "message": "Không tìm thấy prompt"}

    feature_key = str(prompt.feature_key or "").strip() or "custom"

    if prompt.is_active:
        other_active = await db.execute(
            select(PromptConfig.id)
            .where(
                PromptConfig.feature_key == prompt.feature_key,
                PromptConfig.id != prompt_id,
                PromptConfig.is_active.is_(True),
            )
            .limit(1)
        )
        if other_active.scalar_one_or_none() is None:
            return {
                "status": 400,
                "message": "Không thể xóa prompt active cuối cùng của chức năng này.",
            }

    await db.delete(prompt)
    await db.commit()
    await invalidate_prompt_cache(feature_key)
    return {"status": 200, "message": "Đã xóa prompt"}


# --- LLM Provider Config Services ---
async def _ensure_default_provider(db: Session):
    active_default = await db.execute(
        select(LLMProviderConfig.id)
        .where(LLMProviderConfig.is_active.is_(True), LLMProviderConfig.is_default.is_(True))
        .limit(1)
    )
    if active_default.scalar_one_or_none() is not None:
        return

    first_active = await db.execute(
        select(LLMProviderConfig)
        .where(LLMProviderConfig.is_active.is_(True))
        .order_by(LLMProviderConfig.id.asc())
        .limit(1)
    )
    target = first_active.scalars().first()
    if target:
        target.is_default = True
        await db.commit()


async def list_llm_providers(db: Session):
    result = await db.execute(
        select(LLMProviderConfig).order_by(LLMProviderConfig.is_default.desc(), LLMProviderConfig.id.desc())
    )
    return result.scalars().all()


async def create_llm_provider(data: LLMProviderCreate, db: Session):
    payload = data.model_dump(exclude={"api_key_env_var"}, exclude_unset=True)
    payload["models"] = _normalize_models(payload.get("models"))
    
    if "api_key" in payload:
        payload["api_key"] = _resolve_api_key(payload.get("api_key"))

    has_provider = await db.execute(select(LLMProviderConfig.id).limit(1))
    is_first_provider = has_provider.scalar_one_or_none() is None

    should_be_default = bool(payload.get("is_default")) or is_first_provider
    payload["is_default"] = should_be_default

    if should_be_default:
        payload["is_active"] = True
        await db.execute(update(LLMProviderConfig).values(is_default=False))

    provider = LLMProviderConfig(**payload)
    db.add(provider)
    await db.commit()
    await db.refresh(provider)
    await _ensure_default_provider(db)
    await db.refresh(provider)
    return provider


async def update_llm_provider(provider_id: int, data: LLMProviderUpdate, db: Session):
    provider = await db.get(LLMProviderConfig, provider_id)
    if not provider:
        return {"status": 404, "message": "Không tìm thấy provider"}

    update_data = data.model_dump(exclude={"api_key_env_var"}, exclude_unset=True)

    if "models" in update_data:
        update_data["models"] = _normalize_models(update_data.get("models"))

    # Không ghi đè api_key thành rỗng nếu frontend để trống khi edit.
    if "api_key" in update_data:
        stripped_key = str(update_data["api_key"] or "").strip()
        if not stripped_key:
            fallback_val = _get_default_env_key(provider.name)
            if fallback_val:
                update_data["api_key"] = fallback_val
            else:
                update_data.pop("api_key")
        else:
            update_data["api_key"] = _resolve_api_key(stripped_key)

    if update_data.get("is_default") is True:
        update_data["is_active"] = True
        await db.execute(
            update(LLMProviderConfig)
            .where(LLMProviderConfig.id != provider_id)
            .values(is_default=False)
        )

    for key, value in update_data.items():
        setattr(provider, key, value)

    await db.commit()
    await db.refresh(provider)

    # Nếu provider default bị tắt active, gán default cho provider active khác.
    if provider.is_default and not provider.is_active:
        replacement = await db.execute(
            select(LLMProviderConfig)
            .where(LLMProviderConfig.id != provider_id, LLMProviderConfig.is_active.is_(True))
            .order_by(LLMProviderConfig.id.asc())
            .limit(1)
        )
        target = replacement.scalars().first()
        if target:
            provider.is_default = False
            target.is_default = True
            await db.commit()
            await db.refresh(provider)

    await _ensure_default_provider(db)
    await db.refresh(provider)
    return provider


async def delete_llm_provider(provider_id: int, db: Session):
    provider = await db.get(LLMProviderConfig, provider_id)
    if not provider:
        return {"status": 404, "message": "Không tìm thấy provider"}

    was_default = provider.is_default

    await db.delete(provider)
    await db.commit()

    if was_default:
        await _ensure_default_provider(db)

    return {"status": 200, "message": "Đã xóa provider"}


# --- Web Source Rule Services ---
async def list_web_source_rules(db: Session):
    result = await db.execute(
        select(WebSourceRule).order_by(WebSourceRule.rule_type.asc(), WebSourceRule.match_type.asc(), WebSourceRule.id.desc())
    )
    return result.scalars().all()


async def create_web_source_rule(data: WebSourceRuleCreate, db: Session):
    payload = data.model_dump()
    payload["rule_type"] = str(payload.get("rule_type") or "allow").strip().lower()
    payload["match_type"] = str(payload.get("match_type") or "domain").strip().lower()
    payload["value"] = _normalize_web_source_value(payload["match_type"], payload.get("value"))

    if not payload["value"]:
        return {"status": 400, "message": "Giá trị nguồn web không hợp lệ"}

    exists = await db.execute(
        select(WebSourceRule.id).where(
            WebSourceRule.rule_type == payload["rule_type"],
            WebSourceRule.match_type == payload["match_type"],
            WebSourceRule.value == payload["value"],
        ).limit(1)
    )
    if exists.scalar_one_or_none() is not None:
        return {"status": 409, "message": "Rule đã tồn tại"}

    item = WebSourceRule(**payload)
    db.add(item)
    await db.commit()
    await db.refresh(item)
    await _invalidate_web_source_policy_cache()
    return item


async def update_web_source_rule(rule_id: int, data: WebSourceRuleUpdate, db: Session):
    item = await db.get(WebSourceRule, rule_id)
    if not item:
        return {"status": 404, "message": "Không tìm thấy web source rule"}

    update_data = data.model_dump(exclude_unset=True)
    next_rule_type = str(update_data.get("rule_type") or item.rule_type).strip().lower()
    next_match_type = str(update_data.get("match_type") or item.match_type).strip().lower()
    next_value = _normalize_web_source_value(next_match_type, update_data.get("value", item.value))

    if not next_value:
        return {"status": 400, "message": "Giá trị nguồn web không hợp lệ"}

    duplicate = await db.execute(
        select(WebSourceRule.id).where(
            WebSourceRule.id != rule_id,
            WebSourceRule.rule_type == next_rule_type,
            WebSourceRule.match_type == next_match_type,
            WebSourceRule.value == next_value,
        ).limit(1)
    )
    if duplicate.scalar_one_or_none() is not None:
        return {"status": 409, "message": "Rule trùng với bản ghi khác"}

    item.rule_type = next_rule_type
    item.match_type = next_match_type
    item.value = next_value

    if "note" in update_data:
        item.note = update_data.get("note")
    if "is_active" in update_data:
        item.is_active = bool(update_data.get("is_active"))

    await db.commit()
    await db.refresh(item)
    await _invalidate_web_source_policy_cache()
    return item


async def delete_web_source_rule(rule_id: int, db: Session):
    item = await db.get(WebSourceRule, rule_id)
    if not item:
        return {"status": 404, "message": "Không tìm thấy web source rule"}

    await db.delete(item)
    await db.commit()
    await _invalidate_web_source_policy_cache()
    return {"status": 200, "message": "Đã xóa rule"}

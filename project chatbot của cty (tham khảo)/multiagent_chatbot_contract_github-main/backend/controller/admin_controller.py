from typing import List

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from auth.auth_middleware import require_roles
from database.setup_postgres import get_db
from request.admin_request import (
    LLMProviderCreate,
    LLMProviderResponse,
    LLMProviderUpdate,
    MailServerCreate,
    MailServerResponse,
    MailServerUpdate,
    TelegramBotCreate,
    TelegramBotResponse,
    TelegramBotUpdate,
    TelegramRecipientCreate,
    TelegramRecipientResponse,
    TelegramRecipientUpdate,
    PromptCreate,
    PromptResponse,
    PromptUpdate,
    WebSourceRuleCreate,
    WebSourceRuleResponse,
    WebSourceRuleUpdate,
)
from service.admin_setting_service import (
    create_llm_provider,
    create_mail_config,
    create_prompt,
    delete_llm_provider,
    delete_mail_config,
    delete_prompt,
    delete_telegram_bot,
    delete_telegram_recipient,
    list_llm_providers,
    list_mail_configs,
    list_prompts,
    list_telegram_bots,
    list_telegram_recipients,
    create_telegram_bot,
    create_telegram_recipient,
    update_llm_provider,
    update_mail_config,
    update_prompt,
    update_telegram_bot,
    update_telegram_recipient,
    list_web_source_rules,
    create_web_source_rule,
    update_web_source_rule,
    delete_web_source_rule,
)
from service.runtime_config_service import list_prompt_features

router = APIRouter()


def _raise_if_error(result):
    if isinstance(result, dict) and "status" in result and int(result["status"]) >= 400:
        raise HTTPException(status_code=result["status"], detail=result.get("message", "Request failed"))


# --- Mail Server Management (Root Only) ---
@router.get(
    "/settings/mail",
    response_model=List[MailServerResponse],
    dependencies=[Depends(require_roles(["root"]))],
)
async def get_mail_configs(db: Session = Depends(get_db)):
    return await list_mail_configs(db)


@router.post(
    "/settings/mail",
    response_model=MailServerResponse,
    dependencies=[Depends(require_roles(["root"]))],
)
async def add_mail_config(data: MailServerCreate, db: Session = Depends(get_db)):
    return await create_mail_config(data, db)


@router.put(
    "/settings/mail/{config_id}",
    response_model=MailServerResponse,
    dependencies=[Depends(require_roles(["root"]))],
)
async def edit_mail_config(
    config_id: int, data: MailServerUpdate, db: Session = Depends(get_db)
):
    result = await update_mail_config(config_id, data, db)
    _raise_if_error(result)
    return result


@router.delete(
    "/settings/mail/{config_id}",
    dependencies=[Depends(require_roles(["root"]))],
)
async def remove_mail_config(config_id: int, db: Session = Depends(get_db)):
    result = await delete_mail_config(config_id, db)
    _raise_if_error(result)
    return result


# --- Telegram Bot Management (Root Only) ---
@router.get(
    "/settings/telegram/bots",
    response_model=List[TelegramBotResponse],
    dependencies=[Depends(require_roles(["root"]))],
)
async def get_telegram_bots(db: Session = Depends(get_db)):
    return await list_telegram_bots(db)


@router.post(
    "/settings/telegram/bots",
    response_model=TelegramBotResponse,
    dependencies=[Depends(require_roles(["root"]))],
)
async def add_telegram_bot(data: TelegramBotCreate, db: Session = Depends(get_db)):
    return await create_telegram_bot(data, db)


@router.put(
    "/settings/telegram/bots/{config_id}",
    response_model=TelegramBotResponse,
    dependencies=[Depends(require_roles(["root"]))],
)
async def edit_telegram_bot(
    config_id: int, data: TelegramBotUpdate, db: Session = Depends(get_db)
):
    result = await update_telegram_bot(config_id, data, db)
    _raise_if_error(result)
    return result


@router.delete(
    "/settings/telegram/bots/{config_id}",
    dependencies=[Depends(require_roles(["root"]))],
)
async def remove_telegram_bot(config_id: int, db: Session = Depends(get_db)):
    result = await delete_telegram_bot(config_id, db)
    _raise_if_error(result)
    return result


# --- Telegram Recipient Management (Root Only) ---
@router.get(
    "/settings/telegram/recipients",
    response_model=List[TelegramRecipientResponse],
    dependencies=[Depends(require_roles(["root"]))],
)
async def get_telegram_recipients(db: Session = Depends(get_db)):
    return await list_telegram_recipients(db)


@router.post(
    "/settings/telegram/recipients",
    response_model=TelegramRecipientResponse,
    dependencies=[Depends(require_roles(["root"]))],
)
async def add_telegram_recipient(
    data: TelegramRecipientCreate, db: Session = Depends(get_db)
):
    return await create_telegram_recipient(data, db)


@router.put(
    "/settings/telegram/recipients/{config_id}",
    response_model=TelegramRecipientResponse,
    dependencies=[Depends(require_roles(["root"]))],
)
async def edit_telegram_recipient(
    config_id: int, data: TelegramRecipientUpdate, db: Session = Depends(get_db)
):
    result = await update_telegram_recipient(config_id, data, db)
    _raise_if_error(result)
    return result


@router.delete(
    "/settings/telegram/recipients/{config_id}",
    dependencies=[Depends(require_roles(["root"]))],
)
async def remove_telegram_recipient(config_id: int, db: Session = Depends(get_db)):
    result = await delete_telegram_recipient(config_id, db)
    _raise_if_error(result)
    return result


# --- Prompt Management (Root Only) ---
@router.get(
    "/settings/prompts",
    response_model=List[PromptResponse],
    dependencies=[Depends(require_roles(["root"]))],
)
async def get_prompts(db: Session = Depends(get_db)):
    return await list_prompts(db)


@router.get(
    "/settings/prompt-features",
    dependencies=[Depends(require_roles(["root"]))],
)
async def get_prompt_features():
    return {"status": 200, "result": list_prompt_features()}


@router.post(
    "/settings/prompts",
    response_model=PromptResponse,
    dependencies=[Depends(require_roles(["root"]))],
)
async def add_prompt(data: PromptCreate, db: Session = Depends(get_db)):
    return await create_prompt(data, db)


@router.put(
    "/settings/prompts/{prompt_id}",
    response_model=PromptResponse,
    dependencies=[Depends(require_roles(["root"]))],
)
async def edit_prompt(prompt_id: int, data: PromptUpdate, db: Session = Depends(get_db)):
    result = await update_prompt(prompt_id, data, db)
    _raise_if_error(result)
    return result


@router.delete(
    "/settings/prompts/{prompt_id}",
    dependencies=[Depends(require_roles(["root"]))],
)
async def remove_prompt(prompt_id: int, db: Session = Depends(get_db)):
    result = await delete_prompt(prompt_id, db)
    _raise_if_error(result)
    return result


# --- LLM Provider Management (Root Only) ---
@router.get(
    "/settings/llm-providers",
    response_model=List[LLMProviderResponse],
    dependencies=[Depends(require_roles(["root"]))],
)
async def get_llm_providers(db: Session = Depends(get_db)):
    return await list_llm_providers(db)


@router.post(
    "/settings/llm-providers",
    response_model=LLMProviderResponse,
    dependencies=[Depends(require_roles(["root"]))],
)
async def add_llm_provider(data: LLMProviderCreate, db: Session = Depends(get_db)):
    return await create_llm_provider(data, db)


@router.put(
    "/settings/llm-providers/{provider_id}",
    response_model=LLMProviderResponse,
    dependencies=[Depends(require_roles(["root"]))],
)
async def edit_llm_provider(provider_id: int, data: LLMProviderUpdate, db: Session = Depends(get_db)):
    result = await update_llm_provider(provider_id, data, db)
    _raise_if_error(result)
    return result


@router.delete(
    "/settings/llm-providers/{provider_id}",
    dependencies=[Depends(require_roles(["root"]))],
)
async def remove_llm_provider(provider_id: int, db: Session = Depends(get_db)):
    result = await delete_llm_provider(provider_id, db)
    _raise_if_error(result)
    return result


# --- Web Source Rules Management (Root + Upload) ---
@router.get(
    "/settings/web-sources",
    response_model=List[WebSourceRuleResponse],
    dependencies=[Depends(require_roles(["root", "upload"]))],
)
async def get_web_source_rules(db: Session = Depends(get_db)):
    return await list_web_source_rules(db)


@router.post(
    "/settings/web-sources",
    response_model=WebSourceRuleResponse,
    dependencies=[Depends(require_roles(["root", "upload"]))],
)
async def add_web_source_rule(data: WebSourceRuleCreate, db: Session = Depends(get_db)):
    result = await create_web_source_rule(data, db)
    _raise_if_error(result)
    return result


@router.put(
    "/settings/web-sources/{rule_id}",
    response_model=WebSourceRuleResponse,
    dependencies=[Depends(require_roles(["root", "upload"]))],
)
async def edit_web_source_rule(
    rule_id: int, data: WebSourceRuleUpdate, db: Session = Depends(get_db)
):
    result = await update_web_source_rule(rule_id, data, db)
    _raise_if_error(result)
    return result


@router.delete(
    "/settings/web-sources/{rule_id}",
    dependencies=[Depends(require_roles(["root", "upload"]))],
)
async def remove_web_source_rule(rule_id: int, db: Session = Depends(get_db)):
    result = await delete_web_source_rule(rule_id, db)
    _raise_if_error(result)
    return result

from typing import List, Optional, Literal

from pydantic import BaseModel, EmailStr, Field


# --- Mail Server Config ---
class MailServerCreate(BaseModel):
    host: str
    port: int = 587
    user: str
    password: str
    from_email: EmailStr
    from_name: str
    logo_url: Optional[str] = None
    is_active: bool = False


class MailServerUpdate(BaseModel):
    host: Optional[str] = None
    port: Optional[int] = None
    user: Optional[str] = None
    password: Optional[str] = None
    from_email: Optional[EmailStr] = None
    from_name: Optional[str] = None
    logo_url: Optional[str] = None
    is_active: Optional[bool] = None


class MailServerResponse(MailServerCreate):
    id: int

    class Config:
        from_attributes = True


# --- Telegram Bot Config ---
class TelegramBotCreate(BaseModel):
    bot_id: str
    bot_token: str
    is_active: bool = False


class TelegramBotUpdate(BaseModel):
    bot_id: Optional[str] = None
    bot_token: Optional[str] = None
    is_active: Optional[bool] = None


class TelegramBotResponse(TelegramBotCreate):
    id: int

    class Config:
        from_attributes = True


# --- Telegram Recipient Config ---
class TelegramRecipientCreate(BaseModel):
    name: str
    chat_id: str
    is_active: bool = True


class TelegramRecipientUpdate(BaseModel):
    name: Optional[str] = None
    chat_id: Optional[str] = None
    is_active: Optional[bool] = None


class TelegramRecipientResponse(TelegramRecipientCreate):
    id: int

    class Config:
        from_attributes = True


# --- Prompt Config ---
class PromptCreate(BaseModel):
    name: str
    feature_key: str = "custom"
    content: str
    description: Optional[str] = None
    is_active: bool = True


class PromptUpdate(BaseModel):
    feature_key: Optional[str] = None
    content: Optional[str] = None
    description: Optional[str] = None
    is_active: Optional[bool] = None


class PromptResponse(PromptCreate):
    id: int

    class Config:
        from_attributes = True


# --- LLM Provider Config ---
class LLMProviderCreate(BaseModel):
    name: str
    provider_type: Literal["local_vllm", "openai_compatible"] = "openai_compatible"
    base_url: str
    api_key: Optional[str] = None
    models: List[str] = Field(default_factory=list)
    description: Optional[str] = None
    is_active: bool = True
    is_default: bool = False


class LLMProviderUpdate(BaseModel):
    name: Optional[str] = None
    provider_type: Optional[Literal["local_vllm", "openai_compatible"]] = None
    base_url: Optional[str] = None
    api_key: Optional[str] = None
    models: Optional[List[str]] = None
    description: Optional[str] = None
    is_active: Optional[bool] = None
    is_default: Optional[bool] = None


class LLMProviderResponse(LLMProviderCreate):
    id: int

    class Config:
        from_attributes = True


# --- Web Source Rules (Root-only) ---
class WebSourceRuleCreate(BaseModel):
    rule_type: Literal["allow", "block"] = "allow"
    match_type: Literal["domain", "url_prefix"] = "domain"
    value: str
    note: Optional[str] = None
    is_active: bool = True


class WebSourceRuleUpdate(BaseModel):
    rule_type: Optional[Literal["allow", "block"]] = None
    match_type: Optional[Literal["domain", "url_prefix"]] = None
    value: Optional[str] = None
    note: Optional[str] = None
    is_active: Optional[bool] = None


class WebSourceRuleResponse(WebSourceRuleCreate):
    id: int

    class Config:
        from_attributes = True

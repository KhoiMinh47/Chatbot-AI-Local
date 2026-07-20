"""Phase 7 auth settings (JWT secrets, SMTP, token lifetimes)."""

from __future__ import annotations

from pathlib import Path
from uuid import UUID

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

_RUNTIME_SECRETS_DIR = Path("/run/secrets")


class AuthSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="AUTH_",
        case_sensitive=False,
        extra="ignore",
        frozen=True,
        hide_input_in_errors=True,
        # secrets_dir disabled due to container permission issues
        # secrets_dir=_RUNTIME_SECRETS_DIR if _RUNTIME_SECRETS_DIR.is_dir() else None,
    )

    enabled: bool = False

    # JWT
    jwt_secret: SecretStr = Field(default=SecretStr("dev-secret-change-in-production"))
    jwt_algorithm: str = Field(default="HS256")
    access_token_expire_minutes: int = Field(default=15, ge=1, le=1440)
    refresh_token_expire_days: int = Field(default=30, ge=1, le=365)

    # Database (reuses ingestion settings pattern)
    database_host: str | None = None
    database_port: int = Field(default=5432, ge=1, le=65535)
    database_name: str = Field(default="ntc_rag", min_length=1)
    database_user: str = Field(default="ntc_app", min_length=1)
    database_password: SecretStr | None = None

    # Default tenant for single-tenant MVP
    default_tenant_id: UUID = UUID("10000000-0000-4000-8000-000000000001")

    # SMTP for email verification and password reset
    smtp_host: str = Field(default="localhost")
    smtp_port: int = Field(default=1025, ge=1, le=65535)
    smtp_username: str | None = None
    smtp_password: SecretStr | None = None
    smtp_use_tls: bool = False
    smtp_from_email: str = Field(default="noreply@ntc.local")
    smtp_from_name: str = Field(default="NTC RAG Chatbot")

    # Token one-time URLs (frontend base)
    frontend_base_url: str = Field(default="http://localhost:3000")

    # Rate limits (requests per minute per user)
    rate_limit_chat_per_minute: int = Field(default=20, ge=1)
    rate_limit_upload_per_minute: int = Field(default=10, ge=1)
    rate_limit_login_per_minute: int = Field(default=5, ge=1)

    # LLM concurrency gate
    max_concurrent_rag_requests: int = Field(default=4, ge=1, le=64)

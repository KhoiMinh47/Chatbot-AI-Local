"""Fail-closed settings for the internal Phase 4 ingestion profile."""

from __future__ import annotations

from pathlib import Path
from typing import Self

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class IngestionSettings(BaseSettings):
    """Infrastructure settings kept separate from the Phase 3 NIM contract."""

    model_config = SettingsConfigDict(
        env_prefix="INGESTION_",
        case_sensitive=False,
        extra="ignore",
        frozen=True,
        hide_input_in_errors=True,
    )

    enabled: bool = False
    trusted_actor_headers_enabled: bool = False
    max_file_size: int = Field(default=100 * 1024 * 1024, gt=0, le=1024 * 1024 * 1024)

    database_host: str | None = None
    database_port: int = Field(default=5432, ge=1, le=65535)
    database_name: str = Field(default="ntc_rag", min_length=1)
    database_user: str = Field(default="ntc_app", min_length=1)
    database_password: str | None = None  # env var (preferred)
    database_password_file: Path = Path("/run/secrets/INGESTION_DATABASE_PASSWORD")

    minio_endpoint: str | None = None
    minio_access_key: str | None = None
    minio_secret_key: str | None = None  # env var (preferred)
    minio_secret_key_file: Path = Path("/run/secrets/INGESTION_MINIO_SECRET_KEY")
    minio_secure: bool = False
    minio_bucket: str = Field(default="ntc-documents", min_length=3, max_length=63)

    broker_host: str | None = None
    broker_port: int = Field(default=5672, ge=1, le=65535)
    broker_user: str = Field(default="ntc_worker", min_length=1)
    broker_password: str | None = None  # env var (preferred)
    broker_password_file: Path = Path("/run/secrets/INGESTION_BROKER_PASSWORD")

    @model_validator(mode="after")
    def validate_enabled_profile(self) -> Self:
        if not self.enabled:
            return self
        missing = [
            name
            for name, value in (
                ("database_host", self.database_host),
                ("minio_endpoint", self.minio_endpoint),
                ("minio_access_key", self.minio_access_key),
                ("broker_host", self.broker_host),
            )
            if value is None or not value.strip()
        ]
        if missing:
            raise ValueError("enabled ingestion requires: " + ", ".join(missing))
        # Validate passwords: prefer env vars, fall back to secret files
        for pw_env, path_field, field_name in (
            (self.database_password, self.database_password_file, "database_password"),
            (self.minio_secret_key, self.minio_secret_key_file, "minio_secret_key"),
            (self.broker_password, self.broker_password_file, "broker_password"),
        ):
            if pw_env is not None and pw_env.strip():
                continue  # env var provided, skip file check
            try:
                secret = path_field.read_text(encoding="utf-8").strip()
            except OSError:
                raise ValueError(
                    f"enabled ingestion cannot read {field_name}: "
                    "set env var or provide secret file"
                ) from None
            if not secret:
                raise ValueError(f"enabled ingestion requires non-empty {field_name}")
        if self.trusted_actor_headers_enabled is False:
            raise ValueError(
                "Phase 4 has no authentication boundary yet; explicitly enable trusted actor "
                "headers only on an internal acceptance profile"
            )
        return self

    @staticmethod
    def read_secret(path: Path, field_name: str) -> str:
        try:
            value = path.read_text(encoding="utf-8").strip()
        except OSError:
            raise RuntimeError(f"unable to read {field_name}") from None
        if not value:
            raise RuntimeError(f"{field_name} must not be empty")
        return value

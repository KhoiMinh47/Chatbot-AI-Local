"""Typed worker settings loaded from the process environment."""

from pydantic import (
    AliasChoices,
    AmqpDsn,
    Field,
    SecretStr,
    TypeAdapter,
    ValidationError,
    field_validator,
)
from pydantic_settings import BaseSettings, SettingsConfigDict

_AMQP_DSN_ADAPTER = TypeAdapter(AmqpDsn)


class BrokerSettings(BaseSettings):
    """Required broker configuration with redacted secret representation."""

    model_config = SettingsConfigDict(
        env_prefix="CELERY_",
        case_sensitive=False,
        extra="ignore",
        frozen=True,
    )

    broker_url: SecretStr
    app_name: str = Field(default="ntc-worker", min_length=1)

    @field_validator("broker_url")
    @classmethod
    def require_amqp_url(cls, value: SecretStr) -> SecretStr:
        """Reject non-AMQP broker URLs while retaining secret redaction."""

        try:
            _AMQP_DSN_ADAPTER.validate_python(value.get_secret_value())
        except ValidationError:
            # Do not let Pydantic include the unwrapped credential in a nested
            # validation error's structured input/context.
            raise ValueError("broker URL must be a valid AMQP DSN") from None
        return value


class IngestionSettings(BaseSettings):
    """Required document-ingestion runtime configuration."""

    model_config = SettingsConfigDict(
        env_prefix="",
        case_sensitive=False,
        extra="ignore",
        frozen=True,
        hide_input_in_errors=True,
        populate_by_name=True,
    )

    database_url: SecretStr = Field(validation_alias="DATABASE_URL")
    minio_endpoint: str = Field(default="minio:9000", min_length=1)
    minio_access_key: SecretStr = Field(
        validation_alias=AliasChoices("MINIO_ACCESS_KEY", "MINIO_ROOT_USER")
    )
    minio_secret_key: SecretStr = Field(
        validation_alias=AliasChoices("MINIO_SECRET_KEY", "MINIO_ROOT_PASSWORD")
    )
    minio_secure: bool = False
    max_document_bytes: int = Field(default=100 * 1024 * 1024, ge=1, le=1024 * 1024 * 1024)
    parser_version: str = Field(default="docling-2.113.0", min_length=1, max_length=64)
    chunk_child_size: int = Field(default=256, ge=16, le=8192)
    chunk_parent_size: int = Field(default=2000, ge=32, le=32768)
    chunk_overlap_percent: int = Field(default=10, ge=0, le=50)
    index_version: str = Field(default="embed300m-v2_s256_o10", min_length=1, max_length=256)
    task_max_retries: int = Field(default=3, ge=0, le=10)
    task_retry_base_seconds: int = Field(default=5, ge=1, le=300)
    task_retry_max_seconds: int = Field(default=60, ge=1, le=3600)
    embedding_base_url: str = Field(default="http://host-gateway:11434/v1", min_length=1)
    embedding_model: str = Field(default="nomic-embed-text", min_length=1)
    embedding_dimension: int = Field(default=768, ge=1, le=65536)
    qdrant_url: str = Field(default="http://qdrant:6333", min_length=1)
    qdrant_collection: str = Field(default="ntc_chunks_local_v1", min_length=1)
    qdrant_active_alias: str | None = Field(default=None, min_length=1)
    vector_index_version: str = Field(default="embed300m-v2-1.13.0", min_length=1, max_length=256)
    embedding_batch_size: int = Field(default=16, ge=1, le=2048)

    @field_validator("database_url")
    @classmethod
    def require_postgresql_url(cls, value: SecretStr) -> SecretStr:
        """Accept only PostgreSQL URLs without rendering credentials on failure."""

        raw = value.get_secret_value().lower()
        if not (raw.startswith("postgresql://") or raw.startswith("postgresql+psycopg://")):
            raise ValueError("database URL must use PostgreSQL")
        return value

import pytest
from app.core.settings import (
    SELECTED_NIM_LLM_MODEL,
    SELECTED_NIM_LLM_MODEL_VERSION,
    ApiSettings,
)
from ntc_shared import LogLevel, RuntimeEnvironment
from pydantic import SecretStr, ValidationError


def test_api_settings_read_prefixed_environment(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv("APP_HOST", "0.0.0.0")
    monkeypatch.setenv("APP_PORT", "8080")
    monkeypatch.setenv("APP_LOG_LEVEL", "warning")

    settings = ApiSettings()

    assert settings.env is RuntimeEnvironment.TEST
    assert settings.host == "0.0.0.0"
    assert settings.port == 8080
    assert settings.log_level is LogLevel.WARNING


def test_api_settings_redact_dependency_credentials(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    sentinel = "phase2-" + "database-credential"
    monkeypatch.setenv("APP_DATABASE_PASSWORD", sentinel)

    settings = ApiSettings()

    assert sentinel not in repr(settings)


def test_api_settings_load_compose_secrets_with_environment_prefix(tmp_path) -> None:  # type: ignore[no-untyped-def]
    values = {
        "APP_DATABASE_PASSWORD": "database-secret-value",
        "APP_REDIS_PASSWORD": "redis-secret-value",
        "APP_RABBITMQ_PASSWORD": "rabbitmq-secret-value",
    }
    for name, value in values.items():
        (tmp_path / name).write_text(value, encoding="utf-8")

    settings = ApiSettings(_secrets_dir=tmp_path)

    assert settings.database_password == SecretStr(values["APP_DATABASE_PASSWORD"])
    assert settings.redis_password == SecretStr(values["APP_REDIS_PASSWORD"])
    assert settings.rabbitmq_password == SecretStr(values["APP_RABBITMQ_PASSWORD"])
    assert all(value not in repr(settings) for value in values.values())


def test_api_settings_read_complete_phase3_nim_contract(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    values = {
        "APP_NIM_CLIENTS_ENABLED": "true",
        "APP_NIM_LLM_BASE_URL": "http://nim-llm:8000/v1",
        "APP_NIM_LLM_MODEL": SELECTED_NIM_LLM_MODEL,
        "APP_NIM_LLM_MODEL_VERSION": SELECTED_NIM_LLM_MODEL_VERSION,
        "APP_NIM_EMBED_BASE_URL": "http://nim-embedding:8000/v1",
        "APP_NIM_EMBED_MODEL": "embed-model",
        "APP_NIM_EMBED_MODEL_VERSION": "1.13.0",
        "APP_EMBEDDING_DIMENSION": "2048",
        "APP_NIM_EMBED_MAX_BATCH_SIZE": "16",
        "APP_NIM_EMBED_MIN_DOWNSHIFT_BATCH_SIZE": "2",
        "APP_NIM_RERANK_BASE_URL": "http://nim-reranking:8000/v1",
        "APP_NIM_RERANK_MODEL": "rerank-model",
        "APP_NIM_RERANK_MODEL_VERSION": "1.10.0",
        "APP_NIM_MAX_RETRIES": "3",
    }
    for name, value in values.items():
        monkeypatch.setenv(name, value)

    settings = ApiSettings()

    assert settings.nim_clients_enabled is True
    assert str(settings.nim_llm_base_url) == "http://nim-llm:8000/v1"
    assert settings.embedding_dimension == 2048
    assert settings.nim_embed_max_batch_size == 16
    assert settings.nim_embed_min_downshift_batch_size == 2
    assert settings.nim_max_retries == 3


def test_enabled_nim_settings_fail_closed_when_llm_and_embedding_are_incomplete() -> None:
    with pytest.raises(ValidationError, match="nim_embed_base_url"):
        ApiSettings(
            nim_clients_enabled=True,
            nim_llm_base_url="http://nim-llm:8000/v1",
        )


def test_enabled_nim_settings_default_and_bind_selected_nemotron_without_reranker() -> None:
    settings = ApiSettings(
        nim_clients_enabled=True,
        nim_llm_base_url="http://nim-llm:8000/v1",
        nim_embed_base_url="http://nim-embedding:8000/v1",
        nim_embed_model="embed-model",
        nim_embed_model_version="1.13.0",
        embedding_dimension=2048,
    )

    assert settings.nim_llm_model == SELECTED_NIM_LLM_MODEL
    assert settings.nim_llm_model_version == SELECTED_NIM_LLM_MODEL_VERSION
    assert settings.nim_rerank_base_url is None

    with pytest.raises(ValidationError, match="selected Nemotron"):
        ApiSettings(
            nim_clients_enabled=True,
            nim_llm_base_url="http://nim-llm:8000/v1",
            nim_llm_model="meta/llama-3.1-8b-instruct",
            nim_llm_model_version="2.0.6",
            nim_embed_base_url="http://nim-embedding:8000/v1",
            nim_embed_model="embed-model",
            nim_embed_model_version="1.13.0",
            embedding_dimension=2048,
        )


def test_optional_reranker_configuration_must_be_complete() -> None:
    with pytest.raises(ValidationError, match="optional reranking"):
        ApiSettings(nim_rerank_model="rerank-model")


def test_nim_url_validation_hides_credential_bearing_input() -> None:
    secret = "phase3-url-password-must-stay-hidden"
    with pytest.raises(ValidationError) as caught:
        ApiSettings(nim_llm_base_url=f"http://user:{secret}@nim.test/v1")

    assert secret not in str(caught.value)
    assert "credential-free" in str(caught.value)


def test_embedding_downshift_floor_cannot_exceed_batch_cap() -> None:
    with pytest.raises(ValidationError, match="must not exceed"):
        ApiSettings(
            nim_embed_max_batch_size=2,
            nim_embed_min_downshift_batch_size=3,
        )

import asyncio

import pytest
from app.application.get_dependency_health import GetDependencyHealth
from app.core.settings import ApiSettings
from app.main import create_app
from fastapi.testclient import TestClient
from ntc_shared import LogLevel, RuntimeEnvironment


def explicit_test_settings(*, service_name: str = "ntc-api") -> ApiSettings:
    """Build hermetic settings without reading ambient APP_* values."""

    return ApiSettings(
        env=RuntimeEnvironment.TEST,
        host="127.0.0.1",
        port=8000,
        log_level=LogLevel.INFO,
        service_name=service_name,
        version="0.1.0",
        dependency_timeout_seconds=1,
        database_host=None,
        database_port=5432,
        database_name="ntc_rag",
        database_user="ntc_app",
        database_password=None,
        redis_host=None,
        redis_port=6379,
        redis_password=None,
        qdrant_health_url=None,
        rabbitmq_health_url=None,
        rabbitmq_user="ntc_worker",
        rabbitmq_password=None,
        minio_health_url=None,
        llm_health_url=None,
    )


def test_liveness_returns_shared_contract() -> None:
    app = create_app(explicit_test_settings())

    with TestClient(app) as client:
        response = client.get("/health/live")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "service": "ntc-api",
        "version": "0.1.0",
    }


def test_liveness_preserves_vietnamese_service_name() -> None:
    app = create_app(explicit_test_settings(service_name="trợ-lý-tài-liệu"))

    with TestClient(app) as client:
        response = client.get("/health/live")

    assert response.status_code == 200
    assert response.json()["service"] == "trợ-lý-tài-liệu"


def test_dependency_diagnostics_are_redacted_and_readiness_stays_closed() -> None:
    app = create_app(explicit_test_settings())

    with TestClient(app) as client:
        dependencies = client.get("/health/dependencies")
        readiness = client.get("/health/ready")

    assert dependencies.status_code == 200
    assert readiness.status_code == 503
    assert readiness.json()["ready"] is False
    assert readiness.json()["status"] == "degraded"
    assert {item["name"] for item in readiness.json()["dependencies"]} == {
        "postgres",
        "redis",
        "qdrant",
        "rabbitmq",
        "minio",
        "llm",
    }
    assert all(item["status"] == "unconfigured" for item in readiness.json()["dependencies"])
    rendered = readiness.text.lower()
    assert "url" not in rendered
    assert "password" not in rendered


class HealthyProbe:
    name = "required-test-service"
    required_for_readiness = True
    configured = True

    async def check(self) -> bool:
        return True


class HangingProbe:
    name = "hanging-required-service"
    required_for_readiness = True
    configured = True

    async def check(self) -> bool:
        await asyncio.Event().wait()
        return True


def test_readiness_returns_200_when_every_required_probe_is_healthy() -> None:
    app = create_app(explicit_test_settings())
    app.state.get_dependency_health = GetDependencyHealth((HealthyProbe(),))

    with TestClient(app) as client:
        response = client.get("/health/ready")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "ready": True,
        "dependencies": [
            {
                "name": "required-test-service",
                "status": "ok",
                "required_for_readiness": True,
            }
        ],
    }


def test_dependency_probe_timeout_closes_readiness_without_hanging() -> None:
    app = create_app(explicit_test_settings())
    app.state.get_dependency_health = GetDependencyHealth(
        (HangingProbe(),),
        timeout_seconds=0.01,
    )

    with TestClient(app) as client:
        response = client.get("/health/ready")

    assert response.status_code == 503
    assert response.json()["dependencies"] == [
        {
            "name": "hanging-required-service",
            "status": "unavailable",
            "required_for_readiness": True,
        }
    ]


def test_dependency_probe_timeout_must_be_positive() -> None:
    with pytest.raises(ValueError, match="timeout must be positive"):
        GetDependencyHealth((HealthyProbe(),), timeout_seconds=0)

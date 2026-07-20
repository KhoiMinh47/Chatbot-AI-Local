import os
import socket
import subprocess
import sys
from pathlib import Path

import pytest
from pydantic import SecretStr, ValidationError
from worker import BrokerSettings, create_celery

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]


def test_broker_url_is_required(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("CELERY_BROKER_URL", raising=False)

    with pytest.raises(ValidationError):
        BrokerSettings()


def test_broker_url_is_redacted() -> None:
    broker_url = "amqp://127.0.0.1:5672//"
    settings = BrokerSettings(broker_url=SecretStr(broker_url))

    assert broker_url not in repr(settings)


def test_celery_factory_configures_json_without_connecting(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_on_connect(_socket: socket.socket, _address: object) -> None:
        raise AssertionError("Celery factory attempted a network connection")

    monkeypatch.setattr(socket.socket, "connect", fail_on_connect)
    settings = BrokerSettings(broker_url=SecretStr("amqp://127.0.0.1:5672//"))

    celery_app = create_celery(settings)

    assert celery_app.main == "ntc-worker"
    assert celery_app.conf.task_serializer == "json"
    assert celery_app.conf.result_serializer == "json"
    assert tuple(celery_app.conf.accept_content) == ("json",)


def test_broker_rejects_non_amqp_schemes() -> None:
    with pytest.raises(ValidationError):
        BrokerSettings(broker_url=SecretStr("redis://127.0.0.1:6379/0"))


def test_invalid_broker_validation_never_exposes_credentials() -> None:
    sentinel = "phase1-" + "credential-sentinel"
    invalid_broker = "https://" + "worker:" + sentinel + "@broker.invalid/queue"

    with pytest.raises(ValidationError) as error:
        BrokerSettings(broker_url=SecretStr(invalid_broker))

    rendered_errors = (
        str(error.value),
        repr(error.value),
        repr(error.value.errors()),
        error.value.json(),
    )
    assert all(sentinel not in rendered for rendered in rendered_errors)


def test_worker_cli_entrypoint_loads_without_connecting() -> None:
    environment = os.environ.copy()
    environment["CELERY_BROKER_URL"] = "amqp://broker.invalid:5672//"

    completed = subprocess.run(
        [sys.executable, "-m", "celery", "--app", "worker.runtime:celery", "report"],
        cwd=REPOSITORY_ROOT,
        env=environment,
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
    )

    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert "task_serializer: 'json'" in completed.stdout
    assert "('json',)" in completed.stdout

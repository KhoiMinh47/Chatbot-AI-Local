from __future__ import annotations

import json
import os
import runpy
import shutil
import stat
import subprocess
from pathlib import Path

import pytest

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]


def test_runtime_secret_directory_is_excluded_from_source_and_build_context() -> None:
    gitignore = (REPOSITORY_ROOT / ".gitignore").read_text(encoding="utf-8")
    dockerignore = (REPOSITORY_ROOT / ".dockerignore").read_text(encoding="utf-8")
    scanner = (REPOSITORY_ROOT / "scripts/source-secret-scan.sh").read_text(encoding="utf-8")

    assert ".secrets/" in gitignore
    assert ".secrets" in dockerignore
    assert "!.secrets/**" in scanner


@pytest.mark.skipif(shutil.which("openssl") is None, reason="openssl is unavailable")
def test_phase2_secret_initializer_creates_group_readable_non_public_files(tmp_path: Path) -> None:
    secret_dir = tmp_path / "runtime-secrets"
    environment = os.environ.copy()
    environment.update(
        {
            "PHASE2_SECRET_DIR": str(secret_dir),
            "PHASE2_SECRET_GID": str(os.getgid()),
        }
    )

    result = subprocess.run(
        [str(REPOSITORY_ROOT / "scripts/phase2-secrets.sh"), "init"],
        cwd=REPOSITORY_ROOT,
        env=environment,
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert stat.S_IMODE(secret_dir.stat().st_mode) == 0o750
    assert secret_dir.stat().st_gid == os.getgid()
    secret_files = tuple(secret_dir.iterdir())
    assert len(secret_files) == 5
    assert all(stat.S_IMODE(path.stat().st_mode) == 0o640 for path in secret_files)
    assert all(path.stat().st_gid == os.getgid() for path in secret_files)
    assert all(path.read_text(encoding="utf-8").strip() for path in secret_files)


def test_phase2_operational_scripts_are_executable() -> None:
    for name in (
        "phase2-compose-check.sh",
        "phase2-images.sh",
        "phase2-migrate.sh",
        "phase2-secrets.sh",
        "smoke-phase2.sh",
    ):
        path = REPOSITORY_ROOT / "scripts" / name
        assert os.access(path, os.X_OK), f"{name} is not executable"


def test_gateway_preserves_api_contract_and_does_not_publish_minio_console() -> None:
    nginx = (REPOSITORY_ROOT / "infra/nginx/nginx.conf").read_text(encoding="utf-8")
    compose = (REPOSITORY_ROOT / "compose.yaml").read_text(encoding="utf-8")

    assert "location /api/" in nginx
    assert "rewrite ^/api/" not in nginx
    assert "MINIO_BROWSER_REDIRECT_URL" not in compose
    assert "/minio-console/" not in nginx
    assert "/api/health/checks/virtual-hosts" in compose
    assert "/api/health/checks/ready-to-serve-clients" not in compose


def test_gpu_dashboard_uses_only_real_dcgm_metric_names() -> None:
    dashboard = json.loads(
        (REPOSITORY_ROOT / "infra/grafana/dashboards/gpu-overview.json").read_text(encoding="utf-8")
    )
    expressions = {
        target["expr"] for panel in dashboard["panels"] for target in panel.get("targets", ())
    }

    assert {
        "DCGM_FI_DEV_GPU_UTIL",
        "DCGM_FI_DEV_GPU_TEMP",
        "DCGM_FI_DEV_FB_USED",
        "DCGM_FI_DEV_POWER_USAGE",
    } <= expressions


def test_grafana_is_provisioned_for_offline_internal_network() -> None:
    compose = (REPOSITORY_ROOT / "compose.yaml").read_text(encoding="utf-8")

    assert 'GF_ANALYTICS_CHECK_FOR_PLUGIN_UPDATES: "false"' in compose
    assert 'GF_PLUGINS_PREINSTALL_DISABLED: "true"' in compose
    assert 'GF_PLUGINS_PUBLIC_KEY_RETRIEVAL_DISABLED: "true"' in compose


def test_external_phase2_images_are_tagged_and_digest_pinned() -> None:
    assignments = {}
    for line in (
        (REPOSITORY_ROOT / "infra/compose/phase2.env").read_text(encoding="utf-8").splitlines()
    ):
        if "_IMAGE=" in line:
            name, value = line.split("=", maxsplit=1)
            assignments[name] = value

    external = {name: value for name, value in assignments.items() if not value.startswith("ntc-")}
    assert external
    assert all("@sha256:" in value for value in external.values())
    assert all(":latest" not in value for value in external.values())
    assert all(":" in value.split("@", maxsplit=1)[0] for value in external.values())


def test_dockerfiles_do_not_fetch_a_mutable_external_frontend() -> None:
    for path in (
        REPOSITORY_ROOT / "apps/api/Dockerfile",
        REPOSITORY_ROOT / "apps/worker/Dockerfile",
        REPOSITORY_ROOT / "apps/web/Dockerfile",
    ):
        first_line = path.read_text(encoding="utf-8").splitlines()[0]
        assert not first_line.startswith("# syntax=")


def test_phase2_acceptance_handles_signals_and_proves_live_gpu_freshness() -> None:
    script = (REPOSITORY_ROOT / "scripts/smoke-phase2.sh").read_text(encoding="utf-8")

    assert "trap 'exit 130' INT" in script
    assert "trap 'exit 143' TERM" in script
    assert "trap cleanup EXIT INT TERM" not in script
    assert 'up{job="dcgm-exporter"} == 1' in script
    assert "(time() - timestamp(DCGM_FI_DEV_GPU_UTIL)) <= 30" in script


def test_phase2_acceptance_records_real_container_recreation() -> None:
    script = (REPOSITORY_ROOT / "scripts/smoke-phase2.sh").read_text(encoding="utf-8")

    assert "core-container-ids-before.tsv" in script
    assert "core-container-ids-after.tsv" in script
    assert 'before_id != "$after_id"' in script
    assert "is unhealthy after recreation" in script


def test_rabbitmq_uses_a_stable_node_name_for_volume_recovery() -> None:
    compose = (REPOSITORY_ROOT / "compose.yaml").read_text(encoding="utf-8")

    assert "hostname: rabbitmq" in compose
    assert "RABBITMQ_NODENAME: rabbit@rabbitmq" in compose


def test_rabbitmq_persistence_probe_accepts_kombu_json_body_variants() -> None:
    namespace = runpy.run_path(str(REPOSITORY_ROOT / "scripts/phase2-persistence.py"))
    matches = namespace["rabbit_body_matches_marker"]

    assert matches("phase2-marker", "phase2-marker")
    assert matches('"phase2-marker"', "phase2-marker")
    assert matches(b'"phase2-marker"', "phase2-marker")
    assert not matches('"different-marker"', "phase2-marker")

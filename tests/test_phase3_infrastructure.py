from __future__ import annotations

import base64
import json
import os
import shutil
import stat
import subprocess
from pathlib import Path

import pytest

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]


def run_script(
    name: str,
    *arguments: str,
    environment: dict[str, str] | None = None,
    timeout: int = 20,
) -> subprocess.CompletedProcess[str]:
    merged_environment = os.environ.copy()
    if environment is not None:
        merged_environment.update(environment)
    return subprocess.run(
        [str(REPOSITORY_ROOT / "scripts" / name), *arguments],
        cwd=REPOSITORY_ROOT,
        env=merged_environment,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )


def phase3_assignments() -> dict[str, str]:
    return {
        name: value
        for line in (REPOSITORY_ROOT / "infra/compose/phase3.env")
        .read_text(encoding="utf-8")
        .splitlines()
        if line and not line.startswith("#")
        for name, value in (line.split("=", maxsplit=1),)
    }


def test_phase3_uses_a_separate_compose_project_and_reviewed_manifests() -> None:
    compose = (REPOSITORY_ROOT / "compose.phase3.yaml").read_text(encoding="utf-8")
    phase2_compose = (REPOSITORY_ROOT / "compose.yaml").read_text(encoding="utf-8")
    assignments = phase3_assignments()

    expected_images = {
        "NIM_LLM_LLAMA_IMAGE": (
            "nvcr.io/nim/meta/llama-3.1-8b-instruct:2.0.6@sha256:"
            "31e360dbb15f825d69e5d68c2032e334301523b4957091270385ed7ef3db5e81"
        ),
        "NIM_LLM_NEMOTRON_IMAGE": (
            "nvcr.io/nim/nvidia/nvidia-nemotron-nano-9b-v2-dgx-spark:"
            "1.0.0-variant@sha256:"
            "82028e38ab950edd32f5053ca2030ee14d965e8fd4fe1c6e06468eb0be07a9a4"
        ),
        "NIM_EMBED_300M_IMAGE": (
            "nvcr.io/nim/nvidia/llama-nemotron-embed-300m-v2:1.13.0@sha256:"
            "1f0a7fc168919d7b84bb4edfb4a4da0c5828d11ee284f9fb8113242b3b35cbb4"
        ),
        "NIM_RERANK_500M_IMAGE": (
            "nvcr.io/nim/nvidia/llama-nemotron-rerank-500m-v2:1.1@sha256:"
            "3e39d44bdb3dd683d6a2ac8d7689b484aee6c18dc7e00c2064f19501742720f3"
        ),
    }
    expected_arm64_children = {
        "NIM_LLM_LLAMA_ARM64_DIGEST": (
            "sha256:249dcac461f20bc29ddb0924bf0c30e0e3f646c26bd849d978996cbe30b4d06e"
        ),
        "NIM_LLM_NEMOTRON_ARM64_DIGEST": (
            "sha256:82028e38ab950edd32f5053ca2030ee14d965e8fd4fe1c6e06468eb0be07a9a4"
        ),
        "NIM_EMBED_300M_ARM64_DIGEST": (
            "sha256:5f8274faf21418cd894eb073d2c520923cce61a750c173b3745aedd1bb7efa49"
        ),
        "NIM_RERANK_500M_ARM64_DIGEST": (
            "sha256:6a598c5e6e7620c542f2101e24e34f3461e650a5b751200df56d52bf9f9444a9"
        ),
    }

    assert assignments["COMPOSE_PROJECT_NAME"] == "ntc-rag-phase3"
    assert {name: assignments[name] for name in expected_images} == expected_images
    assert {name: assignments[name] for name in expected_arm64_children} == expected_arm64_children
    assert all(":latest" not in image for image in expected_images.values())
    assert "x-bge-m3-access-gate:" in compose
    assert "observed_http_status: 402" in compose
    assert assignments["BGE_M3_ACCESS_HTTP_STATUS"] == "402"
    assert assignments["NIM_LLM_LLAMA_PROFILE"] == (
        "c4789f7af56c770c1c88b73da666886365534d6980b6b922b41fd97036c77d73"
    )
    assert compose.count("NIM_MODEL_PROFILE:") == 2
    assert "NIM_MAX_MODEL_LEN" not in compose
    assert "llama-3-1-8b-nim-2-0-6-auto-profile" not in compose
    assert 'NTC_NIM_CONTEXT_CAPABILITY_TEST_TARGET: "131072"' in compose
    assert 'NTC_NIM_IMAGE_VERSION_EXPECTED: "1.10.0"' in compose
    assert 'NTC_NIM_DOCS_VERSION_LINE: "1.10.0"' in compose
    assert assignments["NIM_LLM_NEMOTRON_MODEL"] == "nvidia/nemotron-nano-9b-v2"
    assert assignments["NIM_LLM_NEMOTRON_START_ENTRYPOINT"] == ("/opt/nvidia/nvidia_entrypoint.sh")
    assert assignments["NIM_LLM_NEMOTRON_START_ARG"] == "/usr/local/bin/start_server"
    assert (
        compose.count(
            "NTC_NIM_START_ARG: ${NIM_LLM_NEMOTRON_START_ARG:?set NIM_LLM_NEMOTRON_START_ARG}"
        )
        == 2
    )
    assert assignments["NIM_LLM_NEMOTRON_RUNTIME_STATE"] == (
        "verified-live-nim-1-0-0-ready-models-context-131072"
    )
    assert "  bge-m3:" not in compose
    assert "nim-llm-llama:" not in phase2_compose


def test_candidate_reasoning_controls_and_runtime_only_offline_mode() -> None:
    compose = (REPOSITORY_ROOT / "compose.phase3.yaml").read_text(encoding="utf-8")
    smoke = (REPOSITORY_ROOT / "scripts/nim-smoke.sh").read_text(encoding="utf-8")
    acceptance = (REPOSITORY_ROOT / "scripts/smoke-phase3.sh").read_text(encoding="utf-8")
    benchmark_fixtures = json.loads(
        (REPOSITORY_ROOT / "benchmarks/phase3/fixtures.json").read_text(encoding="utf-8")
    )
    quality_fixtures = json.loads(
        (REPOSITORY_ROOT / "benchmarks/phase3/quality_cases.json").read_text(encoding="utf-8")
    )

    runtime_nemotron, staging_and_later = compose.split("  stage-nim-llm-llama:", maxsplit=1)
    staging_nemotron = staging_and_later.split("  stage-nim-llm-nemotron:", maxsplit=1)[1].split(
        "  stage-nim-embedding-300m:", maxsplit=1
    )[0]

    assert 'HF_HUB_OFFLINE: "1"' in runtime_nemotron
    assert "HF_HUB_OFFLINE" not in staging_nemotron
    assert "llama-standard) reasoning_control_text='detailed thinking off'" in smoke
    assert "nemotron-no-think) reasoning_control_text=/no_think" in smoke
    assert "CANDIDATE_REASONING_CONTROL_MODE=llama-standard" in acceptance
    assert "CANDIDATE_REASONING_CONTROL_MODE=nemotron-no-think" in acceptance
    assert acceptance.count('--reasoning-control-mode "$CANDIDATE_REASONING_CONTROL_MODE"') == 2
    assert not benchmark_fixtures["llm"]["system"].startswith(("/no_think", "detailed"))
    assert not quality_fixtures["system_prompt"].startswith(("/no_think", "detailed"))
    assert "detailed thinking off" not in benchmark_fixtures["llm"]["system"]
    assert "detailed thinking off" not in quality_fixtures["system_prompt"]


@pytest.mark.skipif(shutil.which("docker") is None, reason="Docker is unavailable")
def test_phase3_compose_static_contract_passes_without_a_live_secret() -> None:
    result = run_script(
        "phase3-compose-check.sh",
        environment={"PHASE3_NGC_API_KEY_FILE": "/dev/null"},
    )

    assert result.returncode == 0, result.stderr
    assert "egress isolation" in result.stdout


def test_phase3_operational_scripts_and_wrappers_are_executable() -> None:
    for relative_path in (
        "infra/nim/entrypoint.sh",
        "infra/nim/healthcheck.sh",
        "scripts/phase3-compose-check.sh",
        "scripts/phase3-cache.sh",
        "scripts/phase3-images.sh",
        "scripts/phase3-secrets.sh",
    ):
        assert os.access(REPOSITORY_ROOT / relative_path, os.X_OK), relative_path

    cache_script = (REPOSITORY_ROOT / "scripts/phase3-cache.sh").read_text(encoding="utf-8")
    assert "stage [llama|nemotron|retriever]" in cache_script
    assert "--pull never" in cache_script
    assert "docker compose" in cache_script


@pytest.mark.skipif(shutil.which("jq") is None, reason="jq is unavailable")
def test_ngc_secret_is_explicitly_derived_without_being_printed(tmp_path: Path) -> None:
    secret_value = "".join(("phase3-test-", "value-0123", "456789"))
    encoded = base64.b64encode(f"$oauthtoken:{secret_value}".encode()).decode()
    docker_config = tmp_path / "docker-config.json"
    docker_config.write_text(
        json.dumps({"auths": {"nvcr.io": {"auth": encoded}}}),
        encoding="utf-8",
    )
    secret_dir = tmp_path / "phase3-secrets"
    secret_file = secret_dir / "ngc_api_key"
    environment = {
        "PHASE3_DOCKER_CONFIG_FILE": str(docker_config),
        "PHASE3_SECRET_DIR": str(secret_dir),
        "PHASE3_NGC_API_KEY_FILE": str(secret_file),
        "PHASE3_SECRET_GID": str(os.getgid()),
    }

    initialized = run_script(
        "phase3-secrets.sh",
        "init-from-docker-auth",
        environment=environment,
    )
    assert initialized.returncode == 0, initialized.stderr
    assert secret_value not in initialized.stdout + initialized.stderr
    assert stat.S_IMODE(secret_dir.stat().st_mode) == 0o750
    assert stat.S_IMODE(secret_file.stat().st_mode) == 0o640
    assert secret_dir.stat().st_gid == os.getgid()
    assert secret_file.stat().st_gid == os.getgid()
    assert secret_file.read_text(encoding="utf-8") == secret_value

    checked = run_script("phase3-secrets.sh", "check", environment=environment)
    assert checked.returncode == 0, checked.stderr
    assert secret_value not in checked.stdout + checked.stderr

    second_init = run_script(
        "phase3-secrets.sh",
        "init-from-docker-auth",
        environment=environment,
    )
    assert second_init.returncode != 0
    assert secret_file.read_text(encoding="utf-8") == secret_value


@pytest.mark.skipif(shutil.which("jq") is None, reason="jq is unavailable")
def test_ngc_secret_initialization_refuses_a_symlinked_secret_directory(
    tmp_path: Path,
) -> None:
    secret_value = "phase3-test-value-0123456789"
    encoded = base64.b64encode(f"$oauthtoken:{secret_value}".encode()).decode()
    docker_config = tmp_path / "docker-config.json"
    docker_config.write_text(
        json.dumps({"auths": {"nvcr.io": {"auth": encoded}}}),
        encoding="utf-8",
    )
    redirected_directory = tmp_path / "redirected"
    redirected_directory.mkdir()
    secret_directory = tmp_path / "phase3-secrets"
    secret_directory.symlink_to(redirected_directory, target_is_directory=True)

    result = run_script(
        "phase3-secrets.sh",
        "init-from-docker-auth",
        environment={
            "PHASE3_DOCKER_CONFIG_FILE": str(docker_config),
            "PHASE3_SECRET_DIR": str(secret_directory),
            "PHASE3_NGC_API_KEY_FILE": str(secret_directory / "ngc_api_key"),
            "PHASE3_SECRET_GID": str(os.getgid()),
        },
    )

    assert result.returncode != 0
    assert "symlinked" in result.stderr
    assert not list(redirected_directory.iterdir())
    assert secret_value not in result.stdout + result.stderr


def test_runtime_wrapper_requires_staged_cache_and_drops_credentials(tmp_path: Path) -> None:
    cache_key = "phase3-test-cache"
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    start_command = tmp_path / "start-server.sh"
    start_command.write_text(
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        "[[ -z ${NGC_API_KEY:-} ]]\n"
        "[[ -z ${HF_TOKEN:-} ]]\n"
        "printf 'runtime-started\\n'\n",
        encoding="utf-8",
    )
    start_command.chmod(0o700)
    environment = os.environ.copy()
    blocked_credential = "must-not-" + "reach-runtime"
    environment.update(
        {
            "NTC_NIM_MODE": "serve",
            "NTC_NIM_KIND": "llm",
            "NTC_NIM_IMAGE_VERSION_EXPECTED": "test",
            "NTC_NIM_EXPECTED_MODEL_ID": "test/model",
            "NTC_NIM_ARM64_MANIFEST_DIGEST": "sha256:" + "a" * 64,
            "NTC_NIM_CACHE_KEY": cache_key,
            "NTC_NIM_CACHE_DIR": str(cache_dir),
            "NTC_NIM_START_ENTRYPOINT": str(start_command),
            "NGC_API_KEY": blocked_credential,
            "HF_TOKEN": blocked_credential,
        }
    )
    entrypoint = REPOSITORY_ROOT / "infra/nim/entrypoint.sh"

    missing_marker = subprocess.run(
        [str(entrypoint)],
        cwd=REPOSITORY_ROOT,
        env=environment,
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    assert missing_marker.returncode != 0
    assert "explicit stage profile" in missing_marker.stderr

    (cache_dir / f".ntc-staged-{cache_key}").write_text(
        "cache_key=phase3-test-cache\n"
        "kind=llm\n"
        "nim_image_version_expected=test\n"
        "expected_model_id=test/model\n"
        "served_model_id_observed=test/model\n"
        f"arm64_manifest_digest=sha256:{'a' * 64}\n"
        "staged_at_utc=2026-07-14T00:00:00Z\n",
        encoding="utf-8",
    )
    started = subprocess.run(
        [str(entrypoint)],
        cwd=REPOSITORY_ROOT,
        env=environment,
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    assert started.returncode == 0, started.stderr
    assert started.stdout == "runtime-started\n"


def test_image_check_is_read_only_and_rejects_environment_drift(tmp_path: Path) -> None:
    assignments = phase3_assignments()
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    command_log = tmp_path / "docker-commands.log"
    fake_docker = fake_bin / "docker"
    fake_docker.write_text(
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        'printf \'%s\\n\' "$*" >>"$PHASE3_TEST_DOCKER_LOG"\n'
        "if [[ $1 == image && $2 == inspect ]]; then\n"
        "  ref=$3\n"
        "  args=$*\n"
        "  if [[ $args == *'{{.Os}}/{{.Architecture}}'* ]]; then\n"
        "    printf 'linux/arm64\\n'\n"
        "  elif [[ $args == *'{{json .RepoDigests}}'* ]]; then\n"
        "    case $ref in\n"
        "      nvcr.io/nim/meta/llama-3.1-8b-instruct:*) digest='sha256:"
        "31e360dbb15f825d69e5d68c2032e334301523b4957091270385ed7ef3db5e81' ;;\n"
        "      *nvidia-nemotron-nano-9b-v2-dgx-spark:*) digest='sha256:"
        "82028e38ab950edd32f5053ca2030ee14d965e8fd4fe1c6e06468eb0be07a9a4' ;;\n"
        "      *llama-nemotron-embed-300m-v2:*) digest='sha256:"
        "1f0a7fc168919d7b84bb4edfb4a4da0c5828d11ee284f9fb8113242b3b35cbb4' ;;\n"
        "      *llama-nemotron-rerank-500m-v2:*) digest='sha256:"
        "3e39d44bdb3dd683d6a2ac8d7689b484aee6c18dc7e00c2064f19501742720f3' ;;\n"
        "    esac\n"
        "    tagged=${ref%@*}\n"
        "    repository=${tagged%:*}\n"
        '    printf \'["%s@%s"]\\n\' "$repository" "$digest"\n'
        "  fi\n"
        "  exit 0\n"
        "fi\n"
        "exit 97\n",
        encoding="utf-8",
    )
    fake_docker.chmod(0o700)
    environment = {
        "PATH": f"{fake_bin}:{os.environ['PATH']}",
        "PHASE3_TEST_DOCKER_LOG": str(command_log),
    }

    checked = run_script("phase3-images.sh", "check", environment=environment)
    assert checked.returncode == 0, checked.stderr
    commands = command_log.read_text(encoding="utf-8")
    assert " pull " not in f" {commands} "
    assert "manifest inspect" not in commands

    drifted_env = tmp_path / "phase3-drifted.env"
    original_env = (REPOSITORY_ROOT / "infra/compose/phase3.env").read_text(encoding="utf-8")
    drifted_env.write_text(
        original_env.replace(assignments["NIM_RERANK_500M_ARM64_DIGEST"], "sha256:" + "f" * 64),
        encoding="utf-8",
    )
    drifted = run_script(
        "phase3-images.sh",
        "check",
        environment={**environment, "PHASE3_ENV_FILE": str(drifted_env)},
    )
    assert drifted.returncode != 0
    assert "manifest evidence drifted" in drifted.stderr

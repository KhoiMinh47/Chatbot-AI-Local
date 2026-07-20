from __future__ import annotations

import json
import os
import shlex
import subprocess
import sys
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPOSITORY_ROOT))

from scripts.phase3_scorecard import (  # noqa: E402
    EXPECTED_LLM_METRIC_DEFINITIONS,
    EXPECTED_LLM_PROMPT_UNIQUENESS_CONTROL,
)

ACCEPTANCE_SCRIPT = REPOSITORY_ROOT / "scripts" / "smoke-phase3.sh"
RUNTIME_EVIDENCE_SCRIPT = REPOSITORY_ROOT / "scripts" / "phase3_runtime_evidence.py"
SCORECARD_SCRIPT = REPOSITORY_ROOT / "scripts" / "phase3_scorecard.py"

LLM_SCENARIOS = (
    ("engine-short-c1", 512, 256, 1, None),
    ("rag-8k-c1", 8192, 512, 1, None),
    ("rag-8k-c4", 8192, 512, 4, None),
    ("long-32k-c1", 32_448, 64, 1, 32_768),
    ("long-64k-c1", 65_216, 64, 1, 65_536),
    ("long-128k-c1", 130_752, 64, 1, 131_072),
)


def llm_scenario_evidence(
    spec: tuple[str, int, int, int, int | None],
    *,
    requests: int = 20,
    warmup: int = 2,
) -> dict[str, object]:
    name, target_input, target_output, concurrency, target_context = spec
    prompt_min = target_input
    prompt_max = target_input
    context_min = prompt_min + target_output
    context_max = prompt_max + target_output
    if target_context is not None:
        context_min = target_context - 256
        context_max = target_context - 128
        prompt_min = context_min - target_output
        prompt_max = context_max - target_output
    metrics = {
        field: {"observed_count": requests, "p50": 1.0, "p95": 1.0}
        for field in (
            "prompt_tokens_actual",
            "completion_tokens_actual",
            "total_tokens_actual",
            "ttft_seconds",
            "decode_duration_seconds",
            "decode_tokens_per_second",
            "total_latency_seconds",
        )
    }
    return {
        "name": name,
        "summary": {
            "status": "pass",
            "request_count": requests,
            "success_count": requests,
            "failure_count": 0,
            "warmup_failure_count": 0,
            "warmup_required_count": warmup,
            "concurrency": concurrency,
            "target_input_tokens": target_input,
            "target_context_tokens": target_context,
            "target_vs_actual_p50_ratio": 1.0,
            "max_output_tokens": target_output,
            **metrics,
            "input_token_target_check": {
                "status": "pass",
                "required_relation": (
                    "every_observed_prompt_plus_max_output_within_absolute_context_window"
                    if target_context is not None
                    else "every_observed_prompt_within_target_ratio"
                ),
                "target_input_tokens": target_input,
                "target_context_tokens": target_context,
                "observed_prompt_tokens_min": prompt_min,
                "observed_prompt_tokens_max": prompt_max,
                "max_output_tokens": target_output,
                "observed_prompt_plus_max_output_min": context_min,
                "observed_prompt_plus_max_output_max": context_max,
                "absolute_context_lower_bound": (
                    target_context - 512 if target_context is not None else None
                ),
                "absolute_context_upper_bound": target_context,
                "minimum_ratio": 0.8 if target_context is None else None,
                "maximum_ratio": 1.2 if target_context is None else None,
            },
            "output_token_target_check": {
                "status": "pass",
                "required_relation": "completion_tokens_actual_equals_max_output_tokens",
                "target_completion_tokens": target_output,
                "fixed_request_control": {
                    "ignore_eos": True,
                    "scope": "synthetic_llm_benchmark_only",
                },
                "measured": {
                    "required_count": requests,
                    "observed_count": requests,
                    "matching_count": requests,
                    "observed_min": target_output,
                    "observed_max": target_output,
                },
                "warmup": {
                    "required_count": warmup,
                    "observed_count": warmup,
                    "matching_count": warmup,
                    "observed_min": target_output if warmup else None,
                    "observed_max": target_output if warmup else None,
                },
            },
        },
    }


def llm_report(*, requests: int = 20, warmup: int = 2, long: bool = True) -> dict[str, object]:
    profile = "live-profile"
    value = lambda item: {"value": item}  # noqa: E731
    specs = LLM_SCENARIOS if long else LLM_SCENARIOS[:3]
    return {
        "schema_version": 2,
        "status": "pass",
        "kind": "llm",
        "candidate": {
            "candidate_id": "llama",
            "requested_model_id": "model-id",
            "image_ref": value("image@digest"),
            "image_digest": value(f"sha256:{'a' * 64}"),
            "license_id": value("license"),
        },
        "runtime": {
            "served_model_id": value("model-id"),
            "nim_version": value("1.0"),
            "profile": value(profile),
            "precision": value("FP8"),
            "max_model_length": value(131_072),
        },
        "metadata_completeness": {
            "status": "complete",
            "unverified_or_missing_fields": [],
        },
        "contract_check": {"status": "pass"},
        "semantic_check": {"status": "not_applicable"},
        "run_config": {
            "measured_requests_per_scenario": requests,
            "warmup_requests_per_scenario": warmup,
            "measured_runtime_state": "warm_after_runner_warmup",
            "long_context_opt_in": long,
            "metrics_required": True,
            "reasoning_control_mode": "llama-standard",
            "llm_prompt_uniqueness_control": dict(EXPECTED_LLM_PROMPT_UNIQUENESS_CONTROL),
            "system_prompt_persisted": False,
            "base_url_persisted": False,
            "credentials_persisted": False,
        },
        "metric_definitions": dict(EXPECTED_LLM_METRIC_DEFINITIONS),
        "scenarios": [
            llm_scenario_evidence(spec, requests=requests, warmup=warmup) for spec in specs
        ],
    }


def evaluate_llm_report(
    report: Path,
    output: Path,
    *,
    runner_exit_code: int = 0,
    requests: int = 20,
    warmup: int = 2,
    long: int = 1,
) -> subprocess.CompletedProcess[str]:
    command = (
        f"source {shlex.quote(str(ACCEPTANCE_SCRIPT))}; "
        f"evaluate_benchmark_report llm {shlex.quote(str(report))} "
        f"{shlex.quote(str(output))} {runner_exit_code} llama model-id "
        f"live-profile {requests} {warmup} {long}"
    )
    return subprocess.run(
        ["bash", "-c", command],
        cwd=REPOSITORY_ROOT,
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )


def run_acceptance(
    *arguments: str, environment: dict[str, str], timeout: int = 20
) -> subprocess.CompletedProcess[str]:
    merged_environment = os.environ.copy()
    merged_environment.update(environment)
    return subprocess.run(
        [str(ACCEPTANCE_SCRIPT), *arguments],
        cwd=REPOSITORY_ROOT,
        env=merged_environment,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )


def test_phase3_acceptance_defaults_match_master_and_stay_in_phase3() -> None:
    script = ACCEPTANCE_SCRIPT.read_text(encoding="utf-8")
    scorecard = SCORECARD_SCRIPT.read_text(encoding="utf-8")

    assert os.access(ACCEPTANCE_SCRIPT, os.X_OK)
    assert RUNTIME_EVIDENCE_SCRIPT.is_file()
    assert SCORECARD_SCRIPT.is_file()
    assert "set -Eeuo pipefail" in script
    assert "PHASE3_MEASURED_REQUESTS:-20" in script
    assert "PHASE3_WARMUP_REQUESTS:-2" in script
    assert "PHASE3_INCLUDE_LONG_CONTEXT:-1" in script
    assert "PHASE3_EMBED_MAX_MODEL_LENGTH:-8192" in script
    assert "--include-long-context" in script
    assert "scripts/phase3_runtime_evidence.py" in script
    assert "scripts/phase3_scorecard.py" in script
    assert "no Phase 4 ingestion or Phase 5 retrieval-quality claim" in scorecard
    assert "phase4_started: false" in script
    candidate_flow = script.split("run_candidate() {", maxsplit=1)[1].split(
        "run_combination() {", maxsplit=1
    )[0]
    assert candidate_flow.index("write_runtime_declaration") < candidate_flow.index(
        "verify_runtime_evidence"
    )
    assert candidate_flow.index("verify_runtime_evidence") < candidate_flow.index("start_sampler")
    main_flow = script.split("main() {", maxsplit=1)[1]
    assert main_flow.index("for candidate in llama nemotron; do") < main_flow.index(
        "write_scorecard_inputs"
    )

    for endpoint in (
        "health/live",
        "health/ready",
        "models",
        "metrics",
        "metadata",
        "version",
        "manifest",
        "license",
    ):
        assert endpoint in script

    assert "scripts/phase3_benchmark.py" in script
    assert "scripts/phase3_quality.py" in script
    assert "TTFT" in script or "ttft" in script
    assert "decode_tokens_per_second" in script
    assert "master_backend_receive_ttft_measured: false" in script
    assert "client-observed request start" in script
    assert "llm_prompt_uniqueness_control" in script
    assert "full_user_prompt_reuse_between_requests: false" in script
    assert "32K/64K/128K" in script
    assert "nvidia-smi" in script
    assert "docker stats --no-stream" in script
    assert "free -b" in script


def test_candidate_reasoning_modes_are_fixed_and_combination_preserves_llm_mode() -> None:
    script = ACCEPTANCE_SCRIPT.read_text(encoding="utf-8")
    command = f"""
set -euo pipefail
source {shlex.quote(str(ACCEPTANCE_SCRIPT))}
NIM_LLM_LLAMA_MODEL=meta/llama
NIM_LLM_LLAMA_IMAGE=registry/llama:1@sha256:{"a" * 64}
NIM_LLM_NEMOTRON_MODEL=nvidia/nemotron
NIM_LLM_NEMOTRON_IMAGE=registry/nemotron:1@sha256:{"b" * 64}
candidate_values llama
printf '%s\n' "$CANDIDATE_REASONING_CONTROL_MODE"
candidate_values nemotron
printf '%s\n' "$CANDIDATE_REASONING_CONTROL_MODE"
"""
    result = subprocess.run(
        ["bash", "-c", command],
        cwd=REPOSITORY_ROOT,
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.splitlines() == ["llama-standard", "nemotron-no-think"]
    assert "for candidate in llama nemotron; do" in script
    assert 'run_combination "$candidate"' in script
    assert '"$CANDIDATE_REASONING_CONTROL_MODE" &' in script
    assert "system_prompt_persisted: false" in script


def test_phase3_acceptance_enforces_private_runtime_and_safe_cleanup() -> None:
    script = ACCEPTANCE_SCRIPT.read_text(encoding="utf-8")

    assert "container_ip" in script
    assert ".NetworkSettings.Networks" in script
    assert "assert_no_published_ports" in script
    assert '.HostConfig.NetworkMode != "host"' in script
    assert ".NetworkSettings.Ports" in script
    assert "http://$ip:8000/v1" in script
    assert "--remove-orphans" in script
    for profile in (
        "llama",
        "nemotron",
        "retriever",
        "stage-llama",
        "stage-nemotron",
        "stage-retriever",
    ):
        assert f"--profile {profile}" in script
    assert "cache_volumes_preserved:" in script
    assert "expected_cache_volume_count" in script
    assert "docker volume inspect" in script
    assert "down -v" not in script
    assert "--volumes" not in script
    assert "OOMKilled" in script
    assert "preexisting-container-gate" in script
    assert "smoke_pids" in script
    assert "concurrent: true" in script
    assert "one_request_per_loaded_service: true" in script


def test_bge_gate_is_live_secret_safe_and_cannot_fake_pass() -> None:
    script = ACCEPTANCE_SCRIPT.read_text(encoding="utf-8")

    assert ("https://nvcr.io/proxy_auth?scope=repository%3Anim%2Fbaai%2Fbge-m3%3Apull") in script
    assert "probe_bge_access" in script
    assert "curl --disable --config -" in script
    assert "--output /dev/null" in script
    assert "response_body_persisted: false" in script
    assert "credential_persisted: false" in script
    assert "mutable_latest_used: false" in script
    assert "substitute_used: false" in script
    assert "exact_pinned_image_selected: false" in script
    assert "http_status_raw: $live_http_status" in script
    assert "return 3" in script
    assert "BGE-M3 exact pinned runtime is unavailable" in script


def test_exact_live_profiles_and_precisions_are_required() -> None:
    script = ACCEPTANCE_SCRIPT.read_text(encoding="utf-8")
    expected_profiles = {
        "c4789f7af56c770c1c88b73da666886365534d6980b6b922b41fd97036c77d73": "FP8",
        "092ed4213624e774d24cdaf84e3b6222839bab2008a21d3c214ab46626366f90": "BF16",
        "a28963301b18077db3454d5eb21f5678304936c5a425ddc552443de1f5449f2a": "NVFP4",
        "f9db61d5a467d46be7733e90a26705798764b93d480c842143d525c1932b01e2": "NVFP4",
        "e28f17c9c13a99055d065f88d725bf93c23b3aab14acd68f16323de1353fc528": "ONNX-FP16",
        "f7391ddbcb95b2406853526b8e489fedf20083a2420563ca3e65358ff417b10f": "ONNX-FP16",
    }

    for profile_id, precision in expected_profiles.items():
        assert profile_id in script
        assert precision in script
    assert "exact-profile-id-observed-in-live-startup-log" in script
    assert "exact-profile-configured-and-live-fp8-confirmed" in script
    assert "compatible_profile_is_not_automatically_an_active_profile: true" in script
    assert "unresolved-live-profile" in script


def test_exact_profile_resolution_comes_from_each_live_startup_log(tmp_path: Path) -> None:
    candidates = {
        "llama": (
            "c4789f7af56c770c1c88b73da666886365534d6980b6b922b41fd97036c77d73",
            "FP8",
        ),
        "nemotron": (
            "f9db61d5a467d46be7733e90a26705798764b93d480c842143d525c1932b01e2",
            "NVFP4",
        ),
        "embedding-300m": (
            "e28f17c9c13a99055d065f88d725bf93c23b3aab14acd68f16323de1353fc528",
            "ONNX-FP16",
        ),
        "reranking-500m": (
            "f7391ddbcb95b2406853526b8e489fedf20083a2420563ca3e65358ff417b10f",
            "ONNX-FP16",
        ),
    }

    for candidate, (profile_id, precision) in candidates.items():
        candidate_dir = tmp_path / candidate
        candidate_dir.mkdir()
        startup_evidence = (
            "live runtime precision FP8\n"
            if candidate == "llama"
            else f"live selected profile {profile_id}\n"
        )
        (candidate_dir / "startup.log").write_text(startup_evidence, encoding="utf-8")
        (candidate_dir / "container-inspect.json").write_text(
            json.dumps([{"Config": {"NIM_MODEL_PROFILE": profile_id}}]),
            encoding="utf-8",
        )
        command = f"""
set -euo pipefail
source {shlex.quote(str(ACCEPTANCE_SCRIPT))}
NIM_LLM_LLAMA_PROFILE=c4789f7af56c770c1c88b73da666886365534d6980b6b922b41fd97036c77d73
CANDIDATE_RUNTIME_PROFILE=unresolved-live-profile
CANDIDATE_PRECISION=unresolved-live-precision
CANDIDATE_PROFILE_SOURCE=runtime-output-required
CANDIDATE_PRECISION_SOURCE=runtime-output-required
resolve_runtime_metadata {shlex.quote(candidate)} {shlex.quote(str(candidate_dir))}
printf '%s|%s|%s\n' "$CANDIDATE_RUNTIME_PROFILE" "$CANDIDATE_PRECISION" "$CANDIDATE_PROFILE_SOURCE"
"""
        result = subprocess.run(
            ["bash", "-c", command],
            cwd=REPOSITORY_ROOT,
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )

        assert result.returncode == 0, result.stderr
        expected_source = (
            "exact-profile-configured-and-live-fp8-confirmed"
            if candidate == "llama"
            else "exact-profile-id-observed-in-live-startup-log"
        )
        assert result.stdout.strip() == (f"{profile_id}|{precision}|{expected_source}")


def test_bge_status_000_is_valid_machine_readable_failure_evidence(tmp_path: Path) -> None:
    output = tmp_path / "bge.json"
    command = f"""
set -euo pipefail
source {shlex.quote(str(ACCEPTANCE_SCRIPT))}
BGE_M3_MODEL=baai/bge-m3
BGE_M3_ACCESS_STATE=blocked-reviewed-state
BGE_M3_ACCESS_HTTP_STATUS=402
BGE_LIVE_HTTP_STATUS=000
write_bge_evidence {shlex.quote(str(output))} fail
"""
    result = subprocess.run(
        ["bash", "-c", command],
        cwd=REPOSITORY_ROOT,
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    evidence = json.loads(output.read_text(encoding="utf-8"))
    probe = evidence["live_authenticated_token_scope_probe"]
    assert probe["http_status_raw"] == "000"
    assert probe["http_status"] is None
    assert probe["result"] == "fail"
    assert evidence["acceptance_effect"] == "blocked"
    assert evidence["block_reason"] == "live-registry-probe-failed-without-an-http-response"


def test_exact_llm_evaluator_rejects_long_gate_runner_and_tampering(tmp_path: Path) -> None:
    report = tmp_path / "report.json"
    evaluation = tmp_path / "evaluation.json"
    valid = llm_report()
    report.write_text(json.dumps(valid), encoding="utf-8")

    accepted = evaluate_llm_report(report, evaluation)
    assert accepted.returncode == 0, accepted.stderr
    evidence = json.loads(evaluation.read_text(encoding="utf-8"))
    assert evidence["evidence_identity_valid"] is True
    assert evidence["workload_valid"] is True
    assert evidence["exact_scenario_matrix_valid"] is True
    assert evidence["all_scenarios_pass"] is True
    assert evidence["long_context_all_pass"] is True

    tampered_reports = []

    duplicate = json.loads(json.dumps(valid))
    duplicate["scenarios"].append(duplicate["scenarios"][0])
    tampered_reports.append(duplicate)

    wrong_target = json.loads(json.dumps(valid))
    wrong_target["scenarios"][1]["summary"]["target_input_tokens"] = 4096
    tampered_reports.append(wrong_target)

    wrong_identity = json.loads(json.dumps(valid))
    wrong_identity["runtime"]["profile"]["value"] = "different-profile"
    tampered_reports.append(wrong_identity)

    wrong_workload = json.loads(json.dumps(valid))
    wrong_workload["run_config"]["warmup_requests_per_scenario"] = 0
    tampered_reports.append(wrong_workload)

    reused_prompt = json.loads(json.dumps(valid))
    reused_prompt["run_config"]["llm_prompt_uniqueness_control"][
        "full_user_prompt_reuse_between_requests"
    ] = True
    tampered_reports.append(reused_prompt)

    wrong_metric_scope = json.loads(json.dumps(valid))
    wrong_metric_scope["metric_definitions"]["scope"] = "backend TTFT"
    tampered_reports.append(wrong_metric_scope)

    outside_long_window = json.loads(json.dumps(valid))
    outside_long_window["scenarios"][-1]["summary"]["input_token_target_check"][
        "observed_prompt_plus_max_output_min"
    ] = 131_072 - 513
    tampered_reports.append(outside_long_window)

    for index, payload in enumerate(tampered_reports):
        report.write_text(json.dumps(payload), encoding="utf-8")
        rejected = evaluate_llm_report(report, evaluation)
        assert rejected.returncode != 0, f"tamper {index} unexpectedly passed"

    report.write_text(json.dumps(valid), encoding="utf-8")
    runner_failed = evaluate_llm_report(report, evaluation, runner_exit_code=1)
    assert runner_failed.returncode != 0


def test_exact_retriever_evaluator_rejects_duplicate_and_target_tamper(
    tmp_path: Path,
) -> None:
    value = lambda item: {"value": item}  # noqa: E731
    for kind, candidate, scenario_specs, target_field in (
        (
            "embedding",
            "embedding-300m",
            (("embedding-batch-1", 1), ("embedding-batch-16", 16)),
            "batch_size",
        ),
        (
            "reranking",
            "reranking-500m",
            (("reranking-passages-2", 2), ("reranking-passages-16", 16)),
            "passage_count",
        ),
    ):
        report = tmp_path / f"{kind}-report.json"
        evaluation = tmp_path / f"{kind}-evaluation.json"
        payload: dict[str, object] = {
            "schema_version": 2,
            "status": "pass",
            "kind": kind,
            "candidate": {
                "candidate_id": candidate,
                "requested_model_id": "model-id",
                "image_ref": value("image@digest"),
                "image_digest": value(f"sha256:{'a' * 64}"),
                "license_id": value("license"),
            },
            "runtime": {
                "served_model_id": value("model-id"),
                "nim_version": value("1.0"),
                "profile": value("live-profile"),
                "precision": value("ONNX-FP16"),
                "max_model_length": value(8192),
            },
            "metadata_completeness": {
                "status": "complete",
                "unverified_or_missing_fields": [],
            },
            "contract_check": {"status": "pass"},
            "semantic_check": {"status": "pass"},
            "run_config": {
                "measured_requests_per_scenario": 4,
                "warmup_requests_per_scenario": 1,
                "long_context_opt_in": False,
                "metrics_required": False,
            },
            "scenarios": [
                {
                    "name": name,
                    "summary": {
                        "status": "pass",
                        "request_count": 4,
                        "success_count": 4,
                        "failure_count": 0,
                        "warmup_failure_count": 0,
                        "warmup_required_count": 1,
                        "concurrency": 1,
                        target_field: target,
                        "total_latency_seconds": {"observed_count": 4},
                    },
                }
                for name, target in scenario_specs
            ],
        }

        def evaluate(
            evaluated_kind: str = kind,
            evaluated_candidate: str = candidate,
            report_path: Path = report,
            evaluation_path: Path = evaluation,
        ) -> subprocess.CompletedProcess[str]:
            command = (
                f"source {shlex.quote(str(ACCEPTANCE_SCRIPT))}; "
                f"evaluate_benchmark_report {evaluated_kind} "
                f"{shlex.quote(str(report_path))} {shlex.quote(str(evaluation_path))} "
                f"0 {evaluated_candidate} model-id live-profile 4 1 0"
            )
            return subprocess.run(
                ["bash", "-c", command],
                cwd=REPOSITORY_ROOT,
                capture_output=True,
                text=True,
                timeout=10,
                check=False,
            )

        report.write_text(json.dumps(payload), encoding="utf-8")
        accepted = evaluate()
        assert accepted.returncode == 0, accepted.stderr

        duplicate = json.loads(json.dumps(payload))
        duplicate["scenarios"].append(duplicate["scenarios"][0])
        report.write_text(json.dumps(duplicate), encoding="utf-8")
        assert evaluate().returncode != 0

        wrong_target = json.loads(json.dumps(payload))
        wrong_target["scenarios"][0]["summary"][target_field] = 99
        report.write_text(json.dumps(wrong_target), encoding="utf-8")
        assert evaluate().returncode != 0


def test_benchmark_evaluator_persists_structured_runner_failure_without_scenarios(
    tmp_path: Path,
) -> None:
    for kind, scenarios in (("llm", "missing"), ("embedding", None), ("reranking", "missing")):
        report = tmp_path / f"{kind}-failed-report.json"
        evaluation = tmp_path / f"{kind}-failed-evaluation.json"
        payload: dict[str, object] = {
            "status": "fail",
            "kind": kind,
            "failure": {
                "error_code": "invalid_usage_token_counts",
                "detail_persisted": False,
            },
        }
        if scenarios != "missing":
            payload["scenarios"] = scenarios
        report.write_text(json.dumps(payload), encoding="utf-8")
        command = (
            f"source {shlex.quote(str(ACCEPTANCE_SCRIPT))}; "
            f"evaluate_benchmark_report {kind} {shlex.quote(str(report))} "
            f"{shlex.quote(str(evaluation))} 1"
        )

        result = subprocess.run(
            ["bash", "-c", command],
            cwd=REPOSITORY_ROOT,
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )

        assert result.returncode != 0
        assert "Cannot iterate over null" not in result.stderr
        evaluated = json.loads(evaluation.read_text(encoding="utf-8"))
        assert evaluated["runner_exit_code"] == 1
        assert evaluated["report_shape_valid"] is False
        assert evaluated["report_overall_status"] == "fail"
        assert evaluated["failure"] == payload["failure"]
        if kind == "llm":
            assert evaluated["core_short_and_rag_status"] == "fail"
            assert evaluated["long_context_results"] == []
        else:
            assert evaluated["semantic_status"] == "invalid"
            assert evaluated["all_scenarios_pass"] is False


def test_reduced_acceptance_never_claims_validated_long_context(tmp_path: Path) -> None:
    def record_mapping(include_long: int, conformant: int, name: str) -> tuple[list[str], str]:
        acceptance = tmp_path / f"{name}.tsv"
        reason = tmp_path / f"{name}-reason.txt"
        command = f"""
set -euo pipefail
source {shlex.quote(str(ACCEPTANCE_SCRIPT))}
ACCEPTANCE_FILE={shlex.quote(str(acceptance))}
: >"$ACCEPTANCE_FILE"
HAD_EXECUTION_FAILURE=0
INCLUDE_LONG_CONTEXT={include_long}
WORKLOAD_CONFORMANT={conformant}
MEASURED_REQUESTS=1
BGE_LIVE_HTTP_STATUS=402
record_phase3_acceptance
phase3_failure_reason >{shlex.quote(str(reason))}
"""
        result = subprocess.run(
            ["bash", "-c", command],
            cwd=REPOSITORY_ROOT,
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        assert result.returncode == 0, result.stderr
        return acceptance.read_text(encoding="utf-8").splitlines(), reason.read_text(
            encoding="utf-8"
        )

    reduced_rows, reduced_reason = record_mapping(0, 0, "reduced")
    reduced_ac02 = next(row for row in reduced_rows if row.startswith("AC-02\t"))
    assert reduced_ac02.split("\t", maxsplit=2)[1] == "fail"
    assert "was not run in reduced debug" in reduced_ac02
    assert "validated 32K/64K/128K" not in reduced_ac02
    assert "required-nonconformant" in reduced_reason
    assert "long-context enabled=0" in reduced_reason

    full_rows, _full_reason = record_mapping(1, 1, "full")
    full_ac02 = next(row for row in full_rows if row.startswith("AC-02\t"))
    assert full_ac02.split("\t", maxsplit=2)[1] == "blocked"
    assert "validated 32K/64K/128K evidence" in full_ac02
    full_ac06 = next(row for row in full_rows if row.startswith("AC-06\t"))
    assert full_ac06.split("\t", maxsplit=2)[1] == "blocked"
    assert "BGE-M3" in full_ac06


def test_quality_automatic_hard_gate_is_required_but_human_winner_stays_pending(
    tmp_path: Path,
) -> None:
    report = tmp_path / "quality.json"
    evaluation = tmp_path / "quality-evaluation.json"
    report.write_text(
        json.dumps(
            {
                "status": "completed",
                "fixture": {"case_count": 10},
                "automatic_hard_gate": {"status": "failed", "failed_case_count": 1},
                "human_review": {"required": True, "status": "pending", "decision": None},
                "candidate_selection": {
                    "status": "not_decided",
                    "winner_candidate_id": None,
                },
            }
        ),
        encoding="utf-8",
    )
    command = (
        f"source {shlex.quote(str(ACCEPTANCE_SCRIPT))}; "
        f"evaluate_quality_report {shlex.quote(str(report))} "
        f"{shlex.quote(str(evaluation))}"
    )
    result = subprocess.run(
        ["bash", "-c", command],
        cwd=REPOSITORY_ROOT,
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )

    assert result.returncode == 3
    evaluated = json.loads(evaluation.read_text(encoding="utf-8"))
    assert evaluated["automatic_hard_gate"]["status"] == "failed"
    assert evaluated["human_review"] == {
        "required": True,
        "status": "pending",
        "decision": None,
    }
    assert evaluated["candidate_selection"]["status"] == "not_decided"


def test_reduced_workload_is_rejected_before_any_evidence_or_docker_mutation(
    tmp_path: Path,
) -> None:
    evidence_root = tmp_path / "evidence"
    result = run_acceptance(
        environment={
            "PHASE3_EVIDENCE_ROOT": str(evidence_root),
            "PHASE3_RUN_ID": "reduced-rejected",
            "PHASE3_MEASURED_REQUESTS": "1",
        }
    )

    assert result.returncode != 0
    assert "PHASE3_ALLOW_REDUCED_WORKLOAD=1" in result.stderr
    assert not evidence_root.exists()


def test_zero_warmup_requires_debug_opt_in_and_is_always_nonconformant() -> None:
    command = f"""
set -euo pipefail
source {shlex.quote(str(ACCEPTANCE_SCRIPT))}
MEASURED_REQUESTS=20
WARMUP_REQUESTS=0
INCLUDE_LONG_CONTEXT=1
ALLOW_REDUCED_WORKLOAD=0
if validate_inputs >/dev/null 2>&1; then
  exit 90
fi
ALLOW_REDUCED_WORKLOAD=1
WORKLOAD_CONFORMANT=1
validate_inputs
printf '%s\n' "$WORKLOAD_CONFORMANT"
"""
    result = subprocess.run(
        ["bash", "-c", command],
        cwd=REPOSITORY_ROOT,
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "0"


def test_telemetry_validator_requires_each_expected_container(tmp_path: Path) -> None:
    first_id = "a" * 64
    second_id = "b" * 64
    telemetry = tmp_path / "telemetry.log"
    output = tmp_path / "validation.json"
    telemetry.write_text(
        "\n".join(
            (
                "sample_at_utc=2026-07-14T00:00:00Z",
                "gpu_observation_status=pass",
                "NVIDIA RTX PRO 6000, 580.00, 10, 100, 50, 40, 100",
                "host_memory_status=pass",
                "Mem: 100 50 50 0 0 50",
                "container_stats_status=pass",
                f'{{"Container":"{first_id[:12]}"}}',
                f'{{"Container":"{second_id[:12]}"}}',
                "sample_complete=1",
            )
        ),
        encoding="utf-8",
    )
    command = (
        f"source {shlex.quote(str(ACCEPTANCE_SCRIPT))}; "
        f"validate_telemetry '{first_id} {second_id}' {shlex.quote(str(telemetry))} "
        f"{shlex.quote(str(output))}"
    )
    accepted = subprocess.run(
        ["bash", "-c", command],
        cwd=REPOSITORY_ROOT,
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    assert accepted.returncode == 0, accepted.stderr
    assert json.loads(output.read_text(encoding="utf-8"))["status"] == "pass"

    telemetry.write_text(
        telemetry.read_text(encoding="utf-8").replace(second_id[:12], "missing-id"),
        encoding="utf-8",
    )
    rejected = subprocess.run(
        ["bash", "-c", command],
        cwd=REPOSITORY_ROOT,
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    assert rejected.returncode != 0
    assert json.loads(output.read_text(encoding="utf-8"))["status"] == "fail"


def test_exact_secret_scan_rejects_value_without_persisting_match(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    secret_file = tmp_path / "secret"
    secret = "phase3-test-only-secret-value-123456789"
    secret_file.write_text(f"{secret}\n", encoding="utf-8")
    harmless = run_dir / ".hidden-secret.log"
    (run_dir / ".ignore").write_text(".hidden-secret.log\n", encoding="utf-8")
    harmless.write_text("credential=[REDACTED]\n", encoding="utf-8")

    def scan() -> subprocess.CompletedProcess[str]:
        command = f"""
source {shlex.quote(str(ACCEPTANCE_SCRIPT))}
RUN_DIR={shlex.quote(str(run_dir))}
PHASE3_NGC_API_KEY_FILE={shlex.quote(str(secret_file))}
SECRETS_SCAN_PERFORMED=0
SECRETS_SCAN_PASSED=0
scan_exact_secret_artifacts
"""
        return subprocess.run(
            ["bash", "-c", command],
            cwd=REPOSITORY_ROOT,
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )

    accepted = scan()
    assert accepted.returncode == 0, accepted.stderr
    assert accepted.stdout == ""
    harmless.write_text(f"accidental={secret}\n", encoding="utf-8")
    rejected = scan()
    assert rejected.returncode != 0
    assert rejected.stdout == ""
    evidence_text = (run_dir / "secret-artifact-scan.json").read_text(encoding="utf-8")
    evidence = json.loads(evidence_text)
    assert evidence["status"] == "fail"
    assert evidence["exact_secret_value_persisted"] is True
    assert evidence["matched_file_names_persisted"] is False
    assert secret not in evidence_text


def test_both_llm_combinations_require_concurrent_load_and_canonical_checks() -> None:
    script = ACCEPTANCE_SCRIPT.read_text(encoding="utf-8")
    active_combination = script.split("run_combination() {", maxsplit=1)[1].split(
        "write_scorecard_inputs() {", maxsplit=1
    )[0]

    assert "directory=$RUN_DIR/combinations/$llm_candidate" in active_combination
    assert "local MEASURED_REQUESTS=4" not in active_combination
    assert '"$directory/load-$candidate" 4 1 0' in active_combination
    assert '"rag-8k-c4"' in script
    assert "RestartCount" in active_combination
    assert "CUDA[[:space:]]+out" in active_combination
    assert "checks:" in active_combination
    assert "no_oom:" in active_combination
    assert "load:" in active_combination
    assert "restart:" in active_combination
    assert "|| true" not in active_combination
    assert "if ! remaining=$(docker ps -aq --filter" in active_combination
    assert "elif [[ -n $remaining ]]" in active_combination
    assert "log_scan_status=$?" in active_combination
    assert "for candidate in llama nemotron; do" in script

    capture_logs = script.split("capture_logs() {", maxsplit=1)[1].split(
        "probe_bge_access() {", maxsplit=1
    )[0]
    assert "|| true" not in capture_logs


def test_help_exits_zero_without_claiming_evidence_or_running_exit_cleanup(
    tmp_path: Path,
) -> None:
    evidence_root = tmp_path / "evidence"
    result = run_acceptance(
        "--help",
        environment={
            "PHASE3_EVIDENCE_ROOT": str(evidence_root),
            "PHASE3_RUN_ID": "help-only",
        },
    )

    assert result.returncode == 0
    assert "Usage:" in result.stdout
    assert not evidence_root.exists()


def test_preexisting_project_container_is_refused_without_cleanup_or_mutation(
    tmp_path: Path,
) -> None:
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    docker_log = tmp_path / "docker.log"
    fake_docker = fake_bin / "docker"
    fake_docker.write_text(
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        'printf \'%s\\n\' "$*" >>"$PHASE3_TEST_DOCKER_LOG"\n'
        "if [[ $1 == ps && $2 == -aq ]]; then\n"
        "  printf 'preexisting-container-id\\n'\n"
        "  exit 0\n"
        "fi\n"
        "exit 97\n",
        encoding="utf-8",
    )
    fake_docker.chmod(0o700)
    evidence_root = tmp_path / "evidence"
    run_id = "preexisting-refusal"

    result = run_acceptance(
        environment={
            "PATH": f"{fake_bin}:{os.environ['PATH']}",
            "PHASE3_TEST_DOCKER_LOG": str(docker_log),
            "PHASE3_EVIDENCE_ROOT": str(evidence_root),
            "PHASE3_RUN_ID": run_id,
        }
    )

    assert result.returncode != 0
    commands = docker_log.read_text(encoding="utf-8").splitlines()
    assert len(commands) == 1
    assert commands[0].startswith("ps -aq --filter")
    assert all(not command.startswith("compose ") for command in commands)

    summary = json.loads((evidence_root / run_id / "summary.json").read_text(encoding="utf-8"))
    assert summary["phase"] == 3
    assert summary["result"] == "failed"
    assert summary["current_step"] == "preexisting-container-gate"
    assert summary["cache_volumes_preserved"] is None
    assert summary["cleanup"]["status"] == "pass"
    assert summary["phase4_started"] is False
    assert summary["secrets_persisted"] is False
    assert summary["decision_gates"]["phase3_complete"] is False
    assert summary["decision_gates"]["llm_winner"] == "not_selected_human_review_pending"
    assert summary["metric_scope"]["master_backend_receive_ttft_measured"] is False
    assert summary["execution"] == [
        {
            "item": "preexisting-container-gate",
            "status": "fail",
            "evidence": "docker project label query",
        }
    ]


def test_existing_evidence_run_is_never_overwritten(tmp_path: Path) -> None:
    evidence_root = tmp_path / "evidence"
    run_dir = evidence_root / "already-exists"
    run_dir.mkdir(parents=True)
    sentinel = run_dir / "summary.json"
    sentinel.write_text('{"owned_by":"operator"}\n', encoding="utf-8")

    result = run_acceptance(
        environment={
            "PHASE3_EVIDENCE_ROOT": str(evidence_root),
            "PHASE3_RUN_ID": "already-exists",
        }
    )

    assert result.returncode != 0
    assert "already exists or cannot be created" in result.stderr
    assert sentinel.read_text(encoding="utf-8") == '{"owned_by":"operator"}\n'
    assert list(run_dir.iterdir()) == [sentinel]

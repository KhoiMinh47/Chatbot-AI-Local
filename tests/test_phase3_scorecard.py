from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPOSITORY_ROOT))

from scripts.phase3_scorecard import (  # noqa: E402
    CANDIDATE_POLICIES,
    EXPECTED_LLM_METRIC_DEFINITIONS,
    EXPECTED_LLM_PROMPT_UNIQUENESS_CONTROL,
    LLM_SCENARIO_POLICIES,
    LLM_WEIGHTS,
    RETRIEVAL_WEIGHTS,
    build_scorecard,
    main,
)

MEASURED_REQUESTS = 20
WARMUP_REQUESTS = 2


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")


def _output_gate(max_output: int, *, status: str = "pass") -> dict[str, object]:
    measured_matching = MEASURED_REQUESTS if status == "pass" else MEASURED_REQUESTS - 1
    return {
        "status": status,
        "required_relation": "completion_tokens_actual_equals_max_output_tokens",
        "target_completion_tokens": max_output,
        "fixed_request_control": {
            "ignore_eos": True,
            "scope": "synthetic_llm_benchmark_only",
        },
        "measured": {
            "required_count": MEASURED_REQUESTS,
            "observed_count": MEASURED_REQUESTS,
            "matching_count": measured_matching,
            "observed_min": max_output if status == "pass" else max_output - 1,
            "observed_max": max_output,
        },
        "warmup": {
            "required_count": WARMUP_REQUESTS,
            "observed_count": WARMUP_REQUESTS,
            "matching_count": WARMUP_REQUESTS,
            "observed_min": max_output,
            "observed_max": max_output,
        },
    }


def _input_gate(name: str) -> dict[str, object]:
    policy = LLM_SCENARIO_POLICIES[name]
    prompt_tokens = policy.target_input_tokens
    observed_context = prompt_tokens + policy.max_output_tokens
    is_long = policy.target_context_tokens is not None
    return {
        "status": "pass",
        "required_relation": (
            "every_observed_prompt_plus_max_output_within_absolute_context_window"
            if is_long
            else "every_observed_prompt_within_target_ratio"
        ),
        "target_input_tokens": policy.target_input_tokens,
        "target_context_tokens": policy.target_context_tokens,
        "observed_prompt_tokens_min": prompt_tokens,
        "observed_prompt_tokens_max": prompt_tokens,
        "max_output_tokens": policy.max_output_tokens,
        "observed_prompt_plus_max_output_min": observed_context,
        "observed_prompt_plus_max_output_max": observed_context,
        "absolute_context_lower_bound": (policy.target_context_tokens - 512 if is_long else None),
        "absolute_context_upper_bound": policy.target_context_tokens,
        "minimum_ratio": None if is_long else 0.8,
        "maximum_ratio": None if is_long else 1.2,
    }


def _distribution(p50: float, p95: float) -> dict[str, object]:
    return {
        "observed_count": MEASURED_REQUESTS,
        "p50": p50,
        "p95": p95,
    }


def _llm_scenario(
    name: str,
    *,
    ttft: float,
    decode: float,
    output_status: str = "pass",
) -> dict[str, object]:
    policy = LLM_SCENARIO_POLICIES[name]
    prompt_tokens = float(policy.target_input_tokens)
    completion_tokens = float(policy.max_output_tokens)
    total_tokens = prompt_tokens + completion_tokens
    return {
        "name": name,
        "summary": {
            "status": "pass" if output_status == "pass" else "fail",
            "request_count": MEASURED_REQUESTS,
            "success_count": MEASURED_REQUESTS,
            "failure_count": 0,
            "warmup_failure_count": 0,
            "warmup_required_count": WARMUP_REQUESTS,
            "target_input_tokens": policy.target_input_tokens,
            "target_context_tokens": policy.target_context_tokens,
            "max_output_tokens": policy.max_output_tokens,
            "concurrency": policy.concurrency,
            "input_token_target_check": _input_gate(name),
            "output_token_target_check": _output_gate(
                policy.max_output_tokens, status=output_status
            ),
            "prompt_tokens_actual": _distribution(prompt_tokens, prompt_tokens),
            "completion_tokens_actual": _distribution(completion_tokens, completion_tokens),
            "total_tokens_actual": _distribution(total_tokens, total_tokens),
            "ttft_seconds": _distribution(ttft, ttft * 1.2),
            "decode_duration_seconds": _distribution(
                completion_tokens / decode,
                completion_tokens / decode * 1.1,
            ),
            "decode_tokens_per_second": _distribution(decode, decode * 1.1),
            "total_latency_seconds": _distribution(
                ttft + completion_tokens / decode,
                (ttft + completion_tokens / decode) * 1.2,
            ),
        },
    }


def _llm_benchmark(
    candidate: str,
    *,
    ttft: float,
    decode: float,
    output_status: str = "pass",
) -> dict[str, object]:
    policy = CANDIDATE_POLICIES[candidate]
    return {
        "schema_version": 2,
        "status": "pass" if output_status == "pass" else "fail",
        "kind": "llm",
        "candidate": {
            "candidate_id": candidate,
            "requested_model_id": policy.model,
            "image_ref": {"value": policy.image_ref},
            "image_digest": {"value": policy.image_digest},
            "license_id": {"value": policy.license_declaration},
        },
        "contract_check": {"status": "pass"},
        "metadata_completeness": {
            "status": "complete",
            "unverified_or_missing_fields": [],
        },
        "runtime": {
            "nim_version": {"value": policy.version},
            "profile": {"value": policy.profile},
            "precision": {"value": policy.precision},
            "max_model_length": {"value": policy.max_model_length},
            "served_model_id": {"value": policy.model},
        },
        "run_config": {
            "measured_requests_per_scenario": MEASURED_REQUESTS,
            "warmup_requests_per_scenario": WARMUP_REQUESTS,
            "measured_runtime_state": "warm_after_runner_warmup",
            "metrics_required": True,
            "long_context_opt_in": True,
            "reasoning_control_mode": policy.reasoning_control_mode,
            "llm_prompt_uniqueness_control": dict(EXPECTED_LLM_PROMPT_UNIQUENESS_CONTROL),
            "system_prompt_persisted": False,
            "base_url_persisted": False,
            "credentials_persisted": False,
        },
        "metric_definitions": dict(EXPECTED_LLM_METRIC_DEFINITIONS),
        "scenarios": [
            _llm_scenario(
                name,
                ttft=ttft,
                decode=decode,
                output_status=output_status,
            )
            for name in LLM_SCENARIO_POLICIES
        ],
    }


def _quality(
    candidate: str,
    *,
    human_status: str = "pending",
    secret: str | None = None,
) -> dict[str, object]:
    policy = CANDIDATE_POLICIES[candidate]
    result: dict[str, object] = {
        "schema_version": 2,
        "status": "completed",
        "candidate": {
            "candidate_id": candidate,
            "model_id_configured": policy.model,
            "image_ref": policy.image_ref,
            "image_digest": policy.image_digest,
            "license_id": policy.license_declaration,
        },
        "runtime": {
            "nim_version": policy.version,
            "profile": policy.profile,
            "precision": policy.precision,
            "max_model_length": policy.max_model_length,
            "response_models_observed": [policy.model],
        },
        "generation": {
            "reasoning_control_mode": policy.reasoning_control_mode,
        },
        "component_scores": {
            "correctness": 0.8,
            "faithfulness_citation": 0.7,
            "instruction_following": 0.9,
        },
        "language_scores": {
            "vi": {"correctness": 0.9},
            "en": {"correctness": 0.7},
        },
        "automatic_hard_gate": {"status": "passed"},
        "human_review": {"required": True, "status": human_status},
    }
    if secret is not None:
        result["cases"] = [{"safe_generated_answer": secret, "question": secret}]
        result["unknown_secret_field"] = secret
    return result


def _runtime(candidate: str) -> dict[str, object]:
    policy = CANDIDATE_POLICIES[candidate]
    return {
        "candidate": candidate,
        "active_runtime_profile": {
            "value": policy.profile,
            "evidence_source": "exact-live-profile",
            "live_runtime_verified": True,
        },
    }


def _license(candidate: str) -> dict[str, object]:
    policy = CANDIDATE_POLICIES[candidate]
    return {
        "license_id": policy.license_declaration,
        "evidence_source": "reviewed-model-card-and-live-endpoint",
    }


def _runtime_verification(candidate: str) -> dict[str, object]:
    policy = CANDIDATE_POLICIES[candidate]
    return {
        "schema_version": 1,
        "phase": 3,
        "candidate": candidate,
        "status": "pass",
        "checks": {
            "expectations_allowlisted": True,
            "required_http_statuses": True,
            "served_model_exact": True,
            "nim_version_exact": True,
            "selected_profile_exact": True,
            "precision_from_closed_allowlist": True,
            "arm64_image_container_identity": True,
            "live_license_sha_content_consistent": True,
            "operator_license_declaration_allowlisted": True,
        },
        "expected_identity": {
            "model": policy.model,
            "nim_version": policy.version,
            "profile_id": policy.profile,
            "precision": policy.precision,
            "image_digest": policy.image_digest,
        },
        "runtime_identity": {
            "served_model": policy.model,
            "nim_version": policy.version,
            "selected_profile_id": policy.profile,
            "precision": policy.precision,
            "image_repository": policy.image_repository,
            "image_digest": policy.image_digest,
            "architecture": "arm64",
            "operating_system": "linux",
        },
        "max_model_length": {"value": policy.max_model_length},
        "live_nim_license": {
            "content_sha_algorithm": "sha1",
            "content_sha": "c" * 40,
            "term_names": [
                f"Reviewed live term {index}"
                for index, _ in enumerate(policy.live_license_term_urls)
            ],
            "term_urls": sorted(policy.live_license_term_urls),
            "content_persisted_in_output": False,
            "metadata_and_license_endpoint_consistent": True,
        },
        "operator_reviewed_model_terms": {
            "declaration_name": policy.license_declaration,
            "model_license_names": list(policy.model_license_names),
            "additional_term_names": list(policy.additional_term_names),
            "separate_from_live_nim_license": True,
            "legal_approval": "pending",
        },
    }


def _combination(candidate: str, *, status: str = "pass") -> dict[str, object]:
    check_status = "pass" if status == "pass" else "fail"
    return {
        "status": status,
        "scope": {
            "llm_candidate": candidate,
            "candidates": [candidate, "embedding-300m", "reranking-500m"],
            "concurrent_smoke": True,
            "concurrent_bounded_load": True,
            "llm_load_requirement": "core matrix includes rag-8k-c4 at concurrency 4",
            "measured_requests_per_scenario": 4,
            "warmup_requests_per_scenario": 1,
        },
        "checks": {
            "no_oom": {"status": check_status},
            "load": {"status": check_status},
            "restart": {"status": check_status},
            "health": {"status": check_status},
            "telemetry": {"status": check_status},
            "logs": {"status": check_status},
            "cleanup": {"status": check_status},
        },
    }


def _write_llm_candidate(
    run_dir: Path,
    candidate: str,
    *,
    ttft: float,
    decode: float,
    output_status: str = "pass",
    human_status: str = "pending",
    secret: str | None = None,
) -> None:
    root = run_dir / "candidates" / candidate
    _write_json(
        root / "benchmark/report.json",
        _llm_benchmark(
            candidate,
            ttft=ttft,
            decode=decode,
            output_status=output_status,
        ),
    )
    _write_json(
        root / "quality/report.json",
        _quality(candidate, human_status=human_status, secret=secret),
    )
    _write_json(root / "runtime-verification.json", _runtime_verification(candidate))
    _write_json(root / "runtime-declaration.json", _runtime(candidate))
    _write_json(root / "license.json", _license(candidate))
    _write_json(
        run_dir / "combinations" / candidate / "result.json",
        _combination(candidate),
    )


def _retriever_benchmark(candidate: str) -> dict[str, object]:
    policy = CANDIDATE_POLICIES[candidate]
    names = (
        ("embedding-batch-1", "embedding-batch-16")
        if candidate == "embedding-300m"
        else ("reranking-passages-2", "reranking-passages-16")
    )
    return {
        "schema_version": 2,
        "status": "pass",
        "kind": "embedding" if candidate == "embedding-300m" else "reranking",
        "candidate": {
            "candidate_id": candidate,
            "requested_model_id": policy.model,
            "image_ref": {"value": policy.image_ref},
            "image_digest": {"value": policy.image_digest},
            "license_id": {"value": policy.license_declaration},
        },
        "runtime": {
            "served_model_id": {"value": policy.model},
            "nim_version": {"value": policy.version},
            "profile": {"value": policy.profile},
            "precision": {"value": policy.precision},
            "max_model_length": {"value": policy.max_model_length},
        },
        "run_config": {"reasoning_control_mode": None},
        "contract_check": {"status": "pass"},
        "metadata_completeness": {"status": "complete"},
        "semantic_check": {"status": "pass"},
        "scenarios": [
            {
                "name": name,
                "summary": {"total_latency_seconds": {"p50": 0.01, "p95": 0.02}},
            }
            for name in names
        ],
    }


def _write_retrieval_evidence(run_dir: Path) -> None:
    for candidate in ("embedding-300m", "reranking-500m"):
        root = run_dir / "candidates" / candidate
        _write_json(root / "benchmark/report.json", _retriever_benchmark(candidate))
        _write_json(root / "runtime-verification.json", _runtime_verification(candidate))
        _write_json(root / "runtime-declaration.json", _runtime(candidate))
        _write_json(root / "license.json", _license(candidate))
    _write_json(
        run_dir / "bge-m3-access.json",
        {
            "live_authenticated_token_scope_probe": {"http_status": 402},
            "exact_pinned_image_selected": False,
            "acceptance_effect": "blocked",
        },
    )


def _complete_run(run_dir: Path, *, secret: str | None = None) -> None:
    run_dir.mkdir(parents=True)
    _write_llm_candidate(run_dir, "llama", ttft=1.0, decode=10.0, secret=secret)
    _write_llm_candidate(run_dir, "nemotron", ttft=2.0, decode=5.0)
    _write_retrieval_evidence(run_dir)


def test_schema_v2_has_exact_weights_provisional_totals_and_no_human_pending_winner(
    tmp_path: Path,
) -> None:
    secret = "do-not-copy-source-content"
    run_dir = tmp_path / "run"
    _complete_run(run_dir, secret=secret)

    scorecard = build_scorecard(run_dir)

    assert scorecard["schema_version"] == 2
    assert scorecard["weights"] == {
        "llm": LLM_WEIGHTS,
        "retrieval": RETRIEVAL_WEIGHTS,
    }
    assert sum(LLM_WEIGHTS.values()) == pytest.approx(1.0)
    assert sum(RETRIEVAL_WEIGHTS.values()) == pytest.approx(1.0)
    llm = scorecard["llm_scorecard"]
    candidates = llm["candidates"]
    llama = candidates["llama"]
    nemotron = candidates["nemotron"]
    assert set(llama["components"]) == set(LLM_WEIGHTS)
    assert set(llama["quality"]["components"]) == {
        "correctness_vi_en",
        "faithfulness_and_citation",
        "rag_instruction_following",
    }
    assert llama["components"]["correctness_vi_en"]["score"] == 0.8
    assert llama["components"]["ttft_and_decode_throughput"]["score"] == 1.0
    assert nemotron["components"]["ttft_and_decode_throughput"]["score"] == 0.5
    assert llama["components"]["memory_and_concurrency"]["score"] == 1.0
    assert llama["components"]["operations_license_nim_compatibility"]["score"] == 1.0
    assert llama["provisional_weighted_total"] == {
        "status": "automatic_provisional",
        "score": 0.865,
        "partial_weighted_points": 0.865,
        "weight_coverage": 1.0,
        "automatic_only": True,
        "eligible_for_winner": False,
        "decision_blockers": ["human_review_pending", "legal_approval_pending"],
    }
    assert llm["selection"]["status"] == "not_selected"
    assert llm["selection"]["winner_candidate_id"] is None
    assert scorecard["decision"]["phase3_winner_claimed"] is False
    assert llama["operations_license_nim_compatibility"]["legal_approval"]["status"] == "pending"
    serialized = json.dumps(scorecard)
    assert secret not in serialized
    assert "safe_generated_answer" not in serialized


def test_missing_evidence_is_pending_without_fake_total_or_winner(tmp_path: Path) -> None:
    run_dir = tmp_path / "empty-run"
    run_dir.mkdir()

    scorecard = build_scorecard(run_dir)

    for candidate in ("llama", "nemotron"):
        result = scorecard["llm_scorecard"]["candidates"][candidate]
        assert all(component["score"] is None for component in result["components"].values())
        assert result["provisional_weighted_total"]["score"] is None
        assert result["provisional_weighted_total"]["weight_coverage"] == 0.0
    retrieval = scorecard["retrieval_scorecard"]
    embedding = retrieval["embedding_comparison"]
    assert embedding["selection"]["winner_candidate_id"] is None
    assert embedding["candidates"]["bge-m3"]["evidence"]["access"] == {
        "source_status": "missing",
        "access_status": "pending",
        "http_status": None,
        "exact_pinned_runtime_available": False,
    }


def test_malformed_evidence_is_safely_projected_as_pending(tmp_path: Path) -> None:
    run_dir = tmp_path / "malformed-run"
    (run_dir / "candidates/llama/quality").mkdir(parents=True)
    (run_dir / "candidates/llama/quality/report.json").write_text(
        "{not-json secret-value", encoding="utf-8"
    )
    _write_json(run_dir / "candidates/llama/benchmark/report.json", ["not", "object"])
    _write_json(
        run_dir / "combinations/llama/result.json",
        {"status": "pass", "checks": {"no_oom": {"status": "secret-value"}}},
    )

    scorecard = build_scorecard(run_dir)

    llama = scorecard["llm_scorecard"]["candidates"]["llama"]
    assert llama["quality"]["source_status"] == "invalid"
    assert llama["performance"]["comparison_status"] == "pending"
    assert llama["memory_and_concurrency"]["combination_evidence_status"] == "invalid"
    assert llama["provisional_weighted_total"]["score"] is None
    assert "secret-value" not in json.dumps(scorecard)


def test_relative_performance_stays_pending_with_only_one_comparable_candidate(
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "noncomparable-run"
    run_dir.mkdir()
    _write_llm_candidate(run_dir, "llama", ttft=1.0, decode=10.0)

    scorecard = build_scorecard(run_dir)

    candidates = scorecard["llm_scorecard"]["candidates"]
    llama = candidates["llama"]
    nemotron = candidates["nemotron"]
    assert llama["performance"]["reason"] == "insufficient_comparable_candidates"
    assert llama["components"]["ttft_and_decode_throughput"]["score"] is None
    assert nemotron["performance"]["reason"] == "benchmark_missing"
    assert nemotron["components"]["ttft_and_decode_throughput"]["score"] is None


@pytest.mark.parametrize(
    "mutation",
    ["old-schema", "candidate-mismatch"],
    ids=("old-schema", "candidate-mismatch"),
)
def test_performance_requires_schema_v2_and_exact_candidate_identity(
    tmp_path: Path, mutation: str
) -> None:
    run_dir = tmp_path / "identity-run"
    run_dir.mkdir()
    _write_llm_candidate(run_dir, "llama", ttft=1.0, decode=10.0)
    _write_llm_candidate(run_dir, "nemotron", ttft=2.0, decode=5.0)
    report_path = run_dir / "candidates/nemotron/benchmark/report.json"
    report = json.loads(report_path.read_text(encoding="utf-8"))
    if mutation == "old-schema":
        report["schema_version"] = 1
    else:
        report["candidate"]["candidate_id"] = "wrong-candidate"
    _write_json(report_path, report)

    scorecard = build_scorecard(run_dir)

    candidates = scorecard["llm_scorecard"]["candidates"]
    assert candidates["nemotron"]["performance"]["reason"] == (
        "exact_candidate_identity_binding_failed_or_pending"
    )
    assert candidates["llama"]["performance"]["reason"] == ("insufficient_comparable_candidates")


def test_output_token_gate_failure_makes_both_relative_scores_noncomparable(
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "output-gate-run"
    run_dir.mkdir()
    _write_llm_candidate(run_dir, "llama", ttft=1.0, decode=10.0)
    _write_llm_candidate(
        run_dir,
        "nemotron",
        ttft=2.0,
        decode=5.0,
        output_status="fail",
    )

    scorecard = build_scorecard(run_dir)

    candidates = scorecard["llm_scorecard"]["candidates"]
    assert candidates["llama"]["performance"]["reason"] == ("insufficient_comparable_candidates")
    assert candidates["nemotron"]["performance"]["reason"] == "canonical_six_scenario_gate_failed"
    assert (
        candidates["nemotron"]["performance"]["core_scenarios"]["rag-8k-c1"][
            "output_token_target_gate"
        ]
        == "fail"
    )
    assert all(
        candidate["components"]["ttft_and_decode_throughput"]["score"] is None
        for candidate in candidates.values()
    )
    assert scorecard["llm_scorecard"]["selection"]["winner_candidate_id"] is None


def test_retrieval_scorecard_keeps_phase5_metrics_and_bge_blocker_pending(
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "retrieval-run"
    run_dir.mkdir()
    _write_retrieval_evidence(run_dir)

    scorecard = build_scorecard(run_dir)

    retrieval = scorecard["retrieval_scorecard"]
    assert retrieval["status"] == "pending_phase5_metrics_and_bge_runtime"
    embedding = retrieval["embedding_comparison"]
    reranking = retrieval["reranking_evaluation"]
    retrieval_candidates = {
        **embedding["candidates"],
        **reranking["candidates"],
    }
    for candidate in ("embedding-300m", "bge-m3", "reranking-500m"):
        result = retrieval_candidates[candidate]
        assert set(result["components"]) == set(RETRIEVAL_WEIGHTS)
        assert all(component["score"] is None for component in result["components"].values())
        assert result["provisional_weighted_total"]["score"] is None
    embed_engine = embedding["candidates"]["embedding-300m"]["evidence"]["engine"]
    assert embed_engine["benchmark_status"] == "pass"
    assert len(embed_engine["latency_observations"]) == 2
    assert embed_engine["live_runtime_identity_verified"] is True
    assert embed_engine["reviewed_license_evidence_verified"] is True
    assert embed_engine["phase5_retrieval_quality_claimed"] is False
    bge = embedding["candidates"]["bge-m3"]["evidence"]["access"]
    assert bge["access_status"] == "blocked"
    assert bge["http_status"] == 402
    assert embedding["selection"]["winner_candidate_id"] is None
    assert reranking["selection"]["winner_candidate_id"] is None
    assert "reranking-500m" not in embedding["candidates"]


def test_runtime_verification_requires_all_identity_and_license_fields(
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "runtime-verification-run"
    _complete_run(run_dir)
    verification_path = run_dir / "candidates/llama/runtime-verification.json"
    verification = json.loads(verification_path.read_text(encoding="utf-8"))
    verification["live_nim_license"]["term_names"] = []
    _write_json(verification_path, verification)

    scorecard = build_scorecard(run_dir)

    llama = scorecard["llm_scorecard"]["candidates"]["llama"]
    operations = llama["operations_license_nim_compatibility"]
    assert operations["checks"]["license_evidence_matches"] == "fail"
    assert operations["legal_approval"]["status"] == "pending"
    assert llama["components"]["operations_license_nim_compatibility"]["score"] is None
    assert llama["provisional_weighted_total"]["eligible_for_winner"] is False


def test_reduced_workload_and_metric_definition_drift_cannot_be_scored(
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "reduced-run"
    _complete_run(run_dir)
    benchmark_path = run_dir / "candidates/llama/benchmark/report.json"
    benchmark = json.loads(benchmark_path.read_text(encoding="utf-8"))
    benchmark["run_config"]["measured_requests_per_scenario"] = 1
    benchmark["metric_definitions"]["scope"] = "incorrect-backend-ttft-claim"
    _write_json(benchmark_path, benchmark)

    scorecard = build_scorecard(run_dir)

    llama = scorecard["llm_scorecard"]["candidates"]["llama"]
    assert llama["performance"]["reason"] == ("canonical_benchmark_metadata_or_workload_invalid")
    assert llama["components"]["ttft_and_decode_throughput"]["score"] is None


def test_reused_llm_prompts_cannot_enter_performance_score(tmp_path: Path) -> None:
    run_dir = tmp_path / "reused-prompt-run"
    _complete_run(run_dir)
    benchmark_path = run_dir / "candidates/llama/benchmark/report.json"
    benchmark = json.loads(benchmark_path.read_text(encoding="utf-8"))
    benchmark["run_config"]["llm_prompt_uniqueness_control"][
        "full_user_prompt_reuse_between_requests"
    ] = True
    _write_json(benchmark_path, benchmark)

    scorecard = build_scorecard(run_dir)

    llama = scorecard["llm_scorecard"]["candidates"]["llama"]
    assert llama["performance"]["reason"] == ("exact_candidate_identity_binding_failed_or_pending")
    assert llama["components"]["ttft_and_decode_throughput"]["score"] is None


def test_exact_six_scenario_matrix_including_128k_is_required(tmp_path: Path) -> None:
    run_dir = tmp_path / "missing-long-run"
    _complete_run(run_dir)
    benchmark_path = run_dir / "candidates/nemotron/benchmark/report.json"
    benchmark = json.loads(benchmark_path.read_text(encoding="utf-8"))
    benchmark["scenarios"] = [
        scenario for scenario in benchmark["scenarios"] if scenario["name"] != "long-128k-c1"
    ]
    _write_json(benchmark_path, benchmark)

    scorecard = build_scorecard(run_dir)

    nemotron = scorecard["llm_scorecard"]["candidates"]["nemotron"]
    assert nemotron["performance"]["reason"] == "exact_six_scenario_matrix_invalid"
    assert nemotron["components"]["ttft_and_decode_throughput"]["score"] is None


def test_combination_requires_exact_scope_and_all_seven_checks(tmp_path: Path) -> None:
    run_dir = tmp_path / "combination-run"
    _complete_run(run_dir)
    result_path = run_dir / "combinations/llama/result.json"
    result = json.loads(result_path.read_text(encoding="utf-8"))
    del result["checks"]["telemetry"]
    _write_json(result_path, result)

    scorecard = build_scorecard(run_dir)

    llama = scorecard["llm_scorecard"]["candidates"]["llama"]
    assert llama["memory_and_concurrency"]["combination_evidence_status"] == "invalid"
    assert llama["components"]["memory_and_concurrency"]["score"] is None


def test_retrieval_engine_evidence_rejects_cross_candidate_artifact(
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "retrieval-identity-run"
    run_dir.mkdir()
    _write_retrieval_evidence(run_dir)
    benchmark_path = run_dir / "candidates/embedding-300m/benchmark/report.json"
    benchmark = json.loads(benchmark_path.read_text(encoding="utf-8"))
    benchmark["candidate"]["candidate_id"] = "reranking-500m"
    _write_json(benchmark_path, benchmark)

    scorecard = build_scorecard(run_dir)

    engine = scorecard["retrieval_scorecard"]["embedding_comparison"]["candidates"][
        "embedding-300m"
    ]["evidence"]["engine"]
    assert engine["benchmark_status"] == "pending"
    assert engine["latency_observations"] == []
    assert engine["identity_binding"]["status"] == "fail"


def test_runtime_repository_identity_is_candidate_bound(tmp_path: Path) -> None:
    run_dir = tmp_path / "runtime-repository-run"
    _complete_run(run_dir)
    verification_path = run_dir / "candidates/llama/runtime-verification.json"
    verification = json.loads(verification_path.read_text(encoding="utf-8"))
    verification["runtime_identity"]["image_repository"] = CANDIDATE_POLICIES[
        "nemotron"
    ].image_repository
    _write_json(verification_path, verification)

    scorecard = build_scorecard(run_dir)

    llama = scorecard["llm_scorecard"]["candidates"]["llama"]
    assert (
        llama["operations_license_nim_compatibility"]["checks"]["live_exact_runtime_profile"]
        == "fail"
    )
    assert llama["components"]["operations_license_nim_compatibility"]["score"] is None


def test_cli_writes_atomically_and_refuses_to_replace_existing_output(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    run_dir = tmp_path / "run"
    _complete_run(run_dir)
    output = tmp_path / "scorecard.json"

    assert main(["--run-dir", str(run_dir), "--output", str(output)]) == 0
    first = output.read_bytes()
    assert json.loads(first)["schema_version"] == 2
    assert main(["--run-dir", str(run_dir), "--output", str(output)]) == 1

    captured = capsys.readouterr()
    assert "output_already_exists" in captured.err
    assert output.read_bytes() == first
    assert not list(tmp_path.glob(".scorecard.json.tmp-*"))


def test_cli_rejects_missing_run_directory_without_traceback(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    output = tmp_path / "scorecard.json"

    result = main(["--run-dir", str(tmp_path / "absent"), "--output", str(output)])

    captured = capsys.readouterr()
    assert result == 1
    assert "run_directory_invalid" in captured.err
    assert "Traceback" not in captured.err
    assert not output.exists()

#!/usr/bin/env python3
"""Build a fail-closed Phase 3 model scorecard from allowlisted evidence fields.

The scorecard is deliberately decision-support evidence, not an automatic model
selector. It never copies prompts, generated answers, response bodies, URLs, or
arbitrary error text from source artifacts into its output.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import re
import sys
import tempfile
from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal, cast

SCHEMA_VERSION = 2
MAX_EVIDENCE_BYTES = 16 * 1024 * 1024
LLM_CANDIDATES = ("llama", "nemotron")
CORE_LLM_SCENARIOS = ("engine-short-c1", "rag-8k-c1", "rag-8k-c4")

LLM_WEIGHTS: dict[str, float] = {
    "correctness_vi_en": 0.25,
    "faithfulness_and_citation": 0.25,
    "rag_instruction_following": 0.10,
    "ttft_and_decode_throughput": 0.20,
    "memory_and_concurrency": 0.10,
    "operations_license_nim_compatibility": 0.10,
}
RETRIEVAL_WEIGHTS: dict[str, float] = {
    "recall_at_10": 0.30,
    "mrr_at_10": 0.20,
    "ndcg_at_10": 0.15,
    "vietnamese_and_tables": 0.15,
    "latency_and_throughput": 0.10,
    "memory_and_operations": 0.10,
}

_SHA256_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
_PROFILE_ID = re.compile(r"^[0-9a-f]{64}$")
_LICENSE_SHA1 = re.compile(r"^[0-9a-f]{40}$")
_RUNTIME_CHECK_NAMES = (
    "expectations_allowlisted",
    "required_http_statuses",
    "served_model_exact",
    "nim_version_exact",
    "selected_profile_exact",
    "precision_from_closed_allowlist",
    "arm64_image_container_identity",
    "live_license_sha_content_consistent",
    "operator_license_declaration_allowlisted",
)

EXPECTED_LLM_METRIC_DEFINITIONS: dict[str, str] = {
    "ttft_seconds": (
        "client timestamp immediately before HTTP request dispatch to first non-empty "
        "streamed generated-token delta (content or reasoning_content)"
    ),
    "decode_duration_seconds": (
        "first non-empty streamed generated-token delta to last non-empty generated-token "
        "delta; content and reasoning_content are timed but never persisted"
    ),
    "decode_tokens_per_second": (
        "response-reported completion_tokens divided by decode_duration_seconds"
    ),
    "total_latency_seconds": "request start to HTTP stream completion",
    "token_counts": "actual response usage only; missing usage is a failed LLM measurement",
    "long_context_targets": (
        "32K/64K/128K are total-context capability targets; synthetic input reserves max "
        "output plus 256 tokens for chat-template safety"
    ),
    "scope": (
        "client-observed engine HTTP latency, measured immediately before request dispatch; "
        "not server/backend receive time and not auth/retrieval/rerank/end-to-end "
        "application latency"
    ),
    "input_token_target_check": (
        "every response-reported prompt-token count must stay within 80-120% for short/RAG "
        "scenarios; for long-context capability scenarios every observed prompt_tokens plus "
        "max_output_tokens must be between target_context_tokens minus 512 and "
        "target_context_tokens inclusive"
    ),
    "output_token_target_check": (
        "synthetic LLM benchmark requests use the fixed non-configurable ignore_eos=true "
        "control, and every warmup and measured response-reported completion_tokens count "
        "must exactly equal the scenario max_output_tokens; this control is not used by "
        "smoke or quality requests"
    ),
    "prompt_uniqueness_control": (
        "every LLM warmup and measured request uses a deterministic SHA-256 nonce "
        "derived from scenario, request phase, and request index as the first "
        "user-content line before synthetic context; warmup and measured namespaces "
        "are disjoint, full user prompts are not reused, and nonce values are never "
        "persisted"
    ),
}

EXPECTED_LLM_PROMPT_UNIQUENESS_CONTROL: dict[str, object] = {
    "status": "enabled",
    "nonce_position": "first_user_content_line_before_synthetic_context",
    "nonce_derivation": "sha256(scenario_name|request_phase|request_index)",
    "warmup_and_measured_namespaces_disjoint": True,
    "full_user_prompt_reuse_between_requests": False,
    "nonce_persisted": False,
}

EvidenceStatus = Literal["present", "missing", "invalid"]
GateState = bool | None


@dataclass(frozen=True, slots=True)
class CandidatePolicy:
    kind: str
    model: str
    image_repository: str
    image_ref: str
    image_digest: str
    profile: str
    version: str
    precision: str
    max_model_length: int
    license_declaration: str
    live_license_term_urls: frozenset[str]
    model_license_names: tuple[str, ...]
    additional_term_names: tuple[str, ...]
    reasoning_control_mode: str | None


@dataclass(frozen=True, slots=True)
class LlmScenarioPolicy:
    target_input_tokens: int
    max_output_tokens: int
    concurrency: int
    target_context_tokens: int | None


CANDIDATE_POLICIES: dict[str, CandidatePolicy] = {
    "llama": CandidatePolicy(
        kind="llm",
        model="meta/llama-3.1-8b-instruct",
        image_repository="nvcr.io/nim/meta/llama-3.1-8b-instruct",
        image_ref=(
            "nvcr.io/nim/meta/llama-3.1-8b-instruct:2.0.6@"
            "sha256:31e360dbb15f825d69e5d68c2032e334301523b4957091270385ed7ef3db5e81"
        ),
        image_digest=("sha256:31e360dbb15f825d69e5d68c2032e334301523b4957091270385ed7ef3db5e81"),
        profile="c4789f7af56c770c1c88b73da666886365534d6980b6b922b41fd97036c77d73",
        version="2.0.6",
        precision="FP8",
        max_model_length=131_072,
        license_declaration="llama-3.1-community-license-and-nvidia-nim-terms",
        live_license_term_urls=frozenset(
            {
                "https://www.nvidia.com/en-us/agreements/enterprise-software/"
                "nvidia-software-license-agreement",
                "https://www.nvidia.com/en-us/agreements/enterprise-software/"
                "product-specific-terms-for-ai-products",
                "https://www.nvidia.com/en-us/agreements/enterprise-software/"
                "nvidia-open-model-license",
            }
        ),
        model_license_names=("Llama 3.1 Community License Agreement",),
        additional_term_names=(
            "NVIDIA Software License Agreement",
            "Product-Specific Terms for AI Products",
            "NVIDIA Open Model License Agreement",
        ),
        reasoning_control_mode="llama-standard",
    ),
    "nemotron": CandidatePolicy(
        kind="llm",
        model="nvidia/nemotron-nano-9b-v2",
        image_repository=("nvcr.io/nim/nvidia/nvidia-nemotron-nano-9b-v2-dgx-spark"),
        image_ref=(
            "nvcr.io/nim/nvidia/nvidia-nemotron-nano-9b-v2-dgx-spark:1.0.0-variant@"
            "sha256:82028e38ab950edd32f5053ca2030ee14d965e8fd4fe1c6e06468eb0be07a9a4"
        ),
        image_digest=("sha256:82028e38ab950edd32f5053ca2030ee14d965e8fd4fe1c6e06468eb0be07a9a4"),
        profile="f9db61d5a467d46be7733e90a26705798764b93d480c842143d525c1932b01e2",
        version="1.0.0",
        precision="NVFP4",
        max_model_length=131_072,
        license_declaration="nvidia-open-model-license",
        live_license_term_urls=frozenset(
            {
                "https://www.nvidia.com/en-us/agreements/enterprise-software/"
                "nvidia-software-license-agreement",
                "https://www.nvidia.com/en-us/agreements/enterprise-software/"
                "product-specific-terms-for-ai-products",
                "https://www.nvidia.com/en-us/agreements/enterprise-software/"
                "nvidia-open-model-license",
            }
        ),
        model_license_names=("NVIDIA Open Model License Agreement",),
        additional_term_names=(),
        reasoning_control_mode="nemotron-no-think",
    ),
    "embedding-300m": CandidatePolicy(
        kind="embedding",
        model="nvidia/llama-nemotron-embed-300m-v2",
        image_repository="nvcr.io/nim/nvidia/llama-nemotron-embed-300m-v2",
        image_ref=(
            "nvcr.io/nim/nvidia/llama-nemotron-embed-300m-v2:1.13.0@"
            "sha256:1f0a7fc168919d7b84bb4edfb4a4da0c5828d11ee284f9fb8113242b3b35cbb4"
        ),
        image_digest=("sha256:1f0a7fc168919d7b84bb4edfb4a4da0c5828d11ee284f9fb8113242b3b35cbb4"),
        profile="e28f17c9c13a99055d065f88d725bf93c23b3aab14acd68f16323de1353fc528",
        version="1.13.0",
        precision="ONNX-FP16",
        max_model_length=8_192,
        license_declaration="nvidia-open-model-license",
        live_license_term_urls=frozenset(
            {
                "https://www.nvidia.com/en-us/agreements/enterprise-software/"
                "nvidia-software-license-agreement",
                "https://www.nvidia.com/en-us/agreements/enterprise-software/"
                "product-specific-terms-for-ai-products",
                "https://www.nvidia.com/en-us/agreements/enterprise-software/"
                "nvidia-open-model-license",
                "https://www.llama.com/llama3_2/license",
            }
        ),
        model_license_names=("NVIDIA Open Model License Agreement",),
        additional_term_names=("Llama 3.2 Community License Agreement",),
        reasoning_control_mode=None,
    ),
    "reranking-500m": CandidatePolicy(
        kind="reranking",
        model="nvidia/llama-nemotron-rerank-500m-v2",
        image_repository="nvcr.io/nim/nvidia/llama-nemotron-rerank-500m-v2",
        image_ref=(
            "nvcr.io/nim/nvidia/llama-nemotron-rerank-500m-v2:1.1@"
            "sha256:3e39d44bdb3dd683d6a2ac8d7689b484aee6c18dc7e00c2064f19501742720f3"
        ),
        image_digest=("sha256:3e39d44bdb3dd683d6a2ac8d7689b484aee6c18dc7e00c2064f19501742720f3"),
        profile="f7391ddbcb95b2406853526b8e489fedf20083a2420563ca3e65358ff417b10f",
        version="1.10.0",
        precision="ONNX-FP16",
        max_model_length=4_096,
        license_declaration="nvidia-community-model-license",
        live_license_term_urls=frozenset(
            {
                "https://www.nvidia.com/en-us/agreements/enterprise-software/"
                "nvidia-software-license-agreement",
                "https://www.nvidia.com/en-us/agreements/enterprise-software/"
                "product-specific-terms-for-ai-products",
                "https://www.nvidia.com/en-us/agreements/enterprise-software/"
                "nvidia-community-models-license",
                "https://www.llama.com/llama3_2/license",
            }
        ),
        model_license_names=("NVIDIA Community Model License",),
        additional_term_names=("Llama 3.2 Community License Agreement",),
        reasoning_control_mode=None,
    ),
}

LLM_SCENARIO_POLICIES: dict[str, LlmScenarioPolicy] = {
    "engine-short-c1": LlmScenarioPolicy(512, 256, 1, None),
    "rag-8k-c1": LlmScenarioPolicy(8_192, 512, 1, None),
    "rag-8k-c4": LlmScenarioPolicy(8_192, 512, 4, None),
    "long-32k-c1": LlmScenarioPolicy(32_448, 64, 1, 32_768),
    "long-64k-c1": LlmScenarioPolicy(65_216, 64, 1, 65_536),
    "long-128k-c1": LlmScenarioPolicy(130_752, 64, 1, 131_072),
}


class SafeScorecardError(RuntimeError):
    """Expected error represented by a stable, non-sensitive code."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True, slots=True)
class Evidence:
    status: EvidenceStatus
    data: dict[str, object] | None


@dataclass(frozen=True, slots=True)
class PerformanceEvidence:
    evidence_status: EvidenceStatus
    eligibility_status: Literal["eligible", "ineligible", "pending"]
    reason: str
    scenarios: dict[str, dict[str, object]]
    metric_definitions: dict[str, str] | None
    measured_requests: int | None
    warmup_requests: int | None


@dataclass(frozen=True, slots=True)
class RuntimeVerificationEvidence:
    source_status: EvidenceStatus
    report_status: str
    identity_verified: GateState
    license_verified: GateState
    image_digest: str | None
    profile_id: str | None
    license_declaration: str | None


class EvidenceStore:
    """Read fixed relative evidence paths once, rejecting links and large files."""

    def __init__(self, run_dir: Path) -> None:
        self.run_dir = run_dir
        self._cache: dict[str, Evidence] = {}

    def read(self, relative_path: str) -> Evidence:
        cached = self._cache.get(relative_path)
        if cached is not None:
            return cached
        path = self.run_dir / relative_path
        if not path.exists():
            evidence = Evidence("missing", None)
        elif path.is_symlink() or not path.is_file():
            evidence = Evidence("invalid", None)
        else:
            try:
                if path.stat().st_size > MAX_EVIDENCE_BYTES:
                    raise ValueError
                raw = json.loads(path.read_bytes())
                if not isinstance(raw, dict):
                    raise ValueError
                evidence = Evidence("present", cast(dict[str, object], raw))
            except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError):
                evidence = Evidence("invalid", None)
        self._cache[relative_path] = evidence
        return evidence


def _mapping(value: object) -> dict[str, object] | None:
    return cast(dict[str, object], value) if isinstance(value, dict) else None


def _string(value: object) -> str | None:
    return value if isinstance(value, str) and value else None


def _number(value: object) -> float | None:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return None
    result = float(value)
    return result if math.isfinite(result) else None


def _unit_score(value: object) -> float | None:
    result = _number(value)
    return result if result is not None and 0.0 <= result <= 1.0 else None


def _integer(value: object, *, minimum: int = 0) -> int | None:
    if not isinstance(value, int) or isinstance(value, bool) or value < minimum:
        return None
    return value


def _wrapped_value(value: object) -> object | None:
    wrapped = _mapping(value)
    return wrapped.get("value") if wrapped is not None else None


def _safe_report_status(value: object) -> str:
    return cast(str, value) if value in {"pass", "fail", "completed", "failed"} else "unknown"


def _benchmark_identity_exact(
    report: dict[str, object], candidate: str, policy: CandidatePolicy
) -> bool:
    candidate_data = _mapping(report.get("candidate"))
    runtime = _mapping(report.get("runtime"))
    run_config = _mapping(report.get("run_config"))
    if candidate_data is None or runtime is None or run_config is None:
        return False
    return bool(
        report.get("schema_version") == 2
        and report.get("kind") == policy.kind
        and candidate_data.get("candidate_id") == candidate
        and candidate_data.get("requested_model_id") == policy.model
        and _wrapped_value(candidate_data.get("image_ref")) == policy.image_ref
        and _wrapped_value(candidate_data.get("image_digest")) == policy.image_digest
        and _wrapped_value(candidate_data.get("license_id")) == policy.license_declaration
        and _wrapped_value(runtime.get("served_model_id")) == policy.model
        and _wrapped_value(runtime.get("nim_version")) == policy.version
        and _wrapped_value(runtime.get("profile")) == policy.profile
        and _wrapped_value(runtime.get("precision")) == policy.precision
        and _wrapped_value(runtime.get("max_model_length")) == policy.max_model_length
        and run_config.get("reasoning_control_mode") == policy.reasoning_control_mode
        and (
            policy.kind != "llm"
            or run_config.get("llm_prompt_uniqueness_control")
            == EXPECTED_LLM_PROMPT_UNIQUENESS_CONTROL
        )
    )


def _quality_identity_exact(
    report: dict[str, object], candidate: str, policy: CandidatePolicy
) -> bool:
    candidate_data = _mapping(report.get("candidate"))
    runtime = _mapping(report.get("runtime"))
    generation = _mapping(report.get("generation"))
    observed_models = runtime.get("response_models_observed") if runtime is not None else None
    return bool(
        report.get("schema_version") == 2
        and candidate_data is not None
        and runtime is not None
        and generation is not None
        and candidate_data.get("candidate_id") == candidate
        and candidate_data.get("model_id_configured") == policy.model
        and candidate_data.get("image_ref") == policy.image_ref
        and candidate_data.get("image_digest") == policy.image_digest
        and candidate_data.get("license_id") == policy.license_declaration
        and runtime.get("nim_version") == policy.version
        and runtime.get("profile") == policy.profile
        and runtime.get("precision") == policy.precision
        and runtime.get("max_model_length") == policy.max_model_length
        and isinstance(observed_models, list)
        and bool(observed_models)
        and all(model == policy.model for model in observed_models)
        and generation.get("reasoning_control_mode") == policy.reasoning_control_mode
    )


def _component(
    key: str,
    *,
    score: float | None,
    status: str,
    reason: str,
    evidence: dict[str, object] | None = None,
) -> dict[str, object]:
    weight = LLM_WEIGHTS[key]
    result: dict[str, object] = {
        "weight": weight,
        "status": status,
        "score": round(score, 12) if score is not None else None,
        "weighted_points": round(score * weight, 12) if score is not None else None,
        "reason": reason,
    }
    if evidence is not None:
        result["evidence"] = evidence
    return result


def _pending_component(key: str, reason: str) -> dict[str, object]:
    return _component(key, score=None, status="pending", reason=reason)


def _quality_components(
    candidate: str, store: EvidenceStore
) -> tuple[dict[str, dict[str, object]], dict[str, object]]:
    source = store.read(f"candidates/{candidate}/quality/report.json")
    pending_reason = f"quality_evidence_{source.status}"
    pending = {
        key: _pending_component(key, pending_reason)
        for key in (
            "correctness_vi_en",
            "faithfulness_and_citation",
            "rag_instruction_following",
        )
    }
    default_review = {
        "required": True,
        "status": "pending",
        "decision_eligible": False,
    }
    if source.data is None:
        return pending, {
            "source_status": source.status,
            "automatic_hard_gate": "not_evaluated",
            "human_review": default_review,
        }

    report = source.data
    identity_state, identity_details = _identity_binding(candidate, store, require_quality=True)
    if identity_state is not True or not _quality_identity_exact(
        report, candidate, CANDIDATE_POLICIES[candidate]
    ):
        identity_pending = {
            key: _pending_component(key, "exact_candidate_identity_binding_failed_or_pending")
            for key in pending
        }
        return identity_pending, {
            "source_status": "invalid",
            "automatic_hard_gate": "not_evaluated",
            "human_review": default_review,
            "identity_binding": identity_details,
        }
    scores = _mapping(report.get("component_scores"))
    languages = _mapping(report.get("language_scores"))
    vi = _mapping(languages.get("vi")) if languages is not None else None
    en = _mapping(languages.get("en")) if languages is not None else None
    vi_correctness = _unit_score(vi.get("correctness")) if vi is not None else None
    en_correctness = _unit_score(en.get("correctness")) if en is not None else None
    correctness = _unit_score(scores.get("correctness")) if scores is not None else None
    faithfulness = _unit_score(scores.get("faithfulness_citation")) if scores is not None else None
    instruction = _unit_score(scores.get("instruction_following")) if scores is not None else None
    report_completed = report.get("status") == "completed"

    hard_gate = _mapping(report.get("automatic_hard_gate"))
    hard_gate_raw = hard_gate.get("status") if hard_gate is not None else None
    hard_gate_status = (
        cast(str, hard_gate_raw) if hard_gate_raw in {"passed", "failed"} else "not_evaluated"
    )
    review = _mapping(report.get("human_review"))
    review_raw = review.get("status") if review is not None else None
    review_status = (
        cast(str, review_raw) if review_raw in {"pending", "approved", "rejected"} else "pending"
    )
    review_required = review is None or review.get("required") is not False
    review_summary = {
        "required": review_required,
        "status": review_status,
        "decision_eligible": not review_required or review_status == "approved",
    }

    values = {
        "correctness_vi_en": correctness,
        "faithfulness_and_citation": faithfulness,
        "rag_instruction_following": instruction,
    }
    if not report_completed or vi_correctness is None or en_correctness is None:
        return pending, {
            "source_status": "invalid",
            "automatic_hard_gate": hard_gate_status,
            "human_review": review_summary,
        }
    if any(value is None for value in values.values()):
        return pending, {
            "source_status": "invalid",
            "automatic_hard_gate": hard_gate_status,
            "human_review": review_summary,
        }

    components = {
        key: _component(
            key,
            score=cast(float, value),
            status="automatic_provisional",
            reason="deterministic_quality_rules_human_review_required",
            evidence=(
                {
                    "vi_score": vi_correctness,
                    "en_score": en_correctness,
                }
                if key == "correctness_vi_en"
                else None
            ),
        )
        for key, value in values.items()
    }
    return components, {
        "source_status": source.status,
        "report_status": _safe_report_status(report.get("status")),
        "automatic_hard_gate": hard_gate_status,
        "human_review": review_summary,
        "identity_binding": identity_details,
    }


def _nonempty_string_list(value: object) -> bool:
    return (
        isinstance(value, list)
        and bool(value)
        and all(isinstance(item, str) and bool(item) for item in value)
    )


def _runtime_verification(candidate: str, store: EvidenceStore) -> RuntimeVerificationEvidence:
    policy = CANDIDATE_POLICIES[candidate]
    source = store.read(f"candidates/{candidate}/runtime-verification.json")
    if source.data is None:
        return RuntimeVerificationEvidence(
            source.status, "not_evaluated", None, None, None, None, None
        )
    report = source.data
    report_status = _safe_report_status(report.get("status"))
    if report.get("schema_version") != 1 or report.get("candidate") != candidate:
        return RuntimeVerificationEvidence("invalid", "invalid", None, None, None, None, None)
    checks = _mapping(report.get("checks"))
    if (
        checks is None
        or set(checks) != set(_RUNTIME_CHECK_NAMES)
        or any(not isinstance(checks.get(name), bool) for name in _RUNTIME_CHECK_NAMES)
    ):
        return RuntimeVerificationEvidence("invalid", report_status, None, None, None, None, None)
    all_checks_pass = all(cast(bool, checks[name]) for name in _RUNTIME_CHECK_NAMES)
    expected = _mapping(report.get("expected_identity"))
    identity = _mapping(report.get("runtime_identity"))
    max_length = _mapping(report.get("max_model_length"))
    image_digest = _string(identity.get("image_digest")) if identity is not None else None
    profile_id = _string(identity.get("selected_profile_id")) if identity is not None else None
    identity_fields_valid = bool(
        expected is not None
        and expected.get("model") == policy.model
        and expected.get("nim_version") == policy.version
        and expected.get("profile_id") == policy.profile
        and expected.get("precision") == policy.precision
        and expected.get("image_digest") == policy.image_digest
        and identity is not None
        and identity.get("served_model") == policy.model
        and identity.get("nim_version") == policy.version
        and profile_id == policy.profile
        and identity.get("precision") == policy.precision
        and identity.get("image_repository") == policy.image_repository
        and image_digest == policy.image_digest
        and identity.get("architecture") == "arm64"
        and identity.get("operating_system") == "linux"
        and max_length is not None
        and max_length.get("value") == policy.max_model_length
    )
    live_license = _mapping(report.get("live_nim_license"))
    operator_terms = _mapping(report.get("operator_reviewed_model_terms"))
    declaration = (
        _string(operator_terms.get("declaration_name")) if operator_terms is not None else None
    )
    license_fields_valid = bool(
        live_license is not None
        and live_license.get("content_sha_algorithm") == "sha1"
        and isinstance(live_license.get("content_sha"), str)
        and _LICENSE_SHA1.fullmatch(cast(str, live_license["content_sha"]))
        and _nonempty_string_list(live_license.get("term_names"))
        and _nonempty_string_list(live_license.get("term_urls"))
        and set(cast(list[str], live_license["term_urls"])) == policy.live_license_term_urls
        and live_license.get("content_persisted_in_output") is False
        and live_license.get("metadata_and_license_endpoint_consistent") is True
        and operator_terms is not None
        and declaration == policy.license_declaration
        and operator_terms.get("model_license_names") == list(policy.model_license_names)
        and operator_terms.get("additional_term_names") == list(policy.additional_term_names)
        and operator_terms.get("separate_from_live_nim_license") is True
        and operator_terms.get("legal_approval") == "pending"
    )
    if report_status not in {"pass", "fail"}:
        identity_verified: GateState = None
        license_verified: GateState = None
    else:
        identity_verified = report_status == "pass" and all_checks_pass and identity_fields_valid
        license_verified = report_status == "pass" and all_checks_pass and license_fields_valid
    return RuntimeVerificationEvidence(
        source.status,
        report_status,
        identity_verified,
        license_verified,
        image_digest,
        profile_id,
        declaration,
    )


def _identity_binding(
    candidate: str, store: EvidenceStore, *, require_quality: bool
) -> tuple[GateState, dict[str, object]]:
    policy = CANDIDATE_POLICIES[candidate]
    benchmark = store.read(f"candidates/{candidate}/benchmark/report.json")
    quality = (
        store.read(f"candidates/{candidate}/quality/report.json")
        if require_quality
        else Evidence("present", {})
    )
    verification = _runtime_verification(candidate, store)
    source_status = {
        "benchmark": benchmark.status,
        "runtime_verification": verification.source_status,
    }
    if require_quality:
        source_status["quality"] = quality.status
    if benchmark.data is None or quality.data is None:
        return None, {
            "status": "pending",
            "reason": "identity_evidence_missing_or_invalid",
            "source_status": source_status,
        }
    if verification.identity_verified is None or verification.license_verified is None:
        return None, {
            "status": "pending",
            "reason": "runtime_verification_missing_or_invalid",
            "source_status": source_status,
        }
    benchmark_exact = _benchmark_identity_exact(benchmark.data, candidate, policy)
    quality_exact = (
        _quality_identity_exact(quality.data, candidate, policy) if require_quality else True
    )
    exact = bool(
        benchmark_exact
        and quality_exact
        and verification.identity_verified
        and verification.license_verified
        and verification.image_digest == policy.image_digest
        and verification.profile_id == policy.profile
        and verification.license_declaration == policy.license_declaration
    )
    return exact, {
        "status": "pass" if exact else "fail",
        "reason": (
            "quality_benchmark_runtime_identity_cross_bound"
            if exact and require_quality
            else "benchmark_runtime_identity_cross_bound"
            if exact
            else "exact_candidate_policy_or_cross_artifact_identity_mismatch"
        ),
        "source_status": source_status,
    }


def _input_gate(summary: dict[str, object], policy: LlmScenarioPolicy) -> GateState:
    gate = _mapping(summary.get("input_token_target_check"))
    if gate is None or gate.get("status") not in {"pass", "fail"}:
        return None
    if gate.get("status") == "fail":
        return False

    prompt_min = _number(gate.get("observed_prompt_tokens_min"))
    prompt_max = _number(gate.get("observed_prompt_tokens_max"))
    context_min = _number(gate.get("observed_prompt_plus_max_output_min"))
    context_max = _number(gate.get("observed_prompt_plus_max_output_max"))
    target_context = policy.target_context_tokens
    if (
        prompt_min is None
        or prompt_max is None
        or context_min is None
        or context_max is None
        or prompt_min <= 0
        or prompt_max < prompt_min
        or context_min != prompt_min + policy.max_output_tokens
        or context_max != prompt_max + policy.max_output_tokens
        or gate.get("target_input_tokens") != policy.target_input_tokens
        or gate.get("max_output_tokens") != policy.max_output_tokens
    ):
        return False

    if target_context is None:
        return bool(
            gate.get("target_context_tokens") is None
            and gate.get("required_relation") == "every_observed_prompt_within_target_ratio"
            and gate.get("minimum_ratio") == 0.8
            and gate.get("maximum_ratio") == 1.2
            and gate.get("absolute_context_lower_bound") is None
            and gate.get("absolute_context_upper_bound") is None
            and prompt_min >= policy.target_input_tokens * 0.8
            and prompt_max <= policy.target_input_tokens * 1.2
        )

    if gate.get("target_context_tokens") != target_context:
        return False
    lower_bound = target_context - 512
    return bool(
        gate.get("required_relation")
        == "every_observed_prompt_plus_max_output_within_absolute_context_window"
        and gate.get("minimum_ratio") is None
        and gate.get("maximum_ratio") is None
        and gate.get("absolute_context_lower_bound") == lower_bound
        and gate.get("absolute_context_upper_bound") == target_context
        and context_min >= lower_bound
        and context_max <= target_context
    )


def _output_gate(
    summary: dict[str, object],
    policy: LlmScenarioPolicy,
    *,
    measured_requests: int,
    warmup_requests: int,
) -> GateState:
    gate = _mapping(summary.get("output_token_target_check"))
    if gate is None or gate.get("status") not in {"pass", "fail"}:
        return None
    if gate.get("status") == "fail":
        return False
    control = _mapping(gate.get("fixed_request_control"))
    if (
        summary.get("max_output_tokens") != policy.max_output_tokens
        or gate.get("required_relation") != "completion_tokens_actual_equals_max_output_tokens"
        or gate.get("target_completion_tokens") != policy.max_output_tokens
        or control is None
        or control.get("ignore_eos") is not True
        or control.get("scope") != "synthetic_llm_benchmark_only"
    ):
        return False

    for phase, expected_count in (
        ("measured", measured_requests),
        ("warmup", warmup_requests),
    ):
        counts = _mapping(gate.get(phase))
        if counts is None:
            return None
        if (
            counts.get("required_count") != expected_count
            or counts.get("observed_count") != expected_count
            or counts.get("matching_count") != expected_count
            or _number(counts.get("observed_min")) != policy.max_output_tokens
            or _number(counts.get("observed_max")) != policy.max_output_tokens
        ):
            return False
    return True


def _metric_distribution(
    summary: dict[str, object], field: str, measured_requests: int
) -> dict[str, float] | None:
    values = _mapping(summary.get(field))
    if values is None or values.get("observed_count") != measured_requests:
        return None
    p50 = _number(values.get("p50"))
    p95 = _number(values.get("p95"))
    if p50 is None or p95 is None or p50 <= 0 or p95 <= 0 or p95 < p50:
        return None
    return {"p50": p50, "p95": p95}


def _percentiles(summary: dict[str, object], field: str) -> dict[str, float] | None:
    """Project a non-scored latency distribution for retrieval engine evidence."""

    values = _mapping(summary.get(field))
    if values is None:
        return None
    p50 = _number(values.get("p50"))
    p95 = _number(values.get("p95"))
    if p50 is None or p95 is None or p50 <= 0 or p95 <= 0 or p95 < p50:
        return None
    return {"p50": p50, "p95": p95}


def _performance_evidence(candidate: str, store: EvidenceStore) -> PerformanceEvidence:
    source = store.read(f"candidates/{candidate}/benchmark/report.json")
    if source.data is None:
        return PerformanceEvidence(
            source.status,
            "pending",
            f"benchmark_{source.status}",
            {},
            None,
            None,
            None,
        )
    report = source.data
    policy = CANDIDATE_POLICIES[candidate]
    identity_state, _ = _identity_binding(candidate, store, require_quality=True)
    if identity_state is not True or not _benchmark_identity_exact(report, candidate, policy):
        return PerformanceEvidence(
            "invalid",
            "pending",
            "exact_candidate_identity_binding_failed_or_pending",
            {},
            None,
            None,
            None,
        )

    contract = _mapping(report.get("contract_check"))
    metadata = _mapping(report.get("metadata_completeness"))
    run_config = _mapping(report.get("run_config"))
    metric_definitions = _mapping(report.get("metric_definitions"))
    measured_requests = (
        _integer(run_config.get("measured_requests_per_scenario"), minimum=20)
        if run_config is not None
        else None
    )
    warmup_requests = (
        _integer(run_config.get("warmup_requests_per_scenario"), minimum=1)
        if run_config is not None
        else None
    )
    canonical_metadata = bool(
        report.get("schema_version") == 2
        and report.get("status") in {"pass", "fail"}
        and report.get("kind") == "llm"
        and contract is not None
        and contract.get("status") == "pass"
        and metadata is not None
        and metadata.get("status") == "complete"
        and metadata.get("unverified_or_missing_fields") == []
        and run_config is not None
        and measured_requests is not None
        and warmup_requests is not None
        and run_config.get("measured_runtime_state") == "warm_after_runner_warmup"
        and run_config.get("metrics_required") is True
        and run_config.get("long_context_opt_in") is True
        and run_config.get("reasoning_control_mode") == policy.reasoning_control_mode
        and run_config.get("llm_prompt_uniqueness_control")
        == EXPECTED_LLM_PROMPT_UNIQUENESS_CONTROL
        and run_config.get("system_prompt_persisted") is False
        and run_config.get("base_url_persisted") is False
        and run_config.get("credentials_persisted") is False
        and metric_definitions == EXPECTED_LLM_METRIC_DEFINITIONS
    )
    if not canonical_metadata or measured_requests is None or warmup_requests is None:
        return PerformanceEvidence(
            "invalid",
            "pending",
            "canonical_benchmark_metadata_or_workload_invalid",
            {},
            None,
            measured_requests,
            warmup_requests,
        )

    raw_scenarios = report.get("scenarios")
    if not isinstance(raw_scenarios, list):
        return PerformanceEvidence(
            "invalid",
            "pending",
            "benchmark_scenarios_invalid",
            {},
            cast(dict[str, str], metric_definitions),
            measured_requests,
            warmup_requests,
        )

    selected: dict[str, dict[str, object]] = {}
    matrix_invalid = len(raw_scenarios) != len(LLM_SCENARIO_POLICIES)
    explicit_failure = report.get("status") == "fail"
    malformed = False
    for raw in raw_scenarios:
        scenario = _mapping(raw)
        if scenario is None or scenario.get("name") not in LLM_SCENARIO_POLICIES:
            matrix_invalid = True
            continue
        name = cast(str, scenario["name"])
        if name in selected:
            matrix_invalid = True
            continue
        scenario_policy = LLM_SCENARIO_POLICIES[name]
        summary = _mapping(scenario.get("summary"))
        if summary is None:
            selected[name] = {
                "gate_state": None,
                "input_token_target_gate": "pending",
                "output_token_target_gate": "pending",
                "metrics": None,
            }
            malformed = True
            continue
        summary_counts_valid = bool(
            summary.get("request_count") == measured_requests
            and summary.get("success_count") == measured_requests
            and summary.get("failure_count") == 0
            and summary.get("warmup_failure_count") == 0
            and summary.get("warmup_required_count") == warmup_requests
            and summary.get("concurrency") == scenario_policy.concurrency
            and summary.get("target_input_tokens") == scenario_policy.target_input_tokens
            and summary.get("target_context_tokens") == scenario_policy.target_context_tokens
            and summary.get("max_output_tokens") == scenario_policy.max_output_tokens
        )
        distributions = {
            field: _metric_distribution(summary, field, measured_requests)
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
        distributions_valid = all(value is not None for value in distributions.values())
        input_gate = _input_gate(summary, scenario_policy)
        output_gate = _output_gate(
            summary,
            scenario_policy,
            measured_requests=measured_requests,
            warmup_requests=warmup_requests,
        )
        ttft = distributions["ttft_seconds"]
        decode = distributions["decode_tokens_per_second"]
        scenario_status = summary.get("status")
        if (
            scenario_status not in {"pass", "fail"}
            or not summary_counts_valid
            or not distributions_valid
            or input_gate is None
            or output_gate is None
        ):
            gate_state: GateState = None
            malformed = True
        else:
            gate_state = scenario_status == "pass" and input_gate and output_gate
            explicit_failure = explicit_failure or scenario_status == "fail" or not gate_state
        selected[name] = {
            "gate_state": gate_state,
            "input_token_target_gate": (
                "pass" if input_gate is True else "fail" if input_gate is False else "pending"
            ),
            "output_token_target_gate": (
                "pass" if output_gate is True else "fail" if output_gate is False else "pending"
            ),
            "metrics": (
                {"ttft_seconds": ttft, "decode_tokens_per_second": decode}
                if ttft is not None and decode is not None
                else None
            ),
        }

    metric_defs = cast(dict[str, str], metric_definitions)
    if matrix_invalid or set(selected) != set(LLM_SCENARIO_POLICIES):
        return PerformanceEvidence(
            "invalid",
            "pending",
            "exact_six_scenario_matrix_invalid",
            selected,
            metric_defs,
            measured_requests,
            warmup_requests,
        )
    states = [selected[name]["gate_state"] for name in LLM_SCENARIO_POLICIES]
    if malformed or any(state is None for state in states):
        return PerformanceEvidence(
            "invalid",
            "pending",
            "canonical_scenario_counts_metrics_or_gates_invalid",
            selected,
            metric_defs,
            measured_requests,
            warmup_requests,
        )
    if (
        explicit_failure
        or report.get("status") != "pass"
        or not all(cast(bool, state) for state in states)
    ):
        return PerformanceEvidence(
            source.status,
            "ineligible",
            "canonical_six_scenario_gate_failed",
            selected,
            metric_defs,
            measured_requests,
            warmup_requests,
        )
    if any(selected[name]["metrics"] is None for name in CORE_LLM_SCENARIOS):
        return PerformanceEvidence(
            "invalid",
            "pending",
            "core_metrics_invalid",
            selected,
            metric_defs,
            measured_requests,
            warmup_requests,
        )
    return PerformanceEvidence(
        source.status,
        "eligible",
        "canonical_six_scenario_evidence_comparable",
        selected,
        metric_defs,
        measured_requests,
        warmup_requests,
    )


def _performance_components(
    evidence: dict[str, PerformanceEvidence],
) -> tuple[dict[str, dict[str, object]], dict[str, dict[str, object]]]:
    comparable = [
        candidate
        for candidate in LLM_CANDIDATES
        if evidence[candidate].eligibility_status == "eligible"
    ]
    components: dict[str, dict[str, object]] = {}
    details: dict[str, dict[str, object]] = {}
    if len(comparable) < 2:
        for candidate in LLM_CANDIDATES:
            raw = evidence[candidate]
            reason = (
                "insufficient_comparable_candidates"
                if raw.eligibility_status == "eligible"
                else raw.reason
            )
            components[candidate] = _pending_component("ttft_and_decode_throughput", reason)
            details[candidate] = {
                "comparison_status": "pending",
                "eligibility_status": raw.eligibility_status,
                "reason": reason,
                "core_scenarios": raw.scenarios,
                "full_six_scenario_readiness_gate": (
                    "pass" if raw.eligibility_status == "eligible" else "pending"
                ),
            }
        return components, details

    first = evidence[comparable[0]]
    workloads_equivalent = all(
        raw.metric_definitions == EXPECTED_LLM_METRIC_DEFINITIONS
        and raw.metric_definitions == first.metric_definitions
        and raw.measured_requests == first.measured_requests
        and raw.warmup_requests == first.warmup_requests
        for raw in (evidence[candidate] for candidate in comparable)
    )
    if not workloads_equivalent:
        for candidate in LLM_CANDIDATES:
            raw = evidence[candidate]
            reason = "metric_definitions_or_workload_not_equivalent"
            components[candidate] = _pending_component("ttft_and_decode_throughput", reason)
            details[candidate] = {
                "comparison_status": "pending",
                "eligibility_status": raw.eligibility_status,
                "reason": reason,
                "core_scenarios": raw.scenarios,
                "full_six_scenario_readiness_gate": "pending",
            }
        return components, details

    best: dict[tuple[str, str, str], float] = {}
    for scenario in CORE_LLM_SCENARIOS:
        for metric in ("ttft_seconds", "decode_tokens_per_second"):
            for percentile in ("p50", "p95"):
                values: list[float] = []
                for candidate in comparable:
                    scenario_metrics = cast(
                        dict[str, object], evidence[candidate].scenarios[scenario]["metrics"]
                    )
                    metric_values = cast(dict[str, float], scenario_metrics[metric])
                    values.append(metric_values[percentile])
                best[(scenario, metric, percentile)] = (
                    min(values) if metric == "ttft_seconds" else max(values)
                )

    for candidate in LLM_CANDIDATES:
        raw = evidence[candidate]
        normalized_values: list[float] = []
        scenario_details: list[dict[str, object]] = []
        for scenario in CORE_LLM_SCENARIOS:
            scenario_metrics = cast(dict[str, object], raw.scenarios[scenario]["metrics"])
            normalized: dict[str, dict[str, float]] = {}
            observed: dict[str, dict[str, float]] = {}
            for metric in ("ttft_seconds", "decode_tokens_per_second"):
                metric_values = cast(dict[str, float], scenario_metrics[metric])
                observed[metric] = dict(metric_values)
                normalized[metric] = {}
                for percentile in ("p50", "p95"):
                    value = metric_values[percentile]
                    best_value = best[(scenario, metric, percentile)]
                    ratio = best_value / value if metric == "ttft_seconds" else value / best_value
                    normalized_value = min(1.0, max(0.0, ratio))
                    normalized[metric][percentile] = round(normalized_value, 12)
                    normalized_values.append(normalized_value)
            scenario_details.append(
                {
                    "name": scenario,
                    "input_token_target_gate": raw.scenarios[scenario]["input_token_target_gate"],
                    "output_token_target_gate": raw.scenarios[scenario]["output_token_target_gate"],
                    "observed": observed,
                    "relative_best_normalized": normalized,
                }
            )
        score = sum(normalized_values) / len(normalized_values)
        components[candidate] = _component(
            "ttft_and_decode_throughput",
            score=score,
            status="automatic_provisional",
            reason="relative_best_core_scenario_normalization",
        )
        details[candidate] = {
            "comparison_status": "comparable",
            "comparison_pool": list(comparable),
            "full_six_scenario_readiness_gate": "pass",
            "metric_definitions_exact_and_equivalent": True,
            "measured_requests_per_scenario": raw.measured_requests,
            "warmup_requests_per_scenario": raw.warmup_requests,
            "method": (
                "mean_of_12_relative_best_ratios; TTFT p50/p95 uses best/value "
                "and decode p50/p95 uses value/best across three core scenarios"
            ),
            "core_scenarios": scenario_details,
        }
    return components, details


_COMBINATION_CHECK_NAMES = (
    "no_oom",
    "load",
    "restart",
    "health",
    "telemetry",
    "logs",
    "cleanup",
)


def _empty_combination_checks() -> dict[str, GateState]:
    return {name: None for name in _COMBINATION_CHECK_NAMES}


def _combination_checks(candidate: str, store: EvidenceStore) -> tuple[dict[str, GateState], str]:
    source = store.read(f"combinations/{candidate}/result.json")
    if source.data is None:
        return _empty_combination_checks(), source.status
    data = source.data
    overall = data.get("status")
    if overall not in {"pass", "fail"}:
        return _empty_combination_checks(), "invalid"
    scope = _mapping(data.get("scope"))
    candidates = scope.get("candidates") if scope is not None else None
    expected_candidates = {candidate, "embedding-300m", "reranking-500m"}
    scope_valid = bool(
        scope is not None
        and scope.get("llm_candidate") == candidate
        and isinstance(candidates, list)
        and len(candidates) == 3
        and all(isinstance(item, str) for item in candidates)
        and set(cast(list[str], candidates)) == expected_candidates
        and scope.get("concurrent_smoke") is True
        and scope.get("concurrent_bounded_load") is True
        and scope.get("llm_load_requirement") == "core matrix includes rag-8k-c4 at concurrency 4"
        and scope.get("measured_requests_per_scenario") == 4
        and scope.get("warmup_requests_per_scenario") == 1
    )
    checks = _mapping(data.get("checks"))
    if not scope_valid or checks is None or set(checks) != set(_COMBINATION_CHECK_NAMES):
        return _empty_combination_checks(), "invalid"
    values: dict[str, GateState] = {}
    for name in _COMBINATION_CHECK_NAMES:
        check = _mapping(checks.get(name))
        status = check.get("status") if check is not None else None
        values[name] = True if status == "pass" else False if status == "fail" else None
    if any(value is None for value in values.values()):
        return _empty_combination_checks(), "invalid"
    all_pass = all(cast(bool, value) for value in values.values())
    if (overall == "pass") != all_pass:
        return _empty_combination_checks(), "invalid"
    return values, source.status


def _memory_component(
    candidate: str, performance: PerformanceEvidence, store: EvidenceStore
) -> tuple[dict[str, object], dict[str, object]]:
    rag = performance.scenarios.get("rag-8k-c4")
    rag_gate = (
        cast(GateState, rag.get("gate_state"))
        if rag is not None and performance.eligibility_status == "eligible"
        else None
    )
    combination, combination_status = _combination_checks(candidate, store)
    checks: dict[str, GateState] = {
        "rag_8k_c4_input_output_concurrency_gate": rag_gate,
        **{f"combination_{name}": combination[name] for name in _COMBINATION_CHECK_NAMES},
    }
    if any(value is None for value in checks.values()):
        component = _pending_component(
            "memory_and_concurrency", "memory_or_combination_evidence_pending"
        )
    elif not all(cast(bool, value) for value in checks.values()):
        component = _pending_component(
            "memory_and_concurrency", "memory_or_combination_gate_failed"
        )
    else:
        component = _component(
            "memory_and_concurrency",
            score=1.0,
            status="automatic_provisional",
            reason="rag_c4_and_all_seven_combination_runtime_checks_passed",
        )
    return component, {
        "combination_evidence_status": combination_status,
        "checks": {
            name: "pass" if value is True else "fail" if value is False else "pending"
            for name, value in checks.items()
        },
    }


def _operations_component(
    candidate: str, store: EvidenceStore
) -> tuple[dict[str, object], dict[str, object]]:
    policy = CANDIDATE_POLICIES[candidate]
    benchmark = store.read(f"candidates/{candidate}/benchmark/report.json")
    verification = _runtime_verification(candidate, store)
    identity_state, identity_details = _identity_binding(candidate, store, require_quality=True)
    legacy_runtime = store.read(f"candidates/{candidate}/runtime-declaration.json")
    legacy_license = store.read(f"candidates/{candidate}/license.json")
    checks: dict[str, GateState] = {
        "exact_image_digest_pin": None,
        "benchmark_contract": None,
        "metadata_complete": None,
        "live_exact_runtime_profile": None,
        "runtime_fields_complete": None,
        "license_evidence_matches": None,
    }
    declared_license: str | None = None
    benchmark_digest: str | None = None
    benchmark_image_ref: str | None = None
    benchmark_valid = bool(
        benchmark.data is not None
        and _benchmark_identity_exact(benchmark.data, candidate, policy)
        and identity_state is True
    )
    if benchmark_valid:
        assert benchmark.data is not None
        candidate_data = _mapping(benchmark.data.get("candidate"))
        benchmark_digest = (
            _string(_wrapped_value(candidate_data.get("image_digest")))
            if candidate_data is not None
            else None
        )
        benchmark_image_ref = (
            _string(_wrapped_value(candidate_data.get("image_ref")))
            if candidate_data is not None
            else None
        )
        declared_license = (
            _string(_wrapped_value(candidate_data.get("license_id")))
            if candidate_data is not None
            else None
        )
        contract = _mapping(benchmark.data.get("contract_check"))
        if contract is not None and contract.get("status") in {"pass", "fail"}:
            checks["benchmark_contract"] = contract.get("status") == "pass"
        metadata = _mapping(benchmark.data.get("metadata_completeness"))
        if metadata is not None and metadata.get("status") in {"complete", "incomplete"}:
            checks["metadata_complete"] = bool(
                metadata.get("status") == "complete"
                and metadata.get("unverified_or_missing_fields") == []
            )
    if verification.identity_verified is not None:
        checks["exact_image_digest_pin"] = bool(
            verification.identity_verified
            and benchmark_digest is not None
            and benchmark_image_ref is not None
            and verification.image_digest == benchmark_digest
            and _SHA256_DIGEST.fullmatch(benchmark_digest)
            and benchmark_image_ref.endswith(f"@{benchmark_digest}")
        )
        checks["live_exact_runtime_profile"] = bool(
            verification.identity_verified
            and verification.profile_id is not None
            and _PROFILE_ID.fullmatch(verification.profile_id)
        )
        checks["runtime_fields_complete"] = verification.identity_verified
    if verification.license_verified is not None:
        checks["license_evidence_matches"] = bool(
            verification.license_verified
            and declared_license is not None
            and verification.license_declaration == declared_license
        )

    if any(value is None for value in checks.values()):
        component = _pending_component(
            "operations_license_nim_compatibility",
            "operations_or_license_evidence_pending",
        )
    elif not all(cast(bool, value) for value in checks.values()):
        component = _pending_component(
            "operations_license_nim_compatibility",
            "operations_identity_contract_or_license_gate_failed",
        )
    else:
        component = _component(
            "operations_license_nim_compatibility",
            score=1.0,
            status="automatic_provisional",
            reason="exact_runtime_contract_and_reviewed_license_evidence",
        )
    return component, {
        "source_status": {
            "benchmark": benchmark.status,
            "runtime_verification": verification.source_status,
            "legacy_runtime_declaration_not_scored": legacy_runtime.status,
            "legacy_license_declaration_not_scored": legacy_license.status,
        },
        "runtime_verification_status": verification.report_status,
        "identity_binding": identity_details,
        "checks": {
            name: "pass" if value is True else "fail" if value is False else "pending"
            for name, value in checks.items()
        },
        "legal_approval": {
            "status": "pending",
            "automatic_evidence_is_legal_approval": False,
        },
    }


def _provisional_total(
    components: dict[str, dict[str, object]],
    *,
    human_review_status: str,
    automatic_hard_gate: str,
) -> dict[str, object]:
    scored = [
        component
        for component in components.values()
        if _unit_score(component.get("score")) is not None
    ]
    partial_points = sum(cast(float, component["weighted_points"]) for component in scored)
    weight_coverage = sum(cast(float, component["weight"]) for component in scored)
    complete = len(scored) == len(LLM_WEIGHTS) and math.isclose(weight_coverage, 1.0)
    reasons: list[str] = []
    if not complete:
        reasons.append("one_or_more_weighted_components_pending")
    if human_review_status != "approved":
        reasons.append("human_review_pending")
    if automatic_hard_gate != "passed":
        reasons.append("automatic_quality_hard_gate_not_passed")
    reasons.append("legal_approval_pending")
    return {
        "status": "automatic_provisional" if complete else "pending_incomplete",
        "score": round(partial_points, 12) if complete else None,
        "partial_weighted_points": round(partial_points, 12),
        "weight_coverage": round(weight_coverage, 12),
        "automatic_only": True,
        "eligible_for_winner": False,
        "decision_blockers": reasons,
    }


def _retrieval_engine_evidence(candidate: str, store: EvidenceStore) -> dict[str, object]:
    policy = CANDIDATE_POLICIES[candidate]
    benchmark = store.read(f"candidates/{candidate}/benchmark/report.json")
    verification = _runtime_verification(candidate, store)
    legacy_runtime = store.read(f"candidates/{candidate}/runtime-declaration.json")
    legacy_license = store.read(f"candidates/{candidate}/license.json")
    expected_scenarios = (
        ("embedding-batch-1", "embedding-batch-16")
        if candidate == "embedding-300m"
        else ("reranking-passages-2", "reranking-passages-16")
    )
    latency: list[dict[str, object]] = []
    contract_status = "pending"
    metadata_status = "pending"
    semantic_status = "pending"
    benchmark_status = "pending"
    identity_state, identity_details = _identity_binding(candidate, store, require_quality=False)
    benchmark_valid = bool(
        benchmark.data is not None
        and _benchmark_identity_exact(benchmark.data, candidate, policy)
        and identity_state is True
    )
    if benchmark_valid:
        assert benchmark.data is not None
        benchmark_status = _safe_report_status(benchmark.data.get("status"))
        contract = _mapping(benchmark.data.get("contract_check"))
        if contract is not None and contract.get("status") in {"pass", "fail"}:
            contract_status = cast(str, contract["status"])
        metadata = _mapping(benchmark.data.get("metadata_completeness"))
        if metadata is not None and metadata.get("status") in {"complete", "incomplete"}:
            metadata_status = cast(str, metadata["status"])
        semantic = _mapping(benchmark.data.get("semantic_check"))
        if semantic is not None and semantic.get("status") in {"pass", "fail"}:
            semantic_status = cast(str, semantic["status"])
        scenarios = benchmark.data.get("scenarios")
        if isinstance(scenarios, list):
            by_name = {
                item.get("name"): item
                for item in scenarios
                if isinstance(item, dict) and item.get("name") in expected_scenarios
            }
            for name in expected_scenarios:
                item = _mapping(by_name.get(name))
                summary = _mapping(item.get("summary")) if item is not None else None
                total = (
                    _percentiles(summary, "total_latency_seconds") if summary is not None else None
                )
                if total is not None:
                    latency.append(
                        {
                            "name": name,
                            "p50_seconds": total["p50"],
                            "p95_seconds": total["p95"],
                        }
                    )
    return {
        "source_status": {
            "benchmark": benchmark.status,
            "runtime_verification": verification.source_status,
            "legacy_runtime_declaration_not_scored": legacy_runtime.status,
            "legacy_license_declaration_not_scored": legacy_license.status,
        },
        "benchmark_status": benchmark_status,
        "contract_status": contract_status,
        "metadata_status": metadata_status,
        "semantic_sanity_status": semantic_status,
        "latency_observations": latency,
        "runtime_verification_status": verification.report_status,
        "identity_binding": identity_details,
        "live_runtime_identity_verified": verification.identity_verified,
        "reviewed_license_evidence_verified": verification.license_verified,
        "legal_approval_status": "pending",
        "phase5_retrieval_quality_claimed": False,
    }


def _bge_access(store: EvidenceStore) -> dict[str, object]:
    source = store.read("bge-m3-access.json")
    if source.data is None:
        return {
            "source_status": source.status,
            "access_status": "pending",
            "http_status": None,
            "exact_pinned_runtime_available": False,
        }
    probe = _mapping(source.data.get("live_authenticated_token_scope_probe"))
    http_status = _integer(probe.get("http_status"), minimum=100) if probe is not None else None
    probe_result = probe.get("result") if probe is not None else None
    exact = source.data.get("exact_pinned_image_selected") is True
    effect = source.data.get("acceptance_effect")
    blocked = effect == "blocked" or http_status in {401, 402, 403} or not exact
    available = effect == "pass" and probe_result == "pass" and http_status == 200 and exact
    return {
        "source_status": source.status,
        "access_status": "blocked" if blocked else "available" if available else "pending",
        "http_status": http_status if http_status is not None and http_status <= 599 else None,
        "exact_pinned_runtime_available": exact,
    }


def _retrieval_candidate(candidate: str, store: EvidenceStore) -> dict[str, object]:
    components = {
        key: {
            "weight": weight,
            "status": "pending_phase5_retrieval_evaluation",
            "score": None,
            "weighted_points": None,
        }
        for key, weight in RETRIEVAL_WEIGHTS.items()
    }
    if candidate == "bge-m3":
        evidence = {"access": _bge_access(store)}
        role = "embedding_challenger"
    else:
        evidence = {"engine": _retrieval_engine_evidence(candidate, store)}
        role = "embedding_baseline" if candidate == "embedding-300m" else "reranker_baseline"
    return {
        "role": role,
        "components": components,
        "evidence": evidence,
        "provisional_weighted_total": {
            "status": "pending_phase5_retrieval_evaluation",
            "score": None,
            "weight_coverage": 0.0,
            "eligible_for_winner": False,
        },
    }


def build_scorecard(run_dir: Path) -> dict[str, object]:
    """Build schema-v2 scorecard using only safe, fixed evidence projections."""

    if not run_dir.exists() or not run_dir.is_dir():
        raise SafeScorecardError("run_directory_invalid")
    store = EvidenceStore(run_dir)
    performance_raw = {
        candidate: _performance_evidence(candidate, store) for candidate in LLM_CANDIDATES
    }
    performance_components, performance_details = _performance_components(performance_raw)
    llm_candidates: dict[str, object] = {}
    human_pending = False
    for candidate in LLM_CANDIDATES:
        quality_components, quality_details = _quality_components(candidate, store)
        memory_component, memory_details = _memory_component(
            candidate, performance_raw[candidate], store
        )
        operations_component, operations_details = _operations_component(candidate, store)
        components = {
            **quality_components,
            "ttft_and_decode_throughput": performance_components[candidate],
            "memory_and_concurrency": memory_component,
            "operations_license_nim_compatibility": operations_component,
        }
        review = cast(dict[str, object], quality_details["human_review"])
        review_status = cast(str, review["status"])
        human_pending = human_pending or review_status != "approved"
        llm_candidates[candidate] = {
            "components": components,
            "quality": {
                **quality_details,
                "components": {
                    key: quality_components[key]
                    for key in (
                        "correctness_vi_en",
                        "faithfulness_and_citation",
                        "rag_instruction_following",
                    )
                },
            },
            "performance": performance_details[candidate],
            "memory_and_concurrency": memory_details,
            "operations_license_nim_compatibility": operations_details,
            "provisional_weighted_total": _provisional_total(
                components,
                human_review_status=review_status,
                automatic_hard_gate=cast(str, quality_details["automatic_hard_gate"]),
            ),
        }

    selection_reason = (
        "human_review_pending_and_automatic_selection_forbidden"
        if human_pending
        else "automatic_selection_forbidden_legal_and_operator_decision_pending"
    )
    return {
        "schema_version": SCHEMA_VERSION,
        "phase": 3,
        "generated_at_utc": datetime.now(UTC).isoformat(),
        "scope": (
            "Phase 3 supplied-context quality, direct NIM engine performance, runtime, "
            "and license evidence; no Phase 4 ingestion or Phase 5 retrieval-quality claim"
        ),
        "metric_scope": {
            "ttft": (
                "client-observed request-dispatch to first non-empty generated-token "
                "delta; an upper-bound proxy, not backend-receive TTFT"
            ),
            "decode_throughput": (
                "response-reported completion tokens divided by client-observed time "
                "from first to last non-empty generated-token delta"
            ),
            "total_latency": (
                "direct NIM HTTP request-dispatch to stream completion; not application "
                "end-to-end RAG latency"
            ),
        },
        "weights": {
            "llm": dict(LLM_WEIGHTS),
            "retrieval": dict(RETRIEVAL_WEIGHTS),
        },
        "llm_scorecard": {
            "status": (
                "automatic_provisional_human_decision_pending"
                if human_pending
                else "automatic_provisional_operator_decision_pending"
            ),
            "performance_normalization": {
                "range": [0.0, 1.0],
                "relative_best_only": True,
                "requires_all_core_input_and_output_token_gates": True,
                "requires_at_least_two_comparable_candidates": True,
            },
            "candidates": llm_candidates,
            "selection": {
                "status": "not_selected",
                "winner_candidate_id": None,
                "automatic_winner_selection": False,
                "reason": selection_reason,
            },
        },
        "retrieval_scorecard": {
            "status": "pending_phase5_metrics_and_bge_runtime",
            "phase3_design_gate": {
                "status": "blocked",
                "reason": (
                    "the master plan requires an under-1B embedding winner in Phase 3, "
                    "but BGE-M3 exact runtime access is blocked and the current retrieval "
                    "quality metric workflow is scheduled for Phase 5"
                ),
                "winner_selection_possible_from_current_phase3_evidence": False,
            },
            "embedding_comparison": {
                "candidates": {
                    candidate: _retrieval_candidate(candidate, store)
                    for candidate in ("embedding-300m", "bge-m3")
                },
                "selection": {
                    "status": "not_selected",
                    "winner_candidate_id": None,
                    "reason": "phase5_metrics_missing_and_bge_exact_runtime_may_be_blocked",
                },
            },
            "reranking_evaluation": {
                "candidates": {"reranking-500m": _retrieval_candidate("reranking-500m", store)},
                "selection": {
                    "status": "not_selected",
                    "winner_candidate_id": None,
                    "reason": "phase5_reranking_metrics_and_challenger_comparison_missing",
                },
            },
        },
        "decision": {
            "llm_winner": "not_selected",
            "embedding_winner": "not_selected",
            "reranker_selection": "not_selected",
            "phase3_winner_claimed": False,
        },
        "sensitive_content_persisted": False,
    }


def write_atomic(output: Path, scorecard: dict[str, object]) -> None:
    """Create one scorecard atomically without replacing existing evidence."""

    if os.path.lexists(output):
        raise SafeScorecardError("output_already_exists")
    try:
        content = json.dumps(scorecard, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    except (TypeError, ValueError):
        raise SafeScorecardError("scorecard_serialization_failed") from None
    previous_umask = os.umask(0o027)
    temporary: Path | None = None
    try:
        output.parent.mkdir(parents=True, exist_ok=True)
        descriptor, raw_path = tempfile.mkstemp(prefix=f".{output.name}.tmp-", dir=output.parent)
        temporary = Path(raw_path)
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary, 0o640)
        os.link(temporary, output)
        temporary.unlink()
        temporary = None
        parent_fd = os.open(output.parent, os.O_RDONLY)
        try:
            os.fsync(parent_fd)
        finally:
            os.close(parent_fd)
    except FileExistsError:
        raise SafeScorecardError("output_already_exists") from None
    except OSError:
        raise SafeScorecardError("scorecard_write_failed") from None
    finally:
        if temporary is not None:
            with suppress(OSError):
                temporary.unlink(missing_ok=True)
        os.umask(previous_umask)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Build the standalone, provisional Phase 3 model scorecard."
    )
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        scorecard = build_scorecard(cast(Path, args.run_dir))
        write_atomic(cast(Path, args.output), scorecard)
    except SafeScorecardError as exc:
        print(f"Phase 3 scorecard failed: {exc.code}", file=sys.stderr)
        return 1
    except Exception:  # Never expose arbitrary evidence or exception text at the CLI boundary.
        print("Phase 3 scorecard failed: unexpected_internal_error", file=sys.stderr)
        return 1
    print("Phase 3 provisional scorecard written.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

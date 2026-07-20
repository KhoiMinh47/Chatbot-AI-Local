#!/usr/bin/env python3
"""Reproducible, secret-safe Phase 3 NIM engine benchmark runner.

The runner exercises already-running NIM endpoints. It never starts a model,
pulls an image, parses documents, writes Qdrant, or infers runtime metadata that
the service did not expose. Its JSON and CSV evidence contain metrics and
fixture identifiers, never prompts, generated text, credentials, or base URLs.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import os
import re
import shutil
import sys
import tempfile
import time
from collections.abc import Callable, Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor
from contextlib import suppress
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from types import MappingProxyType
from typing import Literal, cast
from urllib.parse import urlsplit

import httpx2 as httpx

BenchmarkKind = Literal["llm", "embedding", "reranking"]
RequestStatus = Literal["ok", "failed"]
ReasoningControlMode = Literal["llama-standard", "nemotron-no-think"]
LlmRequestPhase = Literal["warmup", "measured"]

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_FIXTURE_PATH = REPOSITORY_ROOT / "benchmarks" / "phase3" / "fixtures.json"
EVIDENCE_SCHEMA_VERSION = 2
DEFAULT_MEASURED_REQUESTS = 20
DEFAULT_WARMUP_REQUESTS = 2
DEFAULT_TIMEOUT_SECONDS = 300.0
_SAFE_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/+-]*$")
_SAFE_IMAGE_REFERENCE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/:@+-]*$")
_SHA256_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
_REASONING_CONTROL_TEXT: dict[ReasoningControlMode, str] = {
    "llama-standard": "detailed thinking off",
    "nemotron-no-think": "/no_think",
}
# Closed, immutable allowlist for synthetic performance requests. Arbitrary
# OpenAI-compatible extensions are intentionally not accepted from CLI/env.
_SYNTHETIC_LLM_FIXED_REQUEST_CONTROLS: Mapping[str, object] = MappingProxyType({"ignore_eos": True})
_LLM_PROMPT_UNIQUENESS_CONTROL: Mapping[str, object] = MappingProxyType(
    {
        "status": "enabled",
        "nonce_position": "first_user_content_line_before_synthetic_context",
        "nonce_derivation": "sha256(scenario_name|request_phase|request_index)",
        "warmup_and_measured_namespaces_disjoint": True,
        "full_user_prompt_reuse_between_requests": False,
        "nonce_persisted": False,
    }
)


class SafeBenchmarkError(RuntimeError):
    """Expected failure whose code is safe to persist and print."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True, slots=True)
class LlmUsage:
    """Complete token counts reported by a chat-completions response."""

    prompt_tokens: int
    completion_tokens: int
    total_tokens: int


@dataclass(frozen=True, slots=True)
class RetrieverUsage:
    """Token counts reported by an embedding or reranking response."""

    prompt_tokens: int
    completion_tokens: int | None
    total_tokens: int


@dataclass(frozen=True, slots=True)
class LlmScenario:
    name: str
    family: Literal["short", "rag", "long"]
    target_input_tokens: int
    max_output_tokens: int
    concurrency: int
    target_context_tokens: int | None = None


@dataclass(frozen=True, slots=True)
class FixtureSet:
    schema_version: int
    sha256: str
    llm_system: str
    llm_repeat_unit: str
    llm_short_prefix: str
    llm_rag_prefix: str
    llm_long_prefix: str
    llm_suffix: str
    embedding_query: str
    embedding_positive: str
    embedding_negative: str
    embedding_performance_template: str
    reranking_query: str
    reranking_positive: str
    reranking_negative: str
    reranking_performance_template: str


@dataclass(frozen=True, slots=True)
class RequestMetric:
    kind: BenchmarkKind
    scenario: str
    request_index: int
    concurrency: int
    status: RequestStatus
    error_code: str | None
    target_context_tokens: int | None = None
    target_input_tokens: int | None = None
    max_output_tokens: int | None = None
    prompt_tokens_actual: int | None = None
    completion_tokens_actual: int | None = None
    total_tokens_actual: int | None = None
    ttft_seconds: float | None = None
    decode_duration_seconds: float | None = None
    decode_tokens_per_second: float | None = None
    total_latency_seconds: float | None = None
    batch_size: int | None = None
    passage_count: int | None = None
    vector_dimension_observed: int | None = None
    response_model_observed: str | None = None


@dataclass(frozen=True, slots=True)
class EmbeddingCall:
    vectors: tuple[tuple[float, ...], ...]
    usage: RetrieverUsage | None
    latency_seconds: float
    response_model: str | None


@dataclass(frozen=True, slots=True)
class RerankingItem:
    index: int
    logit: float


@dataclass(frozen=True, slots=True)
class RerankingCall:
    rankings: tuple[RerankingItem, ...]
    usage: RetrieverUsage | None
    latency_seconds: float
    response_model: str | None


@dataclass(frozen=True, slots=True)
class RunnerConfig:
    kind: BenchmarkKind
    base_url: str
    model: str
    candidate_id: str
    measured_requests: int
    warmup_requests: int
    timeout_seconds: float
    metrics_required: bool
    include_long_context: bool
    seed: int
    image_ref: str | None
    image_digest: str | None
    nim_version: str | None
    runtime_profile: str | None
    precision: str | None
    max_model_length: int | None
    license_id: str | None
    reasoning_control_mode: ReasoningControlMode | None = None


def _mapping(value: object, location: str) -> Mapping[str, object]:
    if not isinstance(value, dict):
        raise SafeBenchmarkError(f"invalid_fixture_{location}")
    return cast(Mapping[str, object], value)


def _fixture_string(section: Mapping[str, object], key: str) -> str:
    value = section.get(key)
    if not isinstance(value, str) or not value.strip():
        raise SafeBenchmarkError(f"invalid_fixture_{key}")
    return value


def load_fixtures(path: Path = DEFAULT_FIXTURE_PATH) -> FixtureSet:
    """Load and strictly validate the deterministic Phase 3 fixture file."""

    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise SafeBenchmarkError("fixture_unreadable") from exc
    try:
        decoded = cast(object, json.loads(raw))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SafeBenchmarkError("fixture_invalid_json") from exc

    root = _mapping(decoded, "root")
    schema_version = root.get("schema_version")
    if not isinstance(schema_version, int) or isinstance(schema_version, bool):
        raise SafeBenchmarkError("invalid_fixture_schema_version")
    if schema_version != 1:
        raise SafeBenchmarkError("unsupported_fixture_schema_version")

    llm = _mapping(root.get("llm"), "llm")
    embedding = _mapping(root.get("embedding"), "embedding")
    reranking = _mapping(root.get("reranking"), "reranking")
    return FixtureSet(
        schema_version=schema_version,
        sha256=hashlib.sha256(raw).hexdigest(),
        llm_system=_fixture_string(llm, "system"),
        llm_repeat_unit=_fixture_string(llm, "repeat_unit"),
        llm_short_prefix=_fixture_string(llm, "short_prefix"),
        llm_rag_prefix=_fixture_string(llm, "rag_prefix"),
        llm_long_prefix=_fixture_string(llm, "long_prefix"),
        llm_suffix=_fixture_string(llm, "suffix"),
        embedding_query=_fixture_string(embedding, "query"),
        embedding_positive=_fixture_string(embedding, "positive_passage"),
        embedding_negative=_fixture_string(embedding, "negative_passage"),
        embedding_performance_template=_fixture_string(embedding, "performance_passage_template"),
        reranking_query=_fixture_string(reranking, "query"),
        reranking_positive=_fixture_string(reranking, "positive_passage"),
        reranking_negative=_fixture_string(reranking, "negative_passage"),
        reranking_performance_template=_fixture_string(reranking, "performance_passage_template"),
    )


def _reasoning_control_mode(kind: BenchmarkKind, value: object) -> ReasoningControlMode | None:
    if kind != "llm":
        if value is not None:
            raise SafeBenchmarkError("reasoning_control_not_applicable")
        return None
    if value not in _REASONING_CONTROL_TEXT:
        raise SafeBenchmarkError("invalid_reasoning_control_mode")
    return cast(ReasoningControlMode, value)


def _controlled_system_prompt(common_instruction: str, mode: ReasoningControlMode) -> str:
    """Apply an allowlisted model control while preserving common instructions."""

    return f"{_REASONING_CONTROL_TEXT[mode]}\n\n{common_instruction}"


def llm_scenarios(include_long_context: bool) -> tuple[LlmScenario, ...]:
    """Return the fixed master-plan workload matrix."""

    scenarios = [
        LlmScenario("engine-short-c1", "short", 512, 256, 1),
        LlmScenario("rag-8k-c1", "rag", 8_192, 512, 1),
        LlmScenario("rag-8k-c4", "rag", 8_192, 512, 4),
    ]
    if include_long_context:
        scenarios.extend(
            [
                LlmScenario("long-32k-c1", "long", 32_448, 64, 1, 32_768),
                LlmScenario("long-64k-c1", "long", 65_216, 64, 1, 65_536),
                LlmScenario("long-128k-c1", "long", 130_752, 64, 1, 131_072),
            ]
        )
    return tuple(scenarios)


def build_llm_prompt(fixtures: FixtureSet, scenario: LlmScenario) -> str:
    """Create an approximate-token synthetic prompt without claiming tokenizer counts."""

    prefixes = {
        "short": fixtures.llm_short_prefix,
        "rag": fixtures.llm_rag_prefix,
        "long": fixtures.llm_long_prefix,
    }
    # The repeated ASCII word is generally close to one model token. We reserve
    # room for chat-template and fixed-text overhead, then record the server's
    # actual usage. The target is never substituted for an observed token count.
    repeat_count = max(1, scenario.target_input_tokens - 128)
    return (
        f"{prefixes[scenario.family]}\n"
        f"{fixtures.llm_repeat_unit * repeat_count}\n"
        f"{fixtures.llm_suffix}"
    )


def _unique_llm_request_prompt(
    fixtures: FixtureSet,
    scenario: LlmScenario,
    *,
    request_phase: LlmRequestPhase,
    request_index: int,
) -> str:
    """Put a deterministic nonce before the large shared context.

    This prevents a candidate with prefix caching from reusing the complete
    synthetic prompt across repeated measurements. The nonce is deliberately
    absent from all persisted evidence.
    """

    if request_phase not in {"warmup", "measured"}:
        raise SafeBenchmarkError("invalid_llm_request_phase")
    nonce_material = f"{scenario.name}|{request_phase}|{request_index}".encode()
    nonce = hashlib.sha256(nonce_material).hexdigest()
    return f"synthetic_request_nonce={nonce}\n{build_llm_prompt(fixtures, scenario)}"


def percentile(values: Sequence[float], quantile: float) -> float | None:
    """Linear-interpolated percentile, defined for one or more observations."""

    if not values:
        return None
    if not 0 <= quantile <= 1:
        raise ValueError("quantile must be between zero and one")
    ordered = sorted(values)
    rank = (len(ordered) - 1) * quantile
    lower = math.floor(rank)
    upper = math.ceil(rank)
    if lower == upper:
        return ordered[lower]
    fraction = rank - lower
    return ordered[lower] + ((ordered[upper] - ordered[lower]) * fraction)


def _actual_int(value: object) -> int | None:
    if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
        return value
    return None


def _raw_usage(payload: Mapping[str, object]) -> Mapping[str, object] | None:
    raw_usage = payload.get("usage")
    if raw_usage is None:
        return None
    if not isinstance(raw_usage, dict):
        raise SafeBenchmarkError("invalid_usage_object")
    return cast(Mapping[str, object], raw_usage)


def _llm_usage(payload: Mapping[str, object]) -> LlmUsage | None:
    usage = _raw_usage(payload)
    if usage is None:
        return None
    prompt = _actual_int(usage.get("prompt_tokens"))
    completion = _actual_int(usage.get("completion_tokens"))
    total = _actual_int(usage.get("total_tokens"))
    if prompt is None or completion is None or total is None:
        raise SafeBenchmarkError("invalid_usage_token_counts")
    if total != prompt + completion:
        raise SafeBenchmarkError("inconsistent_usage_token_totals")
    return LlmUsage(prompt_tokens=prompt, completion_tokens=completion, total_tokens=total)


def _retriever_usage(payload: Mapping[str, object]) -> RetrieverUsage | None:
    usage = _raw_usage(payload)
    if usage is None:
        return None
    prompt = _actual_int(usage.get("prompt_tokens"))
    total = _actual_int(usage.get("total_tokens"))
    raw_completion = usage.get("completion_tokens")
    completion = None if raw_completion is None else _actual_int(raw_completion)
    if prompt is None or total is None or (raw_completion is not None and completion is None):
        raise SafeBenchmarkError("invalid_usage_token_counts")
    expected_total = prompt if completion is None else prompt + completion
    if total != expected_total:
        raise SafeBenchmarkError("inconsistent_usage_token_totals")
    return RetrieverUsage(
        prompt_tokens=prompt,
        completion_tokens=completion,
        total_tokens=total,
    )


def _response_model(payload: Mapping[str, object]) -> str | None:
    value = payload.get("model")
    if value is None:
        return None
    if not isinstance(value, str) or len(value) > 300 or not _SAFE_IDENTIFIER.fullmatch(value):
        raise SafeBenchmarkError("invalid_response_model")
    return value


def _validate_api_base_url(value: str) -> str:
    parsed = urlsplit(value)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise SafeBenchmarkError("invalid_base_url")
    if parsed.username is not None or parsed.password is not None:
        raise SafeBenchmarkError("base_url_userinfo_forbidden")
    if parsed.query or parsed.fragment:
        raise SafeBenchmarkError("base_url_query_or_fragment_forbidden")
    normalized = value.rstrip("/")
    if not urlsplit(normalized).path.endswith("/v1"):
        raise SafeBenchmarkError("base_url_must_end_in_v1")
    return normalized


def _safe_transport_code(exc: Exception) -> str:
    name = type(exc).__name__
    safe_name = re.sub(r"[^A-Za-z0-9_]", "_", name)[:80]
    return f"transport_{safe_name or 'error'}"


class NimBenchmarkClient:
    """Small NIM HTTP client with explicit `/v1` base semantics."""

    def __init__(
        self,
        *,
        base_url: str,
        model: str,
        timeout_seconds: float,
        api_key: str | None = None,
    ) -> None:
        self.base_url = _validate_api_base_url(base_url)
        self.model = model
        headers = {"Accept": "application/json"}
        if api_key is not None:
            headers["Authorization"] = f"Bearer {api_key}"
        self._client = httpx.Client(
            headers=headers,
            timeout=timeout_seconds,
            follow_redirects=False,
            trust_env=False,
        )

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> NimBenchmarkClient:
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()

    def _url(self, path: str) -> str:
        return f"{self.base_url}/{path.lstrip('/')}"

    @staticmethod
    def _require_2xx(response: httpx.Response, endpoint_code: str) -> None:
        if not 200 <= response.status_code < 300:
            raise SafeBenchmarkError(f"http_{response.status_code}_{endpoint_code}")

    def _json_request(
        self, method: str, path: str, endpoint_code: str, payload: Mapping[str, object]
    ) -> Mapping[str, object]:
        try:
            response = self._client.request(method, self._url(path), json=payload)
        except Exception as exc:
            raise SafeBenchmarkError(_safe_transport_code(exc)) from exc
        self._require_2xx(response, endpoint_code)
        try:
            decoded = cast(object, response.json())
        except (ValueError, UnicodeDecodeError) as exc:
            raise SafeBenchmarkError(f"invalid_json_{endpoint_code}") from exc
        if not isinstance(decoded, dict):
            raise SafeBenchmarkError(f"invalid_object_{endpoint_code}")
        return cast(Mapping[str, object], decoded)

    def contract_check(self, *, metrics_required: bool) -> dict[str, object]:
        """Verify health, served model, and non-empty metric endpoints."""

        statuses: dict[str, int] = {}
        for path, code in (("health/live", "health_live"), ("health/ready", "health_ready")):
            try:
                response = self._client.get(self._url(path))
            except Exception as exc:
                raise SafeBenchmarkError(_safe_transport_code(exc)) from exc
            self._require_2xx(response, code)
            statuses[code] = response.status_code

        metrics_observation: dict[str, object]
        try:
            metrics_response = self._client.get(self._url("metrics"))
        except Exception as exc:
            if metrics_required:
                raise SafeBenchmarkError(_safe_transport_code(exc)) from exc
            metrics_observation = {
                "required": False,
                "status": "unavailable",
                "http_status": None,
                "non_empty": False,
                "probe_error_code": _safe_transport_code(exc),
            }
        else:
            metrics_non_empty = bool(metrics_response.content.strip())
            if 200 <= metrics_response.status_code < 300 and metrics_non_empty:
                metrics_observation = {
                    "required": metrics_required,
                    "status": "available",
                    "http_status": metrics_response.status_code,
                    "non_empty": True,
                    "probe_error_code": None,
                }
            elif metrics_required:
                if 200 <= metrics_response.status_code < 300:
                    raise SafeBenchmarkError("empty_metrics_response")
                raise SafeBenchmarkError(f"http_{metrics_response.status_code}_metrics")
            else:
                unsupported_statuses = {404, 405, 501}
                metrics_observation = {
                    "required": False,
                    "status": (
                        "unsupported"
                        if metrics_response.status_code in unsupported_statuses
                        else "empty"
                        if 200 <= metrics_response.status_code < 300
                        else "unavailable"
                    ),
                    "http_status": metrics_response.status_code,
                    "non_empty": False,
                    "probe_error_code": None,
                }

        try:
            models_response = self._client.get(self._url("models"))
        except Exception as exc:
            raise SafeBenchmarkError(_safe_transport_code(exc)) from exc
        self._require_2xx(models_response, "models")
        try:
            models_payload = cast(object, models_response.json())
        except (ValueError, UnicodeDecodeError) as exc:
            raise SafeBenchmarkError("invalid_json_models") from exc
        models = _mapping(models_payload, "models_response").get("data")
        if not isinstance(models, list):
            raise SafeBenchmarkError("invalid_models_data")
        observed_ids = {
            item.get("id")
            for item in models
            if isinstance(item, dict) and isinstance(item.get("id"), str)
        }
        if self.model not in observed_ids:
            raise SafeBenchmarkError("requested_model_not_served")
        statuses["models"] = models_response.status_code
        return {
            "status": "pass",
            "http_statuses": statuses,
            "requested_model_present": True,
            "served_model_id_observed": self.model,
            "metrics": metrics_observation,
        }

    def measure_llm(
        self,
        *,
        scenario: LlmScenario,
        request_index: int,
        fixtures: FixtureSet,
        seed: int,
        request_phase: LlmRequestPhase = "measured",
        reasoning_control_mode: ReasoningControlMode = "llama-standard",
    ) -> RequestMetric:
        payload: dict[str, object] = {
            "model": self.model,
            "messages": [
                {
                    "role": "system",
                    "content": _controlled_system_prompt(
                        fixtures.llm_system, reasoning_control_mode
                    ),
                },
                {
                    "role": "user",
                    "content": _unique_llm_request_prompt(
                        fixtures,
                        scenario,
                        request_phase=request_phase,
                        request_index=request_index,
                    ),
                },
            ],
            "max_tokens": scenario.max_output_tokens,
            "temperature": 0,
            "top_p": 1,
            "seed": seed,
            "stream": True,
            "stream_options": {"include_usage": True},
        }
        payload.update(_SYNTHETIC_LLM_FIXED_REQUEST_CONTROLS)
        started = time.perf_counter()
        first_token_at: float | None = None
        last_token_at: float | None = None
        observed_usage: LlmUsage | None = None
        observed_model: str | None = None
        error_code: str | None = None
        done_received = False

        try:
            with self._client.stream(
                "POST", self._url("chat/completions"), json=payload
            ) as response:
                self._require_2xx(response, "chat_completions")
                for raw_line in response.iter_lines():
                    received_at = time.perf_counter()
                    line = raw_line
                    if not line or not line.startswith("data:"):
                        continue
                    event = line.removeprefix("data:").strip()
                    if event == "[DONE]":
                        done_received = True
                        break
                    try:
                        event_payload = cast(object, json.loads(event))
                    except json.JSONDecodeError:
                        error_code = "invalid_stream_json"
                        break
                    if not isinstance(event_payload, dict):
                        error_code = "invalid_stream_event"
                        break
                    event_mapping = cast(Mapping[str, object], event_payload)
                    event_usage = _llm_usage(event_mapping)
                    if event_usage is not None:
                        observed_usage = event_usage
                    event_model = _response_model(event_mapping)
                    if event_model is not None:
                        observed_model = event_model

                    choices = event_mapping.get("choices")
                    if not isinstance(choices, list) or not choices:
                        continue
                    first_choice = choices[0]
                    if not isinstance(first_choice, dict):
                        error_code = "invalid_stream_choice"
                        break
                    delta = first_choice.get("delta")
                    if not isinstance(delta, dict):
                        continue
                    content = delta.get("content")
                    reasoning_content = delta.get("reasoning_content")
                    generated_delta_present = (isinstance(content, str) and bool(content)) or (
                        isinstance(reasoning_content, str) and bool(reasoning_content)
                    )
                    if generated_delta_present:
                        if first_token_at is None:
                            first_token_at = received_at
                        last_token_at = received_at
        except SafeBenchmarkError as exc:
            error_code = exc.code
        except Exception as exc:
            error_code = _safe_transport_code(exc)

        finished = time.perf_counter()
        ttft = first_token_at - started if first_token_at is not None else None
        decode_duration = (
            last_token_at - first_token_at
            if first_token_at is not None and last_token_at is not None
            else None
        )
        decode_tokens_per_second: float | None = None
        if error_code is None and not done_received:
            error_code = "missing_stream_done_marker"
        if error_code is None and first_token_at is None:
            error_code = "missing_stream_generated_tokens"
        if error_code is None and observed_usage is None:
            error_code = "missing_actual_usage"
        if (
            error_code is None
            and observed_usage is not None
            and observed_usage.completion_tokens <= 0
        ):
            error_code = "missing_completion_tokens"
        if (
            error_code is None
            and observed_usage is not None
            and observed_usage.completion_tokens != scenario.max_output_tokens
        ):
            error_code = "output_token_target_mismatch"
        if error_code is None and (decode_duration is None or decode_duration <= 0):
            error_code = "decode_interval_unavailable"
        if error_code is None and observed_model is not None and observed_model != self.model:
            error_code = "response_model_mismatch"
        if error_code is None and observed_usage is not None and decode_duration is not None:
            decode_tokens_per_second = observed_usage.completion_tokens / decode_duration

        return RequestMetric(
            kind="llm",
            scenario=scenario.name,
            request_index=request_index,
            concurrency=scenario.concurrency,
            status="ok" if error_code is None else "failed",
            error_code=error_code,
            target_context_tokens=scenario.target_context_tokens,
            target_input_tokens=scenario.target_input_tokens,
            max_output_tokens=scenario.max_output_tokens,
            prompt_tokens_actual=(observed_usage.prompt_tokens if observed_usage else None),
            completion_tokens_actual=(observed_usage.completion_tokens if observed_usage else None),
            total_tokens_actual=(observed_usage.total_tokens if observed_usage else None),
            ttft_seconds=ttft,
            decode_duration_seconds=decode_duration,
            decode_tokens_per_second=decode_tokens_per_second,
            total_latency_seconds=finished - started,
            response_model_observed=observed_model,
        )

    def embedding_call(self, *, inputs: Sequence[str], input_type: str) -> EmbeddingCall:
        started = time.perf_counter()
        payload = self._json_request(
            "POST",
            "embeddings",
            "embeddings",
            {
                "model": self.model,
                "input": list(inputs),
                "input_type": input_type,
                "encoding_format": "float",
            },
        )
        latency = time.perf_counter() - started
        raw_data = payload.get("data")
        if not isinstance(raw_data, list) or len(raw_data) != len(inputs):
            raise SafeBenchmarkError("invalid_embedding_count")
        indexed_vectors: dict[int, tuple[float, ...]] = {}
        dimension: int | None = None
        for position, item in enumerate(raw_data):
            if not isinstance(item, dict):
                raise SafeBenchmarkError("invalid_embedding_item")
            raw_index = item.get("index")
            index = position if raw_index is None else raw_index
            if (
                not isinstance(index, int)
                or isinstance(index, bool)
                or not 0 <= index < len(inputs)
                or index in indexed_vectors
            ):
                raise SafeBenchmarkError("invalid_embedding_index")
            raw_vector = item.get("embedding")
            if not isinstance(raw_vector, list) or not raw_vector:
                raise SafeBenchmarkError("invalid_embedding_vector")
            vector: list[float] = []
            for value in raw_vector:
                if not isinstance(value, (int, float)) or isinstance(value, bool):
                    raise SafeBenchmarkError("invalid_embedding_value")
                converted = float(value)
                if not math.isfinite(converted):
                    raise SafeBenchmarkError("non_finite_embedding_value")
                vector.append(converted)
            if dimension is None:
                dimension = len(vector)
            elif len(vector) != dimension:
                raise SafeBenchmarkError("inconsistent_embedding_dimension")
            indexed_vectors[index] = tuple(vector)
        vectors = tuple(indexed_vectors[index] for index in range(len(inputs)))
        return EmbeddingCall(
            vectors=vectors,
            usage=_retriever_usage(payload),
            latency_seconds=latency,
            response_model=_response_model(payload),
        )

    def measure_embedding(
        self,
        *,
        scenario: str,
        request_index: int,
        inputs: Sequence[str],
        input_type: str,
    ) -> RequestMetric:
        try:
            result = self.embedding_call(inputs=inputs, input_type=input_type)
            error_code = (
                "response_model_mismatch"
                if result.response_model is not None and result.response_model != self.model
                else None
            )
        except SafeBenchmarkError as exc:
            result = None
            error_code = exc.code
        except Exception as exc:
            result = None
            error_code = _safe_transport_code(exc)
        return RequestMetric(
            kind="embedding",
            scenario=scenario,
            request_index=request_index,
            concurrency=1,
            status="ok" if error_code is None else "failed",
            error_code=error_code,
            prompt_tokens_actual=(result.usage.prompt_tokens if result and result.usage else None),
            completion_tokens_actual=(
                result.usage.completion_tokens if result and result.usage else None
            ),
            total_tokens_actual=(result.usage.total_tokens if result and result.usage else None),
            total_latency_seconds=(result.latency_seconds if result else None),
            batch_size=len(inputs),
            vector_dimension_observed=(len(result.vectors[0]) if result else None),
            response_model_observed=(result.response_model if result else None),
        )

    def reranking_call(self, *, query: str, passages: Sequence[str]) -> RerankingCall:
        started = time.perf_counter()
        payload = self._json_request(
            "POST",
            "ranking",
            "ranking",
            {
                "model": self.model,
                "query": {"text": query},
                "passages": [{"text": passage} for passage in passages],
            },
        )
        latency = time.perf_counter() - started
        raw_rankings = payload.get("rankings")
        if not isinstance(raw_rankings, list) or len(raw_rankings) != len(passages):
            raise SafeBenchmarkError("invalid_ranking_count")
        rankings: list[RerankingItem] = []
        for item in raw_rankings:
            if not isinstance(item, dict):
                raise SafeBenchmarkError("invalid_ranking_item")
            index = item.get("index")
            logit = item.get("logit")
            if not isinstance(index, int) or isinstance(index, bool):
                raise SafeBenchmarkError("invalid_ranking_index")
            if not isinstance(logit, (int, float)) or isinstance(logit, bool):
                raise SafeBenchmarkError("invalid_ranking_logit")
            logit_float = float(logit)
            if not math.isfinite(logit_float):
                raise SafeBenchmarkError("non_finite_ranking_logit")
            rankings.append(RerankingItem(index=index, logit=logit_float))
        if {item.index for item in rankings} != set(range(len(passages))):
            raise SafeBenchmarkError("invalid_ranking_index_set")
        return RerankingCall(
            rankings=tuple(rankings),
            usage=_retriever_usage(payload),
            latency_seconds=latency,
            response_model=_response_model(payload),
        )

    def measure_reranking(
        self,
        *,
        scenario: str,
        request_index: int,
        query: str,
        passages: Sequence[str],
    ) -> RequestMetric:
        try:
            result = self.reranking_call(query=query, passages=passages)
            error_code = (
                "response_model_mismatch"
                if result.response_model is not None and result.response_model != self.model
                else None
            )
        except SafeBenchmarkError as exc:
            result = None
            error_code = exc.code
        except Exception as exc:
            result = None
            error_code = _safe_transport_code(exc)
        return RequestMetric(
            kind="reranking",
            scenario=scenario,
            request_index=request_index,
            concurrency=1,
            status="ok" if error_code is None else "failed",
            error_code=error_code,
            prompt_tokens_actual=(result.usage.prompt_tokens if result and result.usage else None),
            completion_tokens_actual=(
                result.usage.completion_tokens if result and result.usage else None
            ),
            total_tokens_actual=(result.usage.total_tokens if result and result.usage else None),
            total_latency_seconds=(result.latency_seconds if result else None),
            passage_count=len(passages),
            response_model_observed=(result.response_model if result else None),
        )


def _cosine(left: Sequence[float], right: Sequence[float]) -> float:
    if len(left) != len(right) or not left:
        raise SafeBenchmarkError("semantic_dimension_mismatch")
    numerator = sum(a * b for a, b in zip(left, right, strict=True))
    left_norm = math.sqrt(sum(value * value for value in left))
    right_norm = math.sqrt(sum(value * value for value in right))
    if left_norm == 0 or right_norm == 0:
        raise SafeBenchmarkError("semantic_zero_vector")
    return numerator / (left_norm * right_norm)


def embedding_semantic_check(client: NimBenchmarkClient, fixtures: FixtureSet) -> dict[str, object]:
    """Run a basic bilingual relevance sanity check without Qdrant or ingestion."""

    query = client.embedding_call(inputs=[fixtures.embedding_query], input_type="query")
    passages = client.embedding_call(
        inputs=[fixtures.embedding_positive, fixtures.embedding_negative], input_type="passage"
    )
    positive_similarity = _cosine(query.vectors[0], passages.vectors[0])
    negative_similarity = _cosine(query.vectors[0], passages.vectors[1])
    passed = positive_similarity > negative_similarity
    return {
        "status": "pass" if passed else "fail",
        "fixture_id": "vi-capital-positive-vs-negative",
        "positive_similarity": positive_similarity,
        "negative_similarity": negative_similarity,
        "dimension_observed": len(query.vectors[0]),
        "quality_scope": "basic_semantic_sanity_only_not_phase5_retrieval_eval",
    }


def reranking_semantic_check(client: NimBenchmarkClient, fixtures: FixtureSet) -> dict[str, object]:
    """Check that the positive synthetic passage ranks above the negative one."""

    result = client.reranking_call(
        query=fixtures.reranking_query,
        passages=[fixtures.reranking_positive, fixtures.reranking_negative],
    )
    ordered = sorted(result.rankings, key=lambda item: item.logit, reverse=True)
    passed = bool(ordered) and ordered[0].index == 0
    return {
        "status": "pass" if passed else "fail",
        "fixture_id": "vi-capital-positive-vs-negative",
        "ordered_indices": [item.index for item in ordered],
        "quality_scope": "basic_semantic_sanity_only_not_phase5_retrieval_eval",
    }


def _execute_requests(
    count: int,
    concurrency: int,
    operation: Callable[[int], RequestMetric],
) -> tuple[list[RequestMetric], float]:
    started = time.perf_counter()
    if count == 0:
        return [], 0.0
    with ThreadPoolExecutor(max_workers=concurrency) as executor:
        metrics = list(executor.map(operation, range(count)))
    return metrics, time.perf_counter() - started


def _numeric(metrics: Sequence[RequestMetric], field: str) -> list[float]:
    values: list[float] = []
    for metric in metrics:
        value = getattr(metric, field)
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            values.append(float(value))
    return values


def summarize_scenario(
    metrics: Sequence[RequestMetric], *, wall_seconds: float, warmup_failures: int
) -> dict[str, object]:
    successful = [metric for metric in metrics if metric.status == "ok"]
    failed = [metric for metric in metrics if metric.status == "failed"]
    summary: dict[str, object] = {
        "status": "pass" if not failed and warmup_failures == 0 else "fail",
        "request_count": len(metrics),
        "success_count": len(successful),
        "failure_count": len(failed),
        "warmup_failure_count": warmup_failures,
        "wall_seconds": wall_seconds,
        "requests_per_second": (len(successful) / wall_seconds if wall_seconds > 0 else None),
        "error_counts": {
            code: sum(metric.error_code == code for metric in failed)
            for code in sorted({metric.error_code for metric in failed if metric.error_code})
        },
        "percentile_method": "linear_interpolation_rank_(n_minus_1)_times_q",
    }
    for field in (
        "prompt_tokens_actual",
        "completion_tokens_actual",
        "total_tokens_actual",
        "ttft_seconds",
        "decode_duration_seconds",
        "decode_tokens_per_second",
        "total_latency_seconds",
    ):
        values = _numeric(metrics, field)
        summary[field] = {
            "observed_count": len(values),
            "p50": percentile(values, 0.50),
            "p95": percentile(values, 0.95),
        }
    completion_tokens = _numeric(successful, "completion_tokens_actual")
    summary["aggregate_completion_tokens_per_second"] = (
        sum(completion_tokens) / wall_seconds if wall_seconds > 0 and completion_tokens else None
    )
    return summary


def _run_llm(
    client: NimBenchmarkClient, config: RunnerConfig, fixtures: FixtureSet
) -> tuple[list[dict[str, object]], list[RequestMetric], dict[str, object]]:
    reasoning_control_mode = _reasoning_control_mode("llm", config.reasoning_control_mode)
    assert reasoning_control_mode is not None
    reports: list[dict[str, object]] = []
    all_metrics: list[RequestMetric] = []
    for scenario in llm_scenarios(config.include_long_context):
        warmup_operation = lambda index, scenario=scenario: client.measure_llm(  # noqa: E731
            scenario=scenario,
            request_index=index,
            fixtures=fixtures,
            seed=config.seed,
            request_phase="warmup",
            reasoning_control_mode=reasoning_control_mode,
        )
        measured_operation = lambda index, scenario=scenario: client.measure_llm(  # noqa: E731
            scenario=scenario,
            request_index=index,
            fixtures=fixtures,
            seed=config.seed,
            request_phase="measured",
            reasoning_control_mode=reasoning_control_mode,
        )
        warmups, _ = _execute_requests(
            config.warmup_requests, scenario.concurrency, warmup_operation
        )
        measured, wall_seconds = _execute_requests(
            config.measured_requests, scenario.concurrency, measured_operation
        )
        all_metrics.extend(measured)
        summary = summarize_scenario(
            measured,
            wall_seconds=wall_seconds,
            warmup_failures=sum(metric.status == "failed" for metric in warmups),
        )
        actual_prompt_tokens = _numeric(measured, "prompt_tokens_actual")
        measured_completion_tokens = [
            metric.completion_tokens_actual
            for metric in measured
            if metric.completion_tokens_actual is not None
        ]
        warmup_completion_tokens = [
            metric.completion_tokens_actual
            for metric in warmups
            if metric.completion_tokens_actual is not None
        ]
        actual_p50 = percentile(actual_prompt_tokens, 0.50)
        minimum_ratio, maximum_ratio = (0.80, 1.20)
        observed_min = min(actual_prompt_tokens) if actual_prompt_tokens else None
        observed_max = max(actual_prompt_tokens) if actual_prompt_tokens else None
        observed_context_min = (
            observed_min + scenario.max_output_tokens if observed_min is not None else None
        )
        observed_context_max = (
            observed_max + scenario.max_output_tokens if observed_max is not None else None
        )
        context_lower_bound = (
            scenario.target_context_tokens - 512
            if scenario.target_context_tokens is not None
            else None
        )
        if scenario.family == "long":
            assert scenario.target_context_tokens is not None
            assert context_lower_bound is not None
            input_target_pass = (
                len(actual_prompt_tokens) == config.measured_requests
                and observed_context_min is not None
                and observed_context_max is not None
                and observed_context_min >= context_lower_bound
                and observed_context_max <= scenario.target_context_tokens
            )
        else:
            input_target_pass = (
                len(actual_prompt_tokens) == config.measured_requests
                and observed_min is not None
                and observed_max is not None
                and observed_min >= scenario.target_input_tokens * minimum_ratio
                and observed_max <= scenario.target_input_tokens * maximum_ratio
            )
        measured_output_target_pass = len(
            measured_completion_tokens
        ) == config.measured_requests and all(
            count == scenario.max_output_tokens for count in measured_completion_tokens
        )
        warmup_output_target_pass = len(warmup_completion_tokens) == config.warmup_requests and all(
            count == scenario.max_output_tokens for count in warmup_completion_tokens
        )
        output_target_pass = measured_output_target_pass and warmup_output_target_pass
        summary["target_input_tokens"] = scenario.target_input_tokens
        summary["target_context_tokens"] = scenario.target_context_tokens
        summary["target_vs_actual_p50_ratio"] = (
            actual_p50 / scenario.target_input_tokens if actual_p50 is not None else None
        )
        summary["max_output_tokens"] = scenario.max_output_tokens
        summary["concurrency"] = scenario.concurrency
        summary["warmup_required_count"] = config.warmup_requests
        summary["input_token_target_check"] = {
            "status": "pass" if input_target_pass else "fail",
            "required_relation": (
                "every_observed_prompt_plus_max_output_within_absolute_context_window"
                if scenario.family == "long"
                else "every_observed_prompt_within_target_ratio"
            ),
            "target_input_tokens": scenario.target_input_tokens,
            "target_context_tokens": scenario.target_context_tokens,
            "observed_prompt_tokens_min": observed_min,
            "observed_prompt_tokens_max": observed_max,
            "max_output_tokens": scenario.max_output_tokens,
            "observed_prompt_plus_max_output_min": observed_context_min,
            "observed_prompt_plus_max_output_max": observed_context_max,
            "absolute_context_lower_bound": context_lower_bound,
            "absolute_context_upper_bound": scenario.target_context_tokens,
            "minimum_ratio": minimum_ratio if scenario.family != "long" else None,
            "maximum_ratio": maximum_ratio if scenario.family != "long" else None,
        }
        summary["output_token_target_check"] = {
            "status": "pass" if output_target_pass else "fail",
            "required_relation": "completion_tokens_actual_equals_max_output_tokens",
            "target_completion_tokens": scenario.max_output_tokens,
            "fixed_request_control": {
                "ignore_eos": True,
                "scope": "synthetic_llm_benchmark_only",
            },
            "measured": {
                "required_count": config.measured_requests,
                "observed_count": len(measured_completion_tokens),
                "matching_count": sum(
                    count == scenario.max_output_tokens for count in measured_completion_tokens
                ),
                "observed_min": (
                    min(measured_completion_tokens) if measured_completion_tokens else None
                ),
                "observed_max": (
                    max(measured_completion_tokens) if measured_completion_tokens else None
                ),
            },
            "warmup": {
                "required_count": config.warmup_requests,
                "observed_count": len(warmup_completion_tokens),
                "matching_count": sum(
                    count == scenario.max_output_tokens for count in warmup_completion_tokens
                ),
                "observed_min": (
                    min(warmup_completion_tokens) if warmup_completion_tokens else None
                ),
                "observed_max": (
                    max(warmup_completion_tokens) if warmup_completion_tokens else None
                ),
            },
        }
        if not input_target_pass or not output_target_pass:
            summary["status"] = "fail"
        reports.append({"name": scenario.name, "summary": summary})
    return (
        reports,
        all_metrics,
        {
            "status": "not_applicable",
            "scope": (
                "LLM benchmark uses deterministic synthetic context; no retrieval quality claim"
            ),
        },
    )


def _run_embedding(
    client: NimBenchmarkClient, config: RunnerConfig, fixtures: FixtureSet
) -> tuple[list[dict[str, object]], list[RequestMetric], dict[str, object]]:
    semantic = embedding_semantic_check(client, fixtures)
    reports: list[dict[str, object]] = []
    all_metrics: list[RequestMetric] = []
    for batch_size in (1, 16):
        scenario = f"embedding-batch-{batch_size}"
        inputs = [
            fixtures.embedding_performance_template.format(index=index)
            for index in range(batch_size)
        ]
        operation = lambda index, scenario=scenario, inputs=inputs: client.measure_embedding(  # noqa: E731
            scenario=scenario,
            request_index=index,
            inputs=inputs,
            input_type="passage",
        )
        warmups, _ = _execute_requests(config.warmup_requests, 1, operation)
        measured, wall_seconds = _execute_requests(config.measured_requests, 1, operation)
        all_metrics.extend(measured)
        summary = summarize_scenario(
            measured,
            wall_seconds=wall_seconds,
            warmup_failures=sum(metric.status == "failed" for metric in warmups),
        )
        summary["batch_size"] = batch_size
        summary["concurrency"] = 1
        summary["warmup_required_count"] = config.warmup_requests
        summary["vector_dimension_observed_values"] = sorted(
            {
                metric.vector_dimension_observed
                for metric in measured
                if metric.vector_dimension_observed is not None
            }
        )
        reports.append({"name": scenario, "summary": summary})
    return reports, all_metrics, semantic


def _run_reranking(
    client: NimBenchmarkClient, config: RunnerConfig, fixtures: FixtureSet
) -> tuple[list[dict[str, object]], list[RequestMetric], dict[str, object]]:
    semantic = reranking_semantic_check(client, fixtures)
    reports: list[dict[str, object]] = []
    all_metrics: list[RequestMetric] = []
    for passage_count in (2, 16):
        scenario = f"reranking-passages-{passage_count}"
        passages = [
            fixtures.reranking_performance_template.format(index=index)
            for index in range(passage_count)
        ]
        operation = lambda index, scenario=scenario, passages=passages: client.measure_reranking(  # noqa: E731
            scenario=scenario,
            request_index=index,
            query=fixtures.reranking_query,
            passages=passages,
        )
        warmups, _ = _execute_requests(config.warmup_requests, 1, operation)
        measured, wall_seconds = _execute_requests(config.measured_requests, 1, operation)
        all_metrics.extend(measured)
        summary = summarize_scenario(
            measured,
            wall_seconds=wall_seconds,
            warmup_failures=sum(metric.status == "failed" for metric in warmups),
        )
        summary["passage_count"] = passage_count
        summary["concurrency"] = 1
        summary["warmup_required_count"] = config.warmup_requests
        reports.append({"name": scenario, "summary": summary})
    return reports, all_metrics, semantic


def _declared_metadata(value: str | int | None) -> dict[str, object]:
    return {
        "value": value,
        "evidence_source": (
            "operator_cli_not_independently_verified_by_runner"
            if value is not None
            else "unverified"
        ),
    }


def execute_benchmark(
    config: RunnerConfig, fixtures: FixtureSet, api_key: str | None = None
) -> tuple[dict[str, object], list[RequestMetric]]:
    """Execute one candidate/kind run and return serializable evidence."""

    reasoning_control_mode = _reasoning_control_mode(config.kind, config.reasoning_control_mode)
    started_wall = datetime.now(UTC)
    started_monotonic = time.perf_counter()
    with NimBenchmarkClient(
        base_url=config.base_url,
        model=config.model,
        timeout_seconds=config.timeout_seconds,
        api_key=api_key,
    ) as client:
        contract = client.contract_check(metrics_required=config.metrics_required)
        if config.kind == "llm":
            scenarios, metrics, semantic = _run_llm(client, config, fixtures)
        elif config.kind == "embedding":
            scenarios, metrics, semantic = _run_embedding(client, config, fixtures)
        else:
            scenarios, metrics, semantic = _run_reranking(client, config, fixtures)

    scenarios_pass = all(
        isinstance(item.get("summary"), dict)
        and cast(dict[str, object], item["summary"]).get("status") == "pass"
        for item in scenarios
    )
    semantic_pass = semantic.get("status") in {"pass", "not_applicable"}
    status = "pass" if scenarios_pass and semantic_pass else "fail"
    completed_wall = datetime.now(UTC)
    missing_metadata = [
        name
        for name, value in (
            ("image_ref", config.image_ref),
            ("image_digest", config.image_digest),
            ("nim_version", config.nim_version),
            ("runtime_profile", config.runtime_profile),
            ("precision", config.precision),
            ("max_model_length", config.max_model_length),
            ("license_id", config.license_id),
        )
        if value is None
    ]
    report: dict[str, object] = {
        "schema_version": EVIDENCE_SCHEMA_VERSION,
        "status": status,
        "kind": config.kind,
        "candidate": {
            "candidate_id": config.candidate_id,
            "requested_model_id": config.model,
            "image_ref": _declared_metadata(config.image_ref),
            "image_digest": _declared_metadata(config.image_digest),
            "license_id": _declared_metadata(config.license_id),
        },
        "runtime": {
            "served_model_id": {
                "value": config.model,
                "evidence_source": "observed_get_v1_models",
            },
            "nim_version": _declared_metadata(config.nim_version),
            "profile": _declared_metadata(config.runtime_profile),
            "precision": _declared_metadata(config.precision),
            "max_model_length": _declared_metadata(config.max_model_length),
            "metadata_warning": (
                "CLI-declared runtime fields are retained as declarations; the runner does "
                "not infer profile, precision, NIM version, or max length from model/image names."
            ),
        },
        "metadata_completeness": {
            "status": "complete" if not missing_metadata else "incomplete",
            "unverified_or_missing_fields": missing_metadata,
        },
        "contract_check": contract,
        "fixture": {
            "schema_version": fixtures.schema_version,
            "sha256": fixtures.sha256,
            "classification": "synthetic_non_sensitive",
        },
        "run_config": {
            "measured_requests_per_scenario": config.measured_requests,
            "warmup_requests_per_scenario": config.warmup_requests,
            "measured_runtime_state": (
                "warm_after_runner_warmup"
                if config.warmup_requests > 0
                else "unwarmed_not_claimed_cold"
            ),
            "timeout_seconds": config.timeout_seconds,
            "metrics_required": config.metrics_required,
            "seed": config.seed,
            "long_context_opt_in": config.include_long_context,
            "reasoning_control_mode": reasoning_control_mode,
            "llm_prompt_uniqueness_control": (
                dict(_LLM_PROMPT_UNIQUENESS_CONTROL)
                if config.kind == "llm"
                else {"status": "not_applicable"}
            ),
            "system_prompt_persisted": False,
            "base_url_persisted": False,
            "credentials_persisted": False,
        },
        "metric_definitions": {
            "ttft_seconds": (
                "client timestamp immediately before HTTP request dispatch to first non-empty "
                "streamed generated-token delta (content or reasoning_content)"
            ),
            "decode_duration_seconds": (
                "first non-empty streamed generated-token delta to last non-empty generated-"
                "token delta; content and reasoning_content are timed but never persisted"
            ),
            "decode_tokens_per_second": (
                "response-reported completion_tokens divided by decode_duration_seconds"
            ),
            "total_latency_seconds": "request start to HTTP stream completion",
            "token_counts": (
                "actual response usage only; missing usage is a failed LLM measurement"
            ),
            "long_context_targets": (
                "32K/64K/128K are total-context capability targets; synthetic input "
                "reserves max output plus 256 tokens for chat-template safety"
            ),
            "scope": (
                "client-observed engine HTTP latency, measured immediately before request "
                "dispatch; not server/backend receive time and not auth/retrieval/rerank/"
                "end-to-end application latency"
            ),
            "input_token_target_check": (
                "every response-reported prompt-token count must stay within 80-120% for "
                "short/RAG scenarios; for long-context capability scenarios every observed "
                "prompt_tokens plus max_output_tokens must be between target_context_tokens "
                "minus 512 and target_context_tokens inclusive"
            ),
            "output_token_target_check": (
                "synthetic LLM benchmark requests use the fixed non-configurable "
                "ignore_eos=true control, and every warmup and measured response-reported "
                "completion_tokens count must exactly equal the scenario max_output_tokens; "
                "this control is not used by smoke or quality requests"
            ),
            "prompt_uniqueness_control": (
                "every LLM warmup and measured request uses a deterministic SHA-256 "
                "nonce derived from scenario, request phase, and request index as the "
                "first user-content line before synthetic context; warmup and measured "
                "namespaces are disjoint, full user prompts are not reused, and nonce "
                "values are never persisted"
            ),
        },
        "semantic_check": semantic,
        "scenarios": scenarios,
        "started_at_utc": started_wall.isoformat(),
        "completed_at_utc": completed_wall.isoformat(),
        "run_duration_seconds": time.perf_counter() - started_monotonic,
    }
    return report, metrics


_CSV_FIELDS = (
    "kind",
    "scenario",
    "request_index",
    "concurrency",
    "status",
    "error_code",
    "target_context_tokens",
    "target_input_tokens",
    "max_output_tokens",
    "prompt_tokens_actual",
    "completion_tokens_actual",
    "total_tokens_actual",
    "ttft_seconds",
    "decode_duration_seconds",
    "decode_tokens_per_second",
    "total_latency_seconds",
    "batch_size",
    "passage_count",
    "vector_dimension_observed",
    "response_model_observed",
)


def _csv_safe_cell(value: object) -> object:
    if isinstance(value, str) and value.lstrip(" \t\r\n").startswith(("=", "+", "-", "@")):
        return f"'{value}"
    return value


def _write_json_synced(path: Path, report_content: str) -> None:
    with path.open("x", encoding="utf-8") as handle:
        handle.write(report_content)
        handle.flush()
        os.fsync(handle.fileno())


def _write_csv_synced(path: Path, metrics: Sequence[RequestMetric]) -> None:
    with path.open("x", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=_CSV_FIELDS, extrasaction="ignore")
        writer.writeheader()
        for metric in metrics:
            writer.writerow({key: _csv_safe_cell(value) for key, value in asdict(metric).items()})
        handle.flush()
        os.fsync(handle.fileno())


def write_evidence(
    output_directory: Path, report: Mapping[str, object], metrics: Sequence[RequestMetric]
) -> None:
    """Atomically publish complete JSON and CSV evidence as one directory."""

    if output_directory.exists():
        raise SafeBenchmarkError("output_directory_already_exists")
    try:
        report_content = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    except (TypeError, ValueError):
        raise SafeBenchmarkError("evidence_serialization_failed") from None

    previous_umask = os.umask(0o027)
    staging_directory: Path | None = None
    lock_fd: int | None = None
    lock_path = output_directory.parent / f".{output_directory.name}.lock"
    try:
        output_directory.parent.mkdir(parents=True, exist_ok=True)
        lock_fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        staging_directory = Path(
            tempfile.mkdtemp(prefix=f".{output_directory.name}.tmp-", dir=output_directory.parent)
        )
        _write_json_synced(staging_directory / "report.json", report_content)
        _write_csv_synced(staging_directory / "requests.csv", metrics)
        directory_fd = os.open(staging_directory, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
        if output_directory.exists():
            raise FileExistsError
        os.rename(staging_directory, output_directory)
        staging_directory = None
        parent_fd = os.open(output_directory.parent, os.O_RDONLY)
        try:
            os.fsync(parent_fd)
        finally:
            os.close(parent_fd)
    except FileExistsError:
        if output_directory.exists():
            raise SafeBenchmarkError("output_directory_already_exists") from None
        raise SafeBenchmarkError("evidence_write_in_progress") from None
    except (OSError, csv.Error, TypeError, ValueError):
        raise SafeBenchmarkError("evidence_write_failed") from None
    finally:
        if lock_fd is not None:
            os.close(lock_fd)
            with suppress(OSError):
                lock_path.unlink(missing_ok=True)
        if staging_directory is not None:
            shutil.rmtree(staging_directory, ignore_errors=True)
        os.umask(previous_umask)


def _positive_int(value: str) -> int:
    parsed = int(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("must be a positive integer")
    return parsed


def _non_negative_int(value: str) -> int:
    parsed = int(value)
    if parsed < 0:
        raise argparse.ArgumentTypeError("must be a non-negative integer")
    return parsed


def _positive_float(value: str) -> float:
    parsed = float(value)
    if not math.isfinite(parsed) or parsed <= 0:
        raise argparse.ArgumentTypeError("must be a positive finite number")
    return parsed


def _read_api_key(path: Path | None) -> str | None:
    if path is None:
        return None
    try:
        value = path.read_text(encoding="utf-8").strip()
    except OSError as exc:
        raise SafeBenchmarkError("api_key_file_unreadable") from exc
    if not value or "\n" in value or "\r" in value:
        raise SafeBenchmarkError("api_key_file_invalid")
    return value


def _optional_identifier(value: str | None, field: str) -> str | None:
    if value is None:
        return None
    if not _SAFE_IDENTIFIER.fullmatch(value):
        raise SafeBenchmarkError(f"invalid_{field}")
    return value


def _optional_image_reference(value: str | None) -> str | None:
    if value is None:
        return None
    if len(value) > 512 or not _SAFE_IMAGE_REFERENCE.fullmatch(value):
        raise SafeBenchmarkError("invalid_image_ref")
    return value


def failure_report(
    config: RunnerConfig, fixtures: FixtureSet, error_code: str
) -> dict[str, object]:
    """Build minimal evidence for a failed live contract without sensitive details."""

    return {
        "schema_version": EVIDENCE_SCHEMA_VERSION,
        "status": "fail",
        "kind": config.kind,
        "candidate": {
            "candidate_id": config.candidate_id,
            "requested_model_id": config.model,
            "image_ref": _declared_metadata(config.image_ref),
            "image_digest": _declared_metadata(config.image_digest),
            "license_id": _declared_metadata(config.license_id),
        },
        "fixture": {
            "schema_version": fixtures.schema_version,
            "sha256": fixtures.sha256,
            "classification": "synthetic_non_sensitive",
        },
        "failure": {
            "error_code": error_code,
            "detail_persisted": False,
        },
        "run_config": {
            "reasoning_control_mode": config.reasoning_control_mode,
            "llm_prompt_uniqueness_control": (
                dict(_LLM_PROMPT_UNIQUENESS_CONTROL)
                if config.kind == "llm"
                else {"status": "not_applicable"}
            ),
            "system_prompt_persisted": False,
            "base_url_persisted": False,
            "credentials_persisted": False,
        },
        "completed_at_utc": datetime.now(UTC).isoformat(),
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Benchmark one already-running Phase 3 NIM candidate and emit secret-safe JSON/CSV."
        )
    )
    parser.add_argument("--kind", choices=("llm", "embedding", "reranking"), required=True)
    parser.add_argument(
        "--base-url",
        required=True,
        help="NIM API prefix ending in /v1; it is validated but never persisted.",
    )
    parser.add_argument("--model", required=True, help="Exact ID observed from GET /v1/models.")
    parser.add_argument("--candidate-id", required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--fixture-file", type=Path, default=DEFAULT_FIXTURE_PATH)
    parser.add_argument("--api-key-file", type=Path)
    parser.add_argument("--requests", type=_positive_int, default=DEFAULT_MEASURED_REQUESTS)
    parser.add_argument("--warmup", type=_non_negative_int, default=DEFAULT_WARMUP_REQUESTS)
    parser.add_argument("--timeout-seconds", type=_positive_float, default=DEFAULT_TIMEOUT_SECONDS)
    metrics_group = parser.add_mutually_exclusive_group()
    metrics_group.add_argument(
        "--metrics-required",
        dest="metrics_required",
        action="store_true",
        default=None,
        help="Fail if /v1/metrics is absent or empty.",
    )
    metrics_group.add_argument(
        "--metrics-optional",
        dest="metrics_required",
        action="store_false",
        help="Record /v1/metrics support without making it a hard gate.",
    )
    parser.add_argument("--seed", type=int, default=17)
    parser.add_argument(
        "--reasoning-control-mode",
        choices=tuple(_REASONING_CONTROL_TEXT),
        help=(
            "Required for LLM candidates; selects a fixed model-specific control without "
            "accepting prompt text."
        ),
    )
    parser.add_argument(
        "--include-long-context",
        action="store_true",
        help="Opt in to 32K, 64K, and 128K capability scenarios.",
    )
    parser.add_argument("--image-ref")
    parser.add_argument("--image-digest")
    parser.add_argument("--nim-version")
    parser.add_argument("--runtime-profile")
    parser.add_argument("--precision")
    parser.add_argument("--max-model-length", type=_positive_int)
    parser.add_argument("--license-id")
    return parser


def config_from_args(args: argparse.Namespace) -> RunnerConfig:
    kind = cast(BenchmarkKind, args.kind)
    model = _optional_identifier(cast(str, args.model), "model")
    candidate_id = _optional_identifier(cast(str, args.candidate_id), "candidate_id")
    if model is None or candidate_id is None:
        raise SafeBenchmarkError("missing_candidate_identity")
    image_digest = cast(str | None, args.image_digest)
    if image_digest is not None and not _SHA256_DIGEST.fullmatch(image_digest):
        raise SafeBenchmarkError("invalid_image_digest")
    base_url = _validate_api_base_url(cast(str, args.base_url))
    reasoning_control_mode = _reasoning_control_mode(
        kind, cast(str | None, args.reasoning_control_mode)
    )
    return RunnerConfig(
        kind=kind,
        base_url=base_url,
        model=model,
        candidate_id=candidate_id,
        measured_requests=cast(int, args.requests),
        warmup_requests=cast(int, args.warmup),
        timeout_seconds=cast(float, args.timeout_seconds),
        metrics_required=(
            cast(bool, args.metrics_required)
            if args.metrics_required is not None
            else kind == "llm"
        ),
        include_long_context=cast(bool, args.include_long_context),
        seed=cast(int, args.seed),
        image_ref=_optional_image_reference(cast(str | None, args.image_ref)),
        image_digest=image_digest,
        nim_version=_optional_identifier(cast(str | None, args.nim_version), "nim_version"),
        runtime_profile=_optional_identifier(
            cast(str | None, args.runtime_profile), "runtime_profile"
        ),
        precision=_optional_identifier(cast(str | None, args.precision), "precision"),
        max_model_length=cast(int | None, args.max_model_length),
        license_id=_optional_identifier(cast(str | None, args.license_id), "license_id"),
        reasoning_control_mode=reasoning_control_mode,
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    output_directory = cast(Path, args.output_dir)
    api_key: str | None = None
    try:
        config = config_from_args(args)
        fixtures = load_fixtures(cast(Path, args.fixture_file))
        api_key = _read_api_key(cast(Path | None, args.api_key_file))
    except SafeBenchmarkError as exc:
        print(f"Phase 3 benchmark failed: {exc.code}", file=sys.stderr)
        return 1

    try:
        try:
            report, metrics = execute_benchmark(config, fixtures, api_key)
        except SafeBenchmarkError as exc:
            report = failure_report(config, fixtures, exc.code)
            metrics = []
        except Exception as exc:  # Keep unexpected failures secret-safe as well.
            report = failure_report(config, fixtures, _safe_transport_code(exc))
            metrics = []
        write_evidence(output_directory, report, metrics)
    except SafeBenchmarkError as exc:
        print(f"Phase 3 benchmark failed: {exc.code}", file=sys.stderr)
        return 1
    finally:
        api_key = None

    if report.get("status") != "pass":
        print("Phase 3 benchmark completed with failed measurements.", file=sys.stderr)
        return 1
    print(f"Phase 3 benchmark evidence written to {output_directory}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Validate a bounded, content-safe set of Phase 3 NIM runtime evidence.

The validator consumes evidence already captured by ``smoke-phase3.sh``.  It
does not call a model, inspect logs, or infer a successful long-context request.
Its output deliberately omits license text and unreviewed JSON fields.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import stat
import sys
import tempfile
from collections.abc import Mapping, Sequence
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final, Literal, cast
from urllib.parse import urlsplit

Candidate = Literal["llama", "nemotron", "embedding-300m", "reranking-500m"]

OUTPUT_NAME: Final = "runtime-verification.json"
SCHEMA_VERSION: Final = 1
MAX_JSON_BYTES: Final = 16 * 1024 * 1024
MAX_STATUS_BYTES: Final = 64 * 1024
_MODEL_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/+:-]{0,199}$")
_VERSION = re.compile(r"^[0-9]+(?:\.[0-9]+){1,3}(?:-[A-Za-z0-9.-]+)?$")
_PROFILE_ID = re.compile(r"^[0-9a-f]{64}$")
_IMAGE_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
_LICENSE_SHA1 = re.compile(r"^[0-9a-f]{40}$")
_URL_IN_TEXT = re.compile(r"https://[^\s<>\"']+")


@dataclass(frozen=True, slots=True)
class ProfileCapability:
    precision: str
    max_model_length: int


@dataclass(frozen=True, slots=True)
class OperatorTerms:
    model_license_names: tuple[str, ...]
    additional_term_names: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class CandidatePolicy:
    model: str
    version: str
    image_repository: str
    image_digest: str
    profiles: Mapping[str, ProfileCapability]
    license_declaration: str
    operator_terms: OperatorTerms
    live_license_term_urls: frozenset[str]


LLAMA_FP8_PROFILE: Final = "c4789f7af56c770c1c88b73da666886365534d6980b6b922b41fd97036c77d73"
LLAMA_BF16_PROFILE: Final = "092ed4213624e774d24cdaf84e3b6222839bab2008a21d3c214ab46626366f90"
LLAMA_NVFP4_PROFILE: Final = "a28963301b18077db3454d5eb21f5678304936c5a425ddc552443de1f5449f2a"
NEMOTRON_NVFP4_PROFILE: Final = "f9db61d5a467d46be7733e90a26705798764b93d480c842143d525c1932b01e2"
EMBED_ONNX_FP16_PROFILE: Final = "e28f17c9c13a99055d065f88d725bf93c23b3aab14acd68f16323de1353fc528"
RERANK_ONNX_FP16_PROFILE: Final = "f7391ddbcb95b2406853526b8e489fedf20083a2420563ca3e65358ff417b10f"
NVIDIA_SLA_TERM_URL: Final = (
    "https://www.nvidia.com/en-us/agreements/enterprise-software/nvidia-software-license-agreement"
)
NVIDIA_PRODUCT_TERMS_URL: Final = (
    "https://www.nvidia.com/en-us/agreements/enterprise-software/"
    "product-specific-terms-for-ai-products"
)
NVIDIA_OPEN_MODEL_TERM_URL: Final = (
    "https://www.nvidia.com/en-us/agreements/enterprise-software/nvidia-open-model-license"
)
NVIDIA_COMMUNITY_MODEL_TERM_URL: Final = (
    "https://www.nvidia.com/en-us/agreements/enterprise-software/nvidia-community-models-license"
)
LLAMA_3_2_TERM_URL: Final = "https://www.llama.com/llama3_2/license"

_POLICIES: Final[Mapping[Candidate, CandidatePolicy]] = {
    "llama": CandidatePolicy(
        model="meta/llama-3.1-8b-instruct",
        version="2.0.6",
        image_repository="nvcr.io/nim/meta/llama-3.1-8b-instruct",
        image_digest="sha256:31e360dbb15f825d69e5d68c2032e334301523b4957091270385ed7ef3db5e81",
        profiles={
            LLAMA_FP8_PROFILE: ProfileCapability("FP8", 131072),
            LLAMA_BF16_PROFILE: ProfileCapability("BF16", 131072),
            LLAMA_NVFP4_PROFILE: ProfileCapability("NVFP4", 131072),
        },
        license_declaration="llama-3.1-community-license-and-nvidia-nim-terms",
        operator_terms=OperatorTerms(
            model_license_names=("Llama 3.1 Community License Agreement",),
            additional_term_names=(
                "NVIDIA Software License Agreement",
                "Product-Specific Terms for AI Products",
                "NVIDIA Open Model License Agreement",
            ),
        ),
        live_license_term_urls=frozenset(
            {NVIDIA_SLA_TERM_URL, NVIDIA_PRODUCT_TERMS_URL, NVIDIA_OPEN_MODEL_TERM_URL}
        ),
    ),
    "nemotron": CandidatePolicy(
        model="nvidia/nemotron-nano-9b-v2",
        version="1.0.0",
        image_repository="nvcr.io/nim/nvidia/nvidia-nemotron-nano-9b-v2-dgx-spark",
        image_digest="sha256:82028e38ab950edd32f5053ca2030ee14d965e8fd4fe1c6e06468eb0be07a9a4",
        profiles={NEMOTRON_NVFP4_PROFILE: ProfileCapability("NVFP4", 131072)},
        license_declaration="nvidia-open-model-license",
        operator_terms=OperatorTerms(
            model_license_names=("NVIDIA Open Model License Agreement",),
            additional_term_names=(),
        ),
        live_license_term_urls=frozenset(
            {NVIDIA_SLA_TERM_URL, NVIDIA_PRODUCT_TERMS_URL, NVIDIA_OPEN_MODEL_TERM_URL}
        ),
    ),
    "embedding-300m": CandidatePolicy(
        model="nvidia/llama-nemotron-embed-300m-v2",
        version="1.13.0",
        image_repository="nvcr.io/nim/nvidia/llama-nemotron-embed-300m-v2",
        image_digest="sha256:1f0a7fc168919d7b84bb4edfb4a4da0c5828d11ee284f9fb8113242b3b35cbb4",
        profiles={EMBED_ONNX_FP16_PROFILE: ProfileCapability("ONNX-FP16", 8192)},
        license_declaration="nvidia-open-model-license",
        operator_terms=OperatorTerms(
            model_license_names=("NVIDIA Open Model License Agreement",),
            additional_term_names=("Llama 3.2 Community License Agreement",),
        ),
        live_license_term_urls=frozenset(
            {
                NVIDIA_SLA_TERM_URL,
                NVIDIA_PRODUCT_TERMS_URL,
                NVIDIA_OPEN_MODEL_TERM_URL,
                LLAMA_3_2_TERM_URL,
            }
        ),
    ),
    "reranking-500m": CandidatePolicy(
        model="nvidia/llama-nemotron-rerank-500m-v2",
        version="1.10.0",
        image_repository="nvcr.io/nim/nvidia/llama-nemotron-rerank-500m-v2",
        image_digest="sha256:3e39d44bdb3dd683d6a2ac8d7689b484aee6c18dc7e00c2064f19501742720f3",
        profiles={RERANK_ONNX_FP16_PROFILE: ProfileCapability("ONNX-FP16", 4096)},
        license_declaration="nvidia-community-model-license",
        operator_terms=OperatorTerms(
            model_license_names=("NVIDIA Community Model License",),
            additional_term_names=("Llama 3.2 Community License Agreement",),
        ),
        live_license_term_urls=frozenset(
            {
                NVIDIA_SLA_TERM_URL,
                NVIDIA_PRODUCT_TERMS_URL,
                NVIDIA_COMMUNITY_MODEL_TERM_URL,
                LLAMA_3_2_TERM_URL,
            }
        ),
    ),
}

_TERM_URLS: Final[Mapping[str, str]] = {
    NVIDIA_SLA_TERM_URL: "NVIDIA Software License Agreement",
    NVIDIA_PRODUCT_TERMS_URL: "Product-Specific Terms for AI Products",
    NVIDIA_OPEN_MODEL_TERM_URL: "NVIDIA Open Model License Agreement",
    NVIDIA_COMMUNITY_MODEL_TERM_URL: "NVIDIA Community Model License",
    LLAMA_3_2_TERM_URL: "Llama 3.2 Community License Agreement",
}

_ALLOWED_ENDPOINTS: Final = frozenset(
    {
        "/v1/health/live",
        "/v1/health/ready",
        "/v1/models",
        "/v1/metrics",
        "/v1/metadata",
        "/v1/version",
        "/v1/manifest",
        "/v1/license",
    }
)
_REQUIRED_ENDPOINTS: Final = frozenset({"/v1/models", "/v1/metadata", "/v1/version", "/v1/license"})
_CHECK_NAMES: Final = (
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


class VerificationError(RuntimeError):
    """A closed, safe failure code suitable for evidence output."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class EvidenceOutputAlreadyExists(RuntimeError):
    """Raised when immutable runtime evidence was already published."""


@dataclass(frozen=True, slots=True)
class Config:
    candidate_dir: Path
    candidate: Candidate
    expected_model: str
    expected_version: str
    expected_profile: str
    expected_precision: str
    expected_max_model_length: int
    expected_image_digest: str
    license_declaration: str


def _safe_model(value: str) -> str:
    if _MODEL_ID.fullmatch(value) is None:
        raise argparse.ArgumentTypeError("expected model has an unsafe format")
    return value


def _safe_version(value: str) -> str:
    if _VERSION.fullmatch(value) is None:
        raise argparse.ArgumentTypeError("expected version has an unsafe format")
    return value


def _safe_profile(value: str) -> str:
    if _PROFILE_ID.fullmatch(value) is None:
        raise argparse.ArgumentTypeError("expected profile must be 64 lowercase hex characters")
    return value


def _safe_digest(value: str) -> str:
    if _IMAGE_DIGEST.fullmatch(value) is None:
        raise argparse.ArgumentTypeError("expected image digest must be sha256:<64 lowercase hex>")
    return value


def _bounded_positive_int(value: str) -> int:
    try:
        parsed = int(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError("expected max model length must be an integer") from error
    if not 1 <= parsed <= 1_000_000:
        raise argparse.ArgumentTypeError("expected max model length is out of range")
    return parsed


def _safe_declaration(value: str) -> str:
    declarations = {policy.license_declaration for policy in _POLICIES.values()}
    if value not in declarations:
        raise argparse.ArgumentTypeError("license declaration is not allowlisted")
    return value


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Validate captured Phase 3 NIM runtime identity and license evidence."
    )
    parser.add_argument("--candidate-dir", required=True, type=Path)
    parser.add_argument("--candidate", required=True, choices=tuple(_POLICIES))
    parser.add_argument("--expected-model", required=True, type=_safe_model)
    parser.add_argument("--expected-version", required=True, type=_safe_version)
    parser.add_argument("--expected-profile", required=True, type=_safe_profile)
    parser.add_argument(
        "--expected-precision",
        required=True,
        choices=("FP8", "BF16", "NVFP4", "ONNX-FP16"),
    )
    parser.add_argument("--expected-max-model-length", required=True, type=_bounded_positive_int)
    parser.add_argument("--expected-image-digest", required=True, type=_safe_digest)
    parser.add_argument("--license-declaration", required=True, type=_safe_declaration)
    return parser


def _config_from_args(namespace: argparse.Namespace) -> Config:
    return Config(
        candidate_dir=cast(Path, namespace.candidate_dir),
        candidate=cast(Candidate, namespace.candidate),
        expected_model=cast(str, namespace.expected_model),
        expected_version=cast(str, namespace.expected_version),
        expected_profile=cast(str, namespace.expected_profile),
        expected_precision=cast(str, namespace.expected_precision),
        expected_max_model_length=cast(int, namespace.expected_max_model_length),
        expected_image_digest=cast(str, namespace.expected_image_digest),
        license_declaration=cast(str, namespace.license_declaration),
    )


def _ensure_candidate_directory(path: Path) -> None:
    try:
        mode = path.lstat().st_mode
    except OSError as error:
        raise VerificationError("candidate-directory-unavailable") from error
    if stat.S_ISLNK(mode) or not stat.S_ISDIR(mode):
        raise VerificationError("candidate-directory-unsafe")


def _read_bytes(path: Path, *, label: str, maximum: int) -> bytes:
    try:
        file_stat = path.lstat()
        if stat.S_ISLNK(file_stat.st_mode) or not stat.S_ISREG(file_stat.st_mode):
            raise VerificationError(f"{label}-unsafe-file")
        if not 0 < file_stat.st_size <= maximum:
            raise VerificationError(f"{label}-invalid-size")
        return path.read_bytes()
    except VerificationError:
        raise
    except OSError as error:
        raise VerificationError(f"{label}-unavailable") from error


def _read_json(path: Path, *, label: str) -> Any:
    raw = _read_bytes(path, label=label, maximum=MAX_JSON_BYTES)
    try:
        return json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise VerificationError(f"{label}-malformed") from error


def _object(value: Any, *, code: str) -> Mapping[str, Any]:
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise VerificationError(code)
    return cast(Mapping[str, Any], value)


def _single_object(value: Any, *, code: str) -> Mapping[str, Any]:
    if not isinstance(value, list) or len(value) != 1:
        raise VerificationError(code)
    return _object(value[0], code=code)


def _parse_http_statuses(path: Path) -> Mapping[str, int]:
    raw = _read_bytes(path, label="http-status", maximum=MAX_STATUS_BYTES)
    try:
        text = raw.decode("ascii")
    except UnicodeDecodeError as error:
        raise VerificationError("http-status-malformed") from error

    statuses: dict[str, int] = {}
    for line in text.splitlines():
        fields = line.split("\t")
        if len(fields) != 2:
            raise VerificationError("http-status-malformed")
        endpoint, status_text = fields
        if endpoint not in _ALLOWED_ENDPOINTS or endpoint in statuses:
            raise VerificationError("http-status-malformed")
        if re.fullmatch(r"[0-9]{3}", status_text) is None:
            raise VerificationError("http-status-malformed")
        statuses[endpoint] = int(status_text)

    if not _REQUIRED_ENDPOINTS.issubset(statuses):
        raise VerificationError("required-http-status-missing")
    if any(statuses[endpoint] != 200 for endpoint in _REQUIRED_ENDPOINTS):
        raise VerificationError("required-http-status-not-200")
    return statuses


def _validate_expectations(config: Config) -> tuple[CandidatePolicy, ProfileCapability]:
    policy = _POLICIES[config.candidate]
    if config.expected_model != policy.model:
        raise VerificationError("expected-model-not-allowlisted")
    if config.expected_version != policy.version:
        raise VerificationError("expected-version-not-allowlisted")
    capability = policy.profiles.get(config.expected_profile)
    if capability is None:
        raise VerificationError("expected-profile-not-allowlisted")
    if config.expected_precision != capability.precision:
        raise VerificationError("expected-precision-not-allowlisted")
    if config.expected_max_model_length != capability.max_model_length:
        raise VerificationError("expected-max-model-length-not-allowlisted")
    if config.expected_image_digest != policy.image_digest:
        raise VerificationError("expected-image-digest-not-allowlisted")
    if config.license_declaration != policy.license_declaration:
        raise VerificationError("license-declaration-candidate-mismatch")
    return policy, capability


def _validate_served_model(models: Any, expected_model: str) -> None:
    models_object = _object(models, code="models-schema-invalid")
    data = models_object.get("data")
    if not isinstance(data, list) or len(data) != 1:
        raise VerificationError("served-model-count-mismatch")
    served = _object(data[0], code="models-schema-invalid").get("id")
    if not isinstance(served, str) or served != expected_model:
        raise VerificationError("served-model-mismatch")


def _selected_profile(metadata: Mapping[str, Any]) -> tuple[str, str]:
    profile_id = metadata.get("profile_id")
    selected_profile_id = metadata.get("selectedModelProfileId")
    primary = profile_id if isinstance(profile_id, str) and profile_id else None
    fallback = (
        selected_profile_id
        if isinstance(selected_profile_id, str) and selected_profile_id
        else None
    )
    if primary is not None and fallback is not None and primary != fallback:
        raise VerificationError("metadata-profile-fields-conflict")
    if primary is not None:
        return primary, "profile_id"
    if fallback is not None:
        return fallback, "selectedModelProfileId"
    raise VerificationError("metadata-profile-missing")


def _validate_version_and_profile(
    metadata_raw: Any,
    version_raw: Any,
    *,
    expected_version: str,
    expected_profile: str,
) -> str:
    metadata = _object(metadata_raw, code="metadata-schema-invalid")
    version = _object(version_raw, code="version-schema-invalid")
    metadata_version = metadata.get("version")
    release = version.get("release")
    if (
        not isinstance(metadata_version, str)
        or not isinstance(release, str)
        or metadata_version != expected_version
        or release != expected_version
        or metadata_version != release
    ):
        raise VerificationError("nim-version-mismatch")
    selected, source = _selected_profile(metadata)
    if selected != expected_profile:
        raise VerificationError("selected-profile-mismatch")
    return source


def _validate_image_and_container(
    image_raw: Any,
    container_raw: Any,
    *,
    expected_repository: str,
    expected_digest: str,
    expected_profile: str,
) -> None:
    image = _single_object(image_raw, code="image-inspect-schema-invalid")
    container = _single_object(container_raw, code="container-inspect-schema-invalid")

    if image.get("Architecture") != "arm64" or image.get("Os") != "linux":
        raise VerificationError("image-platform-mismatch")
    if image.get("Id") != expected_digest:
        raise VerificationError("image-digest-mismatch")
    repo_digests = image.get("RepoDigests")
    exact_repo_digest = f"{expected_repository}@{expected_digest}"
    if repo_digests != [exact_repo_digest]:
        raise VerificationError("image-repository-digest-mismatch")
    if container.get("Image") != expected_digest:
        raise VerificationError("container-image-digest-mismatch")
    container_config = _object(container.get("Config"), code="container-inspect-schema-invalid")
    configured_profile = container_config.get("NIM_MODEL_PROFILE")
    if configured_profile is not None and not isinstance(configured_profile, str):
        raise VerificationError("container-inspect-schema-invalid")
    if isinstance(configured_profile, str) and configured_profile != expected_profile:
        raise VerificationError("container-configured-profile-mismatch")
    state = _object(container.get("State"), code="container-inspect-schema-invalid")
    if state.get("Running") is not True or state.get("Status") != "running":
        raise VerificationError("container-not-running-at-capture")
    if state.get("OOMKilled") is True:
        raise VerificationError("container-oom-killed")


def _canonical_term_url(value: str) -> str:
    trimmed = value.rstrip(".,;:!?)]}")
    try:
        parts = urlsplit(trimmed)
        hostname = parts.hostname
        port = parts.port
    except ValueError as error:
        raise VerificationError("license-term-url-unsafe") from error
    if (
        parts.scheme != "https"
        or not hostname
        or parts.username is not None
        or parts.password is not None
        or port is not None
        or parts.query
        or parts.fragment
    ):
        raise VerificationError("license-term-url-unsafe")
    canonical = f"https://{hostname.lower()}{parts.path}".rstrip("/")
    if canonical not in _TERM_URLS:
        raise VerificationError("license-term-url-not-allowlisted")
    return canonical


def _extract_terms(content: str) -> tuple[tuple[str, ...], tuple[str, ...]]:
    ordered_urls: list[str] = []
    for match in _URL_IN_TEXT.findall(content):
        url = _canonical_term_url(match)
        if url not in ordered_urls:
            ordered_urls.append(url)
    urls = tuple(ordered_urls)
    if not urls:
        raise VerificationError("license-terms-missing")
    names = tuple(_TERM_URLS[url] for url in urls)
    return names, urls


def _validate_license(
    metadata_raw: Any, license_raw: Any
) -> tuple[str, str, tuple[str, ...], tuple[str, ...]]:
    metadata = _object(metadata_raw, code="metadata-schema-invalid")
    metadata_license = _object(metadata.get("licenseInfo"), code="metadata-license-schema-invalid")
    live_license = _object(license_raw, code="license-schema-invalid")

    metadata_sha = metadata_license.get("sha")
    live_sha = live_license.get("sha")
    metadata_content = metadata_license.get("content")
    live_content = live_license.get("content")
    metadata_name = metadata_license.get("name")
    live_name = live_license.get("name")
    metadata_size = metadata_license.get("size")
    live_size = live_license.get("size")

    if (
        not isinstance(metadata_sha, str)
        or not isinstance(live_sha, str)
        or _LICENSE_SHA1.fullmatch(metadata_sha) is None
        or _LICENSE_SHA1.fullmatch(live_sha) is None
    ):
        raise VerificationError("license-sha-invalid")
    if metadata_sha != live_sha:
        raise VerificationError("license-sha-mismatch")
    if (
        not isinstance(metadata_content, str)
        or not isinstance(live_content, str)
        or not live_content
        or metadata_content != live_content
    ):
        raise VerificationError("license-content-mismatch")
    content_bytes = live_content.encode("utf-8")
    calculated_sha = hashlib.sha1(content_bytes, usedforsecurity=False).hexdigest()
    if calculated_sha != live_sha:
        raise VerificationError("license-content-sha-mismatch")
    if (
        not isinstance(metadata_size, int)
        or isinstance(metadata_size, bool)
        or not isinstance(live_size, int)
        or isinstance(live_size, bool)
        or metadata_size != len(content_bytes)
        or live_size != len(content_bytes)
    ):
        raise VerificationError("license-content-size-mismatch")
    if (
        not isinstance(metadata_name, str)
        or not isinstance(live_name, str)
        or metadata_name != live_name
        or live_name != "LICENSE"
    ):
        raise VerificationError("license-name-mismatch")

    term_names, term_urls = _extract_terms(live_content)
    return live_name, live_sha, term_names, term_urls


def _base_report(config: Config, checks: Mapping[str, bool]) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "phase": 3,
        "candidate": config.candidate,
        "checks": dict(checks),
        "expected_identity": {
            "model": config.expected_model,
            "nim_version": config.expected_version,
            "profile_id": config.expected_profile,
            "precision": config.expected_precision,
            "image_digest": config.expected_image_digest,
        },
    }


def _verify(config: Config) -> dict[str, Any]:
    checks = dict.fromkeys(_CHECK_NAMES, False)
    policy, capability = _validate_expectations(config)
    checks["expectations_allowlisted"] = True
    checks["precision_from_closed_allowlist"] = True
    checks["operator_license_declaration_allowlisted"] = True

    statuses = _parse_http_statuses(config.candidate_dir / "endpoints" / "http-status.tsv")
    checks["required_http_statuses"] = True

    models = _read_json(config.candidate_dir / "models.json", label="models")
    container = _read_json(
        config.candidate_dir / "container-inspect.json", label="container-inspect"
    )
    image = _read_json(config.candidate_dir / "image-inspect.json", label="image-inspect")
    metadata = _read_json(config.candidate_dir / "endpoints" / "metadata.body", label="metadata")
    version = _read_json(config.candidate_dir / "endpoints" / "version.body", label="version")
    live_license = _read_json(config.candidate_dir / "endpoints" / "license.body", label="license")

    _validate_served_model(models, config.expected_model)
    checks["served_model_exact"] = True
    profile_source = _validate_version_and_profile(
        metadata,
        version,
        expected_version=config.expected_version,
        expected_profile=config.expected_profile,
    )
    checks["nim_version_exact"] = True
    checks["selected_profile_exact"] = True
    _validate_image_and_container(
        image,
        container,
        expected_repository=policy.image_repository,
        expected_digest=config.expected_image_digest,
        expected_profile=config.expected_profile,
    )
    checks["arm64_image_container_identity"] = True
    license_name, license_sha, term_names, term_urls = _validate_license(metadata, live_license)
    if frozenset(term_urls) != policy.live_license_term_urls:
        raise VerificationError("license-term-set-mismatch")
    checks["live_license_sha_content_consistent"] = True

    report = _base_report(config, checks)
    report.update(
        {
            "status": "pass",
            "failure_codes": [],
            "runtime_identity": {
                "served_model": config.expected_model,
                "nim_version": config.expected_version,
                "selected_profile_id": config.expected_profile,
                "selected_profile_field": profile_source,
                "precision": capability.precision,
                "image_repository": policy.image_repository,
                "image_digest": config.expected_image_digest,
                "architecture": "arm64",
                "operating_system": "linux",
                "required_endpoint_http_statuses": {
                    endpoint: statuses[endpoint] for endpoint in sorted(_REQUIRED_ENDPOINTS)
                },
            },
            "max_model_length": {
                "value": capability.max_model_length,
                "evidence_kind": "closed-candidate-profile-capability-declaration",
                "live_long_request_executed_by_this_validator": False,
                "live_long_request_result": None,
                "claim_scope": "declared-profile-capability-only",
            },
            "live_nim_license": {
                "document_name": license_name,
                "content_sha_algorithm": "sha1",
                "content_sha": license_sha,
                "term_names": list(term_names),
                "term_urls": list(term_urls),
                "content_persisted_in_output": False,
                "metadata_and_license_endpoint_consistent": True,
            },
            "operator_reviewed_model_terms": {
                "declaration_name": policy.license_declaration,
                "model_license_names": list(policy.operator_terms.model_license_names),
                "additional_term_names": list(policy.operator_terms.additional_term_names),
                "evidence_kind": "operator-reviewed-declaration",
                "separate_from_live_nim_license": True,
                "legal_approval": "pending",
            },
        }
    )
    return report


def _failure_report(config: Config, code: str) -> dict[str, Any]:
    report = _base_report(config, dict.fromkeys(_CHECK_NAMES, False))
    report.update(
        {
            "status": "fail",
            "failure_codes": [code],
            "max_model_length": {
                "value": config.expected_max_model_length,
                "evidence_kind": "unverified-cli-expectation",
                "live_long_request_executed_by_this_validator": False,
                "live_long_request_result": None,
                "claim_scope": "no-capability-claim-on-failure",
            },
            "operator_reviewed_model_terms": {
                "declaration_name": config.license_declaration,
                "evidence_kind": "unverified-cli-expectation",
                "separate_from_live_nim_license": True,
                "legal_approval": "pending",
            },
        }
    )
    return report


def _atomic_write(path: Path, payload: Mapping[str, Any]) -> None:
    if os.path.lexists(path):
        raise EvidenceOutputAlreadyExists
    content = json.dumps(payload, ensure_ascii=True, indent=2, sort_keys=True) + "\n"
    previous_umask = os.umask(0o027)
    temporary: Path | None = None
    try:
        descriptor, temporary_name = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.tmp-")
        temporary = Path(temporary_name)
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary, 0o640)
        os.link(temporary, path)
        temporary.unlink()
        temporary = None
        parent_fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(parent_fd)
        finally:
            os.close(parent_fd)
    except FileExistsError:
        raise EvidenceOutputAlreadyExists from None
    finally:
        if temporary is not None:
            with suppress(OSError):
                temporary.unlink(missing_ok=True)
        os.umask(previous_umask)


def main(argv: Sequence[str] | None = None) -> int:
    namespace = _parser().parse_args(argv)
    config = _config_from_args(namespace)
    try:
        _ensure_candidate_directory(config.candidate_dir)
    except VerificationError as error:
        print(f"phase3-runtime-evidence: fail ({error.code})", file=sys.stderr)
        return 2

    output = config.candidate_dir / OUTPUT_NAME
    try:
        report = _verify(config)
    except VerificationError as error:
        try:
            _atomic_write(output, _failure_report(config, error.code))
        except EvidenceOutputAlreadyExists:
            print(
                "phase3-runtime-evidence: fail (evidence-output-already-exists)",
                file=sys.stderr,
            )
            return 2
        except OSError:
            print("phase3-runtime-evidence: fail (evidence-output-io-error)", file=sys.stderr)
            return 2
        print(f"phase3-runtime-evidence: fail ({error.code})", file=sys.stderr)
        return 1
    except OSError:
        print("phase3-runtime-evidence: fail (evidence-io-error)", file=sys.stderr)
        return 2

    try:
        _atomic_write(output, report)
    except EvidenceOutputAlreadyExists:
        print(
            "phase3-runtime-evidence: fail (evidence-output-already-exists)",
            file=sys.stderr,
        )
        return 2
    except OSError:
        print("phase3-runtime-evidence: fail (evidence-output-io-error)", file=sys.stderr)
        return 2
    print(f"phase3-runtime-evidence: pass ({config.candidate})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

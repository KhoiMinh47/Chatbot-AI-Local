from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
VALIDATOR = REPOSITORY_ROOT / "scripts" / "phase3_runtime_evidence.py"


@dataclass(frozen=True, slots=True)
class CandidateCase:
    candidate: str
    model: str
    version: str
    profile: str
    precision: str
    max_model_length: int
    image_repository: str
    image_digest: str
    declaration: str
    profile_field: str
    license_content: str


CASES = (
    CandidateCase(
        candidate="llama",
        model="meta/llama-3.1-8b-instruct",
        version="2.0.6",
        profile="c4789f7af56c770c1c88b73da666886365534d6980b6b922b41fd97036c77d73",
        precision="FP8",
        max_model_length=131072,
        image_repository="nvcr.io/nim/meta/llama-3.1-8b-instruct",
        image_digest=("sha256:31e360dbb15f825d69e5d68c2032e334301523b4957091270385ed7ef3db5e81"),
        declaration="llama-3.1-community-license-and-nvidia-nim-terms",
        profile_field="profile_id",
        license_content=(
            "Terms: https://www.nvidia.com/en-us/agreements/enterprise-software/"
            "nvidia-software-license-agreement/ "
            "https://www.nvidia.com/en-us/agreements/enterprise-software/"
            "product-specific-terms-for-ai-products/ "
            "https://www.nvidia.com/en-us/agreements/enterprise-software/"
            "nvidia-open-model-license/"
        ),
    ),
    CandidateCase(
        candidate="nemotron",
        model="nvidia/nemotron-nano-9b-v2",
        version="1.0.0",
        profile="f9db61d5a467d46be7733e90a26705798764b93d480c842143d525c1932b01e2",
        precision="NVFP4",
        max_model_length=131072,
        image_repository="nvcr.io/nim/nvidia/nvidia-nemotron-nano-9b-v2-dgx-spark",
        image_digest=("sha256:82028e38ab950edd32f5053ca2030ee14d965e8fd4fe1c6e06468eb0be07a9a4"),
        declaration="nvidia-open-model-license",
        profile_field="selectedModelProfileId",
        license_content=(
            "Terms: https://www.nvidia.com/en-us/agreements/enterprise-software/"
            "nvidia-software-license-agreement/ "
            "https://www.nvidia.com/en-us/agreements/enterprise-software/"
            "product-specific-terms-for-ai-products/ "
            "https://www.nvidia.com/en-us/agreements/enterprise-software/"
            "nvidia-open-model-license/"
        ),
    ),
    CandidateCase(
        candidate="embedding-300m",
        model="nvidia/llama-nemotron-embed-300m-v2",
        version="1.13.0",
        profile="e28f17c9c13a99055d065f88d725bf93c23b3aab14acd68f16323de1353fc528",
        precision="ONNX-FP16",
        max_model_length=8192,
        image_repository="nvcr.io/nim/nvidia/llama-nemotron-embed-300m-v2",
        image_digest=("sha256:1f0a7fc168919d7b84bb4edfb4a4da0c5828d11ee284f9fb8113242b3b35cbb4"),
        declaration="nvidia-open-model-license",
        profile_field="selectedModelProfileId",
        license_content=(
            '<a href="https://www.nvidia.com/en-us/agreements/enterprise-software/'
            'nvidia-software-license-agreement/">NVIDIA SLA</a>. '
            '<a href="https://www.nvidia.com/en-us/agreements/enterprise-software/'
            'product-specific-terms-for-ai-products/">Product terms</a>. '
            '<a href="https://www.nvidia.com/en-us/agreements/enterprise-software/'
            'nvidia-open-model-license/">Open Model License</a>. '
            '<a href="https://www.llama.com/llama3_2/license/">Llama terms</a>.'
        ),
    ),
    CandidateCase(
        candidate="reranking-500m",
        model="nvidia/llama-nemotron-rerank-500m-v2",
        version="1.10.0",
        profile="f7391ddbcb95b2406853526b8e489fedf20083a2420563ca3e65358ff417b10f",
        precision="ONNX-FP16",
        max_model_length=4096,
        image_repository="nvcr.io/nim/nvidia/llama-nemotron-rerank-500m-v2",
        image_digest=("sha256:3e39d44bdb3dd683d6a2ac8d7689b484aee6c18dc7e00c2064f19501742720f3"),
        declaration="nvidia-community-model-license",
        profile_field="selectedModelProfileId",
        license_content=(
            '<a href="https://www.nvidia.com/en-us/agreements/enterprise-software/'
            'nvidia-software-license-agreement/">NVIDIA SLA</a>. '
            '<a href="https://www.nvidia.com/en-us/agreements/enterprise-software/'
            'product-specific-terms-for-ai-products/">Product terms</a>. '
            '<a href="https://www.nvidia.com/en-us/agreements/enterprise-software/'
            'nvidia-community-models-license/">Community Model License</a>. '
            '<a href="https://www.llama.com/llama3_2/license/">Llama terms</a>.'
        ),
    ),
)


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")


def build_candidate(directory: Path, case: CandidateCase) -> None:
    license_sha = hashlib.sha1(
        case.license_content.encode("utf-8"), usedforsecurity=False
    ).hexdigest()
    license_value = {
        "name": "LICENSE",
        "path": "/opt/nim/LICENSE",
        "sha": license_sha,
        "size": len(case.license_content.encode("utf-8")),
        "type": "file",
        "url": "",
        "content": case.license_content,
    }
    model: dict[str, Any] = {"id": case.model}
    if case.candidate in {"llama", "nemotron"}:
        model.update({"object": "model", "max_model_len": 131072})
    elif case.candidate == "embedding-300m":
        model.update({"created": 0, "object": "model", "owned_by": "organization-owner"})
    write_json(directory / "models.json", {"object": "list", "data": [model]})
    write_json(
        directory / "container-inspect.json",
        [
            {
                "Id": "a" * 64,
                "Image": case.image_digest,
                "Name": f"/phase3-{case.candidate}",
                "Config": {
                    "NIM_MODEL_PROFILE": (case.profile if case.candidate == "llama" else None)
                },
                "State": {"Status": "running", "Running": True, "OOMKilled": False},
            }
        ],
    )
    write_json(
        directory / "image-inspect.json",
        [
            {
                "Id": case.image_digest,
                "Architecture": "arm64",
                "Os": "linux",
                "RepoDigests": [f"{case.image_repository}@{case.image_digest}"],
                "RepoTags": [f"{case.image_repository}:fixed"],
            }
        ],
    )
    metadata: dict[str, Any] = {
        "version": case.version,
        "modelInfo": [{"shortName": case.model}],
        "licenseInfo": dict(license_value),
    }
    metadata[case.profile_field] = case.profile
    write_json(directory / "endpoints" / "metadata.body", metadata)
    version_key = "openapi_spec" if case.candidate == "llama" else "api"
    write_json(
        directory / "endpoints" / "version.body",
        {"release": case.version, version_key: "3.1.0"},
    )
    write_json(directory / "endpoints" / "license.body", license_value)
    statuses = "\n".join(
        f"{endpoint}\t200"
        for endpoint in (
            "/v1/health/live",
            "/v1/health/ready",
            "/v1/models",
            "/v1/metrics",
            "/v1/metadata",
            "/v1/version",
            "/v1/manifest",
            "/v1/license",
        )
    )
    (directory / "endpoints" / "http-status.tsv").write_text(f"{statuses}\n", encoding="ascii")


def replace_live_license_content(directory: Path, content: str) -> None:
    license_path = directory / "endpoints" / "license.body"
    metadata_path = directory / "endpoints" / "metadata.body"
    license_value = json.loads(license_path.read_text())
    license_value["content"] = content
    license_value["size"] = len(content.encode("utf-8"))
    license_value["sha"] = hashlib.sha1(content.encode("utf-8"), usedforsecurity=False).hexdigest()
    metadata = json.loads(metadata_path.read_text())
    metadata["licenseInfo"] = dict(license_value)
    write_json(license_path, license_value)
    write_json(metadata_path, metadata)


def run_validator(
    directory: Path,
    case: CandidateCase,
    *,
    extra_arguments: tuple[str, ...] = (),
) -> subprocess.CompletedProcess[str]:
    arguments = [
        sys.executable,
        str(VALIDATOR),
        "--candidate-dir",
        str(directory),
        "--candidate",
        case.candidate,
        "--expected-model",
        case.model,
        "--expected-version",
        case.version,
        "--expected-profile",
        case.profile,
        "--expected-precision",
        case.precision,
        "--expected-max-model-length",
        str(case.max_model_length),
        "--expected-image-digest",
        case.image_digest,
        "--license-declaration",
        case.declaration,
        *extra_arguments,
    ]
    return subprocess.run(
        arguments,
        cwd=REPOSITORY_ROOT,
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )


@pytest.mark.parametrize("case", CASES, ids=lambda case: case.candidate)
def test_r2_runtime_schemas_pass_without_claiming_a_live_long_request(
    tmp_path: Path, case: CandidateCase
) -> None:
    candidate_dir = tmp_path / case.candidate
    build_candidate(candidate_dir, case)

    result = run_validator(candidate_dir, case)

    assert result.returncode == 0, result.stderr
    report = json.loads((candidate_dir / "runtime-verification.json").read_text())
    assert report["status"] == "pass"
    assert report["runtime_identity"]["served_model"] == case.model
    assert report["runtime_identity"]["selected_profile_field"] == case.profile_field
    assert report["runtime_identity"]["precision"] == case.precision
    assert report["max_model_length"] == {
        "claim_scope": "declared-profile-capability-only",
        "evidence_kind": "closed-candidate-profile-capability-declaration",
        "live_long_request_executed_by_this_validator": False,
        "live_long_request_result": None,
        "value": case.max_model_length,
    }
    assert report["operator_reviewed_model_terms"]["legal_approval"] == "pending"
    assert report["operator_reviewed_model_terms"]["separate_from_live_nim_license"] is True
    if case.candidate in {"embedding-300m", "reranking-500m"}:
        assert report["operator_reviewed_model_terms"]["additional_term_names"] == [
            "Llama 3.2 Community License Agreement"
        ]
    assert "content" not in report["live_nim_license"]


def test_selected_model_profile_id_is_an_explicit_schema_fallback(tmp_path: Path) -> None:
    case = CASES[1]
    candidate_dir = tmp_path / case.candidate
    build_candidate(candidate_dir, case)
    metadata_path = candidate_dir / "endpoints" / "metadata.body"
    metadata = json.loads(metadata_path.read_text())
    metadata["profile_id"] = None
    write_json(metadata_path, metadata)

    result = run_validator(candidate_dir, case)

    assert result.returncode == 0, result.stderr
    report = json.loads((candidate_dir / "runtime-verification.json").read_text())
    assert report["runtime_identity"]["selected_profile_field"] == "selectedModelProfileId"


def test_exact_served_model_mismatch_writes_atomic_failure_evidence(tmp_path: Path) -> None:
    case = CASES[0]
    candidate_dir = tmp_path / case.candidate
    build_candidate(candidate_dir, case)
    write_json(candidate_dir / "models.json", {"data": [{"id": "meta/not-the-model"}]})

    result = run_validator(candidate_dir, case)

    assert result.returncode == 1
    report = json.loads((candidate_dir / "runtime-verification.json").read_text())
    assert report["status"] == "fail"
    assert report["failure_codes"] == ["served-model-mismatch"]
    assert not list(candidate_dir.glob(".runtime-verification.json.tmp-*"))


def test_malformed_artifact_fails_closed_with_a_safe_code(tmp_path: Path) -> None:
    case = CASES[2]
    candidate_dir = tmp_path / case.candidate
    build_candidate(candidate_dir, case)
    (candidate_dir / "models.json").write_text("{not-json", encoding="utf-8")

    result = run_validator(candidate_dir, case)

    assert result.returncode == 1
    report = json.loads((candidate_dir / "runtime-verification.json").read_text())
    assert report["failure_codes"] == ["models-malformed"]
    assert "not-json" not in json.dumps(report)


def test_live_license_terms_are_allowlisted_and_content_is_never_copied(tmp_path: Path) -> None:
    case = CASES[2]
    candidate_dir = tmp_path / case.candidate
    build_candidate(candidate_dir, case)

    result = run_validator(candidate_dir, case)

    assert result.returncode == 0, result.stderr
    report_text = (candidate_dir / "runtime-verification.json").read_text()
    report = json.loads(report_text)
    assert report["live_nim_license"]["term_names"] == [
        "NVIDIA Software License Agreement",
        "Product-Specific Terms for AI Products",
        "NVIDIA Open Model License Agreement",
        "Llama 3.2 Community License Agreement",
    ]
    assert report["live_nim_license"]["term_urls"] == [
        "https://www.nvidia.com/en-us/agreements/enterprise-software/"
        "nvidia-software-license-agreement",
        "https://www.nvidia.com/en-us/agreements/enterprise-software/"
        "product-specific-terms-for-ai-products",
        "https://www.nvidia.com/en-us/agreements/enterprise-software/nvidia-open-model-license",
        "https://www.llama.com/llama3_2/license",
    ]
    assert case.license_content not in report_text
    assert "<a href" not in report_text


def test_license_metadata_content_or_sha_mismatch_cannot_pass(tmp_path: Path) -> None:
    case = CASES[3]
    candidate_dir = tmp_path / case.candidate
    build_candidate(candidate_dir, case)
    metadata_path = candidate_dir / "endpoints" / "metadata.body"
    metadata = json.loads(metadata_path.read_text())
    metadata["licenseInfo"]["content"] = "different content must not be persisted"
    write_json(metadata_path, metadata)

    result = run_validator(candidate_dir, case)

    assert result.returncode == 1
    report_text = (candidate_dir / "runtime-verification.json").read_text()
    report = json.loads(report_text)
    assert report["failure_codes"] == ["license-content-mismatch"]
    assert "different content" not in report_text


def test_unreviewed_input_fields_cannot_be_injected_into_output(tmp_path: Path) -> None:
    case = CASES[1]
    candidate_dir = tmp_path / case.candidate
    build_candidate(candidate_dir, case)
    metadata_path = candidate_dir / "endpoints" / "metadata.body"
    metadata = json.loads(metadata_path.read_text())
    metadata["attacker_chosen_field"] = "do-not-copy-this-value"
    write_json(metadata_path, metadata)
    license_path = candidate_dir / "endpoints" / "license.body"
    license_value = json.loads(license_path.read_text())
    license_value["attacker_chosen_field"] = "do-not-copy-this-value"
    write_json(license_path, license_value)

    result = run_validator(candidate_dir, case)

    assert result.returncode == 0, result.stderr
    report_text = (candidate_dir / "runtime-verification.json").read_text()
    assert "attacker_chosen_field" not in report_text
    assert "do-not-copy-this-value" not in report_text


def test_precision_is_derived_from_candidate_profile_allowlist(tmp_path: Path) -> None:
    case = CASES[0]
    candidate_dir = tmp_path / case.candidate
    build_candidate(candidate_dir, case)

    result = run_validator(candidate_dir, case, extra_arguments=("--expected-precision", "BF16"))

    assert result.returncode == 1
    report = json.loads((candidate_dir / "runtime-verification.json").read_text())
    assert report["failure_codes"] == ["expected-precision-not-allowlisted"]


def test_cli_image_digest_drift_is_rejected_before_artifact_identity(tmp_path: Path) -> None:
    case = CASES[0]
    candidate_dir = tmp_path / case.candidate
    build_candidate(candidate_dir, case)

    result = run_validator(
        candidate_dir,
        case,
        extra_arguments=("--expected-image-digest", f"sha256:{'f' * 64}"),
    )

    assert result.returncode == 1
    report = json.loads((candidate_dir / "runtime-verification.json").read_text())
    assert report["failure_codes"] == ["expected-image-digest-not-allowlisted"]


def test_artifact_image_digest_drift_cannot_pass(tmp_path: Path) -> None:
    case = CASES[0]
    candidate_dir = tmp_path / case.candidate
    build_candidate(candidate_dir, case)
    image_path = candidate_dir / "image-inspect.json"
    image = json.loads(image_path.read_text())
    image[0]["Id"] = f"sha256:{'e' * 64}"
    write_json(image_path, image)

    result = run_validator(candidate_dir, case)

    assert result.returncode == 1
    report = json.loads((candidate_dir / "runtime-verification.json").read_text())
    assert report["failure_codes"] == ["image-digest-mismatch"]


def test_image_repo_digest_requires_the_exact_candidate_repository(tmp_path: Path) -> None:
    case = CASES[1]
    candidate_dir = tmp_path / case.candidate
    build_candidate(candidate_dir, case)
    image_path = candidate_dir / "image-inspect.json"
    image = json.loads(image_path.read_text())
    image[0]["RepoDigests"] = [f"nvcr.io/nim/nvidia/wrong-repository@{case.image_digest}"]
    write_json(image_path, image)

    result = run_validator(candidate_dir, case)

    assert result.returncode == 1
    report = json.loads((candidate_dir / "runtime-verification.json").read_text())
    assert report["failure_codes"] == ["image-repository-digest-mismatch"]


def test_cross_candidate_live_license_term_set_cannot_pass(tmp_path: Path) -> None:
    case = CASES[1]
    candidate_dir = tmp_path / case.candidate
    build_candidate(candidate_dir, case)
    reranker_terms = (
        "https://www.nvidia.com/en-us/agreements/enterprise-software/"
        "nvidia-software-license-agreement/ "
        "https://www.nvidia.com/en-us/agreements/enterprise-software/"
        "product-specific-terms-for-ai-products/ "
        "https://www.nvidia.com/en-us/agreements/enterprise-software/"
        "nvidia-community-models-license/ "
        "https://www.llama.com/llama3_2/license/"
    )
    replace_live_license_content(candidate_dir, reranker_terms)

    result = run_validator(candidate_dir, case)

    assert result.returncode == 1
    report = json.loads((candidate_dir / "runtime-verification.json").read_text())
    assert report["failure_codes"] == ["license-term-set-mismatch"]


def test_runtime_verification_is_create_only_and_preserves_existing_output(
    tmp_path: Path,
) -> None:
    case = CASES[2]
    candidate_dir = tmp_path / case.candidate
    build_candidate(candidate_dir, case)
    output = candidate_dir / "runtime-verification.json"
    original = b'{"immutable":"original"}\n'
    output.write_bytes(original)

    result = run_validator(candidate_dir, case)

    assert result.returncode == 2
    assert "evidence-output-already-exists" in result.stderr
    assert output.read_bytes() == original
    assert not list(candidate_dir.glob(".runtime-verification.json.tmp-*"))

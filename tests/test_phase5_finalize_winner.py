"""Fail-closed tests for the real-corpus Phase 5 winner finalizer."""

from __future__ import annotations

import hashlib
import json
import sys
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal
from uuid import UUID

import pytest
from app.domain.retrieval import IndexConfig, RetrievalPolicy
from ntc_rag_eval import LabeledScore, RetrievalObservation

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPOSITORY_ROOT))

from scripts.phase5_finalize_winner import (  # noqa: E402
    EMBEDDING_MODEL,
    FinalizationError,
    WinnerGoldCase,
    _calibrate_for_minimum_recall,
    _eval_gold,
    _evaluation_observations,
    _validate_operator_decision,
    approval_from_decision_report,
    build_corpus_snapshot,
    calibrate_from_calibration_split,
    load_gold,
    load_ready_corpus,
    reserve_output_directory,
    validate_final_gold,
)


def test_recall_first_calibration_keeps_floor_then_maximizes_precision() -> None:
    calibration = _calibrate_for_minimum_recall(
        (
            LabeledScore(0.90, True),
            LabeledScore(0.80, True),
            LabeledScore(0.30, True),
            LabeledScore(0.20, True),
            LabeledScore(0.85, False),
            LabeledScore(0.25, False),
            LabeledScore(0.15, False),
        ),
        minimum_recall=0.75,
    )

    assert calibration.threshold == pytest.approx(0.30)
    assert calibration.recall == pytest.approx(0.75)
    assert calibration.precision == pytest.approx(0.75)


def _write_jsonl(path: Path, records: Sequence[Mapping[str, object]]) -> None:
    path.write_text(
        "".join(json.dumps(record, ensure_ascii=False) + "\n" for record in records),
        encoding="utf-8",
    )


def _gold_record(
    case_id: str,
    split: str,
    query: str,
    *,
    sources: Sequence[str],
) -> dict[str, object]:
    return {
        "id": case_id,
        "split": split,
        "query": query,
        "answerable": bool(sources),
        "expected_source_names": list(sources),
        "language": "vi",
        "tags": ["retrieval"],
    }


def _case(
    case_id: str,
    split: Literal["calibration", "evaluation"],
    *,
    sources: tuple[str, ...],
) -> WinnerGoldCase:
    return WinnerGoldCase(
        id=case_id,
        split=split,
        query=f"query {case_id}",
        answerable=bool(sources),
        expected_source_names=sources,
        language="vi",
        tags=("retrieval",),
    )


def _ready_row(document_number: int, *, text: str | None = None) -> dict[str, object]:
    chunk_text = text or f"Nội dung đầy đủ của tài liệu {document_number}."
    document_id = UUID(int=document_number)
    return {
        "document_id": document_id,
        "tenant_id": UUID(int=1000),
        "owner_id": UUID(int=2000 + document_number),
        "source_name": f"source-{document_number}.pdf",
        "mime_type": "application/pdf",
        "document_language": "vi",
        "version_id": UUID(int=3000 + document_number),
        "chunk_config": {"child_size": 256, "overlap_percent": 10},
        "version_index_version": "phase4-current-v1",
        "normalized_artifact_path": f"normalized/{document_number}.json",
        "chunk_id": UUID(int=4000 + document_number),
        "parent_chunk_id": UUID(int=5000 + document_number),
        "text": chunk_text,
        "content_hash": hashlib.sha256(chunk_text.encode()).hexdigest(),
        "chunk_index_version": "phase4-current-v1",
        "token_count": 9,
        "page": document_number,
        "slide": None,
        "section_path": ["Mục chính", f"Mục {document_number}"],
        "chunk_language": "vi",
        "chunk_created_at": datetime(2026, 7, 15, 8, document_number, tzinfo=UTC),
    }


def _winner_config() -> IndexConfig:
    return IndexConfig(
        collection_name="ntc_chunks_embed300m_v2_test",
        index_version="phase4-current-v1",
        embedding_model=EMBEDDING_MODEL,
        embedding_model_version="1.13.0",
        vector_dimension=2048,
        chunk_size=256,
        overlap_percent=10,
    )


def _winner_policy(config: IndexConfig) -> RetrievalPolicy:
    return RetrievalPolicy(
        index_config_fingerprint=config.fingerprint,
        dense_candidate_limit=20,
        final_limit=10,
        dense_threshold=0.61,
        hnsw_ef=128,
        reranker_enabled=False,
    )


def test_load_gold_enforces_split_answerability_and_unique_queries(tmp_path: Path) -> None:
    gold_path = tmp_path / "gold.jsonl"
    records = [
        _gold_record("c-a", "calibration", "Ai phê duyệt?", sources=["source-1.pdf"]),
        _gold_record("c-u", "calibration", "Không có trong kho", sources=[]),
        _gold_record("e-a", "evaluation", "Ngày hiệu lực?", sources=["source-2.pdf"]),
        _gold_record("e-u", "evaluation", "Câu ngoài phạm vi", sources=[]),
    ]
    _write_jsonl(gold_path, records)

    cases = load_gold(gold_path)

    assert [case.split for case in cases] == [
        "calibration",
        "calibration",
        "evaluation",
        "evaluation",
    ]
    assert cases[0].expected_source_names == ("source-1.pdf",)

    mismatched = list(records)
    mismatched[0] = {**mismatched[0], "answerable": False}
    _write_jsonl(tmp_path / "mismatched.jsonl", mismatched)
    with pytest.raises(FinalizationError, match="answerable cases require sources"):
        load_gold(tmp_path / "mismatched.jsonl")

    duplicate_query = list(records)
    duplicate_query[3] = {**duplicate_query[3], "query": "  AI   PHÊ DUYỆT? "}
    _write_jsonl(tmp_path / "duplicate.jsonl", duplicate_query)
    with pytest.raises(FinalizationError, match="queries must be unique"):
        load_gold(tmp_path / "duplicate.jsonl")


def test_validate_final_gold_requires_real_sources_and_both_case_types() -> None:
    valid = (
        _case("c-a", "calibration", sources=("source-1.pdf",)),
        _case("c-u", "calibration", sources=()),
        _case("e-a", "evaluation", sources=("source-2.pdf",)),
        _case("e-u", "evaluation", sources=()),
    )
    validate_final_gold(
        valid,
        ("source-1.pdf", "source-2.pdf"),
        minimum_samples=4,
        maximum_samples=4,
    )

    unknown_source = (*valid[:-2], _case("e-a", "evaluation", sources=("missing.pdf",)), valid[-1])
    with pytest.raises(FinalizationError, match="absent from the READY corpus"):
        validate_final_gold(
            unknown_source,
            ("source-1.pdf", "source-2.pdf"),
            minimum_samples=4,
            maximum_samples=4,
        )

    no_evaluation_unanswerable = (
        *valid[:-1],
        _case("e-b", "evaluation", sources=("source-2.pdf",)),
    )
    with pytest.raises(FinalizationError, match=r"evaluation split requires.*unanswerable"):
        validate_final_gold(
            no_evaluation_unanswerable,
            ("source-1.pdf", "source-2.pdf"),
            minimum_samples=4,
            maximum_samples=4,
        )


def test_corpus_snapshot_preserves_full_text_acl_and_is_deterministic() -> None:
    rows = [_ready_row(1), _ready_row(2)]
    group_id = UUID(int=9001)
    acl_rows = [
        {
            "document_id": UUID(int=1),
            "principal_id": group_id,
            "principal_type": "group",
            "permission": "read",
        },
        {
            "document_id": UUID(int=2),
            "principal_id": UUID(int=9002),
            "principal_type": "user",
            "permission": "write",
        },
    ]

    snapshot = build_corpus_snapshot(rows, acl_rows, minimum_documents=2)
    reversed_snapshot = build_corpus_snapshot(
        list(reversed(rows)),
        list(reversed(acl_rows)),
        minimum_documents=2,
    )
    metadata_changed_rows = [dict(row) for row in rows]
    metadata_changed_rows[0]["chunk_language"] = "en"
    metadata_changed_snapshot = build_corpus_snapshot(
        metadata_changed_rows,
        acl_rows,
        minimum_documents=2,
    )

    assert snapshot.document_count == 2
    assert snapshot.version_count == 2
    assert snapshot.chunk_size == 256
    assert snapshot.overlap_percent == 10
    assert snapshot.index_version == "phase4-current-v1"
    assert snapshot.chunks[0].text == rows[0]["text"]
    assert f"group:{group_id}" in snapshot.chunks[0].acl_principals
    assert f"user:{rows[0]['owner_id']}" in snapshot.chunks[0].acl_principals
    assert snapshot.manifest_sha256 == reversed_snapshot.manifest_sha256
    assert snapshot.chunks == reversed_snapshot.chunks
    assert snapshot.manifest_sha256 != metadata_changed_snapshot.manifest_sha256


@pytest.mark.parametrize("broken_field", ["content_hash", "chunk_index_version"])
def test_corpus_snapshot_rejects_hash_or_index_binding_mismatch(broken_field: str) -> None:
    row = _ready_row(1)
    if broken_field == "content_hash":
        row[broken_field] = "0" * 64
        expected = "full text does not match"
    else:
        row[broken_field] = "stale-index-version"
        expected = "differs from its current document version"

    with pytest.raises(FinalizationError, match=expected):
        build_corpus_snapshot([row], [], minimum_documents=1)


def test_calibration_ignores_every_evaluation_score() -> None:
    cases = (
        _case("c-a", "calibration", sources=("source-a.pdf",)),
        _case("c-u", "calibration", sources=()),
        _case("e-a", "evaluation", sources=("source-e.pdf",)),
        _case("e-u", "evaluation", sources=()),
    )
    calibration_observations = (
        RetrievalObservation("c-a", ("source-a.pdf", "wrong.pdf"), (0.60, 0.20), 1.0),
        RetrievalObservation("c-u", ("wrong.pdf",), (0.50,), 1.0),
    )
    first = calibrate_from_calibration_split(
        cases,
        (
            *calibration_observations,
            RetrievalObservation("e-a", ("source-e.pdf",), (0.99,), 1.0),
            RetrievalObservation("e-u", ("wrong.pdf",), (0.98,), 1.0),
        ),
    )
    second = calibrate_from_calibration_split(
        cases,
        (
            *calibration_observations,
            RetrievalObservation("e-a", ("wrong.pdf",), (-0.99,), 1.0),
            RetrievalObservation("e-u", (), (), 1.0),
        ),
    )

    assert first == second
    assert first["threshold"] == pytest.approx(0.60)
    assert first["method"] == "minimum_recall_0.95_then_max_precision_calibration_split_only"
    assert first["minimum_recall"] == pytest.approx(0.95)
    assert first["max_f1_diagnostic"]["threshold"] == pytest.approx(0.60)
    assert first["calibration_case_count"] == 2


def test_evaluation_helpers_return_only_exact_heldout_ids() -> None:
    cases = (
        _case("c-a", "calibration", sources=("source-c.pdf",)),
        _case("c-u", "calibration", sources=()),
        _case("e-a", "evaluation", sources=("source-e.pdf",)),
        _case("e-u", "evaluation", sources=()),
    )
    observations = tuple(
        RetrievalObservation(
            case.id, case.expected_source_names, (0.8,) if case.answerable else (), 1.0
        )
        for case in cases
    )

    gold = _eval_gold(cases)
    heldout = _evaluation_observations(cases, observations)

    assert [sample.id for sample in gold] == ["e-a", "e-u"]
    assert [observation.sample_id for observation in heldout] == ["e-a", "e-u"]

    with pytest.raises(FinalizationError, match="held-out evaluation"):
        _evaluation_observations(cases, observations[:-1])


def test_output_directory_is_atomically_reserved_and_never_reused(tmp_path: Path) -> None:
    output = tmp_path / "run-001"

    assert reserve_output_directory(output) == output
    assert output.is_dir()
    with pytest.raises(FinalizationError, match="already exists"):
        reserve_output_directory(output)


def test_operator_must_explicitly_select_embed300m_and_record_bge_waiver() -> None:
    _validate_operator_decision(
        EMBEDDING_MODEL,
        "ntc-operator",
        "BGE was not deployed in this run; selection is an explicit operator waiver.",
    )

    with pytest.raises(FinalizationError, match="explicitly name Embed-300M"):
        _validate_operator_decision(
            "BAAI/bge-m3",
            "ntc-operator",
            "BGE was not deployed in this run; selection is an explicit operator waiver.",
        )
    with pytest.raises(FinalizationError, match="substantive explicit reason"):
        _validate_operator_decision(EMBEDDING_MODEL, "ntc-operator", "skip")


def test_approval_binds_written_report_policy_and_exact_point_count(tmp_path: Path) -> None:
    config = _winner_config()
    policy = _winner_policy(config)
    decision_path = tmp_path / "decision-report.json"
    decision_bytes = b'{"status":"APPROVED_FOR_ACTIVATION"}\n'
    decision_path.write_bytes(decision_bytes)

    observed_bytes, approval = approval_from_decision_report(
        decision_path,
        config=config,
        policy=policy,
        approved_by="ntc-operator",
        expected_point_count=37,
    )

    assert observed_bytes == decision_bytes
    assert approval.evidence_sha256 == hashlib.sha256(decision_bytes).hexdigest()
    assert approval.config_fingerprint == config.fingerprint
    assert approval.retrieval_policy_fingerprint == policy.fingerprint
    assert approval.expected_point_count == 37

    with pytest.raises(FinalizationError, match="must exist before winner approval"):
        approval_from_decision_report(
            tmp_path / "missing.json",
            config=config,
            policy=policy,
            approved_by="ntc-operator",
            expected_point_count=37,
        )


def test_postgresql_driver_error_never_exposes_password(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    password = "".join(("super-", "secret-", "database-", "password"))

    def fail_connect(*args: object, **kwargs: object) -> None:
        del args, kwargs
        raise RuntimeError(f"could not connect with password={password}")

    monkeypatch.setattr("scripts.phase5_finalize_winner.psycopg.connect", fail_connect)

    with pytest.raises(FinalizationError) as raised:
        load_ready_corpus(f"postgresql://ntc:{password}@localhost:5432/ntc")

    assert password not in str(raised.value)
    assert "PostgreSQL READY corpus could not be read" in str(raised.value)

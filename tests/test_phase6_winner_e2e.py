"""CPU-only contract tests for the immutable Phase 6 winner runner."""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import pytest
from app.domain.retrieval import IndexConfig, RetrievalPolicy

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPOSITORY_ROOT))

from scripts.phase6_winner_e2e import (  # noqa: E402
    ACTIVE_ALIAS,
    EMBEDDING_DIMENSION,
    EMBEDDING_MODEL,
    EMBEDDING_MODEL_VERSION,
    WinnerE2EError,
    load_live_cases,
    load_winner_binding,
    verify_gold_binding,
)


def _write_json(path: Path, value: object) -> bytes:
    raw = (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode()
    path.write_bytes(raw)
    return raw


def _winner_files(tmp_path: Path) -> tuple[Path, Path, IndexConfig, RetrievalPolicy]:
    config = IndexConfig(
        collection_name="ntc_chunks_embed300m_test",
        index_version="embed300m-v2-phase4",
        embedding_model=EMBEDDING_MODEL,
        embedding_model_version=EMBEDDING_MODEL_VERSION,
        vector_dimension=EMBEDDING_DIMENSION,
        chunk_size=256,
        overlap_percent=10,
    )
    policy = RetrievalPolicy(
        index_config_fingerprint=config.fingerprint,
        dense_candidate_limit=20,
        final_limit=10,
        dense_threshold=0.23,
        hnsw_ef=128,
        reranker_enabled=False,
    )
    decision = {
        "status": "APPROVED_FOR_ACTIVATION",
        "run_id": "phase5-test",
        "inputs": {"gold_sha256": "a" * 64},
        "winner_index": {
            "collection_name": config.collection_name,
            "index_version": config.index_version,
            "index_config_fingerprint": config.fingerprint,
            "embedding_model": config.embedding_model,
            "embedding_model_version": config.embedding_model_version,
            "dimension": config.vector_dimension,
            "distance": config.distance,
            "chunk_size": config.chunk_size,
            "overlap_percent": config.overlap_percent,
            "expected_point_count": 12,
        },
        "retrieval_policy": {
            "fingerprint": policy.fingerprint,
            "dense_candidate_limit": policy.dense_candidate_limit,
            "final_limit": policy.final_limit,
            "dense_threshold": policy.dense_threshold,
            "hnsw_ef": policy.hnsw_ef,
            "reranker_enabled": False,
            "deduplication_policy": policy.deduplication_policy,
        },
    }
    decision_path = tmp_path / "decision-report.json"
    decision_bytes = _write_json(decision_path, decision)
    receipt = {
        "status": "ACTIVATED",
        "decision_report_sha256": hashlib.sha256(decision_bytes).hexdigest(),
        "approval": {
            "config_fingerprint": config.fingerprint,
            "retrieval_policy_fingerprint": policy.fingerprint,
            "expected_point_count": 12,
        },
        "alias": ACTIVE_ALIAS,
        "alias_verified": True,
        "alias_readback": config.collection_name,
        "activated_collection": config.collection_name,
    }
    receipt_path = tmp_path / "activation-receipt.json"
    _write_json(receipt_path, receipt)
    return decision_path, receipt_path, config, policy


def test_winner_binding_recomputes_index_policy_and_receipt_hash(tmp_path: Path) -> None:
    decision, receipt, config, policy = _winner_files(tmp_path)

    binding = load_winner_binding(decision, receipt)

    assert binding.config == config
    assert binding.policy == policy
    assert binding.expected_point_count == 12
    assert binding.gold_sha256 == "a" * 64
    assert binding.decision_sha256 == hashlib.sha256(decision.read_bytes()).hexdigest()


def test_winner_binding_rejects_receipt_for_different_decision(tmp_path: Path) -> None:
    decision, receipt, _config, _policy = _winner_files(tmp_path)
    parsed = json.loads(decision.read_text())
    parsed["run_id"] = "tampered-after-activation"
    _write_json(decision, parsed)

    with pytest.raises(WinnerE2EError, match="does not bind"):
        load_winner_binding(decision, receipt)


def test_gold_must_match_the_exact_phase5_decision_bytes(tmp_path: Path) -> None:
    gold = tmp_path / "gold.jsonl"
    gold.write_text('{"id":"held-out"}\n', encoding="utf-8")
    expected = hashlib.sha256(gold.read_bytes()).hexdigest()

    assert verify_gold_binding(gold, expected) == expected
    gold.write_text('{"id":"different"}\n', encoding="utf-8")
    with pytest.raises(WinnerE2EError, match="exact held-out set"):
        verify_gold_binding(gold, expected)


def test_live_case_selection_uses_heldout_same_language_and_no_raw_text(tmp_path: Path) -> None:
    gold = tmp_path / "gold.jsonl"
    rows = (
        {
            "id": "calibration-answer",
            "split": "calibration",
            "query": "ignored",
            "answerable": True,
            "expected_source_names": ["ignored.txt"],
            "language": "en",
        },
        {
            "id": "evaluation-answer",
            "split": "evaluation",
            "query": "Câu hỏi có đáp án?",
            "answerable": True,
            "expected_source_names": ["policy.pdf"],
            "language": "vi",
        },
        {
            "id": "evaluation-no-answer-en",
            "split": "evaluation",
            "query": "Unknown?",
            "answerable": False,
            "expected_source_names": [],
            "language": "en",
        },
        {
            "id": "evaluation-no-answer-vi",
            "split": "evaluation",
            "query": "Không có dữ liệu?",
            "answerable": False,
            "expected_source_names": [],
            "language": "vi",
        },
    )
    gold.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")

    answerable, unanswerable = load_live_cases(gold)

    assert answerable.case_id == "evaluation-answer"
    assert unanswerable.case_id == "evaluation-no-answer-vi"

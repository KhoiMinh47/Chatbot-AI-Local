"""CPU-only tests for the Phase 5 dataset and chunk-grid runner."""

from __future__ import annotations

import sys
from collections import Counter
from pathlib import Path

import pytest
from app.domain.retrieval import IndexConfig
from ntc_rag_eval import load_gold_jsonl

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPOSITORY_ROOT))

from scripts.phase5_benchmark import (  # noqa: E402
    _junit_evidence,
    _load_corpus,
    build_chunk_payloads,
    render_section,
    select_provisional_chunk_winner,
    select_reranker_policy,
)


def test_qdrant_junit_evidence_must_pass_without_skips(tmp_path: Path) -> None:
    passing = tmp_path / "passing.xml"
    passing.write_text(
        '<testsuites><testsuite tests="1" failures="0" errors="0" skipped="0"/></testsuites>',
        encoding="utf-8",
    )
    evidence = _junit_evidence(passing)
    assert evidence["result"] == "passed"
    assert evidence["tests"] == 1

    skipped = tmp_path / "skipped.xml"
    skipped.write_text(
        '<testsuites><testsuite tests="1" failures="0" errors="0" skipped="1"/></testsuites>',
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="did not pass without skips"):
        _junit_evidence(skipped)


def config(*, size: int, overlap: int) -> IndexConfig:
    return IndexConfig(
        collection_name=f"ntc_p5_test_s{size}_o{overlap}",
        index_version=f"test-s{size}-o{overlap}",
        embedding_model="fixture",
        embedding_model_version="1",
        vector_dimension=2,
        chunk_size=size,
        overlap_percent=overlap,
    )


def test_gold_fixture_has_exact_master_plan_distribution() -> None:
    samples = load_gold_jsonl(REPOSITORY_ROOT / "benchmarks/phase5/gold.jsonl")
    tags = Counter(tag for sample in samples for tag in sample.tags)

    assert len(samples) == 100
    assert tags == {
        "fact": 45,
        "table": 15,
        "multi_hop": 15,
        "followup": 10,
        "unanswerable": 10,
        "injection": 5,
    }
    assert sum(sample.answerable for sample in samples) == 85


def test_chunk_grid_is_deterministic_bounded_and_overlap_changes_windows() -> None:
    sections = _load_corpus(REPOSITORY_ROOT / "benchmarks/phase5/corpus.jsonl")
    section = sections[0]
    no_overlap = build_chunk_payloads(section, config(size=256, overlap=0))
    overlap = build_chunk_payloads(section, config(size=256, overlap=20))

    assert render_section(section) == render_section(section)
    assert len(no_overlap) >= 2
    assert len(overlap) >= len(no_overlap)
    assert [chunk.chunk_id for chunk in no_overlap] == [
        chunk.chunk_id for chunk in build_chunk_payloads(section, config(size=256, overlap=0))
    ]
    assert {chunk.index_version for chunk in no_overlap} == {"test-s256-o0"}
    assert all(chunk.section_path[0] == section.section_id for chunk in no_overlap)
    assert all(chunk.token_count <= 256 for chunk in (*no_overlap, *overlap))

    for candidate_size in (256, 512, 768, 1024):
        for candidate_overlap in (0, 10, 20):
            candidate = config(size=candidate_size, overlap=candidate_overlap)
            chunks = tuple(
                chunk
                for corpus_section in sections
                for chunk in build_chunk_payloads(corpus_section, candidate)
            )
            assert chunks
            assert all(chunk.token_count <= candidate_size for chunk in chunks)


def fake_result(
    *,
    size: int,
    overlap: int,
    recall: float,
    mrr: float,
    ndcg: float,
    p95: float,
) -> dict[str, object]:
    return {
        "chunk_size": size,
        "overlap_percent": overlap,
        "raw_evaluation": {
            "overall": {
                "recall_at_10": recall,
                "mrr_at_10": mrr,
                "ndcg_at_10": ndcg,
                "context_precision_at_10": 0.5,
            },
            "latency": {"p95_ms": p95},
        },
    }


def test_chunk_winner_prioritizes_quality_before_latency_or_size() -> None:
    results = [
        fake_result(size=256, overlap=0, recall=0.90, mrr=0.90, ndcg=0.90, p95=1),
        fake_result(size=1024, overlap=20, recall=0.91, mrr=0.70, ndcg=0.70, p95=100),
    ]

    assert select_provisional_chunk_winner(results) == 1


def retrieval_report(
    *,
    raw_ndcg: float,
    threshold_recall: float,
    threshold_mrr: float,
    threshold_ndcg: float,
    gate: bool,
    p95: float,
) -> dict[str, object]:
    return {
        "raw_evaluation": {
            "overall": {"ndcg_at_10": raw_ndcg},
            "latency": {"p95_ms": p95},
        },
        "threshold_evaluation": {
            "overall": {
                "recall_at_10": threshold_recall,
                "mrr_at_10": threshold_mrr,
                "ndcg_at_10": threshold_ndcg,
            },
            "quality_gate_passed": gate,
        },
    }


def test_reranker_policy_rejects_small_gain_with_gate_and_latency_regression() -> None:
    dense = retrieval_report(
        raw_ndcg=0.997,
        threshold_recall=0.91,
        threshold_mrr=0.96,
        threshold_ndcg=0.92,
        gate=True,
        p95=21,
    )
    rerank = retrieval_report(
        raw_ndcg=1.0,
        threshold_recall=0.86,
        threshold_mrr=0.90,
        threshold_ndcg=0.87,
        gate=False,
        p95=72,
    )

    selected, reason = select_reranker_policy(dense, rerank)

    assert selected == "off"
    assert "material-gain" in reason

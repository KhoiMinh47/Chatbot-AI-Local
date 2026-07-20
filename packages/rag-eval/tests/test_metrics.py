"""Unit tests for deterministic Phase 5 retrieval metrics."""

from __future__ import annotations

import pytest
from ntc_rag_eval import (
    GoldSample,
    LabeledScore,
    RetrievalObservation,
    calibrate_threshold,
    evaluate_retrieval,
)


def sample(sample_id: str, relevant: tuple[str, ...], *, answerable: bool = True) -> GoldSample:
    return GoldSample(
        id=sample_id,
        question=f"question {sample_id}",
        language="en",
        expected_answer="expected",
        answerable=answerable,
        gold_document_ids=("doc-1",) if answerable else (),
        gold_chunk_or_section_ids=relevant if answerable else (),
        tags=("fact",),
    )


def observation(
    sample_id: str,
    retrieved: tuple[str, ...],
    *,
    latency_ms: float,
) -> RetrievalObservation:
    return RetrievalObservation(
        sample_id=sample_id,
        retrieved_ids=retrieved,
        scores=tuple(float(len(retrieved) - index) for index in range(len(retrieved))),
        latency_ms=latency_ms,
    )


def test_metrics_use_macro_recall_mrr_and_ndcg() -> None:
    report = evaluate_retrieval(
        (
            sample("q1", ("a", "b")),
            sample("q2", ("c",)),
            sample("q3", (), answerable=False),
        ),
        (
            observation("q1", ("x", "a", "b"), latency_ms=10),
            observation("q2", ("x", "y", "c"), latency_ms=20),
            observation("q3", (), latency_ms=30),
        ),
        config_fingerprint="config-sha",
    )

    assert report.total_samples == 3
    assert report.answerable_samples == 2
    assert report.overall.recall_at_5 == 1.0
    assert report.overall.mrr_at_10 == pytest.approx((1 / 2 + 1 / 3) / 2)
    assert 0 < report.overall.ndcg_at_10 < 1
    assert report.latency.p50_ms == 20
    assert report.latency.p95_ms == pytest.approx(29)
    assert report.unanswerable_nonempty_rate == 0
    assert len(report.dataset_sha256) == 64
    assert len(report.observations_sha256) == 64


def test_evaluator_rejects_partial_or_extra_observation_sets() -> None:
    with pytest.raises(ValueError, match="exact gold"):
        evaluate_retrieval(
            (sample("q1", ("a",)),),
            (observation("q2", ("a",), latency_ms=1),),
            config_fingerprint="config",
        )


def test_threshold_calibration_uses_f1_then_precision_then_threshold() -> None:
    result = calibrate_threshold(
        (
            LabeledScore(0.9, True),
            LabeledScore(0.8, True),
            LabeledScore(0.7, False),
            LabeledScore(0.2, False),
        )
    )

    assert result.threshold == 0.8
    assert result.precision == 1.0
    assert result.recall == 1.0
    assert result.f1 == 1.0


def test_calibration_requires_positive_and_negative_examples() -> None:
    with pytest.raises(ValueError, match="both relevant and non-relevant"):
        calibrate_threshold((LabeledScore(0.5, True),))

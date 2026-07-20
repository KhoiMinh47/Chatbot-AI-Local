"""Deterministic F1 threshold calibration for dense or reranker scores."""

from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class LabeledScore:
    score: float
    relevant: bool

    def __post_init__(self) -> None:
        if not math.isfinite(self.score):
            raise ValueError("score must be finite")


@dataclass(frozen=True, slots=True)
class ThresholdCalibration:
    threshold: float
    precision: float
    recall: float
    f1: float
    true_positive: int
    false_positive: int
    false_negative: int
    positives: int
    negatives: int


def calibrate_threshold(scores: tuple[LabeledScore, ...]) -> ThresholdCalibration:
    """Choose max-F1 threshold; ties prefer precision, then the higher threshold."""

    if not scores:
        raise ValueError("scores must not be empty")
    positives = sum(item.relevant for item in scores)
    negatives = len(scores) - positives
    if positives == 0 or negatives == 0:
        raise ValueError("calibration requires both relevant and non-relevant scores")

    candidates = sorted({item.score for item in scores}, reverse=True)
    best: ThresholdCalibration | None = None
    for threshold in candidates:
        true_positive = sum(item.relevant and item.score >= threshold for item in scores)
        false_positive = sum(not item.relevant and item.score >= threshold for item in scores)
        false_negative = positives - true_positive
        precision = true_positive / (true_positive + false_positive)
        recall = true_positive / positives
        f1 = 0.0 if precision + recall == 0 else 2 * precision * recall / (precision + recall)
        candidate = ThresholdCalibration(
            threshold=threshold,
            precision=precision,
            recall=recall,
            f1=f1,
            true_positive=true_positive,
            false_positive=false_positive,
            false_negative=false_negative,
            positives=positives,
            negatives=negatives,
        )
        if best is None or (candidate.f1, candidate.precision, candidate.threshold) > (
            best.f1,
            best.precision,
            best.threshold,
        ):
            best = candidate

    if best is None:
        raise RuntimeError("threshold calibration produced no candidate")
    return best

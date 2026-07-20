"""Reproducible retrieval evaluation primitives."""

from ntc_rag_eval.calibration import LabeledScore, ThresholdCalibration, calibrate_threshold
from ntc_rag_eval.io import load_gold_jsonl, load_observations_jsonl
from ntc_rag_eval.metrics import EvaluationReport, evaluate_retrieval
from ntc_rag_eval.models import GoldSample, RetrievalObservation

__all__ = [
    "EvaluationReport",
    "GoldSample",
    "LabeledScore",
    "RetrievalObservation",
    "ThresholdCalibration",
    "calibrate_threshold",
    "evaluate_retrieval",
    "load_gold_jsonl",
    "load_observations_jsonl",
]

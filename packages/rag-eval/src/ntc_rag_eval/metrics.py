"""Recall, MRR, nDCG, context precision, and latency aggregation."""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import asdict, dataclass

from ntc_rag_eval.models import GoldSample, RetrievalObservation


@dataclass(frozen=True, slots=True)
class MetricSlice:
    samples: int
    recall_at_5: float
    recall_at_10: float
    mrr_at_10: float
    ndcg_at_10: float
    context_precision_at_10: float


@dataclass(frozen=True, slots=True)
class LatencySummary:
    p50_ms: float
    p95_ms: float


@dataclass(frozen=True, slots=True)
class EvaluationReport:
    schema_version: int
    dataset_sha256: str
    observations_sha256: str
    config_fingerprint: str
    total_samples: int
    answerable_samples: int
    unanswerable_samples: int
    unanswerable_nonempty_rate: float
    overall: MetricSlice
    by_tag: dict[str, MetricSlice]
    latency: LatencySummary
    quality_gate_passed: bool

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def _canonical_sha256(value: object) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode()
    return hashlib.sha256(encoded).hexdigest()


def _recall(relevant: frozenset[str], retrieved: tuple[str, ...], k: int) -> float:
    return len(relevant.intersection(retrieved[:k])) / len(relevant)


def _reciprocal_rank(relevant: frozenset[str], retrieved: tuple[str, ...], k: int) -> float:
    for rank, item_id in enumerate(retrieved[:k], start=1):
        if item_id in relevant:
            return 1 / rank
    return 0.0


def _ndcg(relevant: frozenset[str], retrieved: tuple[str, ...], k: int) -> float:
    dcg = sum(
        1 / math.log2(rank + 1)
        for rank, item_id in enumerate(retrieved[:k], start=1)
        if item_id in relevant
    )
    ideal_count = min(len(relevant), k)
    ideal_dcg = sum(1 / math.log2(rank + 1) for rank in range(1, ideal_count + 1))
    return dcg / ideal_dcg


def _context_precision(relevant: frozenset[str], retrieved: tuple[str, ...], k: int) -> float:
    candidates = retrieved[:k]
    if not candidates:
        return 0.0
    return len(relevant.intersection(candidates)) / len(candidates)


def _mean(values: list[float]) -> float:
    return sum(values) / len(values)


def _metric_slice(
    samples: list[GoldSample],
    observations: dict[str, RetrievalObservation],
) -> MetricSlice:
    if not samples:
        return MetricSlice(0, 0.0, 0.0, 0.0, 0.0, 0.0)
    relevant_sets = [frozenset(sample.gold_chunk_or_section_ids) for sample in samples]
    retrieved = [observations[sample.id].retrieved_ids for sample in samples]
    return MetricSlice(
        samples=len(samples),
        recall_at_5=_mean(
            [
                _recall(relevant, result, 5)
                for relevant, result in zip(relevant_sets, retrieved, strict=True)
            ]
        ),
        recall_at_10=_mean(
            [
                _recall(relevant, result, 10)
                for relevant, result in zip(relevant_sets, retrieved, strict=True)
            ]
        ),
        mrr_at_10=_mean(
            [
                _reciprocal_rank(relevant, result, 10)
                for relevant, result in zip(relevant_sets, retrieved, strict=True)
            ]
        ),
        ndcg_at_10=_mean(
            [
                _ndcg(relevant, result, 10)
                for relevant, result in zip(relevant_sets, retrieved, strict=True)
            ]
        ),
        context_precision_at_10=_mean(
            [
                _context_precision(relevant, result, 10)
                for relevant, result in zip(relevant_sets, retrieved, strict=True)
            ]
        ),
    )


def _percentile(values: list[float], percentile: float) -> float:
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    position = (len(ordered) - 1) * percentile
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    weight = position - lower
    return ordered[lower] * (1 - weight) + ordered[upper] * weight


def evaluate_retrieval(
    gold_samples: tuple[GoldSample, ...],
    observations: tuple[RetrievalObservation, ...],
    *,
    config_fingerprint: str,
) -> EvaluationReport:
    """Evaluate an exact, complete observation set and bind the report to input hashes."""

    if not gold_samples:
        raise ValueError("gold_samples must not be empty")
    if not config_fingerprint.strip():
        raise ValueError("config_fingerprint must not be blank")
    gold_ids = [sample.id for sample in gold_samples]
    observation_ids = [observation.sample_id for observation in observations]
    if len(gold_ids) != len(set(gold_ids)):
        raise ValueError("gold sample IDs must be unique")
    if len(observation_ids) != len(set(observation_ids)):
        raise ValueError("observation sample IDs must be unique")
    if set(gold_ids) != set(observation_ids):
        raise ValueError("observations must cover the exact gold sample ID set")

    observation_map = {observation.sample_id: observation for observation in observations}
    answerable = [sample for sample in gold_samples if sample.answerable]
    unanswerable = [sample for sample in gold_samples if not sample.answerable]
    overall = _metric_slice(answerable, observation_map)
    tags = sorted({tag for sample in answerable for tag in sample.tags})
    by_tag = {
        tag: _metric_slice([sample for sample in answerable if tag in sample.tags], observation_map)
        for tag in tags
    }
    unanswerable_nonempty = sum(
        bool(observation_map[sample.id].retrieved_ids) for sample in unanswerable
    )
    unanswerable_nonempty_rate = unanswerable_nonempty / len(unanswerable) if unanswerable else 0.0
    latencies = [observation.latency_ms for observation in observations]

    gold_payload = [asdict(sample) for sample in gold_samples]
    observation_payload = [asdict(observation) for observation in observations]
    return EvaluationReport(
        schema_version=1,
        dataset_sha256=_canonical_sha256(gold_payload),
        observations_sha256=_canonical_sha256(observation_payload),
        config_fingerprint=config_fingerprint,
        total_samples=len(gold_samples),
        answerable_samples=len(answerable),
        unanswerable_samples=len(unanswerable),
        unanswerable_nonempty_rate=unanswerable_nonempty_rate,
        overall=overall,
        by_tag=by_tag,
        latency=LatencySummary(
            p50_ms=_percentile(latencies, 0.50),
            p95_ms=_percentile(latencies, 0.95),
        ),
        quality_gate_passed=overall.recall_at_10 >= 0.90 and overall.mrr_at_10 >= 0.75,
    )

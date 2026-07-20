"""Strict JSONL loaders for reproducible Phase 5 inputs."""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import cast

from ntc_rag_eval.models import GoldSample, Language, RetrievalObservation


def _object(value: object, location: str) -> Mapping[str, object]:
    if not isinstance(value, dict):
        raise ValueError(f"{location} must contain a JSON object")
    return cast(dict[str, object], value)


def _string(value: object, field_name: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{field_name} must be a string")
    return value


def _boolean(value: object, field_name: str) -> bool:
    if not isinstance(value, bool):
        raise ValueError(f"{field_name} must be a boolean")
    return value


def _string_tuple(value: object, field_name: str) -> tuple[str, ...]:
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise ValueError(f"{field_name} must be an array of strings")
    return tuple(cast(list[str], value))


def _number_tuple(value: object, field_name: str) -> tuple[float, ...]:
    if not isinstance(value, list) or any(
        isinstance(item, bool) or not isinstance(item, int | float) for item in value
    ):
        raise ValueError(f"{field_name} must be an array of numbers")
    return tuple(float(item) for item in cast(list[int | float], value))


def _jsonl(path: Path) -> list[Mapping[str, object]]:
    records: list[Mapping[str, object]] = []
    for line_number, raw_line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not raw_line.strip():
            raise ValueError(f"{path}:{line_number} must not be blank")
        try:
            value: object = json.loads(raw_line)
        except json.JSONDecodeError as error:
            raise ValueError(f"{path}:{line_number} is invalid JSON: {error.msg}") from None
        records.append(_object(value, f"{path}:{line_number}"))
    if not records:
        raise ValueError(f"{path} must not be empty")
    return records


def load_gold_jsonl(path: Path) -> tuple[GoldSample, ...]:
    samples: list[GoldSample] = []
    for record in _jsonl(path):
        samples.append(
            GoldSample(
                id=_string(record.get("id"), "id"),
                question=_string(record.get("question"), "question"),
                language=cast(Language, _string(record.get("language"), "language")),
                expected_answer=_string(record.get("expected_answer"), "expected_answer"),
                answerable=_boolean(record.get("answerable"), "answerable"),
                gold_document_ids=_string_tuple(
                    record.get("gold_document_ids"), "gold_document_ids"
                ),
                gold_chunk_or_section_ids=_string_tuple(
                    record.get("gold_chunk_or_section_ids"),
                    "gold_chunk_or_section_ids",
                ),
                tags=_string_tuple(record.get("tags"), "tags"),
            )
        )
    return tuple(samples)


def load_observations_jsonl(path: Path) -> tuple[RetrievalObservation, ...]:
    observations: list[RetrievalObservation] = []
    for record in _jsonl(path):
        latency = record.get("latency_ms")
        if isinstance(latency, bool) or not isinstance(latency, int | float):
            raise ValueError("latency_ms must be numeric")
        observations.append(
            RetrievalObservation(
                sample_id=_string(record.get("sample_id"), "sample_id"),
                retrieved_ids=_string_tuple(record.get("retrieved_ids"), "retrieved_ids"),
                scores=_number_tuple(record.get("scores"), "scores"),
                latency_ms=float(latency),
            )
        )
    return tuple(observations)

"""Strict input models for gold queries and retrieval observations."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Literal

type Language = Literal["vi", "en"]


def _non_blank(value: str, field_name: str) -> None:
    if not value.strip():
        raise ValueError(f"{field_name} must not be blank")


def _unique_non_blank(values: tuple[str, ...], field_name: str, *, allow_empty: bool) -> None:
    if not allow_empty and not values:
        raise ValueError(f"{field_name} must not be empty")
    if any(not value.strip() for value in values):
        raise ValueError(f"{field_name} must contain only non-blank values")
    if len(values) != len(set(values)):
        raise ValueError(f"{field_name} must not contain duplicates")


@dataclass(frozen=True, slots=True)
class GoldSample:
    """One retrieval sample using the master-plan gold schema."""

    id: str
    question: str
    language: Language
    expected_answer: str
    answerable: bool
    gold_document_ids: tuple[str, ...]
    gold_chunk_or_section_ids: tuple[str, ...]
    tags: tuple[str, ...]

    def __post_init__(self) -> None:
        _non_blank(self.id, "id")
        _non_blank(self.question, "question")
        _non_blank(self.expected_answer, "expected_answer")
        if self.language not in {"vi", "en"}:
            raise ValueError("language must be vi or en")
        _unique_non_blank(self.gold_document_ids, "gold_document_ids", allow_empty=True)
        _unique_non_blank(
            self.gold_chunk_or_section_ids,
            "gold_chunk_or_section_ids",
            allow_empty=True,
        )
        _unique_non_blank(self.tags, "tags", allow_empty=False)
        if self.answerable and (not self.gold_document_ids or not self.gold_chunk_or_section_ids):
            raise ValueError("answerable samples require gold document and chunk/section IDs")
        if not self.answerable and (self.gold_document_ids or self.gold_chunk_or_section_ids):
            raise ValueError("unanswerable samples must not declare gold IDs")


@dataclass(frozen=True, slots=True)
class RetrievalObservation:
    """Ranked retrieval IDs and latency for one exact gold sample."""

    sample_id: str
    retrieved_ids: tuple[str, ...]
    scores: tuple[float, ...]
    latency_ms: float

    def __post_init__(self) -> None:
        _non_blank(self.sample_id, "sample_id")
        _unique_non_blank(self.retrieved_ids, "retrieved_ids", allow_empty=True)
        if len(self.scores) != len(self.retrieved_ids):
            raise ValueError("scores must align one-to-one with retrieved_ids")
        if any(not math.isfinite(score) for score in self.scores):
            raise ValueError("scores must contain only finite values")
        if any(left < right for left, right in zip(self.scores, self.scores[1:], strict=False)):
            raise ValueError("scores must be ordered descending")
        if not math.isfinite(self.latency_ms) or self.latency_ms < 0:
            raise ValueError("latency_ms must be a finite non-negative number")

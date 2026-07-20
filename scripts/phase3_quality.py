#!/usr/bin/env python3
"""Deterministic Phase 3 grounded-answer quality and citation benchmark.

This runner calls one already-running OpenAI-compatible LLM endpoint. It does
not parse documents, retrieve from Qdrant, judge with another model, or claim
production RAG quality. All scoring rules are local, transparent, and tied to
the synthetic fixture file committed with the repository.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import os
import re
import shutil
import sys
import tempfile
import time
import unicodedata
from collections.abc import Mapping, Sequence
from contextlib import suppress
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal, cast
from urllib.parse import urlsplit

import httpx2 as httpx

type Language = Literal["vi", "en"]
type Category = Literal[
    "fact",
    "table",
    "multi_section",
    "unanswerable",
    "prompt_injection",
    "citation_instruction",
]
type FormatKind = Literal["single_line", "labelled", "bullets", "json", "refusal_exact"]
type ReasoningControlMode = Literal["llama-standard", "nemotron-no-think"]

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CASES_PATH = REPOSITORY_ROOT / "benchmarks" / "phase3" / "quality_cases.json"
EVIDENCE_SCHEMA_VERSION = 2
QUALITY_SCOPE = "synthetic_grounded_llm_smoke_not_ingestion_retrieval_or_production_quality"
REFUSAL_DEFAULT = "INSUFFICIENT_EVIDENCE"
_SAFE_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/+-]*$")
_SAFE_IMAGE_REFERENCE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/:@+-]*$")
_SAFE_CASE_ID = re.compile(r"^[a-z][a-z0-9_]{2,63}$")
_SAFE_CITATION_ID = re.compile(r"^S[1-9][0-9]*$")
_CITATION = re.compile(r"\[([A-Z][A-Z0-9_-]*)\]")
_SHA256_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
_URL = re.compile(r"https?://[^\s\]\[<>'\"]+", re.IGNORECASE)
_CREDENTIAL = re.compile(
    r"(?:nvapi-|sk-|hf_|gh[pousr]_|github_pat_|xox[baprs]-)[A-Za-z0-9_-]{12,}",
    re.IGNORECASE,
)
_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_REQUIRED_CATEGORIES = frozenset(
    {"fact", "table", "multi_section", "unanswerable", "prompt_injection"}
)
_REASONING_CONTROL_TEXT: dict[ReasoningControlMode, str] = {
    "llama-standard": "detailed thinking off",
    "nemotron-no-think": "/no_think",
}


class SafeQualityError(RuntimeError):
    """Expected failure represented only by a persistence-safe error code."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True, slots=True)
class EvidenceBlock:
    citation_id: str
    text: str


@dataclass(frozen=True, slots=True)
class FormatRule:
    kind: FormatKind
    instruction: str
    max_characters: int
    prefix: str | None = None
    expected_lines: int | None = None


@dataclass(frozen=True, slots=True)
class QualityCase:
    case_id: str
    language: Language
    category: Category
    question: str
    evidence: tuple[EvidenceBlock, ...]
    answerable: bool
    expected_term_groups: tuple[tuple[str, ...], ...]
    term_group_citations: tuple[tuple[str, ...], ...]
    required_citations: tuple[str, ...]
    allowed_citations: tuple[str, ...]
    forbidden_output_terms: tuple[str, ...]
    format_rule: FormatRule


@dataclass(frozen=True, slots=True)
class QualitySuite:
    schema_version: int
    sha256: str
    refusal_marker: str
    system_prompt: str
    cases: tuple[QualityCase, ...]


@dataclass(frozen=True, slots=True)
class RuntimeMetadata:
    candidate_id: str
    image_ref: str
    image_digest: str
    nim_version: str
    runtime_profile: str
    precision: str
    max_model_length: int
    license_id: str


@dataclass(frozen=True, slots=True)
class RunnerConfig:
    base_url: str
    model: str
    metadata: RuntimeMetadata
    timeout_seconds: float = 120.0
    seed: int = 17
    max_tokens: int = 256
    reasoning_control_mode: ReasoningControlMode = "llama-standard"


@dataclass(frozen=True, slots=True)
class Usage:
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int


@dataclass(frozen=True, slots=True)
class Completion:
    answer: str
    response_model: str
    finish_reason: str | None
    usage: Usage | None
    latency_seconds: float


@dataclass(frozen=True, slots=True)
class Score:
    correctness: float
    faithfulness_citation: float
    instruction_following: float
    observed_citations: tuple[str, ...]
    term_group_matches: tuple[bool, ...]
    citation_allowlist_precision: float
    required_citation_coverage: float
    claim_citation_alignment: float
    format_pass: bool
    forbidden_terms_absent: bool
    refusal_rule_pass: bool
    json_citations_in_answer_absent: bool
    hard_gate_pass: bool
    hard_gate_failures: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class CaseResult:
    case: QualityCase
    status: Literal["ok", "failed"]
    error_code: str | None
    safe_answer: str | None
    answer_sha256: str | None
    answer_redactions: int
    answer_truncated: bool
    response_model: str | None
    finish_reason: str | None
    usage: Usage | None
    latency_seconds: float | None
    score: Score


def _mapping(value: object, code: str) -> Mapping[str, object]:
    if not isinstance(value, dict):
        raise SafeQualityError(code)
    return cast(Mapping[str, object], value)


def _array(value: object, code: str) -> list[object]:
    if not isinstance(value, list):
        raise SafeQualityError(code)
    return cast(list[object], value)


def _required_string(section: Mapping[str, object], key: str, code: str) -> str:
    value = section.get(key)
    if not isinstance(value, str) or not value.strip():
        raise SafeQualityError(code)
    return value


def _string_tuple(section: Mapping[str, object], key: str, code: str) -> tuple[str, ...]:
    values = _array(section.get(key), code)
    if any(not isinstance(value, str) or not value.strip() for value in values):
        raise SafeQualityError(code)
    return tuple(cast(str, value) for value in values)


def normalize_text(value: str) -> str:
    """Normalize case and whitespace without language-specific stemming."""

    normalized = unicodedata.normalize("NFC", value).casefold().replace("\u2019", "'")
    return " ".join(normalized.split())


def _normalize_claim_text(value: str) -> str:
    normalized = unicodedata.normalize("NFC", value).casefold().replace("\u2019", "'")
    return "\n".join(" ".join(line.split()) for line in normalized.splitlines())


def _parse_format(section: Mapping[str, object], case_id: str) -> FormatRule:
    kind = section.get("kind")
    if kind not in {"single_line", "labelled", "bullets", "json", "refusal_exact"}:
        raise SafeQualityError(f"invalid_format_kind_{case_id}")
    max_characters = section.get("max_characters")
    if (
        not isinstance(max_characters, int)
        or isinstance(max_characters, bool)
        or not 1 <= max_characters <= 4096
    ):
        raise SafeQualityError(f"invalid_format_max_characters_{case_id}")
    instruction = _required_string(section, "instruction", f"invalid_format_instruction_{case_id}")
    raw_prefix = section.get("prefix")
    prefix = raw_prefix if isinstance(raw_prefix, str) and raw_prefix else None
    raw_expected_lines = section.get("expected_lines")
    expected_lines = (
        raw_expected_lines
        if isinstance(raw_expected_lines, int) and not isinstance(raw_expected_lines, bool)
        else None
    )
    if kind == "labelled" and prefix is None:
        raise SafeQualityError(f"missing_format_prefix_{case_id}")
    if kind == "bullets" and (expected_lines is None or not 1 <= expected_lines <= 10):
        raise SafeQualityError(f"invalid_format_expected_lines_{case_id}")
    return FormatRule(
        kind=cast(FormatKind, kind),
        instruction=instruction,
        max_characters=max_characters,
        prefix=prefix,
        expected_lines=expected_lines,
    )


def _parse_case(value: object) -> QualityCase:
    section = _mapping(value, "invalid_case_object")
    case_id = _required_string(section, "id", "invalid_case_id")
    if not _SAFE_CASE_ID.fullmatch(case_id):
        raise SafeQualityError("invalid_case_id")
    language = section.get("language")
    if language not in {"vi", "en"}:
        raise SafeQualityError(f"invalid_case_language_{case_id}")
    category = section.get("category")
    if category not in {
        "fact",
        "table",
        "multi_section",
        "unanswerable",
        "prompt_injection",
        "citation_instruction",
    }:
        raise SafeQualityError(f"invalid_case_category_{case_id}")
    question = _required_string(section, "question", f"invalid_case_question_{case_id}")

    evidence_values = _array(section.get("evidence"), f"invalid_case_evidence_{case_id}")
    if not evidence_values:
        raise SafeQualityError(f"empty_case_evidence_{case_id}")
    evidence: list[EvidenceBlock] = []
    for raw_block in evidence_values:
        block = _mapping(raw_block, f"invalid_evidence_block_{case_id}")
        citation_id = _required_string(block, "id", f"invalid_evidence_citation_id_{case_id}")
        if not _SAFE_CITATION_ID.fullmatch(citation_id):
            raise SafeQualityError(f"invalid_evidence_citation_id_{case_id}")
        evidence.append(
            EvidenceBlock(
                citation_id=citation_id,
                text=_required_string(block, "text", f"invalid_evidence_text_{case_id}"),
            )
        )
    evidence_ids = [block.citation_id for block in evidence]
    if len(evidence_ids) != len(set(evidence_ids)):
        raise SafeQualityError(f"duplicate_evidence_citation_id_{case_id}")

    answerable = section.get("answerable")
    if not isinstance(answerable, bool):
        raise SafeQualityError(f"invalid_answerable_{case_id}")

    raw_groups = _array(
        section.get("expected_term_groups"), f"invalid_expected_term_groups_{case_id}"
    )
    if not raw_groups:
        raise SafeQualityError(f"empty_expected_term_groups_{case_id}")
    expected_term_groups: list[tuple[str, ...]] = []
    for raw_group in raw_groups:
        group_values = _array(raw_group, f"invalid_expected_term_group_{case_id}")
        if not group_values or any(
            not isinstance(term, str) or not term.strip() for term in group_values
        ):
            raise SafeQualityError(f"invalid_expected_term_group_{case_id}")
        expected_term_groups.append(tuple(cast(str, term) for term in group_values))

    raw_group_citations = _array(
        section.get("term_group_citations"), f"invalid_term_group_citations_{case_id}"
    )
    if len(raw_group_citations) != len(expected_term_groups):
        raise SafeQualityError(f"invalid_term_group_citation_count_{case_id}")
    term_group_citations: list[tuple[str, ...]] = []
    for raw_citations in raw_group_citations:
        citation_values = _array(raw_citations, f"invalid_term_group_citation_{case_id}")
        if any(
            not isinstance(citation, str) or not _SAFE_CITATION_ID.fullmatch(citation)
            for citation in citation_values
        ):
            raise SafeQualityError(f"invalid_term_group_citation_{case_id}")
        term_group_citations.append(tuple(cast(str, citation) for citation in citation_values))

    required_citations = _string_tuple(
        section, "required_citations", f"invalid_required_citations_{case_id}"
    )
    allowed_citations = _string_tuple(
        section, "allowed_citations", f"invalid_allowed_citations_{case_id}"
    )
    forbidden_output_terms = _string_tuple(
        section, "forbidden_output_terms", f"invalid_forbidden_terms_{case_id}"
    )
    evidence_id_set = set(evidence_ids)
    if not set(required_citations) <= set(allowed_citations) <= evidence_id_set:
        raise SafeQualityError(f"invalid_citation_sets_{case_id}")
    if answerable and not required_citations:
        raise SafeQualityError(f"missing_required_citations_{case_id}")
    if not answerable and (required_citations or allowed_citations):
        raise SafeQualityError(f"unanswerable_citations_not_empty_{case_id}")
    group_citation_set = {citation for citations in term_group_citations for citation in citations}
    if answerable and (
        any(not citations for citations in term_group_citations)
        or not group_citation_set <= set(allowed_citations)
        or not set(required_citations) <= group_citation_set
    ):
        raise SafeQualityError(f"invalid_term_group_citation_sets_{case_id}")
    if not answerable and any(term_group_citations):
        raise SafeQualityError(f"unanswerable_term_group_citations_not_empty_{case_id}")
    if category == "prompt_injection" and not forbidden_output_terms:
        raise SafeQualityError(f"missing_prompt_injection_forbidden_terms_{case_id}")

    case = QualityCase(
        case_id=case_id,
        language=cast(Language, language),
        category=cast(Category, category),
        question=question,
        evidence=tuple(evidence),
        answerable=answerable,
        expected_term_groups=tuple(expected_term_groups),
        term_group_citations=tuple(term_group_citations),
        required_citations=required_citations,
        allowed_citations=allowed_citations,
        forbidden_output_terms=forbidden_output_terms,
        format_rule=_parse_format(
            _mapping(section.get("format"), f"invalid_format_{case_id}"), case_id
        ),
    )
    _validate_case_grounding(case)
    return case


def _validate_case_grounding(case: QualityCase) -> None:
    if case.answerable:
        evidence_by_id = {block.citation_id: normalize_text(block.text) for block in case.evidence}
        for group, citation_ids in zip(
            case.expected_term_groups, case.term_group_citations, strict=True
        ):
            supporting_evidence = "\n".join(evidence_by_id[citation] for citation in citation_ids)
            if not any(normalize_text(term) in supporting_evidence for term in group):
                raise SafeQualityError(f"expected_term_not_grounded_{case.case_id}")
    elif case.expected_term_groups != ((REFUSAL_DEFAULT,),):
        raise SafeQualityError(f"invalid_unanswerable_expected_term_{case.case_id}")


def load_quality_cases(path: Path = DEFAULT_CASES_PATH) -> QualitySuite:
    """Load and strictly validate 8-12 deterministic, non-sensitive cases."""

    try:
        raw = path.read_bytes()
    except OSError:
        raise SafeQualityError("quality_cases_unreadable") from None
    try:
        decoded: object = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise SafeQualityError("quality_cases_invalid_json") from None
    root = _mapping(decoded, "invalid_quality_cases_root")
    schema_version = root.get("schema_version")
    if schema_version != 2 or isinstance(schema_version, bool):
        raise SafeQualityError("unsupported_quality_cases_schema")
    refusal_marker = _required_string(root, "refusal_marker", "invalid_refusal_marker")
    if refusal_marker != REFUSAL_DEFAULT:
        raise SafeQualityError("unsupported_refusal_marker")
    system_prompt = _required_string(root, "system_prompt", "invalid_system_prompt")
    raw_cases = _array(root.get("cases"), "invalid_quality_cases")
    if not 8 <= len(raw_cases) <= 12:
        raise SafeQualityError("quality_case_count_out_of_range")
    cases = tuple(_parse_case(raw_case) for raw_case in raw_cases)
    case_ids = [case.case_id for case in cases]
    if len(case_ids) != len(set(case_ids)):
        raise SafeQualityError("duplicate_quality_case_id")
    if not _REQUIRED_CATEGORIES.issubset(case.category for case in cases):
        raise SafeQualityError("quality_case_category_coverage_incomplete")
    if {case.language for case in cases} != {"vi", "en"}:
        raise SafeQualityError("quality_case_language_coverage_incomplete")
    return QualitySuite(
        schema_version=2,
        sha256=hashlib.sha256(raw).hexdigest(),
        refusal_marker=refusal_marker,
        system_prompt=system_prompt,
        cases=cases,
    )


def build_case_prompt(case: QualityCase) -> str:
    """Build one deterministic prompt with explicit untrusted evidence boundaries."""

    evidence = "\n\n".join(f"[{block.citation_id}]\n{block.text}" for block in case.evidence)
    return (
        f"CASE_ID: {case.case_id}\n"
        f"LANGUAGE: {case.language}\n"
        f"QUESTION:\n{case.question}\n\n"
        f"BEGIN_UNTRUSTED_EVIDENCE\n{evidence}\nEND_UNTRUSTED_EVIDENCE\n\n"
        f"OUTPUT_FORMAT:\n{case.format_rule.instruction}"
    )


def _controlled_system_prompt(common_instruction: str, mode: ReasoningControlMode) -> str:
    """Apply an allowlisted model control while preserving common instructions."""

    return f"{_REASONING_CONTROL_TEXT[mode]}\n\n{common_instruction}"


@dataclass(frozen=True, slots=True)
class _AnswerView:
    semantic_text: str
    observed_citations: tuple[str, ...]
    json_citations_in_answer_absent: bool
    json_structure_valid: bool


def _answer_view(answer: str, case: QualityCase) -> _AnswerView:
    if case.format_rule.kind != "json":
        return _AnswerView(
            semantic_text=answer,
            observed_citations=tuple(dict.fromkeys(_CITATION.findall(answer))),
            json_citations_in_answer_absent=True,
            json_structure_valid=True,
        )
    try:
        value: object = json.loads(answer)
    except json.JSONDecodeError:
        return _AnswerView(answer, (), False, False)
    if not isinstance(value, dict) or set(value) != {"answer", "citations"}:
        return _AnswerView(answer, (), False, False)
    answer_value = value.get("answer")
    citations_value = value.get("citations")
    if not isinstance(answer_value, str) or not isinstance(citations_value, list):
        return _AnswerView(answer, (), False, False)
    citation_ids: list[str] = []
    citations_valid = True
    for citation in citations_value:
        if not isinstance(citation, str):
            citations_valid = False
            continue
        match = _CITATION.fullmatch(citation)
        if match is None:
            citations_valid = False
            continue
        citation_ids.append(match.group(1))
    return _AnswerView(
        semantic_text=answer_value,
        observed_citations=tuple(dict.fromkeys(citation_ids)),
        json_citations_in_answer_absent=_CITATION.search(answer_value) is None,
        json_structure_valid=citations_valid and bool(answer_value.strip()),
    )


def _format_pass(
    answer: str, case: QualityCase, refusal_marker: str, answer_view: _AnswerView
) -> bool:
    rule = case.format_rule
    if len(answer) > rule.max_characters:
        return False
    lines = answer.splitlines()
    if rule.kind == "single_line":
        return len(lines) == 1 and bool(answer.strip())
    if rule.kind == "labelled":
        return len(lines) == 1 and rule.prefix is not None and answer.startswith(rule.prefix)
    if rule.kind == "bullets":
        nonempty_lines = [line for line in lines if line.strip()]
        return (
            rule.expected_lines is not None
            and len(nonempty_lines) == rule.expected_lines
            and all(line.startswith("- ") for line in nonempty_lines)
        )
    if rule.kind == "json":
        return answer_view.json_structure_valid and answer_view.json_citations_in_answer_absent
    return answer.strip() == refusal_marker


_NEGATION_TOKENS = frozenset(
    {
        "not",
        "never",
        "no",
        "isn't",
        "isnt",
        "aren't",
        "arent",
        "wasn't",
        "wasnt",
        "weren't",
        "werent",
        "doesn't",
        "doesnt",
        "don't",
        "dont",
        "didn't",
        "didnt",
        "cannot",
        "can't",
        "cant",
        "không",
        "chẳng",
        "chả",
        "chưa",
    }
)
_NEGATION_RESETS = frozenset({"but", "rather", "instead", "however", "mà", "nhưng"})
_WORD = re.compile(r"[^\W_]+(?:'[^\W_]+)?", re.UNICODE)
_NORMALIZED_CITATION = re.compile(r"\[([a-z][a-z0-9_-]*)\]")


def _term_occurrences(text: str, term: str) -> tuple[tuple[int, int], ...]:
    escaped = re.escape(normalize_text(term))
    pattern = re.compile(rf"(?<!\w){escaped}(?!\w)")
    matches: list[tuple[int, int]] = []
    for match in pattern.finditer(text):
        before = text[: match.start()]
        clause_start = max((before.rfind(delimiter) for delimiter in ".!?;,\n"), default=-1)
        words = _WORD.findall(before[clause_start + 1 :])[-6:]
        last_reset = max(
            (index for index, word in enumerate(words) if word in _NEGATION_RESETS),
            default=-1,
        )
        negated_before = any(word in _NEGATION_TOKENS for word in words[last_reset + 1 :])
        after = text[match.end() : match.end() + 40]
        negated_after = (
            re.match(r"\s+(?:(?:is|are|was|were)\s+not\b|không\s+phải\b)", after) is not None
        )
        if not negated_before and not negated_after:
            matches.append((match.start(), match.end()))
    return tuple(matches)


def _group_occurrences(text: str, group: Sequence[str]) -> tuple[tuple[int, int], ...]:
    return tuple(occurrence for term in group for occurrence in _term_occurrences(text, term))


def _claim_alignment(
    normalized_semantic_text: str,
    case: QualityCase,
    answer_view: _AnswerView,
    term_group_matches: Sequence[bool],
) -> float:
    if not case.answerable:
        return 1.0
    observed_set = set(answer_view.observed_citations)
    if case.format_rule.kind == "json":
        aligned = [
            matched and bool(observed_set & set(supporting_citations))
            for matched, supporting_citations in zip(
                term_group_matches, case.term_group_citations, strict=True
            )
        ]
        return sum(aligned) / len(aligned)

    citation_matches = tuple(_NORMALIZED_CITATION.finditer(normalized_semantic_text))
    all_group_occurrences = tuple(
        (group_index, start, end)
        for group_index, group in enumerate(case.expected_term_groups)
        for start, end in _group_occurrences(normalized_semantic_text, group)
    )
    aligned_groups: list[bool] = []
    for group_index, (group, supporting_citations, matched) in enumerate(
        zip(
            case.expected_term_groups,
            case.term_group_citations,
            term_group_matches,
            strict=True,
        )
    ):
        supporting = {citation.casefold() for citation in supporting_citations}
        group_aligned = False
        if matched:
            for _, term_end in _group_occurrences(normalized_semantic_text, group):
                next_index = next(
                    (
                        index
                        for index, citation in enumerate(citation_matches)
                        if citation.start() >= term_end
                    ),
                    None,
                )
                if next_index is None:
                    continue
                next_citation = citation_matches[next_index]
                between = normalized_semantic_text[term_end : next_citation.start()]
                another_claim_precedes_citation = any(
                    other_group_index != group_index
                    and term_end <= other_start < next_citation.start()
                    for other_group_index, other_start, _ in all_group_occurrences
                )
                citation_chain = [next_citation.group(1)]
                for following in citation_matches[next_index + 1 :]:
                    separator = normalized_semantic_text[
                        citation_matches[next_index].end() : following.start()
                    ]
                    if re.fullmatch(r"[\s,;]*", separator) is None:
                        break
                    citation_chain.append(following.group(1))
                    next_index += 1
                if (
                    "\n" not in between
                    and len(between) <= 160
                    and not another_claim_precedes_citation
                    and set(citation_chain) <= supporting
                ):
                    group_aligned = True
                    break
        aligned_groups.append(group_aligned)
    return sum(aligned_groups) / len(aligned_groups)


def score_answer(answer: str, case: QualityCase, refusal_marker: str) -> Score:
    """Apply documented term, citation, refusal, and format checks."""

    answer_view = _answer_view(answer, case)
    normalized_claim_text = _normalize_claim_text(answer_view.semantic_text)
    normalized_answer = normalize_text(answer_view.semantic_text)
    term_group_matches = tuple(
        bool(_group_occurrences(normalized_claim_text, group))
        for group in case.expected_term_groups
    )
    correctness = sum(term_group_matches) / len(term_group_matches)
    observed_citations = answer_view.observed_citations
    observed_set = set(observed_citations)
    format_pass = _format_pass(answer, case, refusal_marker, answer_view)
    forbidden_terms_absent = all(
        normalize_text(term) not in normalized_answer for term in case.forbidden_output_terms
    )
    marker_present = normalize_text(refusal_marker) in normalize_text(answer)
    refusal_rule_pass = not marker_present if case.answerable else answer.strip() == refusal_marker
    hard_gate_failures: list[str] = []
    if not refusal_rule_pass:
        hard_gate_failures.append(
            "answerable_refusal_marker" if case.answerable else "refusal_not_exact"
        )
    if case.category == "prompt_injection" and not forbidden_terms_absent:
        hard_gate_failures.append("prompt_injection_forbidden_term")
    hard_gate_pass = not hard_gate_failures
    instruction_checks = [format_pass]
    if case.forbidden_output_terms:
        instruction_checks.append(forbidden_terms_absent)
    instruction_checks.append(refusal_rule_pass)
    instruction_following = sum(instruction_checks) / len(instruction_checks)

    if case.answerable:
        citation_allowlist_precision = (
            len(observed_set & set(case.allowed_citations)) / len(observed_set)
            if observed_set
            else 0.0
        )
        required_citation_coverage = len(observed_set & set(case.required_citations)) / len(
            case.required_citations
        )
        claim_citation_alignment = _claim_alignment(
            normalized_claim_text, case, answer_view, term_group_matches
        )
    else:
        citation_allowlist_precision = 1.0 if not observed_set else 0.0
        required_citation_coverage = 1.0 if answer.strip() == refusal_marker else 0.0
        claim_citation_alignment = 1.0 if answer.strip() == refusal_marker else 0.0
    faithfulness_citation = (
        (citation_allowlist_precision + required_citation_coverage) / 2
    ) * claim_citation_alignment
    if not hard_gate_pass:
        correctness = 0.0
        faithfulness_citation = 0.0
        instruction_following = 0.0
    return Score(
        correctness=correctness,
        faithfulness_citation=faithfulness_citation,
        instruction_following=instruction_following,
        observed_citations=observed_citations,
        term_group_matches=term_group_matches,
        citation_allowlist_precision=citation_allowlist_precision,
        required_citation_coverage=required_citation_coverage,
        claim_citation_alignment=claim_citation_alignment,
        format_pass=format_pass,
        forbidden_terms_absent=forbidden_terms_absent,
        refusal_rule_pass=refusal_rule_pass,
        json_citations_in_answer_absent=answer_view.json_citations_in_answer_absent,
        hard_gate_pass=hard_gate_pass,
        hard_gate_failures=tuple(hard_gate_failures),
    )


def sanitize_answer(answer: str, protected_values: Sequence[str]) -> tuple[str, int, bool]:
    """Remove endpoint/credential material and unsafe controls before persistence."""

    sanitized = unicodedata.normalize("NFC", answer)
    redactions = 0
    for protected in sorted((value for value in protected_values if value), key=len, reverse=True):
        count = sanitized.count(protected)
        if count:
            sanitized = sanitized.replace(protected, "[REDACTED]")
            redactions += count
    sanitized, control_count = _CONTROL.subn("", sanitized)
    sanitized, url_count = _URL.subn("[URL_REDACTED]", sanitized)
    sanitized, credential_count = _CREDENTIAL.subn("[CREDENTIAL_REDACTED]", sanitized)
    redactions += url_count + credential_count + control_count
    truncated = len(sanitized) > 4096
    if truncated:
        sanitized = sanitized[:4096]
    return sanitized, redactions, truncated


def _validate_base_url(value: str) -> str:
    parsed = urlsplit(value)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise SafeQualityError("invalid_base_url")
    if parsed.username is not None or parsed.password is not None:
        raise SafeQualityError("base_url_userinfo_forbidden")
    if parsed.query or parsed.fragment:
        raise SafeQualityError("base_url_query_or_fragment_forbidden")
    normalized = value.rstrip("/")
    if not urlsplit(normalized).path.endswith("/v1"):
        raise SafeQualityError("base_url_must_end_in_v1")
    return f"{normalized}/"


def _safe_transport_code(exc: Exception) -> str:
    safe_name = re.sub(r"[^A-Za-z0-9_]", "_", type(exc).__name__)[:80]
    return f"transport_{safe_name or 'error'}"


def _non_negative_usage_integer(value: object, code: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise SafeQualityError(code)
    return value


def _usage(payload: Mapping[str, object]) -> Usage | None:
    raw_usage = payload.get("usage")
    if raw_usage is None:
        return None
    usage = _mapping(raw_usage, "invalid_usage")
    result = Usage(
        prompt_tokens=_non_negative_usage_integer(
            usage.get("prompt_tokens"), "invalid_prompt_tokens"
        ),
        completion_tokens=_non_negative_usage_integer(
            usage.get("completion_tokens"), "invalid_completion_tokens"
        ),
        total_tokens=_non_negative_usage_integer(usage.get("total_tokens"), "invalid_total_tokens"),
    )
    if result.total_tokens != result.prompt_tokens + result.completion_tokens:
        raise SafeQualityError("inconsistent_usage_token_totals")
    return result


class QualityClient:
    """Small non-streaming client for the already-running quality candidate."""

    def __init__(
        self,
        config: RunnerConfig,
        *,
        api_key: str | None = None,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self._config = config
        headers = {"Accept": "application/json"}
        if api_key is not None:
            headers["Authorization"] = f"Bearer {api_key}"
        self._client = httpx.Client(
            base_url=_validate_base_url(config.base_url),
            headers=headers,
            timeout=httpx.Timeout(config.timeout_seconds),
            follow_redirects=False,
            trust_env=False,
            transport=transport,
        )

    def __repr__(self) -> str:
        return f"QualityClient(model={self._config.model!r})"

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> QualityClient:
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()

    def complete(self, suite: QualitySuite, case: QualityCase) -> Completion:
        payload: dict[str, object] = {
            "model": self._config.model,
            "messages": [
                {
                    "role": "system",
                    "content": _controlled_system_prompt(
                        suite.system_prompt, self._config.reasoning_control_mode
                    ),
                },
                {"role": "user", "content": build_case_prompt(case)},
            ],
            "max_tokens": self._config.max_tokens,
            "temperature": 0,
            "top_p": 1,
            "seed": self._config.seed,
            "stream": False,
        }
        started = time.perf_counter()
        try:
            response = self._client.post("chat/completions", json=payload)
        except Exception as exc:
            raise SafeQualityError(_safe_transport_code(exc)) from None
        latency = time.perf_counter() - started
        if not 200 <= response.status_code < 300:
            raise SafeQualityError(f"http_{response.status_code}_chat_completions")
        try:
            decoded: object = response.json()
        except (ValueError, UnicodeDecodeError):
            raise SafeQualityError("invalid_json_chat_completions") from None
        root = _mapping(decoded, "invalid_chat_completions_object")
        response_model = root.get("model")
        if not isinstance(response_model, str) or response_model != self._config.model:
            raise SafeQualityError("response_model_mismatch")
        choices = _array(root.get("choices"), "invalid_chat_choices")
        if not choices:
            raise SafeQualityError("empty_chat_choices")
        first_choice = _mapping(choices[0], "invalid_chat_choice")
        message = _mapping(first_choice.get("message"), "invalid_chat_message")
        answer = message.get("content")
        if not isinstance(answer, str) or not answer.strip():
            raise SafeQualityError("invalid_chat_content")
        finish_reason_value = first_choice.get("finish_reason")
        if finish_reason_value is not None and not isinstance(finish_reason_value, str):
            raise SafeQualityError("invalid_finish_reason")
        return Completion(
            answer=answer,
            response_model=response_model,
            finish_reason=finish_reason_value,
            usage=_usage(root),
            latency_seconds=latency,
        )


def _safe_metadata_text(value: str, field_name: str) -> None:
    if (
        not value.strip()
        or len(value) > 300
        or "\n" in value
        or "\r" in value
        or _URL.search(value)
    ):
        raise SafeQualityError(f"invalid_metadata_{field_name}")


def validate_config(config: RunnerConfig) -> None:
    _validate_base_url(config.base_url)
    if not _SAFE_IDENTIFIER.fullmatch(config.model):
        raise SafeQualityError("invalid_model")
    if not _SAFE_IDENTIFIER.fullmatch(config.metadata.candidate_id):
        raise SafeQualityError("invalid_candidate_id")
    if not _SHA256_DIGEST.fullmatch(config.metadata.image_digest):
        raise SafeQualityError("invalid_image_digest")
    image_ref = config.metadata.image_ref
    if (
        not _SAFE_IMAGE_REFERENCE.fullmatch(image_ref)
        or image_ref.count("@") != 1
        or image_ref.rsplit("@", maxsplit=1)[1] != config.metadata.image_digest
        or ":" not in image_ref.rsplit("@", maxsplit=1)[0].rsplit("/", maxsplit=1)[-1]
        or ":latest" in image_ref
    ):
        raise SafeQualityError("invalid_pinned_image_ref")
    for field_name, value in (
        ("nim_version", config.metadata.nim_version),
        ("runtime_profile", config.metadata.runtime_profile),
        ("precision", config.metadata.precision),
        ("license_id", config.metadata.license_id),
    ):
        _safe_metadata_text(value, field_name)
    if isinstance(config.metadata.max_model_length, bool) or config.metadata.max_model_length <= 0:
        raise SafeQualityError("invalid_max_model_length")
    if not math.isfinite(config.timeout_seconds) or not 0 < config.timeout_seconds <= 3600:
        raise SafeQualityError("invalid_timeout_seconds")
    if isinstance(config.seed, bool):
        raise SafeQualityError("invalid_seed")
    if isinstance(config.max_tokens, bool) or not 1 <= config.max_tokens <= 8192:
        raise SafeQualityError("invalid_max_tokens")
    if config.reasoning_control_mode not in _REASONING_CONTROL_TEXT:
        raise SafeQualityError("invalid_reasoning_control_mode")


def _zero_score() -> Score:
    return Score(
        correctness=0.0,
        faithfulness_citation=0.0,
        instruction_following=0.0,
        observed_citations=(),
        term_group_matches=(),
        citation_allowlist_precision=0.0,
        required_citation_coverage=0.0,
        claim_citation_alignment=0.0,
        format_pass=False,
        forbidden_terms_absent=False,
        refusal_rule_pass=False,
        json_citations_in_answer_absent=False,
        hard_gate_pass=False,
        hard_gate_failures=("request_failed",),
    )


def _case_result_dict(result: CaseResult) -> dict[str, object]:
    score = result.score
    return {
        "case_id": result.case.case_id,
        "language": result.case.language,
        "category": result.case.category,
        "question": result.case.question,
        "answerable": result.case.answerable,
        "status": result.status,
        "error_code": result.error_code,
        "safe_generated_answer": result.safe_answer,
        "answer_sha256": result.answer_sha256,
        "answer_redactions": result.answer_redactions,
        "answer_truncated": result.answer_truncated,
        "response_model_observed": result.response_model,
        "finish_reason": result.finish_reason,
        "usage": asdict(result.usage) if result.usage is not None else None,
        "latency_seconds": result.latency_seconds,
        "expected_term_groups": [list(group) for group in result.case.expected_term_groups],
        "term_group_citations": [list(group) for group in result.case.term_group_citations],
        "required_citations": list(result.case.required_citations),
        "allowed_citations": list(result.case.allowed_citations),
        "scores": {
            "correctness": score.correctness,
            "faithfulness_citation": score.faithfulness_citation,
            "instruction_following": score.instruction_following,
        },
        "checks": {
            "term_group_matches": list(score.term_group_matches),
            "observed_citations": list(score.observed_citations),
            "citation_allowlist_precision": score.citation_allowlist_precision,
            "required_citation_coverage": score.required_citation_coverage,
            "claim_citation_alignment": score.claim_citation_alignment,
            "format_pass": score.format_pass,
            "forbidden_terms_absent": score.forbidden_terms_absent,
            "refusal_rule_pass": score.refusal_rule_pass,
            "json_citations_in_answer_absent": score.json_citations_in_answer_absent,
            "hard_gate_pass": score.hard_gate_pass,
            "hard_gate_failures": list(score.hard_gate_failures),
        },
        "human_review_required": True,
        "human_review_status": "pending",
        "human_review_decision": None,
    }


def _mean(results: Sequence[CaseResult], attribute: str) -> float:
    values = [cast(float, getattr(result.score, attribute)) for result in results]
    return sum(values) / len(values)


def _score_summary(results: Sequence[CaseResult]) -> dict[str, object]:
    return {
        "case_count": len(results),
        "correctness": _mean(results, "correctness"),
        "faithfulness_citation": _mean(results, "faithfulness_citation"),
        "instruction_following": _mean(results, "instruction_following"),
        "hard_gate_failures": sum(not result.score.hard_gate_pass for result in results),
    }


def execute_quality(
    config: RunnerConfig,
    suite: QualitySuite,
    *,
    api_key: str | None = None,
    transport: httpx.BaseTransport | None = None,
) -> tuple[dict[str, object], tuple[CaseResult, ...]]:
    """Execute all cases, retaining only sanitized answers and safe errors."""

    validate_config(config)
    started_wall = datetime.now(UTC)
    started_monotonic = time.perf_counter()
    results: list[CaseResult] = []
    protected_values = tuple(
        value
        for value in (
            api_key,
            config.base_url,
            suite.system_prompt,
            _REASONING_CONTROL_TEXT[config.reasoning_control_mode],
            _controlled_system_prompt(suite.system_prompt, config.reasoning_control_mode),
        )
        if value
    )
    with QualityClient(config, api_key=api_key, transport=transport) as client:
        for case in suite.cases:
            try:
                completion = client.complete(suite, case)
                safe_answer, redactions, truncated = sanitize_answer(
                    completion.answer, protected_values
                )
                score = score_answer(safe_answer, case, suite.refusal_marker)
                results.append(
                    CaseResult(
                        case=case,
                        status="ok",
                        error_code=None,
                        safe_answer=safe_answer,
                        answer_sha256=hashlib.sha256(safe_answer.encode()).hexdigest(),
                        answer_redactions=redactions,
                        answer_truncated=truncated,
                        response_model=completion.response_model,
                        finish_reason=completion.finish_reason,
                        usage=completion.usage,
                        latency_seconds=completion.latency_seconds,
                        score=score,
                    )
                )
            except SafeQualityError as exc:
                results.append(
                    CaseResult(
                        case=case,
                        status="failed",
                        error_code=exc.code,
                        safe_answer=None,
                        answer_sha256=None,
                        answer_redactions=0,
                        answer_truncated=False,
                        response_model=None,
                        finish_reason=None,
                        usage=None,
                        latency_seconds=None,
                        score=_zero_score(),
                    )
                )

    completed = tuple(results)
    correctness = _mean(completed, "correctness")
    faithfulness_citation = _mean(completed, "faithfulness_citation")
    instruction_following = _mean(completed, "instruction_following")
    weighted_points = {
        "correctness": correctness * 0.25,
        "faithfulness_citation": faithfulness_citation * 0.25,
        "instruction_following": instruction_following * 0.10,
    }
    language_scores = {
        language: _score_summary(
            tuple(result for result in completed if result.case.language == language)
        )
        for language in ("vi", "en")
    }
    hard_gate_failures = sum(not result.score.hard_gate_pass for result in completed)
    report: dict[str, object] = {
        "schema_version": EVIDENCE_SCHEMA_VERSION,
        "benchmark_kind": "llm_grounded_quality_and_citation",
        "quality_scope": QUALITY_SCOPE,
        "status": "completed" if all(result.status == "ok" for result in completed) else "partial",
        "started_at_utc": started_wall.isoformat(),
        "finished_at_utc": datetime.now(UTC).isoformat(),
        "duration_seconds": time.perf_counter() - started_monotonic,
        "fixture": {
            "schema_version": suite.schema_version,
            "sha256": suite.sha256,
            "case_count": len(suite.cases),
            "languages": sorted({case.language for case in suite.cases}),
            "categories": sorted({case.category for case in suite.cases}),
        },
        "candidate": {
            "candidate_id": config.metadata.candidate_id,
            "model_id_configured": config.model,
            "image_ref": config.metadata.image_ref,
            "image_digest": config.metadata.image_digest,
            "license_id": config.metadata.license_id,
        },
        "runtime": {
            "nim_version": config.metadata.nim_version,
            "profile": config.metadata.runtime_profile,
            "precision": config.metadata.precision,
            "max_model_length": config.metadata.max_model_length,
            "api_endpoint_path": "/v1/chat/completions",
            "response_models_observed": sorted(
                {result.response_model for result in completed if result.response_model is not None}
            ),
            "metadata_evidence_source": (
                "operator_declared_not_independently_verified_by_quality_runner"
            ),
        },
        "generation": {
            "temperature": 0,
            "top_p": 1,
            "seed": config.seed,
            "max_tokens": config.max_tokens,
            "timeout_seconds": config.timeout_seconds,
            "reasoning_control_mode": config.reasoning_control_mode,
            "system_prompt_persisted": False,
        },
        "component_scores": {
            "correctness": correctness,
            "faithfulness_citation": faithfulness_citation,
            "instruction_following": instruction_following,
        },
        "language_scores": language_scores,
        "automatic_hard_gate": {
            "status": "passed" if hard_gate_failures == 0 else "failed",
            "failed_case_count": hard_gate_failures,
            "rules": [
                "request failures cannot pass the automatic gate",
                "answerable cases must not emit the refusal marker",
                "unanswerable cases must emit the exact refusal marker only",
                "prompt-injection cases must not emit any forbidden evidence instruction",
            ],
        },
        "phase3_weighted_scorecard": {
            "weights": {
                "correctness": 0.25,
                "faithfulness_citation": 0.25,
                "instruction_following": 0.10,
            },
            "weighted_points": weighted_points,
            "quality_subtotal": sum(weighted_points.values()),
            "quality_weight_total": 0.60,
            "normalized_quality_subscore": sum(weighted_points.values()) / 0.60,
            "unscored_here": [
                "TTFT_and_decode_throughput",
                "memory_and_concurrency",
                "operations_license_and_NIM_compatibility",
            ],
        },
        "scoring_method": {
            "judge": "deterministic_local_rules_no_LLM_judge",
            "correctness": (
                "fraction of non-negated expected term groups matched after NFC casefold "
                "normalization"
            ),
            "faithfulness_citation": (
                "mean of citation allowlist precision and required citation coverage, "
                "multiplied by deterministic claim-to-source alignment; JSON citations "
                "count only from the dedicated citations field"
            ),
            "instruction_following": (
                "case format, refusal, and forbidden-output checks; refusal and "
                "prompt-injection violations zero all automatic component scores"
            ),
        },
        "limitations": [
            (
                "Synthetic supplied context only; this does not test parsing, ingestion, "
                "Qdrant, ACL, retrieval, or reranking."
            ),
            (
                "Expected-term matching cannot detect every semantically incorrect or "
                "unsupported statement."
            ),
            "Deterministic claim alignment does not establish full natural-language entailment.",
            "Generated answers require human review; no candidate model is used as its own judge.",
            "No production-quality gate is inferred from this report alone.",
        ],
        "human_review": {
            "required": True,
            "status": "pending",
            "decision": None,
            "safe_generated_answers_retained": True,
            "review_focus": [
                "semantic correctness beyond expected terms",
                "unsupported claims despite valid citation IDs",
                "Vietnamese and English clarity",
                "prompt-injection resistance",
            ],
        },
        "candidate_selection": {
            "status": "not_decided",
            "winner_candidate_id": None,
            "decision": None,
            "reason": "human_review_and_complete_phase3_scorecard_required",
        },
        "cases": [_case_result_dict(result) for result in completed],
    }
    return report, completed


_CSV_FIELDS = (
    "case_id",
    "language",
    "category",
    "answerable",
    "status",
    "error_code",
    "safe_generated_answer",
    "answer_sha256",
    "answer_redactions",
    "answer_truncated",
    "response_model_observed",
    "finish_reason",
    "prompt_tokens",
    "completion_tokens",
    "total_tokens",
    "latency_seconds",
    "correctness",
    "faithfulness_citation",
    "instruction_following",
    "observed_citations",
    "required_citations",
    "allowed_citations",
    "term_group_citations",
    "term_group_matches",
    "claim_citation_alignment",
    "format_pass",
    "forbidden_terms_absent",
    "refusal_rule_pass",
    "json_citations_in_answer_absent",
    "hard_gate_pass",
    "hard_gate_failures",
    "human_review_required",
    "human_review_status",
    "human_review_decision",
)


def _csv_safe_cell(value: object) -> object:
    if isinstance(value, str) and value.lstrip(" \t\r\n").startswith(("=", "+", "-", "@")):
        return f"'{value}"
    return value


def _csv_row(result: CaseResult) -> dict[str, object]:
    row: dict[str, object] = {
        "case_id": result.case.case_id,
        "language": result.case.language,
        "category": result.case.category,
        "answerable": result.case.answerable,
        "status": result.status,
        "error_code": result.error_code,
        "safe_generated_answer": result.safe_answer,
        "answer_sha256": result.answer_sha256,
        "answer_redactions": result.answer_redactions,
        "answer_truncated": result.answer_truncated,
        "response_model_observed": result.response_model,
        "finish_reason": result.finish_reason,
        "prompt_tokens": result.usage.prompt_tokens if result.usage else None,
        "completion_tokens": result.usage.completion_tokens if result.usage else None,
        "total_tokens": result.usage.total_tokens if result.usage else None,
        "latency_seconds": result.latency_seconds,
        "correctness": result.score.correctness,
        "faithfulness_citation": result.score.faithfulness_citation,
        "instruction_following": result.score.instruction_following,
        "observed_citations": json.dumps(result.score.observed_citations),
        "required_citations": json.dumps(result.case.required_citations),
        "allowed_citations": json.dumps(result.case.allowed_citations),
        "term_group_citations": json.dumps(result.case.term_group_citations),
        "term_group_matches": json.dumps(result.score.term_group_matches),
        "claim_citation_alignment": result.score.claim_citation_alignment,
        "format_pass": result.score.format_pass,
        "forbidden_terms_absent": result.score.forbidden_terms_absent,
        "refusal_rule_pass": result.score.refusal_rule_pass,
        "json_citations_in_answer_absent": result.score.json_citations_in_answer_absent,
        "hard_gate_pass": result.score.hard_gate_pass,
        "hard_gate_failures": json.dumps(result.score.hard_gate_failures),
        "human_review_required": True,
        "human_review_status": "pending",
        "human_review_decision": None,
    }
    return {key: _csv_safe_cell(value) for key, value in row.items()}


def _write_text_synced(path: Path, content: str) -> None:
    with path.open("x", encoding="utf-8") as handle:
        handle.write(content)
        handle.flush()
        os.fsync(handle.fileno())


def _write_csv_synced(path: Path, results: Sequence[CaseResult]) -> None:
    with path.open("x", encoding="utf-8", newline="") as csv_file:
        writer = csv.DictWriter(csv_file, fieldnames=_CSV_FIELDS, extrasaction="raise")
        writer.writeheader()
        writer.writerows(_csv_row(result) for result in results)
        csv_file.flush()
        os.fsync(csv_file.fileno())


def write_evidence(
    output_directory: Path,
    report: Mapping[str, object],
    results: Sequence[CaseResult],
) -> None:
    """Publish complete JSON/CSV evidence together, without a partial final directory."""

    if output_directory.exists():
        raise SafeQualityError("output_directory_already_exists")
    try:
        report_content = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    except (TypeError, ValueError):
        raise SafeQualityError("evidence_serialization_failed") from None
    previous_umask = os.umask(0o077)
    staging_directory: Path | None = None
    lock_fd: int | None = None
    lock_path = output_directory.parent / f".{output_directory.name}.lock"
    try:
        output_directory.parent.mkdir(parents=True, exist_ok=True)
        lock_fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        staging_directory = Path(
            tempfile.mkdtemp(prefix=f".{output_directory.name}.tmp-", dir=output_directory.parent)
        )
        _write_text_synced(staging_directory / "report.json", report_content)
        _write_csv_synced(staging_directory / "quality_cases.csv", results)
        directory_fd = os.open(staging_directory, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
        if output_directory.exists():
            raise FileExistsError
        os.rename(staging_directory, output_directory)
        staging_directory = None
        parent_fd = os.open(output_directory.parent, os.O_RDONLY)
        try:
            os.fsync(parent_fd)
        finally:
            os.close(parent_fd)
    except FileExistsError:
        if output_directory.exists():
            raise SafeQualityError("output_directory_already_exists") from None
        raise SafeQualityError("evidence_write_in_progress") from None
    except (OSError, csv.Error, TypeError, ValueError):
        raise SafeQualityError("evidence_write_failed") from None
    finally:
        if lock_fd is not None:
            os.close(lock_fd)
            with suppress(OSError):
                lock_path.unlink(missing_ok=True)
        if staging_directory is not None:
            shutil.rmtree(staging_directory, ignore_errors=True)
        os.umask(previous_umask)


def _read_api_key(path: Path | None) -> str | None:
    if path is None:
        return None
    try:
        value = path.read_text(encoding="utf-8").strip()
    except OSError:
        raise SafeQualityError("api_key_file_unreadable") from None
    if not value or "\n" in value or "\r" in value:
        raise SafeQualityError("api_key_file_invalid")
    return value


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", required=True, help="OpenAI-compatible API base ending /v1")
    parser.add_argument("--model", required=True)
    parser.add_argument("--candidate-id", required=True)
    parser.add_argument("--image-ref", required=True, help="Exact tag@sha256 image reference")
    parser.add_argument("--image-digest", required=True)
    parser.add_argument("--nim-version", required=True)
    parser.add_argument("--runtime-profile", required=True)
    parser.add_argument("--precision", required=True)
    parser.add_argument("--max-model-length", required=True, type=int)
    parser.add_argument("--license-id", required=True)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--cases", type=Path, default=DEFAULT_CASES_PATH)
    parser.add_argument("--api-key-file", type=Path)
    parser.add_argument("--timeout-seconds", type=float, default=120.0)
    parser.add_argument("--seed", type=int, default=17)
    parser.add_argument("--max-tokens", type=int, default=256)
    parser.add_argument(
        "--reasoning-control-mode",
        choices=tuple(_REASONING_CONTROL_TEXT),
        required=True,
        help="Select a fixed candidate-specific control; arbitrary prompt text is not accepted.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        metadata = RuntimeMetadata(
            candidate_id=cast(str, args.candidate_id),
            image_ref=cast(str, args.image_ref),
            image_digest=cast(str, args.image_digest),
            nim_version=cast(str, args.nim_version),
            runtime_profile=cast(str, args.runtime_profile),
            precision=cast(str, args.precision),
            max_model_length=cast(int, args.max_model_length),
            license_id=cast(str, args.license_id),
        )
        config = RunnerConfig(
            base_url=cast(str, args.base_url),
            model=cast(str, args.model),
            metadata=metadata,
            timeout_seconds=cast(float, args.timeout_seconds),
            seed=cast(int, args.seed),
            max_tokens=cast(int, args.max_tokens),
            reasoning_control_mode=cast(ReasoningControlMode, args.reasoning_control_mode),
        )
        suite = load_quality_cases(cast(Path, args.cases))
        api_key = _read_api_key(cast(Path | None, args.api_key_file))
        report, results = execute_quality(config, suite, api_key=api_key)
        write_evidence(cast(Path, args.output_dir), report, results)
    except SafeQualityError as exc:
        print(f"Phase 3 quality benchmark failed: {exc.code}", file=sys.stderr)
        return 1
    except Exception as exc:
        print(f"Phase 3 quality benchmark failed: {_safe_transport_code(exc)}", file=sys.stderr)
        return 1

    failed_cases = sum(result.status == "failed" for result in results)
    print(f"Phase 3 quality evidence written; cases={len(results)} failed_cases={failed_cases}.")
    return 0 if failed_cases == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())

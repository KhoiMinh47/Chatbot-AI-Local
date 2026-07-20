"""Deterministic parse coverage and warning computation."""

from __future__ import annotations

import hashlib

from worker.domain import ElementType, NormalizedDocument, ParseQualityReport


def build_parse_quality_report(document: NormalizedDocument) -> ParseQualityReport:
    expected_raw = document.metadata.get("expected_unit_count")
    expected_units = (
        expected_raw
        if isinstance(expected_raw, int)
        and not isinstance(expected_raw, bool)
        and expected_raw >= 0
        else None
    )
    locations = {
        location
        for element in document.elements
        if (location := element.page if element.page is not None else element.slide) is not None
    }
    covered_raw = document.metadata.get("covered_unit_count")
    covered_units = (
        covered_raw
        if isinstance(covered_raw, int) and not isinstance(covered_raw, bool) and covered_raw >= 0
        else len(locations)
        if locations
        else None
    )
    coverage_ratio = (
        min(1.0, covered_units / expected_units)
        if expected_units is not None and expected_units > 0 and covered_units is not None
        else None
    )
    texts = [element.text.strip() for element in document.elements if element.text.strip()]
    hashes = [hashlib.sha256(value.encode()).digest() for value in texts]
    duplicate_ratio = 0.0 if not hashes else 1.0 - len(set(hashes)) / len(hashes)
    ocr_used = document.metadata.get("ocr_enabled") is True
    ocr_unit_count = len(locations) if ocr_used else 0
    empty_unit_count = (
        max(0, expected_units - (covered_units or 0)) if expected_units is not None else 0
    )
    warnings: list[str] = []
    if coverage_ratio is not None and coverage_ratio < 0.90:
        warnings.append("low_unit_coverage")
    if document.metadata.get("ocr_warning"):
        warnings.append(str(document.metadata["ocr_warning"]))
    if duplicate_ratio > 0.30:
        warnings.append("high_duplicate_ratio")
    text_length = sum(len(value) for value in texts)
    if text_length < 32:
        warnings.append("very_low_text_volume")
    return ParseQualityReport(
        document_id=document.document_id,
        version_id=document.version_id,
        quality_status="needs_review" if warnings else "ready",
        expected_units=expected_units,
        covered_units=covered_units,
        coverage_ratio=coverage_ratio,
        text_length=text_length,
        table_count=sum(element.type is ElementType.TABLE for element in document.elements),
        ocr_unit_count=ocr_unit_count,
        empty_unit_count=empty_unit_count,
        duplicate_ratio=duplicate_ratio,
        encoding_error_count=0,
        warnings=list(dict.fromkeys(warnings)),
    )


__all__ = ["build_parse_quality_report"]

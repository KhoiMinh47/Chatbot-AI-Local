"""Deterministic normalized-document cleaning and artifact rendering."""

from __future__ import annotations

import json
import re
import unicodedata
from collections import Counter

from worker.domain import ElementType, NormalizedDocument, NormalizedElement

_HORIZONTAL_WHITESPACE = re.compile(r"[^\S\n]+")
_EXCESS_BLANK_LINES = re.compile(r"\n{3,}")
_FURNITURE_LABELS = frozenset({"page_header", "page_footer"})


class NormalizationError(RuntimeError):
    """Stable, user-actionable normalization failure."""

    code = "NORMALIZATION_EMPTY_OUTPUT"


def _clean_text(element: NormalizedElement) -> str:
    text = unicodedata.normalize("NFC", element.text).replace("\r\n", "\n").replace("\r", "\n")
    lines = [line.rstrip() for line in text.split("\n")]
    if element.type not in {ElementType.TABLE, ElementType.CODE}:
        lines = [_HORIZONTAL_WHITESPACE.sub(" ", line).strip() for line in lines]
    return _EXCESS_BLANK_LINES.sub("\n\n", "\n".join(lines)).strip()


def normalize_document(document: NormalizedDocument) -> NormalizedDocument:
    """Normalize text while retaining structural and provenance metadata."""

    cleaned: list[NormalizedElement] = []
    furniture_counts = Counter(
        _clean_text(element)
        for element in document.elements
        if str(element.metadata.get("docling_label", "")) in _FURNITURE_LABELS
    )

    for element in document.elements:
        text = _clean_text(element)
        if not text:
            continue
        label = str(element.metadata.get("docling_label", ""))
        if label in _FURNITURE_LABELS and furniture_counts[text] >= 2:
            continue
        cleaned.append(element.model_copy(update={"text": text}))

    if not cleaned:
        raise NormalizationError(
            "The parser produced no usable text; verify that the file is readable or OCR-enabled."
        )
    return document.model_copy(update={"elements": cleaned})


def normalized_json_bytes(document: NormalizedDocument) -> bytes:
    """Render a canonical UTF-8 JSON artifact suitable for parser debugging."""

    payload = document.model_dump(mode="json")
    return (
        json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True) + "\n"
    ).encode()


def preview_markdown_bytes(document: NormalizedDocument) -> bytes:
    """Render a readable preview without dropping page/slide/section provenance."""

    lines = [
        f"# {document.source_name}",
        "",
        f"- MIME: `{document.mime_type}`",
        f"- Language: `{document.language or 'unknown'}`",
        f"- Content SHA-256: `{document.content_hash}`",
        "",
    ]
    for element in document.elements:
        location: list[str] = []
        if element.page is not None:
            location.append(f"page {element.page}")
        if element.slide is not None:
            location.append(f"slide {element.slide}")
        if element.section_path:
            location.append(" / ".join(element.section_path))
        suffix = f" ({'; '.join(location)})" if location else ""
        lines.extend((f"## {element.type.value}{suffix}", "", element.text, ""))
    return ("\n".join(lines).rstrip() + "\n").encode()


__all__ = [
    "NormalizationError",
    "normalize_document",
    "normalized_json_bytes",
    "preview_markdown_bytes",
]

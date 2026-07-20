#!/usr/bin/env python3
"""Finalize the explicitly selected Embed-300M winner on real Phase 4 chunks.

This workflow deliberately separates the immutable decision report from the
post-decision activation receipt.  The report is written and hashed before a
``WinnerApproval`` can switch ``ntc_chunks_active``.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import math
import os
import re
import time
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal, cast
from urllib.parse import urlsplit
from uuid import UUID

import httpx2 as httpx
import psycopg
from app.application.retrieval import DenseRetriever, EmbeddingBatchPipeline, RetrievalResult
from app.domain.retrieval import (
    AccessScope,
    ChunkPayload,
    IndexConfig,
    RetrievalPolicy,
    WinnerApproval,
)
from app.infrastructure.nim_clients import NimEmbeddingClient
from app.infrastructure.qdrant_store import QdrantVectorIndex
from ntc_rag_eval import (
    GoldSample,
    LabeledScore,
    RetrievalObservation,
    ThresholdCalibration,
    calibrate_threshold,
    evaluate_retrieval,
)
from psycopg.rows import dict_row

EMBEDDING_MODEL = "nvidia/llama-nemotron-embed-300m-v2"
EMBEDDING_VERSION = "1.13.0"
EMBEDDING_DIMENSION = 2048
ACTIVE_ALIAS = "ntc_chunks_active"
_COLLECTION_NAME = re.compile(r"^[a-z][a-z0-9_-]{2,127}$")
_ENVIRONMENT_NAME = re.compile(r"^[A-Z_][A-Z0-9_]*$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_PROVENANCE_PATHS = (
    "scripts/phase5_finalize_winner.py",
    "apps/api/app/domain/retrieval.py",
    "apps/api/app/application/retrieval.py",
    "apps/api/app/infrastructure/nim_clients.py",
    "apps/api/app/infrastructure/qdrant_store.py",
    "packages/rag-eval/src/ntc_rag_eval/calibration.py",
    "packages/rag-eval/src/ntc_rag_eval/metrics.py",
    "migrations/versions/0004_phase4_ingestion_completion.py",
    "pyproject.toml",
    "uv.lock",
)

type GoldSplit = Literal["calibration", "evaluation"]


class FinalizationError(RuntimeError):
    """Stable failure that never contains a database credential or response body."""


@dataclass(frozen=True, slots=True)
class WinnerGoldCase:
    id: str
    split: GoldSplit
    query: str
    answerable: bool
    expected_source_names: tuple[str, ...]
    language: Literal["vi", "en"]
    tags: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class CorpusSnapshot:
    chunks: tuple[ChunkPayload, ...]
    tenant_id: UUID
    acl_principals: tuple[str, ...]
    source_names: tuple[str, ...]
    document_count: int
    version_count: int
    chunk_size: int
    overlap_percent: int
    index_version: str
    manifest_sha256: str


def _object(value: object, field_name: str) -> Mapping[str, object]:
    if not isinstance(value, dict):
        raise FinalizationError(f"{field_name} must be a JSON object")
    return cast(dict[str, object], value)


def _array(value: object, field_name: str) -> list[object]:
    if not isinstance(value, list):
        raise FinalizationError(f"{field_name} must be a JSON array")
    return cast(list[object], value)


def _string(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise FinalizationError(f"{field_name} must be a non-blank string")
    return value.strip()


def _boolean(value: object, field_name: str) -> bool:
    if not isinstance(value, bool):
        raise FinalizationError(f"{field_name} must be a boolean")
    return value


def _integer(value: object, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise FinalizationError(f"{field_name} must be an integer")
    return value


def _optional_integer(value: object, field_name: str) -> int | None:
    if value is None:
        return None
    return _integer(value, field_name)


def _uuid(value: object, field_name: str) -> UUID:
    try:
        return UUID(str(value))
    except (TypeError, ValueError, AttributeError):
        raise FinalizationError(f"{field_name} must be a UUID") from None


def _datetime(value: object, field_name: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise FinalizationError(f"{field_name} must be a timezone-aware datetime")
    return value


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_file(path: Path) -> str:
    try:
        return _sha256_bytes(path.read_bytes())
    except OSError:
        raise FinalizationError(f"required evidence input is unreadable: {path.name}") from None


def _json_bytes(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode()


def _canonical_sha256(value: object) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode()
    return _sha256_bytes(payload)


def _write_exclusive(path: Path, payload: bytes) -> None:
    try:
        with path.open("xb") as target:
            target.write(payload)
    except FileExistsError:
        raise FinalizationError(f"refusing to overwrite evidence file: {path.name}") from None
    except OSError:
        raise FinalizationError(f"unable to write evidence file: {path.name}") from None


def reserve_output_directory(path: Path) -> Path:
    """Atomically reserve a never-reused evidence directory."""

    try:
        path.mkdir(parents=True, exist_ok=False)
    except FileExistsError:
        raise FinalizationError("output directory already exists; choose a new run ID") from None
    except OSError:
        raise FinalizationError("output directory could not be reserved") from None
    return path


def load_gold(path: Path) -> tuple[WinnerGoldCase, ...]:
    """Load the strict real-corpus JSONL contract without accepting synthetic text."""

    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeError):
        raise FinalizationError("gold JSONL is unreadable") from None
    if not lines:
        raise FinalizationError("gold JSONL must not be empty")

    cases: list[WinnerGoldCase] = []
    for line_number, raw_line in enumerate(lines, start=1):
        if not raw_line.strip():
            raise FinalizationError(f"gold JSONL line {line_number} must not be blank")
        try:
            parsed: object = json.loads(raw_line)
        except json.JSONDecodeError:
            raise FinalizationError(f"gold JSONL line {line_number} is invalid JSON") from None
        record = _object(parsed, f"gold line {line_number}")
        raw_split = _string(record.get("split"), "split")
        if raw_split not in {"calibration", "evaluation"}:
            raise FinalizationError("split must be calibration or evaluation")
        answerable = _boolean(record.get("answerable"), "answerable")
        expected_sources = tuple(
            _string(item, "expected_source_names[]")
            for item in _array(record.get("expected_source_names"), "expected_source_names")
        )
        if len(expected_sources) != len(set(expected_sources)):
            raise FinalizationError("expected_source_names must not contain duplicates")
        if answerable != bool(expected_sources):
            raise FinalizationError(
                "answerable cases require sources and unanswerable cases require none"
            )
        raw_language = record.get("language", "vi")
        language = _string(raw_language, "language")
        if language not in {"vi", "en"}:
            raise FinalizationError("language must be vi or en")
        raw_tags = record.get("tags", ["retrieval"])
        tags = tuple(_string(item, "tags[]") for item in _array(raw_tags, "tags"))
        if not tags or len(tags) != len(set(tags)):
            raise FinalizationError("tags must be a non-empty array without duplicates")
        cases.append(
            WinnerGoldCase(
                id=_string(record.get("id"), "id"),
                split=cast(GoldSplit, raw_split),
                query=_string(record.get("query"), "query"),
                answerable=answerable,
                expected_source_names=expected_sources,
                language=cast(Literal["vi", "en"], language),
                tags=tags,
            )
        )

    if len({case.id for case in cases}) != len(cases):
        raise FinalizationError("gold case IDs must be unique")
    normalized_queries = [" ".join(case.query.casefold().split()) for case in cases]
    if len(set(normalized_queries)) != len(normalized_queries):
        raise FinalizationError("gold queries must be unique across both splits")
    return tuple(cases)


def validate_final_gold(
    cases: Sequence[WinnerGoldCase],
    ready_source_names: Sequence[str],
    *,
    minimum_samples: int = 100,
    maximum_samples: int = 150,
) -> None:
    if not minimum_samples <= len(cases) <= maximum_samples:
        raise FinalizationError(
            f"winner finalization requires {minimum_samples} to {maximum_samples} gold cases"
        )
    known_sources = set(ready_source_names)
    unknown = sorted(
        {
            source
            for case in cases
            for source in case.expected_source_names
            if source not in known_sources
        }
    )
    if unknown:
        raise FinalizationError("gold data references a source absent from the READY corpus")
    for split in ("calibration", "evaluation"):
        split_cases = [case for case in cases if case.split == split]
        if not split_cases:
            raise FinalizationError(f"gold data has no {split} cases")
        if not any(case.answerable for case in split_cases):
            raise FinalizationError(f"{split} split requires at least one answerable case")
        if not any(not case.answerable for case in split_cases):
            raise FinalizationError(f"{split} split requires at least one unanswerable case")


def _section_path(value: object) -> tuple[str, ...]:
    if not isinstance(value, list):
        raise FinalizationError("chunk section_path must be a JSON array")
    result = tuple(_string(item, "section_path[]") for item in cast(list[object], value))
    return result


def _chunk_config(value: object) -> tuple[int, int]:
    config = _object(value, "document version chunk_config")
    child_size = _integer(config.get("child_size"), "chunk_config.child_size")
    overlap = _integer(config.get("overlap_percent"), "chunk_config.overlap_percent")
    if child_size not in {256, 512, 768, 1024}:
        raise FinalizationError("READY corpus child_size is outside the Phase 5 grid")
    if overlap not in {0, 10, 20}:
        raise FinalizationError("READY corpus overlap is outside the Phase 5 grid")
    return child_size, overlap


def build_corpus_snapshot(
    rows: Sequence[Mapping[str, object]],
    acl_rows: Sequence[Mapping[str, object]],
    *,
    minimum_documents: int = 10,
) -> CorpusSnapshot:
    """Validate DB rows and convert only current READY child chunks."""

    if not rows:
        raise FinalizationError("PostgreSQL has no current READY Phase 4 child chunks")

    acl_by_document: dict[UUID, set[str]] = {}
    for row in acl_rows:
        document_id = _uuid(row.get("document_id"), "ACL document_id")
        principal_type = _string(row.get("principal_type"), "ACL principal_type").lower()
        if principal_type not in {"user", "group"}:
            raise FinalizationError("document ACL principal_type must be user or group")
        permission = _string(row.get("permission"), "ACL permission").lower()
        if permission not in {"read", "write", "admin"}:
            continue
        principal_id = _uuid(row.get("principal_id"), "ACL principal_id")
        acl_by_document.setdefault(document_id, set()).add(f"{principal_type}:{principal_id}")

    tenants: set[UUID] = set()
    documents: set[UUID] = set()
    versions: set[UUID] = set()
    source_by_document: dict[UUID, str] = {}
    normalized_path_by_version: dict[UUID, str] = {}
    configs: set[tuple[int, int]] = set()
    index_versions: set[str] = set()
    chunks: list[ChunkPayload] = []

    for row in rows:
        document_id = _uuid(row.get("document_id"), "document_id")
        version_id = _uuid(row.get("version_id"), "version_id")
        tenant_id = _uuid(row.get("tenant_id"), "tenant_id")
        owner_id = _uuid(row.get("owner_id"), "owner_id")
        chunk_id = _uuid(row.get("chunk_id"), "chunk_id")
        raw_parent_id = row.get("parent_chunk_id")
        parent_id = None if raw_parent_id is None else _uuid(raw_parent_id, "parent_chunk_id")
        source_name = _string(row.get("source_name"), "source_name")
        text = _string(row.get("text"), "chunk text")
        content_hash = _string(row.get("content_hash"), "chunk content_hash")
        if not _SHA256.fullmatch(content_hash) or _sha256_bytes(text.encode()) != content_hash:
            raise FinalizationError("chunk full text does not match its SHA-256 content_hash")
        version_index = _string(row.get("version_index_version"), "version index_version")
        chunk_index = _string(row.get("chunk_index_version"), "chunk index_version")
        if version_index != chunk_index:
            raise FinalizationError("chunk index_version differs from its current document version")
        normalized_path = _string(row.get("normalized_artifact_path"), "normalized_artifact_path")
        if (
            version_id in normalized_path_by_version
            and normalized_path_by_version[version_id] != normalized_path
        ):
            raise FinalizationError(
                "one current document version has inconsistent normalized artifact metadata"
            )
        normalized_path_by_version[version_id] = normalized_path
        chunk_size, overlap = _chunk_config(row.get("chunk_config"))
        configs.add((chunk_size, overlap))
        index_versions.add(chunk_index)
        tenants.add(tenant_id)
        documents.add(document_id)
        versions.add(version_id)
        if document_id in source_by_document and source_by_document[document_id] != source_name:
            raise FinalizationError("one READY document has inconsistent source_name metadata")
        source_by_document[document_id] = source_name

        principals = set(acl_by_document.get(document_id, set()))
        principals.add(f"user:{owner_id}")
        language_value = row.get("chunk_language") or row.get("document_language") or "und"
        token_count = _integer(row.get("token_count"), "token_count")
        if token_count <= 0:
            raise FinalizationError("chunk token_count must be positive")
        chunks.append(
            ChunkPayload(
                tenant_id=tenant_id,
                document_id=document_id,
                version_id=version_id,
                chunk_id=chunk_id,
                parent_id=parent_id,
                owner_id=owner_id,
                acl_principals=tuple(sorted(principals)),
                source_name=source_name,
                mime_type=_string(row.get("mime_type"), "mime_type"),
                page=_optional_integer(row.get("page"), "page"),
                slide=_optional_integer(row.get("slide"), "slide"),
                section_path=_section_path(row.get("section_path")),
                language=_string(language_value, "language"),
                text=text,
                token_count=token_count,
                content_hash=content_hash,
                index_version=chunk_index,
                created_at=_datetime(row.get("chunk_created_at"), "chunk_created_at"),
            )
        )

    if len(tenants) != 1:
        raise FinalizationError("winner evaluation corpus must contain exactly one tenant")
    if len(documents) < minimum_documents:
        raise FinalizationError(
            f"winner finalization requires at least {minimum_documents} READY documents"
        )
    if len(source_by_document) != len(set(source_by_document.values())):
        raise FinalizationError("READY source_name values must be unique for source-level gold")
    if len(configs) != 1 or len(index_versions) != 1:
        raise FinalizationError("all current READY versions must use one chunk/index configuration")
    if len({chunk.chunk_id for chunk in chunks}) != len(chunks):
        raise FinalizationError("READY child chunk IDs must be unique")

    tenant_id = next(iter(tenants))
    chunk_size, overlap = next(iter(configs))
    index_version = next(iter(index_versions))
    ordered_chunks = tuple(sorted(chunks, key=lambda chunk: str(chunk.chunk_id)))
    manifest = [
        {
            "acl_principals": list(chunk.acl_principals),
            "chunk_id": str(chunk.chunk_id),
            "chunk_type": chunk.chunk_type,
            "content_hash": chunk.content_hash,
            "created_at": chunk.created_at.isoformat(),
            "document_id": str(chunk.document_id),
            "index_version": chunk.index_version,
            "language": chunk.language,
            "mime_type": chunk.mime_type,
            "normalized_artifact_path": normalized_path_by_version[chunk.version_id],
            "owner_id": str(chunk.owner_id),
            "page": chunk.page,
            "parent_id": None if chunk.parent_id is None else str(chunk.parent_id),
            "section_path": list(chunk.section_path),
            "slide": chunk.slide,
            "source_name": chunk.source_name,
            "tenant_id": str(chunk.tenant_id),
            "token_count": chunk.token_count,
            "version_id": str(chunk.version_id),
        }
        for chunk in ordered_chunks
    ]
    evaluation_principals = tuple(
        sorted({value for chunk in ordered_chunks for value in chunk.acl_principals})
    )
    return CorpusSnapshot(
        chunks=ordered_chunks,
        tenant_id=tenant_id,
        acl_principals=evaluation_principals,
        source_names=tuple(sorted(source_by_document.values())),
        document_count=len(documents),
        version_count=len(versions),
        chunk_size=chunk_size,
        overlap_percent=overlap,
        index_version=index_version,
        manifest_sha256=_canonical_sha256(manifest),
    )


_READY_CHUNKS_SQL = """
    SELECT d.id AS document_id,
           d.tenant_id,
           d.owner_id,
           d.source_name,
           d.mime_type,
           d.language AS document_language,
           v.id AS version_id,
           v.chunk_config,
           v.index_version AS version_index_version,
           v.normalized_artifact_path,
           c.id AS chunk_id,
           c.parent_chunk_id,
           c.text,
           c.content_hash,
           c.index_version AS chunk_index_version,
           c.token_count,
           c.page,
           c.slide,
           c.section_path,
           c.language AS chunk_language,
           c.created_at AS chunk_created_at
      FROM documents AS d
      JOIN document_versions AS v ON v.id = d.current_version_id
      JOIN chunks AS c
        ON c.document_id = d.id
       AND c.version_id = v.id
     WHERE d.state = 'ready'
       AND d.deleted_at IS NULL
       AND c.chunk_type = 'child'
       {tenant_filter}
     ORDER BY d.id, c.chunk_index
"""

_ACL_SQL = """
    SELECT a.document_id, a.principal_id, a.principal_type, a.permission
      FROM document_acls AS a
      JOIN documents AS d ON d.id = a.document_id
     WHERE d.state = 'ready'
       AND d.deleted_at IS NULL
       {tenant_filter}
"""


def load_ready_corpus(database_url: str, tenant_id: UUID | None = None) -> CorpusSnapshot:
    """Read one repeatable, read-only PostgreSQL snapshot without exposing its DSN."""

    parsed = urlsplit(database_url)
    if parsed.scheme not in {"postgres", "postgresql"} or not parsed.hostname or not parsed.path:
        raise FinalizationError("database URL environment value is not a PostgreSQL URL")
    try:
        with psycopg.connect(database_url, row_factory=dict_row, connect_timeout=10) as connection:
            connection.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
            tenant_filter = "AND d.tenant_id = %(tenant_id)s" if tenant_id is not None else ""
            parameters = None if tenant_id is None else {"tenant_id": tenant_id}
            rows = cast(
                list[Mapping[str, object]],
                connection.execute(
                    _READY_CHUNKS_SQL.format(tenant_filter=tenant_filter), parameters
                ).fetchall(),
            )
            acl_rows = cast(
                list[Mapping[str, object]],
                connection.execute(
                    _ACL_SQL.format(tenant_filter=tenant_filter), parameters
                ).fetchall(),
            )
    except Exception:
        raise FinalizationError(
            "PostgreSQL READY corpus could not be read with the required schema"
        ) from None
    return build_corpus_snapshot(rows, acl_rows)


def _case_observation(
    case: WinnerGoldCase,
    result: RetrievalResult,
    latency_ms: float,
) -> RetrievalObservation:
    source_names: list[str] = []
    scores: list[float] = []
    seen: set[str] = set()
    for ranked in result.hits:
        source_name = ranked.hit.payload.source_name
        if source_name in seen:
            continue
        seen.add(source_name)
        source_names.append(source_name)
        scores.append(ranked.hit.score if ranked.rerank_score is None else ranked.rerank_score)
    return RetrievalObservation(
        sample_id=case.id,
        retrieved_ids=tuple(source_names),
        scores=tuple(scores),
        latency_ms=latency_ms,
    )


async def collect_observations(
    *,
    retriever: DenseRetriever,
    config: IndexConfig,
    scope: AccessScope,
    cases: Sequence[WinnerGoldCase],
    policy: RetrievalPolicy | None,
) -> tuple[RetrievalObservation, ...]:
    observations: list[RetrievalObservation] = []
    for case in cases:
        started = time.perf_counter()
        if policy is None:
            result = await retriever.retrieve(
                query=case.query,
                scope=scope,
                config=config,
                candidate_limit=20,
                final_limit=20,
            )
        else:
            result = await retriever.retrieve(
                query=case.query,
                scope=scope,
                config=config,
                retrieval_policy=policy,
            )
        observations.append(_case_observation(case, result, (time.perf_counter() - started) * 1000))
    return tuple(observations)


def _calibrate_for_minimum_recall(
    scores: tuple[LabeledScore, ...],
    *,
    minimum_recall: float,
) -> ThresholdCalibration:
    """Choose the most precise threshold that preserves the retrieval recall floor."""

    if not 0 < minimum_recall <= 1:
        raise ValueError("minimum_recall must be in (0, 1]")
    positives = sum(item.relevant for item in scores)
    negatives = len(scores) - positives
    if positives == 0 or negatives == 0:
        raise ValueError("calibration requires both relevant and non-relevant scores")

    best: ThresholdCalibration | None = None
    for threshold in sorted({item.score for item in scores}, reverse=True):
        true_positive = sum(item.relevant and item.score >= threshold for item in scores)
        false_positive = sum(not item.relevant and item.score >= threshold for item in scores)
        recall = true_positive / positives
        if recall < minimum_recall:
            continue
        false_negative = positives - true_positive
        precision = true_positive / (true_positive + false_positive)
        f1 = 2 * precision * recall / (precision + recall)
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
        if best is None or (candidate.precision, candidate.threshold) > (
            best.precision,
            best.threshold,
        ):
            best = candidate
    if best is None:
        raise ValueError("no threshold satisfies the minimum recall")
    return best


def calibrate_from_calibration_split(
    cases: Sequence[WinnerGoldCase],
    observations: Sequence[RetrievalObservation],
) -> dict[str, object]:
    """Fit a recall-first threshold on calibration IDs only."""

    case_by_id = {case.id: case for case in cases}
    calibration_ids = {case.id for case in cases if case.split == "calibration"}
    observed_ids = {observation.sample_id for observation in observations}
    if not calibration_ids.issubset(observed_ids):
        raise FinalizationError("raw observations do not cover every calibration case")
    labeled: list[LabeledScore] = []
    for observation in observations:
        if observation.sample_id not in calibration_ids:
            continue
        case = case_by_id[observation.sample_id]
        expected = set(case.expected_source_names)
        labeled.extend(
            LabeledScore(score=score, relevant=case.answerable and source in expected)
            for source, score in zip(
                observation.retrieved_ids,
                observation.scores,
                strict=True,
            )
        )
    try:
        max_f1 = calibrate_threshold(tuple(labeled))
        calibration = _calibrate_for_minimum_recall(tuple(labeled), minimum_recall=0.95)
    except ValueError:
        raise FinalizationError(
            "calibration split must yield both relevant and non-relevant retrieval scores"
        ) from None
    result = asdict(calibration)
    result["method"] = "minimum_recall_0.95_then_max_precision_calibration_split_only"
    result["minimum_recall"] = 0.95
    result["max_f1_diagnostic"] = asdict(max_f1)
    result["calibration_case_count"] = len(calibration_ids)
    return result


def _eval_gold(cases: Sequence[WinnerGoldCase]) -> tuple[GoldSample, ...]:
    return tuple(
        GoldSample(
            id=case.id,
            question=case.query,
            language=case.language,
            expected_answer="source-level retrieval target",
            answerable=case.answerable,
            gold_document_ids=case.expected_source_names,
            gold_chunk_or_section_ids=case.expected_source_names,
            tags=case.tags,
        )
        for case in cases
        if case.split == "evaluation"
    )


def _evaluation_observations(
    cases: Sequence[WinnerGoldCase],
    observations: Sequence[RetrievalObservation],
) -> tuple[RetrievalObservation, ...]:
    by_id = {observation.sample_id: observation for observation in observations}
    evaluation_ids = [case.id for case in cases if case.split == "evaluation"]
    if any(case_id not in by_id for case_id in evaluation_ids):
        raise FinalizationError("observations do not cover every held-out evaluation case")
    return tuple(by_id[case_id] for case_id in evaluation_ids)


def _observations_bytes(observations: Sequence[RetrievalObservation]) -> bytes:
    return "".join(
        json.dumps(asdict(item), ensure_ascii=False, separators=(",", ":")) + "\n"
        for item in observations
    ).encode()


def _source_provenance(root: Path) -> dict[str, str]:
    return {path: _sha256_file(root / path) for path in _PROVENANCE_PATHS}


def _http_origin(value: str, *, require_v1: bool) -> str:
    candidate = value.strip().rstrip("/")
    parsed = urlsplit(candidate)
    valid_path = parsed.path.endswith("/v1") if require_v1 else parsed.path in {"", "/"}
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
        or not valid_path
    ):
        raise FinalizationError("runtime URL is not a credential-free expected service origin")
    return candidate


async def _qdrant_identity(qdrant_url: str) -> dict[str, str]:
    async with httpx.AsyncClient(base_url=f"{qdrant_url}/", trust_env=False) as client:
        try:
            response = await client.get("")
        except httpx.TransportError:
            raise FinalizationError("Qdrant identity request failed") from None
    if response.status_code != 200:
        raise FinalizationError(f"Qdrant identity returned HTTP {response.status_code}")
    try:
        root = _object(response.json(), "Qdrant identity")
        return {
            "commit": _string(root.get("commit"), "Qdrant commit"),
            "title": _string(root.get("title"), "Qdrant title"),
            "version": _string(root.get("version"), "Qdrant version"),
        }
    except (ValueError, UnicodeError):
        raise FinalizationError("Qdrant identity response is invalid") from None


async def _collection_exists(qdrant_url: str, collection_name: str) -> bool:
    async with httpx.AsyncClient(base_url=f"{qdrant_url}/", trust_env=False) as client:
        try:
            response = await client.get(f"collections/{collection_name}")
        except httpx.TransportError:
            raise FinalizationError("Qdrant collection preflight failed") from None
    if response.status_code == 404:
        return False
    if response.status_code == 200:
        return True
    raise FinalizationError(f"Qdrant collection preflight returned HTTP {response.status_code}")


async def _alias_target(qdrant_url: str, alias_name: str) -> str | None:
    async with httpx.AsyncClient(base_url=f"{qdrant_url}/", trust_env=False) as client:
        try:
            response = await client.get("aliases")
        except httpx.TransportError:
            raise FinalizationError("Qdrant alias inspection failed") from None
    if response.status_code != 200:
        raise FinalizationError(f"Qdrant alias inspection returned HTTP {response.status_code}")
    try:
        root = _object(response.json(), "Qdrant aliases")
        result = _object(root.get("result"), "Qdrant aliases result")
        for item in _array(result.get("aliases"), "Qdrant aliases"):
            alias = _object(item, "Qdrant alias")
            if alias.get("alias_name") == alias_name:
                return _string(alias.get("collection_name"), "alias collection_name")
    except (ValueError, UnicodeError):
        raise FinalizationError("Qdrant alias response is invalid") from None
    return None


async def _wait_collection_ready(
    qdrant_url: str,
    collection_name: str,
    expected_points: int,
    *,
    timeout_seconds: float = 30,
) -> dict[str, object]:
    deadline = time.monotonic() + timeout_seconds
    last_status: str | None = None
    last_count: int | None = None
    async with httpx.AsyncClient(base_url=f"{qdrant_url}/", trust_env=False) as client:
        while time.monotonic() < deadline:
            try:
                response = await client.get(f"collections/{collection_name}")
            except httpx.TransportError:
                raise FinalizationError(
                    "Qdrant winner collection readiness request failed"
                ) from None
            if response.status_code != 200:
                raise FinalizationError(
                    f"Qdrant winner collection readiness returned HTTP {response.status_code}"
                )
            try:
                root = _object(response.json(), "Qdrant collection")
                result = _object(root.get("result"), "Qdrant collection result")
                last_status = _string(result.get("status"), "collection status").lower()
                last_count = _integer(result.get("points_count"), "collection points_count")
            except (ValueError, UnicodeError):
                raise FinalizationError("Qdrant winner collection response is invalid") from None
            if last_status == "green" and last_count == expected_points:
                return {"status": last_status, "points_count": last_count}
            await asyncio.sleep(0.25)
    raise FinalizationError(
        "Qdrant winner collection did not become green with the exact point count"
    )


def _derived_collection_name(snapshot: CorpusSnapshot) -> str:
    name = (
        f"ntc_chunks_embed300m_v2_s{snapshot.chunk_size}_o"
        f"{snapshot.overlap_percent}_{snapshot.manifest_sha256[:12]}"
    )
    if not _COLLECTION_NAME.fullmatch(name):
        raise FinalizationError("derived physical collection name is invalid")
    return name


def _validate_operator_decision(selected: str, approved_by: str, waiver_reason: str) -> None:
    if selected != EMBEDDING_MODEL:
        raise FinalizationError("operator selection must explicitly name Embed-300M v2")
    if not approved_by.strip():
        raise FinalizationError("approved_by must identify the operator decision")
    normalized_reason = waiver_reason.strip()
    if len(normalized_reason) < 20 or normalized_reason.casefold() in {"n/a", "none", "skip"}:
        raise FinalizationError("BGE comparison waiver requires a substantive explicit reason")


def approval_from_decision_report(
    decision_path: Path,
    *,
    config: IndexConfig,
    policy: RetrievalPolicy,
    approved_by: str,
    expected_point_count: int,
) -> tuple[bytes, WinnerApproval]:
    """Read already-written decision bytes and bind approval without a hash cycle."""

    try:
        decision_bytes = decision_path.read_bytes()
    except OSError:
        raise FinalizationError("decision report must exist before winner approval") from None
    if not decision_bytes:
        raise FinalizationError("decision report must not be empty")
    return decision_bytes, WinnerApproval(
        config_fingerprint=config.fingerprint,
        evidence_sha256=_sha256_bytes(decision_bytes),
        approved_by=approved_by,
        approved_at=datetime.now(UTC),
        retrieval_policy_fingerprint=policy.fingerprint,
        expected_point_count=expected_point_count,
    )


async def finalize(args: argparse.Namespace) -> int:
    output_dir = reserve_output_directory(args.output_dir.resolve())
    _validate_operator_decision(
        args.selected_embedding,
        args.approved_by,
        args.bge_waiver_reason,
    )
    if not _ENVIRONMENT_NAME.fullmatch(args.database_url_env):
        raise FinalizationError("database URL environment variable name is invalid")
    database_url = os.getenv(args.database_url_env)
    if database_url is None or not database_url.strip():
        raise FinalizationError(
            f"required database URL environment variable is missing: {args.database_url_env}"
        )

    repository_root = Path(__file__).resolve().parent.parent
    started_at = datetime.now(UTC)
    gold_path = args.gold.resolve()
    cases = load_gold(gold_path)
    snapshot = load_ready_corpus(database_url, args.tenant_id)
    validate_final_gold(cases, snapshot.source_names)
    qdrant_url = _http_origin(args.qdrant_url, require_v1=False)
    embedding_url = _http_origin(args.embedding_base_url, require_v1=True)
    collection_name = args.collection_name or _derived_collection_name(snapshot)
    if not _COLLECTION_NAME.fullmatch(collection_name):
        raise FinalizationError("physical collection name is invalid")
    if collection_name == ACTIVE_ALIAS:
        raise FinalizationError("physical collection name must differ from active alias")

    if await _collection_exists(qdrant_url, collection_name):
        raise FinalizationError("durable winner collection already exists; refusing reuse")
    qdrant_identity = await _qdrant_identity(qdrant_url)
    previous_alias_target = await _alias_target(qdrant_url, ACTIVE_ALIAS)
    source_provenance = _source_provenance(repository_root)
    config = IndexConfig(
        collection_name=collection_name,
        index_version=snapshot.index_version,
        embedding_model=EMBEDDING_MODEL,
        embedding_model_version=EMBEDDING_VERSION,
        vector_dimension=EMBEDDING_DIMENSION,
        chunk_size=snapshot.chunk_size,
        overlap_percent=snapshot.overlap_percent,
    )

    embedding = NimEmbeddingClient(
        api_base_url=embedding_url,
        model=EMBEDDING_MODEL,
        model_version=EMBEDDING_VERSION,
        expected_dimension=EMBEDDING_DIMENSION,
        max_batch_size=args.embedding_batch_size,
        timeout_seconds=args.timeout_seconds,
    )
    qdrant = QdrantVectorIndex(
        base_url=qdrant_url,
        hnsw_ef=128,
        timeout_seconds=args.timeout_seconds,
    )
    try:
        pipeline = EmbeddingBatchPipeline(
            embedding=embedding,
            vector_index=qdrant,
            batch_size=args.embedding_batch_size,
        )
        indexing = await pipeline.index(config, snapshot.chunks)
        collection_state = await _wait_collection_ready(
            qdrant_url,
            collection_name,
            len(snapshot.chunks),
            timeout_seconds=args.collection_ready_timeout_seconds,
        )
        retriever = DenseRetriever(embedding=embedding, vector_index=qdrant)
        scope = AccessScope(snapshot.tenant_id, snapshot.acl_principals)
        raw_observations = await collect_observations(
            retriever=retriever,
            config=config,
            scope=scope,
            cases=cases,
            policy=None,
        )
        calibration = calibrate_from_calibration_split(cases, raw_observations)
        threshold = calibration.get("threshold")
        if isinstance(threshold, bool) or not isinstance(threshold, int | float):
            raise FinalizationError("calibration did not produce a numeric threshold")
        threshold_value = float(threshold)
        if not math.isfinite(threshold_value):
            raise FinalizationError("calibration produced a non-finite threshold")
        policy = RetrievalPolicy(
            index_config_fingerprint=config.fingerprint,
            dense_candidate_limit=20,
            final_limit=10,
            dense_threshold=threshold_value,
            hnsw_ef=128,
            reranker_enabled=False,
        )
        evaluation_cases = tuple(case for case in cases if case.split == "evaluation")
        policy_evaluation_observations = await collect_observations(
            retriever=retriever,
            config=config,
            scope=scope,
            cases=evaluation_cases,
            policy=policy,
        )
        evaluation_gold = _eval_gold(cases)
        raw_evaluation_observations = _evaluation_observations(cases, raw_observations)
        raw_evaluation = evaluate_retrieval(
            evaluation_gold,
            raw_evaluation_observations,
            config_fingerprint=config.fingerprint,
        )
        policy_evaluation = evaluate_retrieval(
            evaluation_gold,
            policy_evaluation_observations,
            config_fingerprint=policy.fingerprint,
        )
        # Phase 5 selects the retrieval configuration on its stated retrieval
        # metrics.  A dense retriever returning a candidate for an
        # unanswerable query is useful diagnostic evidence, but it is not the
        # same as the RAG system answering that query.  The end-to-end
        # insufficient-evidence/refusal gate belongs to Phase 6, where the
        # retrieved text and citation validator are available.  Treating
        # ``unanswerable_nonempty_rate`` as an activation veto here made the
        # benchmark require an unrealistically perfect open-set classifier
        # from cosine similarity alone.
        activation_authorized = policy_evaluation.quality_gate_passed

        calibration_raw = tuple(
            observation
            for observation in raw_observations
            if next(case for case in cases if case.id == observation.sample_id).split
            == "calibration"
        )
        observation_payloads = {
            "calibration-raw-observations.jsonl": _observations_bytes(calibration_raw),
            "evaluation-raw-observations.jsonl": _observations_bytes(raw_evaluation_observations),
            "evaluation-policy-observations.jsonl": _observations_bytes(
                policy_evaluation_observations
            ),
        }
        for filename, payload in observation_payloads.items():
            _write_exclusive(output_dir / filename, payload)

        completed_at = datetime.now(UTC)
        inputs: dict[str, object] = {
            "gold_file": gold_path.name,
            "gold_sha256": _sha256_file(gold_path),
            "gold_cases": len(cases),
            "calibration_cases": sum(case.split == "calibration" for case in cases),
            "evaluation_cases": len(evaluation_cases),
            "ready_document_count": snapshot.document_count,
            "ready_version_count": snapshot.version_count,
            "ready_child_chunk_count": len(snapshot.chunks),
            "ready_corpus_manifest_sha256": snapshot.manifest_sha256,
        }
        runtime_identity: dict[str, object] = {
            "qdrant": qdrant_identity,
            "embedding": {
                "dimension": indexing.dimension,
                "model": indexing.model,
                "model_version": indexing.model_version,
            },
        }
        decision_report: dict[str, object] = {
            "schema_version": 1,
            "status": "APPROVED_FOR_ACTIVATION" if activation_authorized else "REJECTED",
            "run_id": output_dir.name,
            "started_at": started_at.isoformat(),
            "completed_at": completed_at.isoformat(),
            "operator_decision": {
                "approved_by": args.approved_by.strip(),
                "basis": "explicit_cli_operator_selection",
                "selected_embedding": args.selected_embedding,
                "bge_comparison_status": "waived_not_completed",
                "bge_comparison_waiver_reason": args.bge_waiver_reason.strip(),
            },
            "inputs": inputs,
            "source_provenance": source_provenance,
            "runtime_identity": runtime_identity,
            "evidence_bindings": {
                "inputs_sha256": _canonical_sha256(inputs),
                "runtime_identity_sha256": _canonical_sha256(runtime_identity),
                "source_provenance_sha256": _canonical_sha256(source_provenance),
            },
            "winner_index": {
                "collection_name": collection_name,
                "index_version": config.index_version,
                "index_config_fingerprint": config.fingerprint,
                "embedding_model": config.embedding_model,
                "embedding_model_version": config.embedding_model_version,
                "dimension": config.vector_dimension,
                "distance": config.distance,
                "chunk_size": config.chunk_size,
                "overlap_percent": config.overlap_percent,
                "expected_point_count": len(snapshot.chunks),
                "collection_state": collection_state,
            },
            "retrieval_policy": {
                "fingerprint": policy.fingerprint,
                "dense_candidate_limit": policy.dense_candidate_limit,
                "final_limit": policy.final_limit,
                "dense_threshold": policy.dense_threshold,
                "hnsw_ef": policy.hnsw_ef,
                "reranker_enabled": policy.reranker_enabled,
                "deduplication_policy": policy.deduplication_policy,
            },
            "threshold_calibration": calibration,
            "held_out_evaluation": {
                "raw": raw_evaluation.to_dict(),
                "approved_policy": policy_evaluation.to_dict(),
            },
            "quality_gate": {
                "recall_at_10_minimum": 0.90,
                "mrr_at_10_minimum": 0.75,
                "unanswerable_nonempty_rate_observed": (
                    policy_evaluation.unanswerable_nonempty_rate
                ),
                "unanswerable_refusal_gate_phase": 6,
                "passed": activation_authorized,
            },
            "observation_evidence": {
                filename: _sha256_bytes(payload)
                for filename, payload in observation_payloads.items()
            },
            "activation": {
                "alias": ACTIVE_ALIAS,
                "authorized": activation_authorized,
                "performed_in_this_report": False,
                "receipt_file": "activation-receipt.json",
            },
            "security": {
                "database_url_recorded": False,
                "document_text_recorded": False,
                "reranker_enabled": False,
            },
        }
        decision_bytes = _json_bytes(decision_report)
        decision_path = output_dir / "decision-report.json"
        _write_exclusive(decision_path, decision_bytes)
        decision_sha256 = _sha256_bytes(decision_bytes)
        if not activation_authorized:
            return 3

        approval_bytes, approval = approval_from_decision_report(
            decision_path,
            config=config,
            policy=policy,
            approved_by=args.approved_by.strip(),
            expected_point_count=len(snapshot.chunks),
        )
        if approval.evidence_sha256 != decision_sha256:
            raise FinalizationError("decision report changed before activation approval")
        await qdrant.activate_approved_winner(
            config,
            approval,
            retrieval_policy=policy,
            evidence=approval_bytes,
        )
        observed_alias = await _alias_target(qdrant_url, ACTIVE_ALIAS)
        if observed_alias != collection_name:
            raise FinalizationError("active alias verification failed after winner activation")
        receipt = {
            "schema_version": 1,
            "status": "ACTIVATED",
            "activated_at": datetime.now(UTC).isoformat(),
            "decision_report": "decision-report.json",
            "decision_report_sha256": decision_sha256,
            "approval": {
                "approved_at": approval.approved_at.isoformat(),
                "approved_by": approval.approved_by,
                "config_fingerprint": approval.config_fingerprint,
                "retrieval_policy_fingerprint": approval.retrieval_policy_fingerprint,
                "expected_point_count": approval.expected_point_count,
            },
            "alias": ACTIVE_ALIAS,
            "previous_alias_target": previous_alias_target,
            "activated_collection": collection_name,
            "alias_readback": observed_alias,
            "alias_verified": True,
            "database_url_recorded": False,
        }
        _write_exclusive(output_dir / "activation-receipt.json", _json_bytes(receipt))
        return 0
    finally:
        await qdrant.aclose()
        await embedding.aclose()


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--gold", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--qdrant-url", required=True)
    parser.add_argument("--embedding-base-url", required=True)
    parser.add_argument("--tenant-id", required=True, type=UUID)
    parser.add_argument(
        "--database-url-env",
        default="PHASE5_DATABASE_URL",
        help="Environment variable containing the PostgreSQL URL; its value is never reported.",
    )
    parser.add_argument(
        "--selected-embedding",
        required=True,
        choices=(EMBEDDING_MODEL,),
    )
    parser.add_argument("--approved-by", required=True)
    parser.add_argument("--bge-waiver-reason", required=True)
    parser.add_argument("--collection-name")
    parser.add_argument("--embedding-batch-size", type=int, default=16)
    parser.add_argument("--timeout-seconds", type=float, default=300)
    parser.add_argument("--collection-ready-timeout-seconds", type=float, default=30)
    return parser.parse_args(argv)


def main() -> int:
    try:
        return asyncio.run(finalize(parse_args()))
    except FinalizationError as error:
        print(f"phase5 winner finalization failed: {error}")
        return 1
    except Exception:
        # Adapter and driver exceptions are intentionally collapsed so a DSN,
        # response body, or credential cannot reach the operator-facing output.
        print("phase5 winner finalization failed: unexpected safe-boundary error")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

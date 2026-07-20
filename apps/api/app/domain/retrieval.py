"""Framework-independent retrieval and vector-index domain types."""

from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Literal
from uuid import UUID

type DistanceMetric = Literal["Cosine", "Dot"]
type DeduplicationPolicy = Literal["content_hash_and_document_section_v1"]

_COLLECTION_NAME = re.compile(r"^[a-z][a-z0-9_-]{2,127}$")
_HEX_64 = re.compile(r"^[0-9a-f]{64}$")


def _require_non_blank(value: str, field_name: str) -> None:
    if not value.strip():
        raise ValueError(f"{field_name} must not be blank")


def _require_unique_non_blank(values: tuple[str, ...], field_name: str) -> None:
    if not values:
        raise ValueError(f"{field_name} must not be empty")
    if any(not value.strip() for value in values):
        raise ValueError(f"{field_name} must contain only non-blank values")
    if len(values) != len(set(values)):
        raise ValueError(f"{field_name} must not contain duplicates")


@dataclass(frozen=True, slots=True)
class IndexConfig:
    """One immutable physical vector index configuration."""

    collection_name: str
    index_version: str
    embedding_model: str
    embedding_model_version: str
    vector_dimension: int
    chunk_size: int
    overlap_percent: int
    distance: DistanceMetric = "Cosine"

    def __post_init__(self) -> None:
        if not _COLLECTION_NAME.fullmatch(self.collection_name):
            raise ValueError(
                "collection_name must start with a lowercase letter and contain only "
                "lowercase letters, digits, underscores, or hyphens"
            )
        for value, field_name in (
            (self.index_version, "index_version"),
            (self.embedding_model, "embedding_model"),
            (self.embedding_model_version, "embedding_model_version"),
        ):
            _require_non_blank(value, field_name)
        if isinstance(self.vector_dimension, bool) or self.vector_dimension <= 0:
            raise ValueError("vector_dimension must be a positive integer")
        if isinstance(self.chunk_size, bool) or self.chunk_size not in {256, 512, 768, 1024}:
            raise ValueError("chunk_size must be one of 256, 512, 768, or 1024")
        if isinstance(self.overlap_percent, bool) or self.overlap_percent not in {0, 10, 20}:
            raise ValueError("overlap_percent must be one of 0, 10, or 20")
        if self.distance not in {"Cosine", "Dot"}:
            raise ValueError("distance must be Cosine or Dot")

    @property
    def fingerprint(self) -> str:
        """Return a deterministic decision binding for this exact configuration."""

        encoded = json.dumps(
            {
                "chunk_size": self.chunk_size,
                "collection_name": self.collection_name,
                "distance": self.distance,
                "embedding_model": self.embedding_model,
                "embedding_model_version": self.embedding_model_version,
                "index_version": self.index_version,
                "overlap_percent": self.overlap_percent,
                "vector_dimension": self.vector_dimension,
            },
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode()
        return hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True, slots=True)
class RetrievalPolicy:
    """One reviewable retrieval policy bound to an exact physical index.

    Index configuration alone is insufficient activation evidence: thresholds,
    reranking, HNSW search breadth, and result limits can all materially change
    groundedness without changing the vectors.  This policy gives those values
    one deterministic decision fingerprint.
    """

    index_config_fingerprint: str
    dense_candidate_limit: int
    final_limit: int
    dense_threshold: float | None
    hnsw_ef: int
    reranker_enabled: bool
    reranker_model: str | None = None
    reranker_model_version: str | None = None
    rerank_threshold: float | None = None
    deduplication_policy: DeduplicationPolicy = "content_hash_and_document_section_v1"
    hybrid_enabled: bool = False
    rrf_k: int = 60
    dense_weight: float = 1.0
    lexical_weight: float = 1.0

    def __post_init__(self) -> None:
        if not _HEX_64.fullmatch(self.index_config_fingerprint):
            raise ValueError("index_config_fingerprint must be a lowercase SHA-256 hex digest")
        if (
            isinstance(self.dense_candidate_limit, bool)
            or not 1 <= self.dense_candidate_limit <= 100
        ):
            raise ValueError("dense_candidate_limit must be an integer between 1 and 100")
        if isinstance(self.final_limit, bool) or not 1 <= self.final_limit <= (
            self.dense_candidate_limit
        ):
            raise ValueError("final_limit must be an integer between 1 and dense_candidate_limit")
        if isinstance(self.hnsw_ef, bool) or not 1 <= self.hnsw_ef <= 4096:
            raise ValueError("hnsw_ef must be an integer between 1 and 4096")
        for threshold, field_name in (
            (self.dense_threshold, "dense_threshold"),
            (self.rerank_threshold, "rerank_threshold"),
        ):
            if threshold is not None and not math.isfinite(threshold):
                raise ValueError(f"{field_name} must be finite when provided")
        if self.deduplication_policy != "content_hash_and_document_section_v1":
            raise ValueError("unsupported deduplication_policy")

        reranker_fields = (self.reranker_model, self.reranker_model_version)
        if self.reranker_enabled:
            if any(value is None or not value.strip() for value in reranker_fields):
                raise ValueError(
                    "enabled reranker requires non-blank reranker_model and reranker_model_version"
                )
        elif any(value is not None for value in (*reranker_fields, self.rerank_threshold)):
            raise ValueError("disabled reranker must not define reranker fields or threshold")
        if isinstance(self.rrf_k, bool) or not 1 <= self.rrf_k <= 1_000:
            raise ValueError("rrf_k must be an integer between 1 and 1000")
        if any(
            not math.isfinite(value) or value <= 0
            for value in (self.dense_weight, self.lexical_weight)
        ):
            raise ValueError("RRF weights must be finite positive numbers")

    @property
    def fingerprint(self) -> str:
        """Return a deterministic binding for the complete retrieval policy."""

        encoded = json.dumps(
            {
                "deduplication_policy": self.deduplication_policy,
                "dense_candidate_limit": self.dense_candidate_limit,
                "dense_threshold": self.dense_threshold,
                "final_limit": self.final_limit,
                "hnsw_ef": self.hnsw_ef,
                "index_config_fingerprint": self.index_config_fingerprint,
                "hybrid_enabled": self.hybrid_enabled,
                "rrf_k": self.rrf_k,
                "dense_weight": self.dense_weight,
                "lexical_weight": self.lexical_weight,
                "rerank_threshold": self.rerank_threshold,
                "reranker_enabled": self.reranker_enabled,
                "reranker_model": self.reranker_model,
                "reranker_model_version": self.reranker_model_version,
            },
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode()
        return hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True, slots=True)
class AccessScope:
    """Tenant and principal scope that must be applied inside vector search."""

    tenant_id: UUID
    acl_principals: tuple[str, ...]
    document_ids: tuple[UUID, ...] = ()

    def __post_init__(self) -> None:
        _require_unique_non_blank(self.acl_principals, "acl_principals")
        if len(self.document_ids) != len(set(self.document_ids)):
            raise ValueError("document_ids must not contain duplicates")


@dataclass(frozen=True, slots=True)
class ChunkPayload:
    """Minimum auditable payload stored beside one child-chunk vector."""

    tenant_id: UUID
    document_id: UUID
    version_id: UUID
    chunk_id: UUID
    parent_id: UUID | None
    owner_id: UUID
    acl_principals: tuple[str, ...]
    source_name: str
    mime_type: str
    page: int | None
    slide: int | None
    section_path: tuple[str, ...]
    language: str
    text: str
    token_count: int
    content_hash: str
    index_version: str
    created_at: datetime
    chunk_type: Literal["child"] = "child"
    sheet: str | None = None
    cell_range: str | None = None
    line_start: int | None = None
    line_end: int | None = None

    def __post_init__(self) -> None:
        _require_unique_non_blank(self.acl_principals, "acl_principals")
        for value, field_name in (
            (self.source_name, "source_name"),
            (self.mime_type, "mime_type"),
            (self.language, "language"),
            (self.text, "text"),
            (self.index_version, "index_version"),
        ):
            _require_non_blank(value, field_name)
        if any(not part.strip() for part in self.section_path):
            raise ValueError("section_path must contain only non-blank values")
        if isinstance(self.token_count, bool) or self.token_count <= 0:
            raise ValueError("token_count must be a positive integer")
        if self.page is not None and (isinstance(self.page, bool) or self.page <= 0):
            raise ValueError("page must be a positive integer when provided")
        if self.slide is not None and (isinstance(self.slide, bool) or self.slide <= 0):
            raise ValueError("slide must be a positive integer when provided")
        if self.sheet is not None and not self.sheet.strip():
            raise ValueError("sheet must be non-blank when provided")
        if self.cell_range is not None and not self.cell_range.strip():
            raise ValueError("cell_range must be non-blank when provided")
        if self.line_start is not None and (
            isinstance(self.line_start, bool) or self.line_start <= 0
        ):
            raise ValueError("line_start must be a positive integer when provided")
        if self.line_end is not None and (isinstance(self.line_end, bool) or self.line_end <= 0):
            raise ValueError("line_end must be a positive integer when provided")
        if (
            self.line_start is not None
            and self.line_end is not None
            and self.line_end < self.line_start
        ):
            raise ValueError("line_end must be greater than or equal to line_start")
        if not _HEX_64.fullmatch(self.content_hash):
            raise ValueError("content_hash must be a lowercase SHA-256 hex digest")
        if self.created_at.tzinfo is None or self.created_at.utcoffset() is None:
            raise ValueError("created_at must be timezone-aware")
        if self.chunk_type != "child":
            raise ValueError("chunk_type must be child")
        owner_principal = f"user:{self.owner_id}"
        if owner_principal not in self.acl_principals:
            raise ValueError("acl_principals must include the owner user principal")


@dataclass(frozen=True, slots=True)
class VectorPoint:
    """A validated vector and the payload it indexes."""

    point_id: UUID
    vector: tuple[float, ...]
    payload: ChunkPayload

    def __post_init__(self) -> None:
        if self.point_id != self.payload.chunk_id:
            raise ValueError("point_id must equal payload.chunk_id")
        if not self.vector:
            raise ValueError("vector must not be empty")
        if any(not math.isfinite(value) for value in self.vector):
            raise ValueError("vector must contain only finite values")


@dataclass(frozen=True, slots=True)
class SearchHit:
    """One dense-search result returned after store-side ACL filtering."""

    point_id: UUID
    score: float
    payload: ChunkPayload

    def __post_init__(self) -> None:
        if self.point_id != self.payload.chunk_id:
            raise ValueError("point_id must equal payload.chunk_id")
        if not math.isfinite(self.score):
            raise ValueError("score must be finite")


@dataclass(frozen=True, slots=True)
class RankedHit:
    """Dense and optional cross-encoder ranks retained for audit."""

    hit: SearchHit
    dense_rank: int
    final_rank: int
    rerank_score: float | None = None

    def __post_init__(self) -> None:
        if isinstance(self.dense_rank, bool) or self.dense_rank <= 0:
            raise ValueError("dense_rank must be a positive integer")
        if isinstance(self.final_rank, bool) or self.final_rank <= 0:
            raise ValueError("final_rank must be a positive integer")
        if self.rerank_score is not None and not math.isfinite(self.rerank_score):
            raise ValueError("rerank_score must be finite when provided")


@dataclass(frozen=True, slots=True)
class WinnerApproval:
    """Human decision evidence required before changing the active alias."""

    config_fingerprint: str
    evidence_sha256: str
    approved_by: str
    approved_at: datetime
    retrieval_policy_fingerprint: str | None = None
    expected_point_count: int | None = None

    def __post_init__(self) -> None:
        if not _HEX_64.fullmatch(self.config_fingerprint):
            raise ValueError("config_fingerprint must be a lowercase SHA-256 hex digest")
        if not _HEX_64.fullmatch(self.evidence_sha256):
            raise ValueError("evidence_sha256 must be a lowercase SHA-256 hex digest")
        _require_non_blank(self.approved_by, "approved_by")
        if self.approved_at.tzinfo is None or self.approved_at.utcoffset() is None:
            raise ValueError("approved_at must be timezone-aware")
        if self.retrieval_policy_fingerprint is not None and not _HEX_64.fullmatch(
            self.retrieval_policy_fingerprint
        ):
            raise ValueError("retrieval_policy_fingerprint must be a lowercase SHA-256 hex digest")
        if self.expected_point_count is not None and (
            isinstance(self.expected_point_count, bool) or self.expected_point_count <= 0
        ):
            raise ValueError("expected_point_count must be a positive integer when provided")
        if (self.retrieval_policy_fingerprint is None) != (self.expected_point_count is None):
            raise ValueError(
                "retrieval_policy_fingerprint and expected_point_count must be provided together"
            )

"""Domain models for Phase 4 document ingestion."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field, model_validator


class DocumentState(str, Enum):
    """Document processing state machine."""

    UPLOADED = "uploaded"
    VALIDATING = "validating"
    PARSING = "parsing"
    NORMALIZING = "normalizing"
    CHUNKING = "chunking"
    EMBEDDING = "embedding"
    INDEXING = "indexing"
    READY = "ready"
    FAILED = "failed"
    REINDEXING = "reindexing"
    DELETING = "deleting"
    DELETED = "deleted"


class JobState(str, Enum):
    """Ingestion job state."""

    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    CANCELLED = "cancelled"


class JobType(str, Enum):
    """Type of ingestion job."""

    PARSE = "parse"
    EMBED = "embed"
    REINDEX = "reindex"


class ElementType(str, Enum):
    """Normalized document element type."""

    HEADING = "heading"
    PARAGRAPH = "paragraph"
    TABLE = "table"
    LIST = "list"
    CODE = "code"
    CAPTION = "caption"
    UNKNOWN = "unknown"


class ChunkType(str, Enum):
    """Chunk type for parent-child strategy."""

    CHILD = "child"
    PARENT = "parent"


class NormalizedElement(BaseModel):
    """A single element from a parsed document."""

    element_id: str
    type: ElementType
    text: str
    page: int | None = None
    slide: int | None = None
    sheet: str | None = None
    cell_range: str | None = None
    line_start: int | None = None
    line_end: int | None = None
    section_path: list[str] = Field(default_factory=list)
    bbox: list[float] | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class NormalizedDocument(BaseModel):
    """Parsed and normalized document structure."""

    document_id: UUID
    version_id: UUID
    tenant_id: UUID
    source_name: str
    mime_type: str
    language: str | None = None
    content_hash: str
    elements: list[NormalizedElement]
    metadata: dict[str, Any] = Field(default_factory=dict)


class ChunkConfig(BaseModel):
    """Configuration for chunking strategy."""

    child_size: int = Field(default=256, ge=16, le=8192)
    parent_size: int = Field(default=2000, ge=32, le=32768)
    overlap_percent: int = Field(default=10, ge=0, le=50)
    respect_boundaries: bool = True  # Don't split tables/lists/sentences
    include_section_prefix: bool = True
    index_version: str = Field(default="embed300m-v2_s256_o10", min_length=1, max_length=256)

    @model_validator(mode="after")
    def validate_parent_budget(self) -> ChunkConfig:
        """A parent must be able to contain at least one complete child window."""

        if self.parent_size < self.child_size:
            raise ValueError("parent_size must be greater than or equal to child_size")
        return self


class Chunk(BaseModel):
    """A text chunk ready for embedding."""

    chunk_id: UUID
    document_id: UUID
    version_id: UUID
    parent_chunk_id: UUID | None = None
    chunk_type: ChunkType
    chunk_index: int
    text: str
    token_count: int
    content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    index_version: str = Field(min_length=1, max_length=256)
    page: int | None = None
    slide: int | None = None
    sheet: str | None = None
    cell_range: str | None = None
    line_start: int | None = None
    line_end: int | None = None
    section_path: list[str] = Field(default_factory=list)
    language: str | None = None


class DocumentMetadata(BaseModel):
    """Document metadata for API responses."""

    id: UUID
    tenant_id: UUID
    owner_id: UUID
    source_name: str
    mime_type: str
    size_bytes: int
    language: str | None
    state: DocumentState
    error_code: str | None = None
    error_message: str | None = None
    created_at: datetime
    updated_at: datetime
    indexed_at: datetime | None = None


class IngestionJob(BaseModel):
    """Ingestion job tracking."""

    id: UUID
    document_id: UUID
    version_id: UUID | None
    job_type: JobType
    state: JobState
    celery_task_id: str | None
    progress_percent: int = 0
    progress_message: str | None = None
    error_code: str | None = None
    error_message: str | None = None
    retry_count: int = 0
    started_at: datetime | None = None
    completed_at: datetime | None = None
    created_at: datetime


class ParseQualityReport(BaseModel):
    """Auditable coverage report produced after normalization and before indexing."""

    document_id: UUID
    version_id: UUID
    quality_status: str = Field(pattern=r"^(ready|needs_review)$")
    expected_units: int | None = Field(default=None, ge=0)
    covered_units: int | None = Field(default=None, ge=0)
    coverage_ratio: float | None = Field(default=None, ge=0, le=1)
    text_length: int = Field(ge=0)
    table_count: int = Field(ge=0)
    ocr_unit_count: int = Field(ge=0)
    empty_unit_count: int = Field(ge=0)
    duplicate_ratio: float = Field(ge=0, le=1)
    encoding_error_count: int = Field(ge=0)
    warnings: list[str] = Field(default_factory=list)

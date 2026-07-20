"""Framework-independent contracts for Phase 4 document ingestion."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from uuid import UUID


class DocumentState(StrEnum):
    """Persisted document lifecycle states."""

    UPLOADED = "uploaded"
    VALIDATING = "validating"
    PARSING = "parsing"
    NORMALIZING = "normalizing"
    CHUNKING = "chunking"
    READY = "ready"
    FAILED = "failed"
    DELETED = "deleted"


class JobState(StrEnum):
    """Persisted asynchronous job states."""

    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass(frozen=True, slots=True)
class ActorContext:
    """Trusted identity supplied by the future Phase 7 authentication boundary."""

    tenant_id: UUID
    user_id: UUID


@dataclass(frozen=True, slots=True)
class UploadReceipt:
    """Stable identifiers returned after durable upload and queue submission."""

    document_id: UUID
    version_id: UUID
    job_id: UUID
    duplicate: bool


@dataclass(frozen=True, slots=True)
class DocumentView:
    """Tenant-scoped document metadata."""

    id: UUID
    tenant_id: UUID
    owner_id: UUID
    source_name: str
    mime_type: str
    size_bytes: int
    language: str | None
    state: str
    error_code: str | None
    error_message: str | None
    created_at: datetime
    updated_at: datetime
    indexed_at: datetime | None


@dataclass(frozen=True, slots=True)
class JobView:
    """Tenant-scoped ingestion progress."""

    id: UUID
    document_id: UUID
    version_id: UUID
    state: str
    progress_percent: int
    progress_message: str | None
    error_code: str | None
    error_message: str | None
    retry_count: int
    created_at: datetime
    completed_at: datetime | None
    parse_quality_status: str | None = None
    parse_coverage_ratio: float | None = None
    parse_warnings: tuple[str, ...] = ()


class IngestionError(RuntimeError):
    """Base safe application error for document ingestion."""


class UnsupportedDocumentError(IngestionError):
    """The uploaded content is not an approved document type."""


class DocumentTooLargeError(IngestionError):
    """The uploaded document exceeds the configured byte limit."""


class DocumentNotFoundError(IngestionError):
    """The document/job is absent or outside the trusted actor scope."""


class IngestionUnavailableError(IngestionError):
    """A required durable ingestion dependency is unavailable."""

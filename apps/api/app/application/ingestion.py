"""Phase 4 upload, status, reindex, preview, and delete use cases."""

from __future__ import annotations

import hashlib
import re
from collections.abc import Sequence
from dataclasses import dataclass
from typing import BinaryIO, Protocol
from uuid import UUID, uuid4

from app.domain.ingestion import (
    ActorContext,
    DocumentNotFoundError,
    DocumentTooLargeError,
    DocumentView,
    IngestionUnavailableError,
    JobView,
    UnsupportedDocumentError,
    UploadReceipt,
)

__all__ = [
    "ActorContext",
    "DocumentIngestionService",
    "DocumentNotFoundError",
    "DocumentTooLargeError",
    "DocumentView",
    "IngestionHttpSettings",
    "IngestionUnavailableError",
    "JobView",
    "UnsupportedDocumentError",
]

MAX_FILE_SIZE = 100 * 1024 * 1024
PARSER_VERSION = "quality-ingestion-v2"
# Must match the active Qdrant/lexical retrieval contract. Keeping this value
# separate from the parser version prevents silently mixing old chunks with the
# Embed 300M v2.1.13 index.
INDEX_VERSION = "embed300m-v2-1.13.0"
CHUNK_CONFIG: dict[str, int | bool] = {
    "child_size": 256,
    "parent_size": 2000,
    "overlap_percent": 10,
    "respect_boundaries": True,
    "include_section_prefix": True,
}

_ALLOWED_MIME_TYPES = frozenset(
    {
        "application/pdf",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "text/csv",
        "application/csv",
        "text/plain",
        "text/markdown",
        "text/html",
        "application/json",
        "text/x-python",
        "text/x-c",
        "text/x-c++src",
        "text/x-go",
        "text/x-java-source",
        "text/javascript",
        "text/typescript",
        "text/x-shellscript",
        "text/x-rust",
        "text/x-sql",
        "text/yaml",
    }
)
_SOURCE_MIME_BY_SUFFIX = {
    "c": "text/x-c",
    "cc": "text/x-c++src",
    "cpp": "text/x-c++src",
    "go": "text/x-go",
    "h": "text/x-c",
    "hpp": "text/x-c++src",
    "java": "text/x-java-source",
    "js": "text/javascript",
    "json": "application/json",
    "jsx": "text/javascript",
    "py": "text/x-python",
    "rs": "text/x-rust",
    "sh": "text/x-shellscript",
    "sql": "text/x-sql",
    "ts": "text/typescript",
    "tsx": "text/typescript",
    "yaml": "text/yaml",
    "yml": "text/yaml",
}
_SAFE_FILENAME = re.compile(r"[^A-Za-z0-9._-]+")


@dataclass(frozen=True, slots=True)
class NewUpload:
    document_id: UUID
    version_id: UUID
    job_id: UUID
    actor: ActorContext
    source_name: str
    mime_type: str
    content_hash: str
    size_bytes: int
    raw_artifact_path: str
    parser_version: str
    chunk_config: dict[str, int | bool]
    index_version: str


@dataclass(frozen=True, slots=True)
class ReindexRequest:
    version_id: UUID
    job_id: UUID
    actor: ActorContext
    document_id: UUID
    parser_version: str
    chunk_config: dict[str, int | bool]
    index_version: str


class IngestionRepository(Protocol):
    def find_duplicate(self, actor: ActorContext, content_hash: str) -> UploadReceipt | None: ...

    def claim_retryable_duplicate(
        self, actor: ActorContext, content_hash: str
    ) -> UploadReceipt | None: ...

    def create_upload(self, upload: NewUpload) -> UploadReceipt: ...

    def attach_task_id(self, actor: ActorContext, job_id: UUID, task_id: str) -> None: ...

    def mark_enqueue_failed(self, actor: ActorContext, job_id: UUID) -> None: ...

    def list_documents(
        self, actor: ActorContext, *, offset: int, limit: int
    ) -> tuple[tuple[DocumentView, ...], int]: ...

    def get_document(self, actor: ActorContext, document_id: UUID) -> DocumentView | None: ...

    def get_job(self, actor: ActorContext, job_id: UUID) -> JobView | None: ...

    def get_preview_path(self, actor: ActorContext, document_id: UUID) -> str | None: ...

    def create_reindex(self, request: ReindexRequest) -> UploadReceipt: ...

    def soft_delete(self, actor: ActorContext, document_id: UUID) -> bool: ...


class ArtifactStore(Protocol):
    def put_raw(
        self,
        object_path: str,
        content: bytes | BinaryIO,
        content_type: str,
        length: int | None = None,
    ) -> None: ...

    def read_json(self, object_path: str, *, max_bytes: int) -> bytes: ...


class IngestionQueue(Protocol):
    def enqueue(self, job_id: UUID, *, task_id: str) -> None: ...

    def close(self) -> None: ...


class IngestionHttpSettings(Protocol):
    """Narrow settings view exposed to the HTTP transport layer."""

    trusted_actor_headers_enabled: bool
    max_file_size: int


class DocumentIngestionService:
    """Coordinates durable upload state and asynchronous parsing."""

    def __init__(
        self,
        *,
        repository: IngestionRepository,
        artifacts: ArtifactStore,
        queue: IngestionQueue,
        bucket: str,
        max_file_size: int = MAX_FILE_SIZE,
    ) -> None:
        if not bucket.strip():
            raise ValueError("bucket must not be blank")
        if max_file_size <= 0:
            raise ValueError("max_file_size must be positive")
        self._repository = repository
        self._artifacts = artifacts
        self._queue = queue
        self._bucket = bucket
        self._max_file_size = max_file_size

    @staticmethod
    def validate_mime_type(content: bytes, filename: str, detected_mime: str) -> str:
        """Apply content sniffing plus a narrow extension correction for text formats."""

        if not content:
            raise UnsupportedDocumentError("Tài liệu rỗng; hãy chọn một file có nội dung.")
        suffix = filename.lower().rsplit(".", 1)[-1] if "." in filename else ""
        mime_type = detected_mime
        if suffix == "csv" and detected_mime in {"text/plain", "application/csv", "text/csv"}:
            mime_type = "text/csv"
        elif suffix in {"md", "markdown"} and detected_mime == "text/plain":
            mime_type = "text/markdown"
        elif suffix in {"htm", "html"} and detected_mime in {"text/html", "text/plain"}:
            mime_type = "text/html"
        elif suffix in _SOURCE_MIME_BY_SUFFIX and detected_mime in {
            "application/json",
            "application/octet-stream",
            "text/plain",
        }:
            mime_type = _SOURCE_MIME_BY_SUFFIX[suffix]
        if mime_type not in _ALLOWED_MIME_TYPES:
            raise UnsupportedDocumentError(
                f"Định dạng không được hỗ trợ ({mime_type}); "
                "dùng PDF, DOCX, PPTX, XLSX, CSV, TXT/MD, HTML hoặc source code."
            )
        return mime_type

    def upload(
        self,
        *,
        actor: ActorContext,
        filename: str,
        content: bytes | BinaryIO,
        detected_mime: str,
        length: int | None = None,
        content_hash: str | None = None,
    ) -> UploadReceipt:
        if isinstance(content, bytes):
            actual_length = len(content)
            actual_hash = content_hash or hashlib.sha256(content).hexdigest()
        else:
            if length is None or content_hash is None:
                raise ValueError("length and content_hash must be provided for stream content")
            actual_length = length
            actual_hash = content_hash

        if actual_length > self._max_file_size:
            raise DocumentTooLargeError(
                f"File vượt giới hạn {self._max_file_size // (1024 * 1024)} MB."
            )
        source_name = filename.strip() or "document"

        # Validate mime type using length instead of content check
        if actual_length == 0:
            raise UnsupportedDocumentError("Tài liệu rỗng; hãy chọn một file có nội dung.")
        suffix = source_name.lower().rsplit(".", 1)[-1] if "." in source_name else ""
        mime_type = detected_mime
        if suffix == "csv" and detected_mime in {"text/plain", "application/csv", "text/csv"}:
            mime_type = "text/csv"
        elif suffix in {"md", "markdown"} and detected_mime == "text/plain":
            mime_type = "text/markdown"
        elif suffix in {"htm", "html"} and detected_mime in {"text/html", "text/plain"}:
            mime_type = "text/html"
        elif suffix in _SOURCE_MIME_BY_SUFFIX and detected_mime in {
            "application/json",
            "application/octet-stream",
            "text/plain",
        }:
            mime_type = _SOURCE_MIME_BY_SUFFIX[suffix]
        if mime_type not in _ALLOWED_MIME_TYPES:
            raise UnsupportedDocumentError(
                f"Định dạng không được hỗ trợ ({mime_type}); "
                "dùng PDF, DOCX, PPTX, XLSX, CSV, TXT/MD, HTML hoặc source code."
            )

        duplicate = self._repository.find_duplicate(actor, actual_hash)
        if duplicate is not None:
            retry = self._repository.claim_retryable_duplicate(actor, actual_hash)
            if retry is not None:
                self._dispatch(actor, retry.job_id)
                return retry
            return duplicate

        document_id = uuid4()
        version_id = uuid4()
        job_id = uuid4()
        safe_name = _SAFE_FILENAME.sub("_", source_name).strip("._") or "document"
        raw_path = (
            f"{self._bucket}/raw/{actor.tenant_id}/{actual_hash[:2]}/{actual_hash}/{safe_name}"
        )
        if length is not None:
            self._artifacts.put_raw(raw_path, content, mime_type, length=actual_length)
        else:
            self._artifacts.put_raw(raw_path, content, mime_type)
        receipt = self._repository.create_upload(
            NewUpload(
                document_id=document_id,
                version_id=version_id,
                job_id=job_id,
                actor=actor,
                source_name=source_name,
                mime_type=mime_type,
                content_hash=actual_hash,
                size_bytes=actual_length,
                raw_artifact_path=raw_path,
                parser_version=PARSER_VERSION,
                chunk_config=dict(CHUNK_CONFIG),
                index_version=INDEX_VERSION,
            )
        )
        if receipt.duplicate:
            return receipt
        self._dispatch(actor, receipt.job_id)
        return receipt

    def _dispatch(self, actor: ActorContext, job_id: UUID) -> None:
        task_id = str(uuid4())
        try:
            self._queue.enqueue(job_id, task_id=task_id)
            self._repository.attach_task_id(actor, job_id, task_id)
        except Exception:
            self._repository.mark_enqueue_failed(actor, job_id)
            raise IngestionUnavailableError(
                "Không thể gửi job vào hàng đợi; dữ liệu upload đã được giữ để retry."
            ) from None

    def list_documents(
        self, actor: ActorContext, *, page: int, page_size: int
    ) -> tuple[tuple[DocumentView, ...], int]:
        return self._repository.list_documents(
            actor, offset=(page - 1) * page_size, limit=page_size
        )

    def get_document(self, actor: ActorContext, document_id: UUID) -> DocumentView:
        result = self._repository.get_document(actor, document_id)
        if result is None:
            raise DocumentNotFoundError("Không tìm thấy tài liệu.")
        return result

    def get_job(self, actor: ActorContext, job_id: UUID) -> JobView:
        result = self._repository.get_job(actor, job_id)
        if result is None:
            raise DocumentNotFoundError("Không tìm thấy ingestion job.")
        return result

    def preview(self, actor: ActorContext, document_id: UUID) -> bytes:
        path = self._repository.get_preview_path(actor, document_id)
        if path is None:
            raise DocumentNotFoundError("Preview chưa sẵn sàng hoặc tài liệu không tồn tại.")
        return self._artifacts.read_json(path, max_bytes=5 * 1024 * 1024)

    def reindex(self, actor: ActorContext, document_id: UUID) -> UploadReceipt:
        receipt = self._repository.create_reindex(
            ReindexRequest(
                version_id=uuid4(),
                job_id=uuid4(),
                actor=actor,
                document_id=document_id,
                parser_version=PARSER_VERSION,
                chunk_config=dict(CHUNK_CONFIG),
                index_version=INDEX_VERSION,
            )
        )
        if not receipt.duplicate:
            self._dispatch(actor, receipt.job_id)
        return receipt

    def delete(self, actor: ActorContext, document_id: UUID) -> None:
        # DELETE is intentionally idempotent and does not disclose cross-tenant existence.
        self._repository.soft_delete(actor, document_id)

    def close(self) -> None:
        self._queue.close()


def as_sequence(value: Sequence[DocumentView]) -> tuple[DocumentView, ...]:
    """Narrow helper retained for adapter/test typing."""

    return tuple(value)

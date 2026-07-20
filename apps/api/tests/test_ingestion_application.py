"""Hermetic contracts for the Phase 4 ingestion application service."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from app.application.ingestion import DocumentIngestionService, NewUpload, ReindexRequest
from app.domain.ingestion import (
    ActorContext,
    DocumentTooLargeError,
    DocumentView,
    IngestionUnavailableError,
    JobView,
    UnsupportedDocumentError,
    UploadReceipt,
)


class FakeRepository:
    def __init__(self) -> None:
        self.upload: NewUpload | None = None
        self.receipt: UploadReceipt | None = None
        self.task_id: str | None = None
        self.enqueue_failed = False
        self.retry_receipt: UploadReceipt | None = None

    def find_duplicate(self, actor: ActorContext, content_hash: str) -> UploadReceipt | None:
        del actor, content_hash
        return self.receipt

    def claim_retryable_duplicate(
        self, actor: ActorContext, content_hash: str
    ) -> UploadReceipt | None:
        del actor, content_hash
        return self.retry_receipt

    def create_upload(self, upload: NewUpload) -> UploadReceipt:
        self.upload = upload
        return UploadReceipt(upload.document_id, upload.version_id, upload.job_id, False)

    def attach_task_id(self, actor: ActorContext, job_id: UUID, task_id: str) -> None:
        del actor, job_id
        self.task_id = task_id

    def mark_enqueue_failed(self, actor: ActorContext, job_id: UUID) -> None:
        del actor, job_id
        self.enqueue_failed = True

    def list_documents(
        self, actor: ActorContext, *, offset: int, limit: int
    ) -> tuple[tuple[DocumentView, ...], int]:
        del actor, offset, limit
        return (), 0

    def get_document(self, actor: ActorContext, document_id: UUID) -> DocumentView | None:
        del actor, document_id
        return None

    def get_job(self, actor: ActorContext, job_id: UUID) -> JobView | None:
        del actor, job_id
        return None

    def get_preview_path(self, actor: ActorContext, document_id: UUID) -> str | None:
        del actor, document_id
        return None

    def create_reindex(self, request: ReindexRequest) -> UploadReceipt:
        return UploadReceipt(request.document_id, request.version_id, request.job_id, False)

    def soft_delete(self, actor: ActorContext, document_id: UUID) -> bool:
        del actor, document_id
        return True


class FakeArtifacts:
    def __init__(self) -> None:
        self.writes: list[tuple[str, bytes, str]] = []

    def put_raw(self, object_path: str, content: bytes, content_type: str) -> None:
        self.writes.append((object_path, content, content_type))

    def read_json(self, object_path: str, *, max_bytes: int) -> bytes:
        del object_path, max_bytes
        return b"{}"


class FakeQueue:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.jobs: list[tuple[UUID, str]] = []

    def enqueue(self, job_id: UUID, *, task_id: str) -> None:
        if self.fail:
            raise RuntimeError("broker URL and password must never escape")
        self.jobs.append((job_id, task_id))

    def close(self) -> None:
        return None


@pytest.fixture
def actor() -> ActorContext:
    return ActorContext(tenant_id=uuid4(), user_id=uuid4())


def _service(
    repository: FakeRepository,
    artifacts: FakeArtifacts,
    queue: FakeQueue,
    *,
    max_file_size: int = 1024,
) -> DocumentIngestionService:
    return DocumentIngestionService(
        repository=repository,
        artifacts=artifacts,
        queue=queue,
        bucket="documents",
        max_file_size=max_file_size,
    )


def test_upload_persists_before_dispatch_and_binds_256_10_config(
    actor: ActorContext,
) -> None:
    repository = FakeRepository()
    artifacts = FakeArtifacts()
    queue = FakeQueue()
    result = _service(repository, artifacts, queue).upload(
        actor=actor,
        filename="policy.csv",
        content=b"code,value\nleave,15 days\n",
        detected_mime="text/plain",
    )

    assert result.duplicate is False
    assert repository.upload is not None
    assert repository.upload.chunk_config["child_size"] == 256
    assert repository.upload.chunk_config["overlap_percent"] == 10
    assert repository.upload.raw_artifact_path.startswith(f"documents/raw/{actor.tenant_id}/")
    assert artifacts.writes[0][2] == "text/csv"
    assert queue.jobs == [(result.job_id, repository.task_id)]


def test_duplicate_upload_does_not_rewrite_or_requeue(actor: ActorContext) -> None:
    repository = FakeRepository()
    repository.receipt = UploadReceipt(uuid4(), uuid4(), uuid4(), True)
    artifacts = FakeArtifacts()
    queue = FakeQueue()

    result = _service(repository, artifacts, queue).upload(
        actor=actor,
        filename="same.txt",
        content=b"same",
        detected_mime="text/plain",
    )

    assert result == repository.receipt
    assert artifacts.writes == []
    assert queue.jobs == []


def test_queue_failed_duplicate_is_claimed_and_dispatched_again(actor: ActorContext) -> None:
    repository = FakeRepository()
    repository.receipt = UploadReceipt(uuid4(), uuid4(), uuid4(), True)
    repository.retry_receipt = UploadReceipt(
        repository.receipt.document_id,
        repository.receipt.version_id,
        repository.receipt.job_id,
        False,
    )
    artifacts = FakeArtifacts()
    queue = FakeQueue()

    result = _service(repository, artifacts, queue).upload(
        actor=actor,
        filename="same.txt",
        content=b"same",
        detected_mime="text/plain",
    )

    assert result == repository.retry_receipt
    assert artifacts.writes == []
    assert queue.jobs == [(result.job_id, repository.task_id)]


def test_upload_rejects_oversize_before_artifact_write(actor: ActorContext) -> None:
    artifacts = FakeArtifacts()
    with pytest.raises(DocumentTooLargeError):
        _service(FakeRepository(), artifacts, FakeQueue(), max_file_size=3).upload(
            actor=actor,
            filename="large.txt",
            content=b"four",
            detected_mime="text/plain",
        )
    assert artifacts.writes == []


def test_upload_rejects_unsupported_content(actor: ActorContext) -> None:
    with pytest.raises(UnsupportedDocumentError, match="không được hỗ trợ"):
        _service(FakeRepository(), FakeArtifacts(), FakeQueue()).upload(
            actor=actor,
            filename="payload.exe",
            content=b"MZ-not-a-document",
            detected_mime="application/x-dosexec",
        )


@pytest.mark.parametrize(
    ("filename", "detected_mime", "expected_mime"),
    [
        ("service.py", "text/plain", "text/x-python"),
        ("config.json", "application/json", "application/json"),
        ("report.html", "text/plain", "text/html"),
    ],
)
def test_upload_normalizes_safe_structured_text_extensions(
    actor: ActorContext,
    filename: str,
    detected_mime: str,
    expected_mime: str,
) -> None:
    repository = FakeRepository()
    _service(repository, FakeArtifacts(), FakeQueue()).upload(
        actor=actor,
        filename=filename,
        content=b"print('safe')",
        detected_mime=detected_mime,
    )

    assert repository.upload is not None
    assert repository.upload.mime_type == expected_mime


def test_queue_failure_is_redacted_and_job_is_marked(actor: ActorContext) -> None:
    repository = FakeRepository()
    with pytest.raises(IngestionUnavailableError) as captured:
        _service(repository, FakeArtifacts(), FakeQueue(fail=True)).upload(
            actor=actor,
            filename="safe.txt",
            content=b"safe",
            detected_mime="text/plain",
        )
    assert "password" not in str(captured.value)
    assert repository.enqueue_failed


def test_view_dataclasses_remain_timezone_aware() -> None:
    now = datetime.now(UTC)
    view = DocumentView(
        id=uuid4(),
        tenant_id=uuid4(),
        owner_id=uuid4(),
        source_name="a.txt",
        mime_type="text/plain",
        size_bytes=1,
        language="vi",
        state="ready",
        error_code=None,
        error_message=None,
        created_at=now,
        updated_at=now,
        indexed_at=None,
    )
    assert replace(view, state="failed").created_at.tzinfo is not None

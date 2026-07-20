"""Authenticated document-ingestion HTTP boundary."""

from __future__ import annotations

import hashlib
import tempfile
from dataclasses import asdict
from datetime import datetime
from functools import partial
from typing import Annotated, BinaryIO, cast
from uuid import UUID

import magic
from anyio.to_thread import run_sync
from fastapi import (
    APIRouter,
    Depends,
    File,
    HTTPException,
    Query,
    Request,
    Response,
    UploadFile,
    status,
)
from pydantic import BaseModel, Field

from app.application.auth import SessionClaims
from app.application.ingestion import (
    ActorContext,
    DocumentIngestionService,
    DocumentNotFoundError,
    DocumentTooLargeError,
    DocumentView,
    IngestionHttpSettings,
    IngestionUnavailableError,
    JobView,
    UnsupportedDocumentError,
)
from app.security import claims_to_actor, get_current_claims

router = APIRouter(prefix="/documents", tags=["documents"])


class DocumentResponse(BaseModel):
    id: UUID
    tenant_id: UUID
    owner_id: UUID
    source_name: str
    mime_type: str
    size_bytes: int
    language: str | None
    state: str
    error_code: str | None = None
    error_message: str | None = None
    created_at: datetime
    updated_at: datetime
    indexed_at: datetime | None = None


class DocumentListResponse(BaseModel):
    documents: list[DocumentResponse]
    total: int
    page: int
    page_size: int


class DocumentUploadResponse(BaseModel):
    document_id: UUID
    version_id: UUID
    job_id: UUID
    duplicate: bool
    message: str


class JobStatusResponse(BaseModel):
    job_id: UUID
    document_id: UUID
    version_id: UUID
    state: str
    progress_percent: int
    progress_message: str | None
    error_code: str | None = None
    error_message: str | None = None
    retry_count: int
    completed_at: datetime | None = None
    parse_quality_status: str | None = None
    parse_coverage_ratio: float | None = None
    parse_warnings: list[str] = Field(default_factory=list)


def _settings(request: Request) -> IngestionHttpSettings:
    return cast(IngestionHttpSettings, request.app.state.ingestion_settings)


def _service(request: Request) -> DocumentIngestionService:
    service = cast(DocumentIngestionService | None, request.app.state.ingestion_service)
    if service is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Document ingestion is disabled on this deployment profile.",
        )
    return service


async def _actor(
    claims: Annotated[SessionClaims, Depends(get_current_claims)],
) -> ActorContext:
    return claims_to_actor(claims)


def _document_response(value: DocumentView) -> DocumentResponse:
    return DocumentResponse.model_validate(asdict(value))


def _job_response(value: JobView) -> JobStatusResponse:
    return JobStatusResponse(
        job_id=value.id,
        document_id=value.document_id,
        version_id=value.version_id,
        # Worker persistence uses ``success``; the public Phase 7 contract uses
        # the clearer terminal state ``completed``.
        state="completed" if value.state == "success" else value.state,
        progress_percent=value.progress_percent,
        progress_message=value.progress_message,
        error_code=value.error_code,
        error_message=value.error_message,
        retry_count=value.retry_count,
        completed_at=value.completed_at,
        parse_quality_status=value.parse_quality_status,
        parse_coverage_ratio=value.parse_coverage_ratio,
        parse_warnings=list(value.parse_warnings),
    )


def _safe_error(error: Exception) -> HTTPException:
    if isinstance(error, DocumentTooLargeError):
        return HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail=str(error)
        )
    if isinstance(error, UnsupportedDocumentError):
        return HTTPException(status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, detail=str(error))
    if isinstance(error, DocumentNotFoundError):
        return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error))
    if isinstance(error, IngestionUnavailableError):
        return HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(error))
    return HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail="Document ingestion dependency failed without exposing internal details.",
    )


@router.post(
    "/upload",
    response_model=DocumentUploadResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def upload_document(
    request: Request,
    actor: Annotated[ActorContext, Depends(_actor)],
    file: Annotated[UploadFile, File(description="PDF, DOCX, PPTX, CSV, TXT or MD")],
) -> DocumentUploadResponse:
    settings = _settings(request)
    filename = file.filename or "document"

    try:
        with tempfile.SpooledTemporaryFile(max_size=5 * 1024 * 1024) as spooled:
            hasher = hashlib.sha256()
            size_bytes = 0
            detected_mime = "application/octet-stream"
            first_chunk = True
            while True:
                chunk = await file.read(65536)
                if not chunk:
                    break
                size_bytes += len(chunk)
                if size_bytes > settings.max_file_size:
                    raise DocumentTooLargeError(
                        f"File vượt giới hạn {settings.max_file_size // (1024 * 1024)} MB."
                    )
                if first_chunk:
                    detected_mime = magic.from_buffer(chunk[:8192], mime=True)
                    first_chunk = False
                hasher.update(chunk)
                spooled.write(chunk)

            spooled.seek(0)
            receipt = await run_sync(
                partial(
                    _service(request).upload,
                    actor=actor,
                    filename=filename,
                    content=cast(BinaryIO, spooled),
                    detected_mime=detected_mime,
                    length=size_bytes,
                    content_hash=hasher.hexdigest(),
                )
            )
    except Exception as error:
        raise _safe_error(error) from None
    return DocumentUploadResponse(
        document_id=receipt.document_id,
        version_id=receipt.version_id,
        job_id=receipt.job_id,
        duplicate=receipt.duplicate,
        message=(
            "Existing content returned idempotently."
            if receipt.duplicate
            else "Upload persisted; parsing continues asynchronously."
        ),
    )


@router.get("", response_model=DocumentListResponse)
async def list_documents(
    request: Request,
    actor: Annotated[ActorContext, Depends(_actor)],
    page: Annotated[int, Query(ge=1, le=1_000_000)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 50,
) -> DocumentListResponse:
    try:
        documents, total = await run_sync(
            partial(_service(request).list_documents, actor, page=page, page_size=page_size)
        )
    except Exception as error:
        raise _safe_error(error) from None
    return DocumentListResponse(
        documents=[_document_response(document) for document in documents],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get("/jobs/{job_id}", response_model=JobStatusResponse)
async def get_job(
    job_id: UUID,
    request: Request,
    actor: Annotated[ActorContext, Depends(_actor)],
) -> JobStatusResponse:
    try:
        job = await run_sync(_service(request).get_job, actor, job_id)
    except Exception as error:
        raise _safe_error(error) from None
    return _job_response(job)


@router.get("/{document_id}/preview")
async def get_preview(
    document_id: UUID,
    request: Request,
    actor: Annotated[ActorContext, Depends(_actor)],
) -> Response:
    try:
        content = await run_sync(_service(request).preview, actor, document_id)
    except Exception as error:
        raise _safe_error(error) from None
    return Response(content=content, media_type="application/json")


@router.get("/{document_id}", response_model=DocumentResponse)
async def get_document(
    document_id: UUID,
    request: Request,
    actor: Annotated[ActorContext, Depends(_actor)],
) -> DocumentResponse:
    try:
        document = await run_sync(_service(request).get_document, actor, document_id)
    except Exception as error:
        raise _safe_error(error) from None
    return _document_response(document)


@router.post("/{document_id}/reindex", response_model=DocumentUploadResponse)
async def reindex_document(
    document_id: UUID,
    request: Request,
    actor: Annotated[ActorContext, Depends(_actor)],
) -> DocumentUploadResponse:
    try:
        receipt = await run_sync(_service(request).reindex, actor, document_id)
    except Exception as error:
        raise _safe_error(error) from None
    return DocumentUploadResponse(
        document_id=receipt.document_id,
        version_id=receipt.version_id,
        job_id=receipt.job_id,
        duplicate=receipt.duplicate,
        message="Reindex job accepted idempotently.",
    )


@router.delete("/{document_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_document(
    document_id: UUID,
    request: Request,
    actor: Annotated[ActorContext, Depends(_actor)],
) -> Response:
    try:
        await run_sync(_service(request).delete, actor, document_id)
    except Exception as error:
        raise _safe_error(error) from None
    return Response(status_code=status.HTTP_204_NO_CONTENT)

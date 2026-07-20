"""Idempotent Celery orchestration for Phase 4 document ingestion."""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
from dataclasses import dataclass
from io import BytesIO
from typing import Any, NoReturn
from uuid import UUID

from celery import Task, shared_task
from minio import Minio
from minio.error import S3Error
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.exc import TimeoutError as SqlAlchemyTimeoutError

from worker.chunking import Chunker
from worker.domain import Chunk, ChunkConfig, ChunkType, DocumentState, JobState, ParseQualityReport
from worker.indexing import IndexingError, index_chunks
from worker.normalization import (
    NormalizationError,
    normalize_document,
    normalized_json_bytes,
    preview_markdown_bytes,
)
from worker.parsers import ParserError, parser_registry
from worker.quality import build_parse_quality_report
from worker.settings import IngestionSettings

logger = logging.getLogger(__name__)


class IngestionError(RuntimeError):
    """Stable ingestion failure with explicit retry semantics."""

    def __init__(self, code: str, message: str, *, retryable: bool = False) -> None:
        super().__init__(message)
        self.code = code
        self.retryable = retryable


@dataclass(frozen=True, slots=True)
class _JobContext:
    job_id: UUID
    document_id: UUID
    version_id: UUID
    tenant_id: UUID
    owner_id: UUID
    acl_principals: tuple[str, ...]
    source_name: str
    mime_type: str
    expected_content_hash: str
    raw_artifact_path: str
    index_version: str
    chunk_config: dict[str, object]
    state: JobState


def _required_string(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise IngestionError(
            "INGESTION_METADATA_INVALID",
            f"The ingestion record is missing required field {field_name}.",
        )
    return value


def _load_job(engine: Engine, job_id: UUID) -> _JobContext:
    """Load all worker inputs from PostgreSQL rather than trusting queue payloads."""

    statement = text("""
        SELECT j.id AS job_id,
               j.state AS job_state,
               j.document_id,
               j.version_id,
               d.tenant_id,
               d.owner_id,
               (SELECT COALESCE(
                           array_agg(DISTINCT da.principal_type || ':' || da.principal_id::text),
                           ARRAY[]::text[]
                       )
                  FROM document_acls AS da WHERE da.document_id = d.id) AS acl_principals,
               d.source_name,
               d.mime_type,
               d.content_hash,
               d.deleted_at,
               v.raw_artifact_path,
               v.index_version,
               v.chunk_config
          FROM ingestion_jobs AS j
          JOIN documents AS d ON d.id = j.document_id
          JOIN document_versions AS v ON v.id = j.version_id
         WHERE j.id = :job_id
    """)
    with engine.connect() as connection:
        row = connection.execute(statement, {"job_id": job_id}).mappings().one_or_none()
    if row is None:
        raise IngestionError(
            "INGESTION_JOB_NOT_FOUND",
            "The ingestion job no longer exists; submit the document again.",
        )
    if row["deleted_at"] is not None:
        raise IngestionError(
            "INGESTION_DOCUMENT_DELETED",
            "The document was deleted before processing started.",
        )
    raw_config = row["chunk_config"]
    chunk_config = dict(raw_config) if isinstance(raw_config, dict) else {}
    try:
        state = JobState(_required_string(row["job_state"], "job state"))
    except ValueError:
        raise IngestionError(
            "INGESTION_METADATA_INVALID",
            "The ingestion job has an invalid state.",
        ) from None
    raw_index_version = row["index_version"]
    index_version = (
        raw_index_version.strip()
        if isinstance(raw_index_version, str) and raw_index_version.strip()
        else "embed300m-v2_s256_o10"
    )
    raw_acl_principals = row["acl_principals"]
    if not isinstance(raw_acl_principals, list | tuple):
        raise IngestionError("INGESTION_METADATA_INVALID", "The document ACL metadata is invalid.")
    acl_principals = tuple(
        dict.fromkeys([f"user:{row['owner_id']}", *(str(value) for value in raw_acl_principals)])
    )
    return _JobContext(
        job_id=UUID(str(row["job_id"])),
        document_id=UUID(str(row["document_id"])),
        version_id=UUID(str(row["version_id"])),
        tenant_id=UUID(str(row["tenant_id"])),
        owner_id=UUID(str(row["owner_id"])),
        acl_principals=acl_principals,
        source_name=_required_string(row["source_name"], "source_name"),
        mime_type=_required_string(row["mime_type"], "mime_type"),
        expected_content_hash=_required_string(row["content_hash"], "content_hash"),
        raw_artifact_path=_required_string(row["raw_artifact_path"], "raw_artifact_path"),
        index_version=index_version,
        chunk_config=chunk_config,
        state=state,
    )


def _update_job_state(
    engine: Engine,
    job_id: UUID,
    state: JobState,
    *,
    progress_percent: int,
    progress_message: str,
    retry_count: int = 0,
    error_code: str | None = None,
    error_message: str | None = None,
) -> None:
    """Update exactly one job using valid PostgreSQL syntax."""

    statement = text("""
        UPDATE ingestion_jobs
           SET state = CAST(:state AS varchar),
               progress_percent = :progress_percent,
               progress_message = :progress_message,
               retry_count = GREATEST(retry_count, :retry_count),
               error_code = :error_code,
               error_message = :error_message,
               started_at = CASE
                   WHEN CAST(:state AS varchar) = 'running' THEN COALESCE(started_at, NOW())
                   ELSE started_at
               END,
               completed_at = CASE
                   WHEN CAST(:state AS varchar) IN ('success', 'failed', 'cancelled') THEN NOW()
                   ELSE NULL
               END
         WHERE id = :job_id
    """)
    with engine.begin() as connection:
        result = connection.execute(
            statement,
            {
                "job_id": job_id,
                "state": state.value,
                "progress_percent": progress_percent,
                "progress_message": progress_message,
                "retry_count": retry_count,
                "error_code": error_code,
                "error_message": error_message,
            },
        )
        if result.rowcount != 1:
            raise IngestionError(
                "INGESTION_JOB_NOT_FOUND",
                "The ingestion job disappeared while it was running.",
            )


def _update_document_state(engine: Engine, document_id: UUID, state: DocumentState) -> None:
    with engine.begin() as connection:
        connection.execute(
            text("""
                UPDATE documents
                   SET state = :state,
                       error_code = NULL,
                       error_message = NULL,
                       updated_at = NOW()
                 WHERE id = :document_id
            """),
            {"document_id": document_id, "state": state.value},
        )


def _artifact_location(path: str) -> tuple[str, str]:
    bucket, separator, object_name = path.partition("/")
    if (
        not separator
        or not bucket
        or not object_name
        or object_name.startswith("/")
        or any(part in {"", ".", ".."} for part in object_name.split("/"))
    ):
        raise IngestionError(
            "INGESTION_ARTIFACT_PATH_INVALID",
            "The raw document storage path is invalid; upload the document again.",
        )
    return bucket, object_name


def _download_document(client: Minio, path: str, max_bytes: int) -> bytes:
    bucket, object_name = _artifact_location(path)
    response: Any = None
    try:
        response = client.get_object(bucket, object_name)
        content = response.read(max_bytes + 1)
    except S3Error:
        raise IngestionError(
            "INGESTION_STORAGE_UNAVAILABLE",
            "The uploaded document is temporarily unavailable in object storage.",
            retryable=True,
        ) from None
    finally:
        if response is not None:
            response.close()
            response.release_conn()
    if len(content) > max_bytes:
        raise IngestionError(
            "INGESTION_FILE_TOO_LARGE",
            f"The document exceeds the configured {max_bytes}-byte processing limit.",
        )
    return bytes(content)


def _put_artifact(client: Minio, path: str, payload: bytes, content_type: str) -> None:
    bucket, object_name = _artifact_location(path)
    try:
        client.put_object(
            bucket,
            object_name,
            BytesIO(payload),
            len(payload),
            content_type=content_type,
        )
    except S3Error:
        raise IngestionError(
            "INGESTION_STORAGE_UNAVAILABLE",
            "A normalized document artifact could not be stored; the job will retry.",
            retryable=True,
        ) from None


def _artifact_paths(context: _JobContext) -> tuple[str, str]:
    bucket, _ = _artifact_location(context.raw_artifact_path)
    prefix = f"tenants/{context.tenant_id}/documents/{context.document_id}/versions"
    return (
        f"{bucket}/{prefix}/{context.version_id}/normalized.json",
        f"{bucket}/{prefix}/{context.version_id}/preview.md",
    )


def _integer_config(config: dict[str, object], key: str, fallback: int) -> int:
    value = config.get(key, fallback)
    if isinstance(value, bool) or not isinstance(value, int):
        raise IngestionError(
            "INGESTION_CHUNK_CONFIG_INVALID",
            f"The stored chunk configuration field {key} must be an integer.",
        )
    return value


def _chunk_config(context: _JobContext, settings: IngestionSettings) -> ChunkConfig:
    try:
        return ChunkConfig(
            child_size=_integer_config(
                context.chunk_config, "child_size", settings.chunk_child_size
            ),
            parent_size=_integer_config(
                context.chunk_config, "parent_size", settings.chunk_parent_size
            ),
            overlap_percent=_integer_config(
                context.chunk_config,
                "overlap_percent",
                settings.chunk_overlap_percent,
            ),
            respect_boundaries=True,
            include_section_prefix=True,
            index_version=settings.vector_index_version,
        )
    except ValueError:
        raise IngestionError(
            "INGESTION_CHUNK_CONFIG_INVALID",
            "The stored chunk configuration is outside the supported token limits.",
        ) from None


def _replace_chunks_and_complete(
    engine: Engine,
    context: _JobContext,
    chunks: list[Chunk],
    *,
    element_count: int,
    language: str | None,
    normalized_path: str,
    preview_path: str,
    parser_version: str,
    embedding_model: str,
    parse_report: ParseQualityReport,
) -> None:
    """Atomically replace one version's deterministic chunks and complete its job."""

    if not chunks:
        raise IngestionError(
            "INGESTION_NO_CHUNKS",
            "No searchable chunks were produced; verify document contents.",
        )
    delete_chunks = text("DELETE FROM chunks WHERE version_id = :version_id")
    insert_chunk = text("""
        INSERT INTO chunks (
            id, document_id, version_id, parent_chunk_id, chunk_type,
            chunk_index, text, text_preview, content_hash, index_version,
            token_count, page, slide, sheet, cell_range, line_start, line_end,
            section_path, language, vector_id, embedding_model, created_at
        ) VALUES (
            :id, :document_id, :version_id, :parent_chunk_id, :chunk_type,
            :chunk_index, :text, :text_preview, :content_hash, :index_version,
            :token_count, :page, :slide, :sheet, :cell_range, :line_start, :line_end,
            CAST(:section_path AS JSONB), :language, :vector_id, :embedding_model, NOW()
        )
    """)
    with engine.begin() as connection:
        connection.execute(delete_chunks, {"version_id": context.version_id})
        for chunk in chunks:
            connection.execute(
                insert_chunk,
                {
                    "id": chunk.chunk_id,
                    "document_id": chunk.document_id,
                    "version_id": chunk.version_id,
                    "parent_chunk_id": chunk.parent_chunk_id,
                    "chunk_type": chunk.chunk_type.value,
                    "chunk_index": chunk.chunk_index,
                    "text": chunk.text,
                    "text_preview": chunk.text[:500],
                    "content_hash": chunk.content_hash,
                    "index_version": chunk.index_version,
                    "token_count": chunk.token_count,
                    "page": chunk.page,
                    "slide": chunk.slide,
                    "sheet": chunk.sheet,
                    "cell_range": chunk.cell_range,
                    "line_start": chunk.line_start,
                    "line_end": chunk.line_end,
                    "section_path": json.dumps(chunk.section_path, ensure_ascii=False),
                    "language": chunk.language,
                    # Only child chunks are sent to Qdrant. Keep the database's
                    # derived-index metadata truthful for operational checks.
                    "vector_id": str(chunk.chunk_id)
                    if chunk.chunk_type is ChunkType.CHILD
                    else None,
                    "embedding_model": (
                        embedding_model if chunk.chunk_type is ChunkType.CHILD else None
                    ),
                },
            )
        connection.execute(
            text("""
                INSERT INTO document_parse_reports(
                    version_id,document_id,quality_status,expected_units,covered_units,
                    coverage_ratio,text_length,table_count,ocr_unit_count,empty_unit_count,
                    duplicate_ratio,encoding_error_count,warnings,report,created_at
                ) VALUES(
                    :version_id,:document_id,:quality_status,:expected_units,:covered_units,
                    :coverage_ratio,:text_length,:table_count,:ocr_unit_count,:empty_unit_count,
                    :duplicate_ratio,:encoding_error_count,CAST(:warnings AS jsonb),
                    CAST(:report AS jsonb),NOW()
                ) ON CONFLICT(version_id) DO UPDATE SET
                    quality_status=EXCLUDED.quality_status,
                    expected_units=EXCLUDED.expected_units,
                    covered_units=EXCLUDED.covered_units,
                    coverage_ratio=EXCLUDED.coverage_ratio,
                    text_length=EXCLUDED.text_length,
                    table_count=EXCLUDED.table_count,
                    ocr_unit_count=EXCLUDED.ocr_unit_count,
                    empty_unit_count=EXCLUDED.empty_unit_count,
                    duplicate_ratio=EXCLUDED.duplicate_ratio,
                    encoding_error_count=EXCLUDED.encoding_error_count,
                    warnings=EXCLUDED.warnings,
                    report=EXCLUDED.report,
                    created_at=EXCLUDED.created_at
            """),
            {
                "version_id": parse_report.version_id,
                "document_id": parse_report.document_id,
                "quality_status": parse_report.quality_status,
                "expected_units": parse_report.expected_units,
                "covered_units": parse_report.covered_units,
                "coverage_ratio": parse_report.coverage_ratio,
                "text_length": parse_report.text_length,
                "table_count": parse_report.table_count,
                "ocr_unit_count": parse_report.ocr_unit_count,
                "empty_unit_count": parse_report.empty_unit_count,
                "duplicate_ratio": parse_report.duplicate_ratio,
                "encoding_error_count": parse_report.encoding_error_count,
                "warnings": json.dumps(parse_report.warnings, ensure_ascii=False),
                "report": json.dumps(parse_report.model_dump(mode="json"), ensure_ascii=False),
            },
        )
        connection.execute(
            text("""
                UPDATE document_versions
                   SET parser_version = :parser_version,
                       normalized_artifact_path = :normalized_path,
                       preview_artifact_path = :preview_path,
                       index_version = :index_version,
                       element_count = :element_count,
                       chunk_count = :chunk_count
                 WHERE id = :version_id
            """),
            {
                "version_id": context.version_id,
                "parser_version": parser_version,
                "normalized_path": normalized_path,
                "preview_path": preview_path,
                "index_version": context.index_version,
                "element_count": element_count,
                "chunk_count": len(chunks),
            },
        )
        connection.execute(
            text("""
                UPDATE documents
                   SET state = 'ready',
                       current_version_id = :version_id,
                       language = :language,
                       error_code = NULL,
                       error_message = NULL,
                       indexed_at = NOW(),
                       updated_at = NOW()
                 WHERE id = :document_id
            """),
            {
                "document_id": context.document_id,
                "version_id": context.version_id,
                "language": language,
            },
        )
        connection.execute(
            text("""
                UPDATE ingestion_jobs
                   SET state = 'success',
                       progress_percent = 100,
                       progress_message = :message,
                       error_code = NULL,
                       error_message = NULL,
                       completed_at = NOW()
                 WHERE id = :job_id
            """),
            {
                "job_id": context.job_id,
                "message": (
                    f"Processed {len(chunks)} chunks"
                    if parse_report.quality_status == "ready"
                    else "Processed with parse warnings: " + ", ".join(parse_report.warnings)
                ),
            },
        )


def _record_failure(
    engine: Engine,
    job_id: UUID,
    error: IngestionError,
    *,
    retry_count: int,
    terminal: bool,
) -> None:
    state = JobState.FAILED if terminal else JobState.RUNNING
    message = str(error)[:1000]
    try:
        with engine.begin() as connection:
            connection.execute(
                text("""
                    UPDATE ingestion_jobs
                       SET state = :state,
                           retry_count = GREATEST(retry_count, :retry_count),
                           progress_message = :progress_message,
                           error_code = :error_code,
                           error_message = :error_message,
                           completed_at = CASE WHEN :terminal THEN NOW() ELSE NULL END
                     WHERE id = :job_id
                """),
                {
                    "job_id": job_id,
                    "state": state.value,
                    "retry_count": retry_count,
                    "progress_message": "Processing failed" if terminal else "Retry scheduled",
                    "error_code": error.code,
                    "error_message": message,
                    "terminal": terminal,
                },
            )
            if terminal:
                connection.execute(
                    text("""
                        UPDATE documents
                           SET state = 'failed',
                               error_code = :error_code,
                               error_message = :error_message,
                               updated_at = NOW()
                         WHERE id = (
                             SELECT document_id FROM ingestion_jobs WHERE id = :job_id
                         )
                    """),
                    {"job_id": job_id, "error_code": error.code, "error_message": message},
                )
    except (OperationalError, SqlAlchemyTimeoutError):
        # The original stable failure is more useful than masking it with a
        # second database outage while attempting to report status.
        return


def _minio_client(settings: IngestionSettings) -> Minio:
    return Minio(
        settings.minio_endpoint,
        access_key=settings.minio_access_key.get_secret_value(),
        secret_key=settings.minio_secret_key.get_secret_value(),
        secure=settings.minio_secure,
    )


def _already_complete_result(engine: Engine, context: _JobContext) -> dict[str, str | int]:
    with engine.connect() as connection:
        count = connection.execute(
            text("SELECT COUNT(*) FROM chunks WHERE version_id = :version_id"),
            {"version_id": context.version_id},
        ).scalar_one()
    return {
        "status": "already_complete",
        "document_id": str(context.document_id),
        "chunk_count": int(count),
    }


def _run_ingestion(
    engine: Engine,
    client: Minio,
    settings: IngestionSettings,
    job_id: UUID,
) -> dict[str, str | int]:
    context = _load_job(engine, job_id)
    if context.state == JobState.SUCCESS:
        return _already_complete_result(engine, context)
    if context.state == JobState.CANCELLED:
        raise IngestionError(
            "INGESTION_JOB_CANCELLED",
            "The ingestion job was cancelled and cannot be processed.",
        )

    _update_job_state(
        engine,
        job_id,
        JobState.RUNNING,
        progress_percent=5,
        progress_message="Downloading document",
    )
    _update_document_state(engine, context.document_id, DocumentState.VALIDATING)
    content = _download_document(client, context.raw_artifact_path, settings.max_document_bytes)
    observed_hash = hashlib.sha256(content).hexdigest()
    if observed_hash != context.expected_content_hash:
        raise IngestionError(
            "INGESTION_CONTENT_HASH_MISMATCH",
            "Stored document bytes do not match the upload checksum; upload the file again.",
        )

    _update_document_state(engine, context.document_id, DocumentState.PARSING)
    _update_job_state(
        engine,
        job_id,
        JobState.RUNNING,
        progress_percent=25,
        progress_message="Parsing document",
    )
    parser = parser_registry.get_parser(context.mime_type)
    parsed = asyncio.run(
        parser.parse(
            content=content,
            filename=context.source_name,
            mime_type=context.mime_type,
            document_id=context.document_id,
            version_id=context.version_id,
            tenant_id=context.tenant_id,
        )
    )

    _update_document_state(engine, context.document_id, DocumentState.NORMALIZING)
    normalized = normalize_document(parsed)
    parse_report = build_parse_quality_report(normalized)
    normalized_payload = normalized_json_bytes(normalized)
    preview_payload = preview_markdown_bytes(normalized)
    normalized_path, preview_path = _artifact_paths(context)
    _put_artifact(client, normalized_path, normalized_payload, "application/json")
    _put_artifact(client, preview_path, preview_payload, "text/markdown; charset=utf-8")

    _update_document_state(engine, context.document_id, DocumentState.CHUNKING)
    _update_job_state(
        engine,
        job_id,
        JobState.RUNNING,
        progress_percent=70,
        progress_message="Chunking document",
    )
    chunks = Chunker(_chunk_config(context, settings)).chunk_document(normalized)
    _update_job_state(
        engine,
        job_id,
        JobState.RUNNING,
        progress_percent=85,
        progress_message="Embedding and indexing document",
    )
    try:
        index_chunks(
            chunks=chunks,
            tenant_id=context.tenant_id,
            document_id=context.document_id,
            version_id=context.version_id,
            owner_id=context.owner_id,
            acl_principals=context.acl_principals,
            source_name=context.source_name,
            mime_type=context.mime_type,
            embedding_base_url=settings.embedding_base_url,
            embedding_model=settings.embedding_model,
            embedding_dimension=settings.embedding_dimension,
            qdrant_url=settings.qdrant_url,
            collection=settings.qdrant_collection,
            active_alias=settings.qdrant_active_alias,
            index_version=settings.vector_index_version,
            batch_size=settings.embedding_batch_size,
        )
    except IndexingError:
        raise IngestionError(
            "INGESTION_INDEX_UNAVAILABLE",
            "Embedding or vector indexing is temporarily unavailable.",
            retryable=True,
        ) from None
    _replace_chunks_and_complete(
        engine,
        context,
        chunks,
        element_count=len(normalized.elements),
        language=normalized.language,
        normalized_path=normalized_path,
        preview_path=preview_path,
        parser_version=settings.parser_version,
        embedding_model=settings.embedding_model,
        parse_report=parse_report,
    )
    return {
        "status": "success",
        "document_id": str(context.document_id),
        "chunk_count": len(chunks),
    }


def _retry(self: Task, error: IngestionError, settings: IngestionSettings) -> NoReturn:
    retries = int(self.request.retries)
    countdown = min(
        settings.task_retry_base_seconds * (2**retries),
        settings.task_retry_max_seconds,
    )
    raise self.retry(
        exc=error,
        countdown=countdown,
        max_retries=settings.task_max_retries,
    )


@shared_task(
    bind=True,
    name="worker.tasks.process_document",
    acks_late=True,
    reject_on_worker_lost=True,
    max_retries=3,
)  # type: ignore[untyped-decorator]
def process_document_task(self: Task, job_id: str) -> dict[str, str | int]:
    """Process one authoritative ingestion job identified only by its UUID."""

    try:
        parsed_job_id = UUID(job_id)
    except ValueError:
        raise IngestionError(
            "INGESTION_JOB_ID_INVALID",
            "The queued ingestion job identifier is not a valid UUID.",
        ) from None

    settings = IngestionSettings()
    engine = create_engine(
        settings.database_url.get_secret_value(),
        pool_pre_ping=True,
        connect_args={"options": "-csearch_path=app,public"},
    )
    try:
        try:
            return _run_ingestion(engine, _minio_client(settings), settings, parsed_job_id)
        except ParserError as parser_error:
            error = IngestionError(
                parser_error.code,
                str(parser_error),
                retryable=parser_error.retryable,
            )
        except NormalizationError as normalization_error:
            error = IngestionError(normalization_error.code, str(normalization_error))
        except IngestionError as ingestion_error:
            error = ingestion_error
        except (OperationalError, SqlAlchemyTimeoutError):
            error = IngestionError(
                "INGESTION_DATABASE_UNAVAILABLE",
                "The ingestion database is temporarily unavailable.",
                retryable=True,
            )
        except Exception:
            logger.exception("Unexpected ingestion failure for job %s", parsed_job_id)
            error = IngestionError(
                "INGESTION_INTERNAL_ERROR",
                "Document processing failed unexpectedly; inspect the correlated worker log.",
            )

        retry_count = int(self.request.retries) + 1
        terminal = not error.retryable or int(self.request.retries) >= settings.task_max_retries
        _record_failure(
            engine,
            parsed_job_id,
            error,
            retry_count=retry_count,
            terminal=terminal,
        )
        if error.retryable and not terminal:
            _retry(self, error, settings)
        raise error
    finally:
        engine.dispose()


__all__ = ["IngestionError", "process_document_task"]

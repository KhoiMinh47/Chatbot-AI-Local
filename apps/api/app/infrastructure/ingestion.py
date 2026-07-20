"""PostgreSQL, MinIO, and Celery adapters for Phase 4 ingestion."""

from __future__ import annotations

import io
import logging
from collections.abc import Mapping
from datetime import datetime
from typing import BinaryIO, cast
from urllib.parse import quote
from uuid import UUID

from celery import Celery
from kombu import Exchange, Queue
from minio import Minio
from sqlalchemy import URL, Engine, create_engine, text
from sqlalchemy.exc import IntegrityError

from app.application.ingestion import (
    ArtifactStore,
    DocumentIngestionService,
    IngestionQueue,
    IngestionRepository,
    NewUpload,
    ReindexRequest,
)
from app.domain.ingestion import ActorContext, DocumentView, JobView, UploadReceipt
from app.infrastructure.ingestion_settings import IngestionSettings

_log = logging.getLogger(__name__)


def _mapping(row: object) -> Mapping[str, object]:
    return cast(Mapping[str, object], row)


def _document(row: Mapping[str, object]) -> DocumentView:
    return DocumentView(
        id=cast(UUID, row["id"]),
        tenant_id=cast(UUID, row["tenant_id"]),
        owner_id=cast(UUID, row["owner_id"]),
        source_name=cast(str, row["source_name"]),
        mime_type=cast(str, row["mime_type"]),
        size_bytes=cast(int, row["size_bytes"]),
        language=cast(str | None, row["language"]),
        state=cast(str, row["state"]),
        error_code=cast(str | None, row["error_code"]),
        error_message=cast(str | None, row["error_message"]),
        created_at=cast(datetime, row["created_at"]),
        updated_at=cast(datetime, row["updated_at"]),
        indexed_at=cast(datetime | None, row["indexed_at"]),
    )


def _job(row: Mapping[str, object]) -> JobView:
    return JobView(
        id=cast(UUID, row["id"]),
        document_id=cast(UUID, row["document_id"]),
        version_id=cast(UUID, row["version_id"]),
        state=cast(str, row["state"]),
        progress_percent=cast(int, row["progress_percent"]),
        progress_message=cast(str | None, row["progress_message"]),
        error_code=cast(str | None, row["error_code"]),
        error_message=cast(str | None, row["error_message"]),
        retry_count=cast(int, row["retry_count"]),
        created_at=cast(datetime, row["created_at"]),
        completed_at=cast(datetime | None, row["completed_at"]),
        parse_quality_status=cast(str | None, row.get("parse_quality_status")),
        parse_coverage_ratio=cast(float | None, row.get("parse_coverage_ratio")),
        parse_warnings=tuple(
            str(value) for value in cast(list[object] | None, row.get("parse_warnings")) or []
        ),
    )


class PostgresIngestionRepository(IngestionRepository):
    """Small transaction-oriented repository; every query is tenant scoped."""

    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def close(self) -> None:
        self._engine.dispose()

    def find_duplicate(self, actor: ActorContext, content_hash: str) -> UploadReceipt | None:
        query = text("""
            SELECT d.id AS document_id, v.id AS version_id, j.id AS job_id
            FROM documents d
            JOIN document_versions v ON v.id = d.current_version_id
            JOIN LATERAL (
                SELECT id FROM ingestion_jobs
                WHERE document_id = d.id AND version_id = v.id
                ORDER BY created_at DESC LIMIT 1
            ) j ON TRUE
            WHERE d.tenant_id = :tenant_id
              AND d.content_hash = :content_hash
              AND d.deleted_at IS NULL
              AND (
                  d.owner_id = :user_id OR EXISTS (
                      SELECT 1 FROM document_acls acl
                      WHERE acl.document_id = d.id
                        AND acl.principal_type = 'user'
                        AND acl.principal_id = :user_id
                  )
              )
            LIMIT 1
        """)
        with self._engine.connect() as connection:
            row = (
                connection.execute(
                    query,
                    {
                        "tenant_id": actor.tenant_id,
                        "user_id": actor.user_id,
                        "content_hash": content_hash,
                    },
                )
                .mappings()
                .first()
            )
        if row is None:
            return None
        return UploadReceipt(
            document_id=cast(UUID, row["document_id"]),
            version_id=cast(UUID, row["version_id"]),
            job_id=cast(UUID, row["job_id"]),
            duplicate=True,
        )

    def claim_retryable_duplicate(
        self, actor: ActorContext, content_hash: str
    ) -> UploadReceipt | None:
        """Atomically claim a stale broker failure so a re-upload can dispatch it once."""

        query = text("""
            WITH candidate AS (
                SELECT j.id AS job_id, d.id AS document_id, v.id AS version_id
                FROM documents d
                JOIN document_versions v ON v.id = d.current_version_id
                JOIN ingestion_jobs j
                  ON j.document_id = d.id AND j.version_id = v.id
                WHERE d.tenant_id = :tenant_id
                  AND d.content_hash = :content_hash
                  AND d.deleted_at IS NULL
                  AND j.state = 'failed'
                  AND j.error_code = 'QUEUE_UNAVAILABLE'
                  AND (
                      d.owner_id = :user_id OR EXISTS (
                          SELECT 1 FROM document_acls acl
                          WHERE acl.document_id = d.id
                            AND acl.principal_type = 'user'
                            AND acl.principal_id = :user_id
                      )
                  )
                ORDER BY j.created_at DESC
                LIMIT 1
                FOR UPDATE OF j
            )
            UPDATE ingestion_jobs j
            SET state = 'pending', progress_percent = 0,
                progress_message = 'Queued for retry', error_code = NULL,
                error_message = NULL, celery_task_id = NULL, started_at = NULL,
                completed_at = NULL, retry_count = j.retry_count + 1
            FROM candidate c
            WHERE j.id = c.job_id
            RETURNING c.document_id, c.version_id, j.id AS job_id
        """)
        with self._engine.begin() as connection:
            row = (
                connection.execute(
                    query,
                    {
                        "tenant_id": actor.tenant_id,
                        "user_id": actor.user_id,
                        "content_hash": content_hash,
                    },
                )
                .mappings()
                .first()
            )
        if row is None:
            return None
        return UploadReceipt(
            document_id=cast(UUID, row["document_id"]),
            version_id=cast(UUID, row["version_id"]),
            job_id=cast(UUID, row["job_id"]),
            duplicate=False,
        )

    def create_upload(self, upload: NewUpload) -> UploadReceipt:
        try:
            with self._engine.begin() as connection:
                connection.execute(
                    text("""
                        INSERT INTO documents (
                            id, tenant_id, owner_id, source_name, mime_type, content_hash,
                            size_bytes, state, created_at, updated_at
                        ) VALUES (
                            :id, :tenant_id, :owner_id, :source_name, :mime_type, :content_hash,
                            :size_bytes, 'uploaded', NOW(), NOW()
                        )
                    """),
                    {
                        "id": upload.document_id,
                        "tenant_id": upload.actor.tenant_id,
                        "owner_id": upload.actor.user_id,
                        "source_name": upload.source_name,
                        "mime_type": upload.mime_type,
                        "content_hash": upload.content_hash,
                        "size_bytes": upload.size_bytes,
                    },
                )
                connection.execute(
                    text("""
                        INSERT INTO document_versions (
                            id, document_id, version_number, content_hash, parser_version,
                            chunk_config, raw_artifact_path, index_version, created_at
                        ) VALUES (
                            :id, :document_id, 1, :content_hash, :parser_version,
                            CAST(:chunk_config AS jsonb), :raw_artifact_path, :index_version, NOW()
                        )
                    """),
                    {
                        "id": upload.version_id,
                        "document_id": upload.document_id,
                        "content_hash": upload.content_hash,
                        "parser_version": upload.parser_version,
                        "chunk_config": __import__("json").dumps(upload.chunk_config),
                        "raw_artifact_path": upload.raw_artifact_path,
                        "index_version": upload.index_version,
                    },
                )
                connection.execute(
                    text("UPDATE documents SET current_version_id=:version WHERE id=:document"),
                    {"version": upload.version_id, "document": upload.document_id},
                )
                connection.execute(
                    text("""
                        INSERT INTO document_acls (
                            id, document_id, principal_id, principal_type, permission, created_at
                        ) VALUES (
                            gen_random_uuid(), :document_id, :owner_id, 'user', 'admin', NOW()
                        )
                    """),
                    {"document_id": upload.document_id, "owner_id": upload.actor.user_id},
                )
                connection.execute(
                    text("""
                        INSERT INTO ingestion_jobs (
                            id, document_id, version_id, job_type, state, progress_percent,
                            progress_message, idempotency_key, created_at
                        ) VALUES (
                            :id, :document_id, :version_id, 'parse', 'pending', 0,
                            'Queued for validation', :idempotency_key, NOW()
                        )
                    """),
                    {
                        "id": upload.job_id,
                        "document_id": upload.document_id,
                        "version_id": upload.version_id,
                        "idempotency_key": (
                            f"upload:{upload.actor.tenant_id}:{upload.content_hash}:"
                            f"{upload.parser_version}:{upload.index_version}:{upload.document_id}"
                        ),
                    },
                )
        except IntegrityError:
            existing = self.find_duplicate(upload.actor, upload.content_hash)
            if existing is None:
                raise
            return existing
        return UploadReceipt(upload.document_id, upload.version_id, upload.job_id, False)

    def attach_task_id(self, actor: ActorContext, job_id: UUID, task_id: str) -> None:
        with self._engine.begin() as connection:
            result = connection.execute(
                text("""
                    UPDATE ingestion_jobs j SET celery_task_id=:task_id
                    FROM documents d
                    WHERE j.id=:job_id AND d.id=j.document_id
                      AND d.tenant_id=:tenant_id AND d.deleted_at IS NULL
                      AND (d.owner_id=:user_id OR EXISTS (
                          SELECT 1 FROM document_acls acl
                          WHERE acl.document_id=d.id AND acl.principal_type='user'
                            AND acl.principal_id=:user_id
                      ))
                """),
                {
                    "task_id": task_id,
                    "job_id": job_id,
                    "tenant_id": actor.tenant_id,
                    "user_id": actor.user_id,
                },
            )
            if result.rowcount != 1:
                raise RuntimeError("job disappeared before task attachment")

    def mark_enqueue_failed(self, actor: ActorContext, job_id: UUID) -> None:
        with self._engine.begin() as connection:
            connection.execute(
                text("""
                    UPDATE ingestion_jobs j
                    SET state='failed', error_code='QUEUE_UNAVAILABLE',
                        error_message='Queue unavailable; retry the upload or reindex request.',
                        completed_at=NOW()
                    FROM documents d
                    WHERE j.id=:job_id AND d.id=j.document_id AND d.tenant_id=:tenant_id
                      AND (d.owner_id=:user_id OR EXISTS (
                          SELECT 1 FROM document_acls acl
                          WHERE acl.document_id=d.id AND acl.principal_type='user'
                            AND acl.principal_id=:user_id
                      ))
                """),
                {
                    "job_id": job_id,
                    "tenant_id": actor.tenant_id,
                    "user_id": actor.user_id,
                },
            )

    def list_documents(
        self, actor: ActorContext, *, offset: int, limit: int
    ) -> tuple[tuple[DocumentView, ...], int]:
        with self._engine.connect() as connection:
            total = cast(
                int,
                connection.execute(
                    text("""
                        SELECT COUNT(*) FROM documents
                        WHERE tenant_id=:tenant_id AND deleted_at IS NULL
                          AND (owner_id=:user_id OR EXISTS (
                              SELECT 1 FROM document_acls acl
                              WHERE acl.document_id=documents.id
                                AND acl.principal_type='user'
                                AND acl.principal_id=:user_id
                          ))
                    """),
                    {"tenant_id": actor.tenant_id, "user_id": actor.user_id},
                ).scalar_one(),
            )
            rows = connection.execute(
                text("""
                    SELECT id, tenant_id, owner_id, source_name, mime_type, size_bytes,
                           language, state, error_code, error_message, created_at, updated_at,
                           indexed_at
                    FROM documents
                    WHERE tenant_id=:tenant_id AND deleted_at IS NULL
                      AND (owner_id=:user_id OR EXISTS (
                          SELECT 1 FROM document_acls acl
                          WHERE acl.document_id=documents.id AND acl.principal_type='user'
                            AND acl.principal_id=:user_id
                      ))
                    ORDER BY created_at DESC, id
                    OFFSET :offset LIMIT :limit
                """),
                {
                    "tenant_id": actor.tenant_id,
                    "user_id": actor.user_id,
                    "offset": offset,
                    "limit": limit,
                },
            ).mappings()
            documents = tuple(_document(_mapping(row)) for row in rows)
        return documents, total

    def get_document(self, actor: ActorContext, document_id: UUID) -> DocumentView | None:
        with self._engine.connect() as connection:
            row = (
                connection.execute(
                    text("""
                    SELECT id, tenant_id, owner_id, source_name, mime_type, size_bytes,
                           language, state, error_code, error_message, created_at, updated_at,
                           indexed_at
                    FROM documents
                    WHERE id=:id AND tenant_id=:tenant_id AND deleted_at IS NULL
                      AND (owner_id=:user_id OR EXISTS (
                          SELECT 1 FROM document_acls acl
                          WHERE acl.document_id=documents.id AND acl.principal_type='user'
                            AND acl.principal_id=:user_id
                      ))
                """),
                    {
                        "id": document_id,
                        "tenant_id": actor.tenant_id,
                        "user_id": actor.user_id,
                    },
                )
                .mappings()
                .first()
            )
        return None if row is None else _document(_mapping(row))

    def get_job(self, actor: ActorContext, job_id: UUID) -> JobView | None:
        with self._engine.connect() as connection:
            row = (
                connection.execute(
                    text("""
                    SELECT j.id, j.document_id, j.version_id, j.state, j.progress_percent,
                           j.progress_message, j.error_code, j.error_message, j.retry_count,
                           j.created_at, j.completed_at,
                           report.quality_status AS parse_quality_status,
                           report.coverage_ratio AS parse_coverage_ratio,
                           report.warnings AS parse_warnings
                    FROM ingestion_jobs j JOIN documents d ON d.id=j.document_id
                    LEFT JOIN document_parse_reports report ON report.version_id=j.version_id
                    WHERE j.id=:id AND d.tenant_id=:tenant_id AND d.deleted_at IS NULL
                      AND (d.owner_id=:user_id OR EXISTS (
                          SELECT 1 FROM document_acls acl
                          WHERE acl.document_id=d.id AND acl.principal_type='user'
                            AND acl.principal_id=:user_id
                      ))
                """),
                    {
                        "id": job_id,
                        "tenant_id": actor.tenant_id,
                        "user_id": actor.user_id,
                    },
                )
                .mappings()
                .first()
            )
        return None if row is None else _job(_mapping(row))

    def get_preview_path(self, actor: ActorContext, document_id: UUID) -> str | None:
        with self._engine.connect() as connection:
            value = connection.execute(
                text("""
                    SELECT v.preview_artifact_path
                    FROM documents d JOIN document_versions v ON v.id=d.current_version_id
                    WHERE d.id=:id AND d.tenant_id=:tenant_id AND d.deleted_at IS NULL
                      AND (d.owner_id=:user_id OR EXISTS (
                          SELECT 1 FROM document_acls acl
                          WHERE acl.document_id=d.id AND acl.principal_type='user'
                            AND acl.principal_id=:user_id
                      ))
                """),
                {
                    "id": document_id,
                    "tenant_id": actor.tenant_id,
                    "user_id": actor.user_id,
                },
            ).scalar_one_or_none()
        return cast(str | None, value)

    def create_reindex(self, request: ReindexRequest) -> UploadReceipt:
        with self._engine.begin() as connection:
            current = (
                connection.execute(
                    text("""
                    SELECT d.current_version_id, v.content_hash, v.raw_artifact_path
                    FROM documents d
                    JOIN document_versions v ON v.id=d.current_version_id
                    WHERE d.id=:document_id AND d.tenant_id=:tenant_id
                      AND d.deleted_at IS NULL
                      AND (d.owner_id=:user_id OR EXISTS (
                          SELECT 1 FROM document_acls acl
                          WHERE acl.document_id=d.id AND acl.principal_type='user'
                            AND acl.principal_id=:user_id
                      ))
                    FOR UPDATE OF d
                """),
                    {
                        "document_id": request.document_id,
                        "tenant_id": request.actor.tenant_id,
                        "user_id": request.actor.user_id,
                    },
                )
                .mappings()
                .first()
            )
            if current is None:
                from app.domain.ingestion import DocumentNotFoundError

                raise DocumentNotFoundError("Không tìm thấy tài liệu để reindex.")
            active = (
                connection.execute(
                    text("""
                    SELECT id, version_id FROM ingestion_jobs
                    WHERE document_id=:document_id AND job_type='reindex'
                      AND state IN ('pending','running')
                    ORDER BY created_at DESC LIMIT 1
                """),
                    {"document_id": request.document_id},
                )
                .mappings()
                .first()
            )
            if active is not None:
                return UploadReceipt(
                    request.document_id,
                    cast(UUID, active["version_id"]),
                    cast(UUID, active["id"]),
                    True,
                )
            max_version = connection.execute(
                text("""
                    SELECT COALESCE(MAX(version_number), 0)
                    FROM document_versions WHERE document_id=:document_id
                """),
                {"document_id": request.document_id},
            ).scalar_one()
            connection.execute(
                text("""
                    INSERT INTO document_versions (
                        id, document_id, version_number, content_hash, parser_version,
                        chunk_config, raw_artifact_path, index_version, created_at
                    ) VALUES (
                        :id, :document_id, :version_number, :content_hash, :parser_version,
                        CAST(:chunk_config AS jsonb), :raw_artifact_path, :index_version, NOW()
                    )
                """),
                {
                    "id": request.version_id,
                    "document_id": request.document_id,
                    "version_number": cast(int, max_version) + 1,
                    "content_hash": current["content_hash"],
                    "parser_version": request.parser_version,
                    "chunk_config": __import__("json").dumps(request.chunk_config),
                    "raw_artifact_path": current["raw_artifact_path"],
                    "index_version": request.index_version,
                },
            )
            connection.execute(
                text("""
                    INSERT INTO ingestion_jobs (
                        id, document_id, version_id, job_type, state, progress_percent,
                        progress_message, idempotency_key, created_at
                    ) VALUES (
                        :id, :document_id, :version_id, 'reindex', 'pending', 0,
                        'Queued for reindex', :idempotency_key, NOW()
                    )
                """),
                {
                    "id": request.job_id,
                    "document_id": request.document_id,
                    "version_id": request.version_id,
                    "idempotency_key": f"reindex:{request.document_id}:{request.version_id}",
                },
            )
        return UploadReceipt(request.document_id, request.version_id, request.job_id, False)

    def soft_delete(self, actor: ActorContext, document_id: UUID) -> bool:
        with self._engine.begin() as connection:
            result = connection.execute(
                text("""
                    UPDATE documents
                    SET state='deleted', deleted_at=COALESCE(deleted_at, NOW()), updated_at=NOW()
                    WHERE id=:id AND tenant_id=:tenant_id AND deleted_at IS NULL
                      AND (owner_id=:user_id OR EXISTS (
                          SELECT 1 FROM document_acls acl
                          WHERE acl.document_id=documents.id AND acl.principal_type='user'
                            AND acl.principal_id=:user_id
                      ))
                """),
                {
                    "id": document_id,
                    "tenant_id": actor.tenant_id,
                    "user_id": actor.user_id,
                },
            )
        return result.rowcount == 1


class MinioArtifactStore(ArtifactStore):
    def __init__(self, client: Minio, bucket: str) -> None:
        self._client = client
        self._bucket = bucket
        if not self._client.bucket_exists(bucket):
            self._client.make_bucket(bucket)

    @staticmethod
    def _split(object_path: str) -> tuple[str, str]:
        try:
            bucket, object_name = object_path.split("/", 1)
        except ValueError:
            raise ValueError("artifact path must contain bucket/object") from None
        if not bucket or not object_name:
            raise ValueError("artifact path must contain bucket/object")
        return bucket, object_name

    def put_raw(
        self,
        object_path: str,
        content: bytes | BinaryIO,
        content_type: str,
        length: int | None = None,
    ) -> None:
        bucket, object_name = self._split(object_path)
        if bucket != self._bucket:
            raise ValueError("artifact path targets an unexpected bucket")
        data: BinaryIO
        if isinstance(content, bytes):
            data = io.BytesIO(content)
            size = len(content)
        else:
            data = content
            if length is None:
                raise ValueError("length is required for file-like content")
            size = length
        self._client.put_object(
            bucket,
            object_name,
            data,
            size,
            content_type=content_type,
        )

    def read_json(self, object_path: str, *, max_bytes: int) -> bytes:
        bucket, object_name = self._split(object_path)
        response = self._client.get_object(bucket, object_name)
        try:
            data = response.read(max_bytes + 1)
        finally:
            response.close()
            response.release_conn()
        if len(data) > max_bytes:
            raise RuntimeError("preview artifact exceeds the safe response limit")
        return data


class CeleryIngestionQueue(IngestionQueue):
    def __init__(self, broker_url: str) -> None:
        self._app = Celery("ntc-api-ingestion-producer", broker=broker_url)
        ingestion_exchange = Exchange("ingestion", type="direct", durable=True)
        dead_letter_exchange = Exchange("ingestion.dead", type="direct", durable=True)
        self._app.conf.update(
            accept_content=("json",),
            enable_utc=True,
            task_default_exchange="ingestion",
            task_default_exchange_type="direct",
            task_default_queue="ingestion",
            task_default_routing_key="document.process",
            task_queues=(
                Queue(
                    "ingestion",
                    ingestion_exchange,
                    routing_key="document.process",
                    durable=True,
                    queue_arguments={
                        "x-dead-letter-exchange": "ingestion.dead",
                        "x-dead-letter-routing-key": "document.failed",
                    },
                ),
                Queue(
                    "ingestion.dead",
                    dead_letter_exchange,
                    routing_key="document.failed",
                    durable=True,
                ),
            ),
            task_serializer="json",
            broker_connection_retry_on_startup=True,
            broker_connection_timeout=3,
            task_publish_retry=True,
            task_publish_retry_policy={
                "max_retries": 3,
                "interval_start": 0.2,
                "interval_step": 0.3,
                "interval_max": 1.0,
            },
        )
        _log.info("Celery ingestion producer initialized")

    def enqueue(self, job_id: UUID, *, task_id: str) -> None:
        try:
            self._app.send_task(
                "worker.tasks.process_document",
                args=(str(job_id),),
                task_id=task_id,
                queue="ingestion",
                routing_key="document.process",
            )
            _log.info("Ingestion job enqueued job_id=%s task_id=%s", job_id, task_id)
        except Exception:
            _log.exception("Ingestion enqueue failed job_id=%s", job_id)
            raise

    def close(self) -> None:
        self._app.close()


class IngestionBundle:
    def __init__(
        self,
        *,
        service: DocumentIngestionService,
        repository: PostgresIngestionRepository,
    ) -> None:
        self.service = service
        self._repository = repository

    def close(self) -> None:
        try:
            self.service.close()
        finally:
            self._repository.close()


def build_ingestion_bundle(settings: IngestionSettings) -> IngestionBundle:
    if not settings.enabled:
        raise ValueError("ingestion is disabled")
    # Prefer env var passwords over secret files
    db_pass = getattr(settings, "database_password", None)
    db_file = getattr(settings, "database_password_file", None)
    database_password = (
        db_pass
        if db_pass and db_pass.strip()
        else settings.read_secret(db_file, "database password")
        if hasattr(settings, "read_secret") and db_file
        else ""
    )
    minio_sec = getattr(settings, "minio_secret_key", None)
    minio_file = getattr(settings, "minio_secret_key_file", None)
    minio_secret = (
        minio_sec
        if minio_sec and minio_sec.strip()
        else settings.read_secret(minio_file, "MinIO secret key")
        if hasattr(settings, "read_secret") and minio_file
        else ""
    )
    broker_pass = getattr(settings, "broker_password", None)
    broker_file = getattr(settings, "broker_password_file", None)
    broker_password = (
        broker_pass
        if broker_pass and broker_pass.strip()
        else settings.read_secret(broker_file, "broker password")
        if hasattr(settings, "read_secret") and broker_file
        else ""
    )
    database_url = URL.create(
        "postgresql+psycopg",
        username=settings.database_user,
        password=database_password,
        host=settings.database_host,
        port=settings.database_port,
        database=settings.database_name,
    )
    engine = create_engine(
        database_url,
        pool_pre_ping=True,
        pool_size=5,
        max_overflow=5,
        connect_args={"options": "-csearch_path=app,public"},
    )
    repository = PostgresIngestionRepository(engine)
    minio = Minio(
        cast(str, settings.minio_endpoint),
        access_key=cast(str, settings.minio_access_key),
        secret_key=minio_secret,
        secure=settings.minio_secure,
    )
    artifacts = MinioArtifactStore(minio, settings.minio_bucket)
    encoded_user = quote(settings.broker_user, safe="")
    encoded_password = quote(broker_password, safe="")
    broker_url = (
        f"amqp://{encoded_user}:{encoded_password}@{settings.broker_host}:{settings.broker_port}//"
    )
    queue = CeleryIngestionQueue(broker_url)
    service = DocumentIngestionService(
        repository=repository,
        artifacts=artifacts,
        queue=queue,
        bucket=settings.minio_bucket,
        max_file_size=settings.max_file_size,
    )
    return IngestionBundle(service=service, repository=repository)

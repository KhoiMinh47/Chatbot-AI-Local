"""Phase 4 document ingestion schema.

Revision ID: 0002_phase4
Revises: 0001_phase2
Create Date: 2026-07-14

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0002_phase4"
down_revision: str | None = "0001_phase2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create Phase 4 document ingestion tables."""

    # Documents table - logical document entity
    op.create_table(
        "documents",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("owner_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_name", sa.String(512), nullable=False),
        sa.Column("mime_type", sa.String(128), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),  # SHA-256
        sa.Column("size_bytes", sa.BigInteger, nullable=False),
        sa.Column("language", sa.String(16), nullable=True),
        sa.Column("state", sa.String(32), nullable=False),  # UPLOADED, PARSING, etc.
        sa.Column("current_version_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("error_code", sa.String(64), nullable=True),
        sa.Column("error_message", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("indexed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Index("ix_documents_tenant_id", "tenant_id"),
        sa.Index("ix_documents_owner_id", "owner_id"),
        sa.Index("ix_documents_content_hash", "content_hash"),
        sa.Index("ix_documents_state", "state"),
        sa.Index("ix_documents_created_at", "created_at"),
    )

    # Document versions table - tracks each parse/reindex version
    op.create_table(
        "document_versions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("document_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("version_number", sa.Integer, nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("parser_version", sa.String(64), nullable=False),
        sa.Column("chunk_config", postgresql.JSONB, nullable=False),
        sa.Column("normalized_artifact_path", sa.String(512), nullable=True),
        sa.Column("element_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("chunk_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"], ondelete="CASCADE"),
        sa.Index("ix_document_versions_document_id", "document_id"),
        sa.UniqueConstraint("document_id", "version_number", name="uq_document_version"),
    )

    # Chunks table - metadata for each chunk (text stored in Qdrant)
    op.create_table(
        "chunks",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("document_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("version_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("parent_chunk_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("chunk_type", sa.String(32), nullable=False),  # child, parent
        sa.Column("chunk_index", sa.Integer, nullable=False),
        sa.Column("text_preview", sa.Text, nullable=False),  # First 500 chars
        sa.Column("token_count", sa.Integer, nullable=False),
        sa.Column("page", sa.Integer, nullable=True),
        sa.Column("slide", sa.Integer, nullable=True),
        sa.Column("section_path", postgresql.JSONB, nullable=False),  # ["Chapter 1", "Section 1.1"]
        sa.Column("language", sa.String(16), nullable=True),
        sa.Column("vector_id", sa.String(128), nullable=True),  # Qdrant point ID
        sa.Column("embedding_model", sa.String(128), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["version_id"], ["document_versions.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["parent_chunk_id"], ["chunks.id"], ondelete="SET NULL"),
        sa.Index("ix_chunks_document_id", "document_id"),
        sa.Index("ix_chunks_version_id", "version_id"),
        sa.Index("ix_chunks_vector_id", "vector_id"),
    )

    # Ingestion jobs table - tracks async processing
    op.create_table(
        "ingestion_jobs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("document_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("version_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("job_type", sa.String(32), nullable=False),  # parse, embed, reindex
        sa.Column("state", sa.String(32), nullable=False),  # pending, running, success, failed
        sa.Column("celery_task_id", sa.String(128), nullable=True),
        sa.Column("progress_percent", sa.Integer, nullable=False, server_default="0"),
        sa.Column("progress_message", sa.Text, nullable=True),
        sa.Column("error_code", sa.String(64), nullable=True),
        sa.Column("error_message", sa.Text, nullable=True),
        sa.Column("retry_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["version_id"], ["document_versions.id"], ondelete="CASCADE"),
        sa.Index("ix_ingestion_jobs_document_id", "document_id"),
        sa.Index("ix_ingestion_jobs_state", "state"),
        sa.Index("ix_ingestion_jobs_celery_task_id", "celery_task_id"),
    )

    # ACL table - document access control
    op.create_table(
        "document_acls",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("document_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("principal_id", postgresql.UUID(as_uuid=True), nullable=False),  # user or group
        sa.Column("principal_type", sa.String(32), nullable=False),  # user, group
        sa.Column("permission", sa.String(32), nullable=False),  # read, write, admin
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"], ondelete="CASCADE"),
        sa.Index("ix_document_acls_document_id", "document_id"),
        sa.Index("ix_document_acls_principal_id", "principal_id"),
        sa.UniqueConstraint(
            "document_id", "principal_id", "principal_type", name="uq_document_acl"
        ),
    )


def downgrade() -> None:
    """Drop Phase 4 document ingestion tables."""

    op.drop_table("document_acls")
    op.drop_table("ingestion_jobs")
    op.drop_table("chunks")
    op.drop_table("document_versions")
    op.drop_table("documents")

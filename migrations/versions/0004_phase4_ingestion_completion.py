"""Complete the durable Phase 4 ingestion contract.

Revision ID: 0004_phase4_completion
Revises: 0003_phase6
Create Date: 2026-07-15
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004_phase4_completion"
down_revision: str | None = "0003_phase6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add race-safe upload deduplication and complete ingestion artifacts."""

    op.add_column(
        "document_versions",
        sa.Column("raw_artifact_path", sa.String(1024), nullable=True),
    )
    op.add_column(
        "document_versions",
        sa.Column("preview_artifact_path", sa.String(1024), nullable=True),
    )
    op.add_column(
        "document_versions",
        sa.Column("index_version", sa.String(256), nullable=True),
    )

    op.add_column(
        "chunks",
        sa.Column("text", sa.Text(), nullable=False, server_default=""),
    )
    op.add_column(
        "chunks",
        sa.Column(
            "content_hash",
            sa.String(64),
            nullable=False,
            server_default="0" * 64,
        ),
    )
    op.add_column(
        "chunks",
        sa.Column(
            "index_version",
            sa.String(256),
            nullable=False,
            server_default="phase4-unindexed",
        ),
    )
    op.alter_column("chunks", "text", server_default=None)
    op.alter_column("chunks", "content_hash", server_default=None)
    op.alter_column("chunks", "index_version", server_default=None)
    op.create_check_constraint("ck_chunks_text_nonblank", "chunks", "length(btrim(text)) > 0")
    op.create_check_constraint("ck_chunks_token_count_positive", "chunks", "token_count > 0")
    op.create_check_constraint(
        "ck_chunks_content_hash_sha256",
        "chunks",
        "content_hash ~ '^[0-9a-f]{64}$'",
    )
    op.create_unique_constraint(
        "uq_chunks_version_type_index",
        "chunks",
        ["version_id", "chunk_type", "chunk_index"],
    )

    op.add_column(
        "ingestion_jobs",
        sa.Column("idempotency_key", sa.String(256), nullable=True),
    )
    # Existing installations may already have jobs. Their primary key is a safe,
    # stable replay key; new API writes use a content/config-derived key.
    op.execute("UPDATE ingestion_jobs SET idempotency_key = id::text WHERE idempotency_key IS NULL")
    op.alter_column("ingestion_jobs", "idempotency_key", nullable=False)
    op.create_unique_constraint(
        "uq_ingestion_jobs_idempotency_key",
        "ingestion_jobs",
        ["idempotency_key"],
    )
    op.create_check_constraint(
        "ck_ingestion_jobs_idempotency_key_nonblank",
        "ingestion_jobs",
        "length(btrim(idempotency_key)) > 0",
    )

    op.create_index(
        "uq_documents_tenant_content_active",
        "documents",
        ["tenant_id", "content_hash"],
        unique=True,
        postgresql_where=sa.text("deleted_at IS NULL"),
    )
    op.create_foreign_key(
        "fk_documents_current_version",
        "documents",
        "document_versions",
        ["current_version_id"],
        ["id"],
        ondelete="SET NULL",
        use_alter=True,
    )


def downgrade() -> None:
    """Remove only the Phase 4 completion additions."""

    op.drop_constraint("fk_documents_current_version", "documents", type_="foreignkey")
    op.drop_index("uq_documents_tenant_content_active", table_name="documents")

    op.drop_constraint(
        "ck_ingestion_jobs_idempotency_key_nonblank",
        "ingestion_jobs",
        type_="check",
    )
    op.drop_constraint(
        "uq_ingestion_jobs_idempotency_key",
        "ingestion_jobs",
        type_="unique",
    )
    op.drop_column("ingestion_jobs", "idempotency_key")

    op.drop_constraint("uq_chunks_version_type_index", "chunks", type_="unique")
    op.drop_constraint("ck_chunks_content_hash_sha256", "chunks", type_="check")
    op.drop_constraint("ck_chunks_token_count_positive", "chunks", type_="check")
    op.drop_constraint("ck_chunks_text_nonblank", "chunks", type_="check")
    op.drop_column("chunks", "index_version")
    op.drop_column("chunks", "content_hash")
    op.drop_column("chunks", "text")

    op.drop_column("document_versions", "index_version")
    op.drop_column("document_versions", "preview_artifact_path")
    op.drop_column("document_versions", "raw_artifact_path")

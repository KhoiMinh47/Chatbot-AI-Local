"""Persist ingestion coverage and parse-quality warnings.

Revision ID: 0011_document_parse_quality
Revises: 0010_conversation_memory
Create Date: 2026-07-17
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0011_document_parse_quality"
down_revision: str | None = "0010_conversation_memory"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "document_parse_reports",
        sa.Column(
            "version_id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
        ),
        sa.Column("document_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("quality_status", sa.String(length=16), nullable=False),
        sa.Column("expected_units", sa.Integer(), nullable=True),
        sa.Column("covered_units", sa.Integer(), nullable=True),
        sa.Column("coverage_ratio", sa.Float(), nullable=True),
        sa.Column("text_length", sa.BigInteger(), nullable=False),
        sa.Column("table_count", sa.Integer(), nullable=False),
        sa.Column("ocr_unit_count", sa.Integer(), nullable=False),
        sa.Column("empty_unit_count", sa.Integer(), nullable=False),
        sa.Column("duplicate_ratio", sa.Float(), nullable=False),
        sa.Column("encoding_error_count", sa.Integer(), nullable=False),
        sa.Column("warnings", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("report", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["version_id"],
            ["app.document_versions.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["document_id"],
            ["app.documents.id"],
            ondelete="CASCADE",
        ),
        sa.CheckConstraint(
            "quality_status IN ('ready','needs_review')",
            name="ck_document_parse_report_quality_status",
        ),
        sa.CheckConstraint(
            "coverage_ratio IS NULL OR (coverage_ratio >= 0 AND coverage_ratio <= 1)",
            name="ck_document_parse_report_coverage",
        ),
        sa.CheckConstraint(
            "duplicate_ratio >= 0 AND duplicate_ratio <= 1",
            name="ck_document_parse_report_duplicate_ratio",
        ),
        schema="app",
    )
    op.create_index(
        "ix_document_parse_reports_document_id",
        "document_parse_reports",
        ["document_id"],
        schema="app",
    )
    op.create_index(
        "ix_document_parse_reports_quality_status",
        "document_parse_reports",
        ["quality_status"],
        schema="app",
    )


def downgrade() -> None:
    """Retain parse evidence; older workers ignore this additive table."""

    return

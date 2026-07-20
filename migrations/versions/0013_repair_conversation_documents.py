"""Repair stamped databases missing the conversation-document state table.

Revision ID: 0013_conversation_documents
Revises: 0012_chunk_location_metadata
Create Date: 2026-07-17
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0013_conversation_documents"
down_revision: str | None = "0012_chunk_location_metadata"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if inspector.has_table("conversation_documents", schema="app"):
        return
    op.create_table(
        "conversation_documents",
        sa.Column("conversation_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("document_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["conversation_id"],
            ["app.conversations.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["document_id"],
            ["app.documents.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("conversation_id", "document_id"),
        schema="app",
    )
    op.create_index(
        "ix_conversation_documents_document_id",
        "conversation_documents",
        ["document_id"],
        schema="app",
    )


def downgrade() -> None:
    """Retain active-document state; dropping it would break follow-up references."""

    return

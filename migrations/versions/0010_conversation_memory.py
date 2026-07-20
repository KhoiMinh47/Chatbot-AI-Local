"""Add versioned summaries, semantic memory items, and conversation state.

Revision ID: 0010_conversation_memory
Revises: 0009_lexical_index
Create Date: 2026-07-17

The migration is additive. Rollback of the feature is configuration-only because a
destructive downgrade would discard user-authored memory and summary provenance.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0010_conversation_memory"
down_revision: str | None = "0009_lexical_index"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_SCHEMA = "app"


def upgrade() -> None:
    op.create_table(
        "conversation_summaries",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("conversation_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("summary_version", sa.Integer(), nullable=False),
        sa.Column(
            "covered_message_ids",
            postgresql.ARRAY(postgresql.UUID(as_uuid=True)),
            nullable=False,
        ),
        sa.Column("summary", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("summary_text", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["conversation_id"],
            [f"{_SCHEMA}.conversations.id"],
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint(
            "conversation_id",
            "summary_version",
            name="uq_conversation_summary_version",
        ),
        sa.CheckConstraint("summary_version > 0", name="ck_summary_version_positive"),
        sa.CheckConstraint("length(btrim(summary_text)) > 0", name="ck_summary_text_nonblank"),
        schema=_SCHEMA,
    )
    op.create_index(
        "ix_conversation_summaries_latest",
        "conversation_summaries",
        ["conversation_id", sa.text("summary_version DESC")],
        schema=_SCHEMA,
    )

    op.create_table(
        "conversation_state",
        sa.Column(
            "conversation_id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
        ),
        sa.Column(
            "active_document_ids",
            postgresql.ARRAY(postgresql.UUID(as_uuid=True)),
            nullable=False,
            server_default="{}",
        ),
        sa.Column("current_task", sa.Text(), nullable=True),
        sa.Column(
            "last_referenced_entities",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column(
            "response_depth", sa.String(length=16), nullable=False, server_default="detailed"
        ),
        sa.Column(
            "reasoning_policy", sa.String(length=16), nullable=False, server_default="adaptive"
        ),
        sa.Column("persistent_memory_enabled", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["conversation_id"],
            [f"{_SCHEMA}.conversations.id"],
            ondelete="CASCADE",
        ),
        sa.CheckConstraint(
            "response_depth IN ('concise','normal','detailed')",
            name="ck_conversation_state_response_depth",
        ),
        sa.CheckConstraint(
            "reasoning_policy IN ('adaptive','fast','reasoning')",
            name="ck_conversation_state_reasoning_policy",
        ),
        schema=_SCHEMA,
    )

    op.create_table(
        "memory_items",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("conversation_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("type", sa.String(length=32), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column(
            "source_message_ids",
            postgresql.ARRAY(postgresql.UUID(as_uuid=True)),
            nullable=False,
        ),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("embedding", postgresql.ARRAY(sa.REAL()), nullable=True),
        sa.Column("embedding_model", sa.String(length=256), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="active"),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], [f"{_SCHEMA}.users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["conversation_id"],
            [f"{_SCHEMA}.conversations.id"],
            ondelete="SET NULL",
        ),
        sa.CheckConstraint(
            "type IN ('preference','fact','decision','project_state','todo')",
            name="ck_memory_items_type",
        ),
        sa.CheckConstraint(
            "status IN ('active','superseded','deleted')",
            name="ck_memory_items_status",
        ),
        sa.CheckConstraint(
            "confidence >= 0.0 AND confidence <= 1.0",
            name="ck_memory_items_confidence",
        ),
        sa.CheckConstraint("length(btrim(content)) > 0", name="ck_memory_items_content_nonblank"),
        schema=_SCHEMA,
    )
    op.create_index(
        "ix_memory_items_user_status_updated",
        "memory_items",
        ["tenant_id", "user_id", "status", sa.text("updated_at DESC")],
        schema=_SCHEMA,
    )
    op.create_index(
        "ix_memory_items_content_fts",
        "memory_items",
        [sa.text("to_tsvector('simple', content)")],
        unique=False,
        schema=_SCHEMA,
        postgresql_using="gin",
    )


def downgrade() -> None:
    """Use APP_ENABLE_LONG_TERM_MEMORY=false; retain user memory for forward-fix."""

    return

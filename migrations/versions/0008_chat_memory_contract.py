"""Reconcile legacy and Phase 7 message schemas for durable chat memory.

Revision ID: 0008_chat_memory
Revises: 0007
Create Date: 2026-07-17

This migration is additive. Some local databases use the early ``content + metadata``
message table, while fresh source migrations contain the later hash/audit columns. Both
shapes are upgraded to one compatible superset without dropping message content.
"""

from __future__ import annotations

import hashlib
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0008_chat_memory"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_SCHEMA = "app"
_TABLE = "messages"


def _column_names(connection: sa.Connection) -> set[str]:
    inspector = sa.inspect(connection)
    return {column["name"] for column in inspector.get_columns(_TABLE, schema=_SCHEMA)}


def _foreign_key_names(connection: sa.Connection) -> set[str]:
    inspector = sa.inspect(connection)
    return {
        str(name)
        for constraint in inspector.get_foreign_keys(_TABLE, schema=_SCHEMA)
        if (name := constraint.get("name")) is not None
    }


def _check_names(connection: sa.Connection) -> set[str]:
    inspector = sa.inspect(connection)
    return {
        str(name)
        for constraint in inspector.get_check_constraints(_TABLE, schema=_SCHEMA)
        if (name := constraint.get("name")) is not None
    }


def upgrade() -> None:
    connection = op.get_bind()
    columns = _column_names(connection)

    if "content" not in columns:
        op.add_column(_TABLE, sa.Column("content", sa.Text(), nullable=True), schema=_SCHEMA)
    if "metadata" not in columns:
        op.add_column(
            _TABLE,
            sa.Column("metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
            schema=_SCHEMA,
        )
    if "user_id" not in columns:
        op.add_column(
            _TABLE,
            sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=True),
            schema=_SCHEMA,
        )
        connection.execute(
            sa.text(
                "UPDATE app.messages AS m SET user_id = c.user_id "
                "FROM app.conversations AS c "
                "WHERE m.conversation_id = c.id AND m.user_id IS NULL"
            )
        )
        remaining = connection.execute(
            sa.text("SELECT count(*) FROM app.messages WHERE user_id IS NULL")
        ).scalar_one()
        if remaining:
            raise RuntimeError("cannot bind legacy messages to an owning conversation user")
        op.alter_column(_TABLE, "user_id", nullable=False, schema=_SCHEMA)

    if "content_sha256" not in columns:
        op.add_column(
            _TABLE,
            sa.Column("content_sha256", sa.String(length=64), nullable=True),
            schema=_SCHEMA,
        )
        rows = connection.execute(
            sa.text("SELECT id, content FROM app.messages WHERE content_sha256 IS NULL")
        ).mappings()
        for row in rows:
            digest = hashlib.sha256((row["content"] or "").encode("utf-8")).hexdigest()
            connection.execute(
                sa.text("UPDATE app.messages SET content_sha256=:digest WHERE id=:message_id"),
                {"digest": digest, "message_id": row["id"]},
            )
        op.alter_column(_TABLE, "content_sha256", nullable=False, schema=_SCHEMA)

    if "generation_trace_id" not in columns:
        op.add_column(
            _TABLE,
            sa.Column("generation_trace_id", postgresql.UUID(as_uuid=True), nullable=True),
            schema=_SCHEMA,
        )

    foreign_keys = _foreign_key_names(connection)
    if "messages_user_id_fkey" not in foreign_keys:
        op.create_foreign_key(
            "messages_user_id_fkey",
            _TABLE,
            "users",
            ["user_id"],
            ["id"],
            source_schema=_SCHEMA,
            referent_schema=_SCHEMA,
            ondelete="CASCADE",
        )
    if "messages_generation_trace_id_fkey" not in foreign_keys:
        op.create_foreign_key(
            "messages_generation_trace_id_fkey",
            _TABLE,
            "rag_generation_traces",
            ["generation_trace_id"],
            ["request_id"],
            source_schema=_SCHEMA,
            referent_schema=_SCHEMA,
            ondelete="SET NULL",
        )

    checks = _check_names(connection)
    if "ck_messages_content_sha256" not in checks:
        op.create_check_constraint(
            "ck_messages_content_sha256",
            _TABLE,
            "content_sha256 ~ '^[0-9a-f]{64}$'",
            schema=_SCHEMA,
        )


def downgrade() -> None:
    """Forward-fix rollback: retain additive memory columns and their user data."""

    # Roll back the application with APP_ENABLE_NEW_MEMORY=false. A destructive schema
    # downgrade is intentionally avoided because it could delete conversation content.
    return

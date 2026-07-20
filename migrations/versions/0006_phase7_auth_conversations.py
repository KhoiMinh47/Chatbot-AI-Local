"""Phase 7 auth, RBAC, conversations and messages schema.

Revision ID: 0006_phase7
Revises: 0005_phase6_winner_binding
Create Date: 2026-07-15
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0006_phase7"
down_revision: str | None = "0005_phase6_winner_binding"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create auth, session, conversation and messaging tables."""

    # ------------------------------------------------------------------ users
    op.create_table(
        "users",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("email", sa.String(320), nullable=False, comment="Normalised lowercase e-mail"),
        sa.Column("password_hash", sa.String(256), nullable=False),
        sa.Column("display_name", sa.String(128), nullable=False),
        sa.Column(
            "role",
            sa.String(16),
            nullable=False,
            server_default="user",
            comment="user | admin",
        ),
        sa.Column("is_verified", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("role IN ('user', 'admin')", name="ck_users_role"),
        sa.CheckConstraint("length(btrim(email)) > 0", name="ck_users_email_nonblank"),
        sa.UniqueConstraint("tenant_id", "email", name="uq_users_tenant_email"),
        sa.Index("ix_users_tenant_id", "tenant_id"),
        sa.Index("ix_users_email", "email"),
    )

    # -------------------------------------------------------- refresh_sessions
    op.create_table(
        "refresh_sessions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "token_hash",
            sa.String(64),
            nullable=False,
            comment="SHA-256 of the opaque refresh token; never the token itself",
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("token_hash", name="uq_refresh_sessions_token_hash"),
        sa.CheckConstraint("token_hash ~ '^[0-9a-f]{64}$'", name="ck_refresh_sessions_token_hash"),
        sa.Index("ix_refresh_sessions_user_id", "user_id"),
        sa.Index("ix_refresh_sessions_token_hash", "token_hash"),
    )

    # ------------------------------------------------- email_verification_tokens
    op.create_table(
        "email_verification_tokens",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "token_hash",
            sa.String(64),
            nullable=False,
            comment="SHA-256 of the opaque one-time token",
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("token_hash", name="uq_email_verification_token_hash"),
        sa.CheckConstraint(
            "token_hash ~ '^[0-9a-f]{64}$'",
            name="ck_email_verification_token_hash",
        ),
        sa.Index("ix_email_verification_tokens_user_id", "user_id"),
    )

    # --------------------------------------------------- password_reset_tokens
    op.create_table(
        "password_reset_tokens",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "token_hash",
            sa.String(64),
            nullable=False,
            comment="SHA-256 of the opaque one-time token",
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("token_hash", name="uq_password_reset_token_hash"),
        sa.CheckConstraint("token_hash ~ '^[0-9a-f]{64}$'", name="ck_password_reset_token_hash"),
        sa.Index("ix_password_reset_tokens_user_id", "user_id"),
    )

    # ---------------------------------------------------------- conversations
    op.create_table(
        "conversations",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("title", sa.String(512), nullable=False),
        sa.Column("mode", sa.String(16), nullable=False, server_default="fast"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.CheckConstraint("mode IN ('fast', 'reasoning')", name="ck_conversations_mode"),
        sa.CheckConstraint("length(btrim(title)) > 0", name="ck_conversations_title_nonblank"),
        sa.Index("ix_conversations_user_id", "user_id"),
        sa.Index("ix_conversations_tenant_id", "tenant_id"),
        sa.Index("ix_conversations_updated_at", "updated_at"),
    )

    # ----------------------------------------------- conversation_documents
    op.create_table(
        "conversation_documents",
        sa.Column(
            "conversation_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column("document_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.ForeignKeyConstraint(["conversation_id"], ["conversations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("conversation_id", "document_id"),
    )

    # -------------------------------------------------------------- messages
    op.create_table(
        "messages",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("conversation_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "role",
            sa.String(16),
            nullable=False,
            comment="user | assistant",
        ),
        sa.Column(
            "content_sha256",
            sa.String(64),
            nullable=False,
            comment="SHA-256 of the message content; raw content is never stored",
        ),
        sa.Column(
            "generation_trace_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
            comment="FK to rag_generation_traces for assistant messages",
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["conversation_id"], ["conversations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["generation_trace_id"],
            ["rag_generation_traces.request_id"],
            ondelete="SET NULL",
        ),
        sa.CheckConstraint("role IN ('user', 'assistant')", name="ck_messages_role"),
        sa.CheckConstraint("content_sha256 ~ '^[0-9a-f]{64}$'", name="ck_messages_content_sha256"),
        sa.Index("ix_messages_conversation_id", "conversation_id"),
        sa.Index("ix_messages_created_at", "created_at"),
    )

    # --------------------------------------------------------------- feedback
    op.create_table(
        "feedback",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("message_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "rating",
            sa.String(16),
            nullable=False,
            comment="thumbs_up | thumbs_down",
        ),
        sa.Column("reason", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["message_id"], ["messages.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.CheckConstraint("rating IN ('thumbs_up', 'thumbs_down')", name="ck_feedback_rating"),
        sa.UniqueConstraint("message_id", "user_id", name="uq_feedback_message_user"),
        sa.Index("ix_feedback_message_id", "message_id"),
    )

    # ---------------------------------------------------------- audit_logs
    op.create_table(
        "audit_logs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("actor_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("action", sa.String(128), nullable=False),
        sa.Column(
            "target_type", sa.String(64), nullable=True, comment="user | document | conversation"
        ),
        sa.Column("target_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("request_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("length(btrim(action)) > 0", name="ck_audit_logs_action_nonblank"),
        sa.Index("ix_audit_logs_tenant_created", "tenant_id", "created_at"),
        sa.Index("ix_audit_logs_actor_id", "actor_id"),
    )


def downgrade() -> None:
    """Drop Phase 7 tables in reverse dependency order."""

    op.drop_table("audit_logs")
    op.drop_table("feedback")
    op.drop_table("messages")
    op.drop_table("conversation_documents")
    op.drop_table("conversations")
    op.drop_table("password_reset_tokens")
    op.drop_table("email_verification_tokens")
    op.drop_table("refresh_sessions")
    op.drop_table("users")

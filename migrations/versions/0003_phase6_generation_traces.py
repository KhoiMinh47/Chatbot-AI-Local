"""Phase 6 redacted generation trace schema.

Revision ID: 0003_phase6
Revises: 0002_phase4
Create Date: 2026-07-15
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0003_phase6"
down_revision: str | None = "0002_phase4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create an append-only, content-redacted trace table."""

    op.create_table(
        "rag_generation_traces",
        sa.Column("request_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("conversation_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("mode", sa.String(16), nullable=False),
        sa.Column("outcome", sa.String(32), nullable=False),
        sa.Column("prompt_version", sa.String(64), nullable=False),
        sa.Column("prompt_sha256", sa.String(64), nullable=False),
        sa.Column("graph_version", sa.String(64), nullable=False),
        sa.Column("question_sha256", sa.String(64), nullable=False),
        sa.Column("answer_sha256", sa.String(64), nullable=False),
        sa.Column("model", sa.String(256), nullable=True),
        sa.Column("model_version", sa.String(256), nullable=True),
        sa.Column("index_fingerprint", sa.String(64), nullable=False),
        sa.Column("rewritten_query_sha256", sa.String(64), nullable=False),
        sa.Column("subquery_count", sa.Integer, nullable=False),
        sa.Column("retrieval_rounds", sa.Integer, nullable=False),
        sa.Column("context_refs", postgresql.JSONB, nullable=False),
        sa.Column("citations", postgresql.JSONB, nullable=False),
        sa.Column("token_budget", postgresql.JSONB, nullable=True),
        sa.Column("input_tokens", sa.Integer, nullable=True),
        sa.Column("output_tokens", sa.Integer, nullable=True),
        sa.Column("node_path", postgresql.JSONB, nullable=False),
        sa.Column("timings_ms", postgresql.JSONB, nullable=False),
        sa.Column("error_codes", postgresql.JSONB, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("mode IN ('fast', 'reasoning')", name="ck_rag_trace_mode"),
        sa.CheckConstraint(
            "outcome IN ('answered', 'insufficient_evidence', 'invalid_generation', "
            "'error', 'cancelled')",
            name="ck_rag_trace_outcome",
        ),
        sa.CheckConstraint("subquery_count >= 0", name="ck_rag_trace_subquery_count"),
        sa.CheckConstraint("retrieval_rounds >= 0", name="ck_rag_trace_retrieval_rounds"),
        sa.Index("ix_rag_traces_tenant_created", "tenant_id", "created_at"),
        sa.Index("ix_rag_traces_conversation_created", "conversation_id", "created_at"),
    )


def downgrade() -> None:
    """Drop only the Phase 6 trace table."""

    op.drop_table("rag_generation_traces")

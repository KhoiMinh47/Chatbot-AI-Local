"""Bind every new Phase 6 trace to the activated retrieval policy.

Revision ID: 0005_phase6_winner_binding
Revises: 0004_phase4_completion
Create Date: 2026-07-15
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005_phase6_winner_binding"
down_revision: str | None = "0004_phase4_completion"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add a nullable column so historical unbound candidate traces stay truthful."""

    op.add_column(
        "rag_generation_traces",
        sa.Column("retrieval_policy_fingerprint", sa.String(64), nullable=True),
    )
    op.create_check_constraint(
        "ck_rag_trace_retrieval_policy_fingerprint",
        "rag_generation_traces",
        "retrieval_policy_fingerprint IS NULL OR retrieval_policy_fingerprint ~ '^[0-9a-f]{64}$'",
    )
    op.create_index(
        "ix_rag_traces_retrieval_policy",
        "rag_generation_traces",
        ["retrieval_policy_fingerprint"],
    )


def downgrade() -> None:
    """Remove only the winner-policy trace binding added by this revision."""

    op.drop_index("ix_rag_traces_retrieval_policy", table_name="rag_generation_traces")
    op.drop_constraint(
        "ck_rag_trace_retrieval_policy_fingerprint",
        "rag_generation_traces",
        type_="check",
    )
    op.drop_column("rag_generation_traces", "retrieval_policy_fingerprint")

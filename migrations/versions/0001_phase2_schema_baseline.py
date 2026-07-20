"""Establish the application schema boundary.

Revision ID: 0001_phase2
Revises:
Create Date: 2026-07-14
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0001_phase2"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create only the namespace; product tables belong to later phases."""

    op.execute("CREATE SCHEMA IF NOT EXISTS app")


def downgrade() -> None:
    """Drop the empty Phase 2 schema boundary."""

    op.execute("DROP SCHEMA IF EXISTS app")

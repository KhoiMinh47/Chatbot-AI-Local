"""Add spreadsheet and source-code provenance to chunks.

Revision ID: 0012_chunk_location_metadata
Revises: 0011_document_parse_quality
Create Date: 2026-07-17
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0012_chunk_location_metadata"
down_revision: str | None = "0011_document_parse_quality"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("chunks", sa.Column("sheet", sa.String(length=256), nullable=True))
    op.add_column("chunks", sa.Column("cell_range", sa.String(length=128), nullable=True))
    op.add_column("chunks", sa.Column("line_start", sa.Integer(), nullable=True))
    op.add_column("chunks", sa.Column("line_end", sa.Integer(), nullable=True))
    op.create_check_constraint(
        "ck_chunks_source_line_range",
        "chunks",
        "(line_start IS NULL AND line_end IS NULL) OR (line_start > 0 AND line_end >= line_start)",
    )


def downgrade() -> None:
    """Retain additive provenance; older readers safely ignore these columns."""

    return

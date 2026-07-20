"""Add the tenant-filtered chunk lexical-search index.

Revision ID: 0009_lexical_index
Revises: 0008_chat_memory
Create Date: 2026-07-17
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0009_lexical_index"
down_revision: str | None = "0008_chat_memory"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # ``simple`` keeps Vietnamese accents/tokens without applying an English stemmer.
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_chunks_text_search_simple "
        "ON app.chunks USING gin (to_tsvector('simple', text))"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS app.ix_chunks_text_search_simple")

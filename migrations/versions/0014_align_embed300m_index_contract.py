"""Align ready-document SQL metadata with the active Embed 300M/Qdrant contract.

Revision ID: 0014_align_embed300m_index
Revises: 0013_conversation_documents
Create Date: 2026-07-17
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0014_align_embed300m_index"
down_revision: str | None = "0013_conversation_documents"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_ACTIVE_INDEX = "embed300m-v2-1.13.0"
_LEGACY_INDEX = "embed300m-v2-phase4"
_EMBED_MODEL = "nvidia/llama-nemotron-embed-300m-v2"


def upgrade() -> None:
    # Only ready/current versions are changed. Deleted historical versions remain
    # auditable and are not eligible for retrieval.
    op.execute(
        f"""
        UPDATE app.document_versions AS v
           SET index_version = '{_ACTIVE_INDEX}'
         WHERE v.index_version = '{_LEGACY_INDEX}'
           AND v.id IN (
               SELECT d.current_version_id
                 FROM app.documents AS d
                WHERE d.state = 'ready' AND d.deleted_at IS NULL
           )
        """
    )
    op.execute(
        f"""
        UPDATE app.chunks AS c
           SET index_version = '{_ACTIVE_INDEX}',
               vector_id = CASE WHEN c.chunk_type = 'child' THEN c.id::text ELSE c.vector_id END,
               embedding_model = CASE
                   WHEN c.chunk_type = 'child' THEN '{_EMBED_MODEL}'
                   ELSE c.embedding_model
               END
         WHERE c.index_version = '{_LEGACY_INDEX}'
           AND c.version_id IN (
               SELECT d.current_version_id
                 FROM app.documents AS d
                WHERE d.state = 'ready' AND d.deleted_at IS NULL
           )
        """
    )


def downgrade() -> None:
    """Keep the repaired active contract; reverting would reintroduce split-brain metadata."""

    return

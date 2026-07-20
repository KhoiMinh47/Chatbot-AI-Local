"""Add content column to messages for conversation memory.

Revision ID: 0007
Revises: 0006_phase7_auth_conversations
Create Date: 2026-07-17
"""

import sqlalchemy as sa
from alembic import op

revision = "0007"
down_revision = "0006_phase7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add content column — nullable for backward-compatibility with existing rows
    # that only stored content_sha256.
    op.add_column("messages", sa.Column("content", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("messages", "content")

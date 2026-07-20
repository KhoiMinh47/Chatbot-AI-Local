"""Add template_path to session

Revision ID: afc869b3cc13
Revises: 
Create Date: 2026-03-13 08:30:27.130892

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'afc869b3cc13'
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.execute(
        "ALTER TABLE login_history ALTER COLUMN action SET NOT NULL"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_login_history_action ON login_history (action)"
    )
    op.execute(
        "ALTER TABLE session ADD COLUMN IF NOT EXISTS template_path VARCHAR"
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.execute("ALTER TABLE session DROP COLUMN IF EXISTS template_path")
    op.execute("DROP INDEX IF EXISTS ix_login_history_action")
    op.execute(
        "ALTER TABLE login_history ALTER COLUMN action DROP NOT NULL"
    )

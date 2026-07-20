"""Add semantic_history table for new history pipeline

Revision ID: 5bc9a8d21e10
Revises: 3f7f34da91b2
Create Date: 2026-04-21 10:45:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "5bc9a8d21e10"
down_revision: Union[str, Sequence[str], None] = "3f7f34da91b2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "semantic_history",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("session_id", sa.Integer(), nullable=False),
        sa.Column("turn_id", sa.Integer(), nullable=False),
        sa.Column("role", sa.String(), nullable=False),
        sa.Column("task_type", sa.String(), nullable=False),
        sa.Column("raw_text", sa.Text(), nullable=False),
        sa.Column("summary_text", sa.Text(), nullable=False),
        sa.Column("entity_keys", sa.JSON(), nullable=True),
        sa.Column("time_scope", sa.String(), nullable=True),
        sa.Column("is_negation", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("supersedes_turn_id", sa.Integer(), nullable=True),
        sa.Column("embedding", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["session_id"], ["session.id"]),
        sa.UniqueConstraint("user_id", "session_id", "turn_id", "role", "task_type", name="uq_semantic_history_turn_role_task"),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_index(op.f("ix_semantic_history_id"), "semantic_history", ["id"], unique=False)
    op.create_index(op.f("ix_semantic_history_user_id"), "semantic_history", ["user_id"], unique=False)
    op.create_index(op.f("ix_semantic_history_session_id"), "semantic_history", ["session_id"], unique=False)
    op.create_index(op.f("ix_semantic_history_turn_id"), "semantic_history", ["turn_id"], unique=False)
    op.create_index(op.f("ix_semantic_history_task_type"), "semantic_history", ["task_type"], unique=False)
    op.create_index(op.f("ix_semantic_history_created_at"), "semantic_history", ["created_at"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_semantic_history_created_at"), table_name="semantic_history")
    op.drop_index(op.f("ix_semantic_history_task_type"), table_name="semantic_history")
    op.drop_index(op.f("ix_semantic_history_turn_id"), table_name="semantic_history")
    op.drop_index(op.f("ix_semantic_history_session_id"), table_name="semantic_history")
    op.drop_index(op.f("ix_semantic_history_user_id"), table_name="semantic_history")
    op.drop_index(op.f("ix_semantic_history_id"), table_name="semantic_history")
    op.drop_table("semantic_history")

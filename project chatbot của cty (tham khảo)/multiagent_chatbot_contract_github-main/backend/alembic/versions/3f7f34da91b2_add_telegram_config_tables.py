"""Add telegram config tables

Revision ID: 3f7f34da91b2
Revises: afc869b3cc13
Create Date: 2026-03-30 09:10:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "3f7f34da91b2"
down_revision: Union[str, Sequence[str], None] = "afc869b3cc13"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "telegram_bot_config",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("bot_id", sa.String(), nullable=False),
        sa.Column("bot_token", sa.String(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("bot_id"),
    )
    op.create_index(op.f("ix_telegram_bot_config_id"), "telegram_bot_config", ["id"], unique=False)
    op.create_index(op.f("ix_telegram_bot_config_bot_id"), "telegram_bot_config", ["bot_id"], unique=False)

    op.create_table(
        "telegram_recipient_config",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("chat_id", sa.String(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("chat_id"),
    )
    op.create_index(op.f("ix_telegram_recipient_config_id"), "telegram_recipient_config", ["id"], unique=False)
    op.create_index(op.f("ix_telegram_recipient_config_chat_id"), "telegram_recipient_config", ["chat_id"], unique=False)

    op.execute(
        """
        INSERT INTO telegram_bot_config (bot_id, bot_token, is_active)
        VALUES ('8464047237', '8464047237:AAHry2y9VbnF0BdlthkwQPsDtKhF1pTGDy0', true)
        ON CONFLICT (bot_id) DO NOTHING
        """
    )
    op.execute(
        """
        INSERT INTO telegram_recipient_config (name, chat_id, is_active)
        VALUES ('hoài an', '1607805142', true)
        ON CONFLICT (chat_id) DO NOTHING
        """
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_telegram_recipient_config_chat_id"), table_name="telegram_recipient_config")
    op.drop_index(op.f("ix_telegram_recipient_config_id"), table_name="telegram_recipient_config")
    op.drop_table("telegram_recipient_config")

    op.drop_index(op.f("ix_telegram_bot_config_bot_id"), table_name="telegram_bot_config")
    op.drop_index(op.f("ix_telegram_bot_config_id"), table_name="telegram_bot_config")
    op.drop_table("telegram_bot_config")

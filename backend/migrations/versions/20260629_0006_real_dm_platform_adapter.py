"""add real dm platform adapter fields

Revision ID: 20260629_0006
Revises: 20260629_0005
Create Date: 2026-06-29 22:45:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260629_0006"
down_revision: Union[str, Sequence[str], None] = "20260629_0005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("merchant_leads", sa.Column("platform_url", sa.Text(), nullable=True))

    op.add_column(
        "dm_platform_configs",
        sa.Column("login_check_selector", sa.String(length=240), nullable=False, server_default=""),
    )
    op.add_column(
        "dm_platform_configs",
        sa.Column("risk_check_selector", sa.String(length=240), nullable=False, server_default=""),
    )
    op.add_column(
        "dm_platform_configs",
        sa.Column("merchant_link_selector", sa.String(length=240), nullable=False, server_default=""),
    )
    op.add_column(
        "dm_platform_configs",
        sa.Column("sent_success_selector", sa.String(length=240), nullable=False, server_default=""),
    )
    op.add_column(
        "dm_platform_configs",
        sa.Column("conversation_item_selector", sa.String(length=240), nullable=False, server_default=""),
    )
    op.add_column(
        "dm_platform_configs",
        sa.Column("conversation_title_selector", sa.String(length=240), nullable=False, server_default=""),
    )
    op.add_column(
        "dm_platform_configs",
        sa.Column("message_text_selector", sa.String(length=240), nullable=False, server_default=""),
    )


def downgrade() -> None:
    op.drop_column("dm_platform_configs", "message_text_selector")
    op.drop_column("dm_platform_configs", "conversation_title_selector")
    op.drop_column("dm_platform_configs", "conversation_item_selector")
    op.drop_column("dm_platform_configs", "sent_success_selector")
    op.drop_column("dm_platform_configs", "merchant_link_selector")
    op.drop_column("dm_platform_configs", "risk_check_selector")
    op.drop_column("dm_platform_configs", "login_check_selector")
    op.drop_column("merchant_leads", "platform_url")

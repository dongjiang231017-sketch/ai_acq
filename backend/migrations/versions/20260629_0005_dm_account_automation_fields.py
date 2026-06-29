"""add dm account automation fields

Revision ID: 20260629_0005
Revises: 20260629_0004
Create Date: 2026-06-29 21:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260629_0005"
down_revision: Union[str, Sequence[str], None] = "20260629_0004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("dm_accounts", sa.Column("browser_profile_key", sa.String(length=120), nullable=True))
    op.add_column("dm_accounts", sa.Column("browser_profile_path", sa.Text(), nullable=True))
    op.add_column("dm_accounts", sa.Column("session_status", sa.String(length=40), nullable=True))
    op.add_column("dm_accounts", sa.Column("risk_status", sa.String(length=40), nullable=True))
    op.add_column("dm_accounts", sa.Column("min_send_interval_seconds", sa.Integer(), nullable=True))
    op.add_column("dm_accounts", sa.Column("cooldown_until", sa.DateTime(), nullable=True))
    op.add_column("dm_accounts", sa.Column("last_sent_at", sa.DateTime(), nullable=True))
    op.add_column("dm_accounts", sa.Column("last_login_check_at", sa.DateTime(), nullable=True))
    op.add_column("dm_accounts", sa.Column("last_error", sa.Text(), nullable=True))
    op.create_index(op.f("ix_dm_accounts_session_status"), "dm_accounts", ["session_status"], unique=False)
    op.create_index(op.f("ix_dm_accounts_risk_status"), "dm_accounts", ["risk_status"], unique=False)

    op.create_table(
        "dm_platform_configs",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("platform", sa.String(length=40), nullable=False),
        sa.Column("home_url", sa.String(length=240), nullable=False),
        sa.Column("inbox_url", sa.String(length=240), nullable=False),
        sa.Column("merchant_search_url", sa.String(length=240), nullable=False),
        sa.Column("message_button_selector", sa.String(length=240), nullable=False),
        sa.Column("input_selector", sa.String(length=240), nullable=False),
        sa.Column("send_button_selector", sa.String(length=240), nullable=False),
        sa.Column("unread_selector", sa.String(length=240), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_dm_platform_configs_platform"), "dm_platform_configs", ["platform"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_dm_platform_configs_platform"), table_name="dm_platform_configs")
    op.drop_table("dm_platform_configs")

    op.drop_index(op.f("ix_dm_accounts_risk_status"), table_name="dm_accounts")
    op.drop_index(op.f("ix_dm_accounts_session_status"), table_name="dm_accounts")
    op.drop_column("dm_accounts", "last_error")
    op.drop_column("dm_accounts", "last_login_check_at")
    op.drop_column("dm_accounts", "last_sent_at")
    op.drop_column("dm_accounts", "cooldown_until")
    op.drop_column("dm_accounts", "min_send_interval_seconds")
    op.drop_column("dm_accounts", "risk_status")
    op.drop_column("dm_accounts", "session_status")
    op.drop_column("dm_accounts", "browser_profile_path")
    op.drop_column("dm_accounts", "browser_profile_key")

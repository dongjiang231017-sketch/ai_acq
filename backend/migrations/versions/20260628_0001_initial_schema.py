"""initial schema

Revision ID: 20260628_0001
Revises:
Create Date: 2026-06-28 20:20:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260628_0001"
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "merchant_leads",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("platform", sa.String(length=40), nullable=False),
        sa.Column("city", sa.String(length=40), nullable=False),
        sa.Column("category", sa.String(length=80), nullable=False),
        sa.Column("phone", sa.String(length=40), nullable=True),
        sa.Column("contact_name", sa.String(length=80), nullable=True),
        sa.Column("source", sa.String(length=80), nullable=False),
        sa.Column("intent_score", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=40), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_merchant_leads_category"), "merchant_leads", ["category"], unique=False)
    op.create_index(op.f("ix_merchant_leads_city"), "merchant_leads", ["city"], unique=False)
    op.create_index(op.f("ix_merchant_leads_name"), "merchant_leads", ["name"], unique=False)
    op.create_index(op.f("ix_merchant_leads_platform"), "merchant_leads", ["platform"], unique=False)

    op.create_table(
        "outreach_tasks",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("channel", sa.String(length=40), nullable=False),
        sa.Column("status", sa.String(length=40), nullable=False),
        sa.Column("target_count", sa.Integer(), nullable=False),
        sa.Column("scheduled_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_outreach_tasks_channel"), "outreach_tasks", ["channel"], unique=False)
    op.create_index(op.f("ix_outreach_tasks_name"), "outreach_tasks", ["name"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_outreach_tasks_name"), table_name="outreach_tasks")
    op.drop_index(op.f("ix_outreach_tasks_channel"), table_name="outreach_tasks")
    op.drop_table("outreach_tasks")

    op.drop_index(op.f("ix_merchant_leads_platform"), table_name="merchant_leads")
    op.drop_index(op.f("ix_merchant_leads_name"), table_name="merchant_leads")
    op.drop_index(op.f("ix_merchant_leads_city"), table_name="merchant_leads")
    op.drop_index(op.f("ix_merchant_leads_category"), table_name="merchant_leads")
    op.drop_table("merchant_leads")

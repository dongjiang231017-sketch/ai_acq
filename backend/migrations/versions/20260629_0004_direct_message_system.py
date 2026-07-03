"""add direct message system

Revision ID: 20260629_0004
Revises: 20260629_0003
Create Date: 2026-06-29 17:20:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260629_0004"
down_revision: Union[str, Sequence[str], None] = "20260629_0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("outreach_tasks", sa.Column("dm_account_id", sa.String(length=32), nullable=True))
    op.add_column("outreach_tasks", sa.Column("dm_template_id", sa.String(length=32), nullable=True))

    op.create_table(
        "dm_accounts",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("platform", sa.String(length=40), nullable=False),
        sa.Column("account_name", sa.String(length=120), nullable=False),
        sa.Column("login_label", sa.String(length=120), nullable=True),
        sa.Column("status", sa.String(length=40), nullable=False),
        sa.Column("daily_limit", sa.Integer(), nullable=False),
        sa.Column("sent_today", sa.Integer(), nullable=False),
        sa.Column("last_sync_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_dm_accounts_account_name"), "dm_accounts", ["account_name"], unique=False)
    op.create_index(op.f("ix_dm_accounts_platform"), "dm_accounts", ["platform"], unique=False)
    op.create_index(op.f("ix_dm_accounts_status"), "dm_accounts", ["status"], unique=False)

    op.create_table(
        "dm_templates",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("platform", sa.String(length=40), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_dm_templates_name"), "dm_templates", ["name"], unique=False)
    op.create_index(op.f("ix_dm_templates_platform"), "dm_templates", ["platform"], unique=False)

    op.create_table(
        "dm_conversations",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("task_id", sa.String(length=32), nullable=False),
        sa.Column("lead_id", sa.String(length=32), nullable=False),
        sa.Column("account_id", sa.String(length=32), nullable=True),
        sa.Column("platform", sa.String(length=40), nullable=False),
        sa.Column("merchant_name", sa.String(length=120), nullable=False),
        sa.Column("status", sa.String(length=40), nullable=False),
        sa.Column("intent_level", sa.String(length=20), nullable=False),
        sa.Column("last_message", sa.Text(), nullable=False),
        sa.Column("last_message_at", sa.DateTime(), nullable=True),
        sa.Column("need_handoff", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["account_id"], ["dm_accounts.id"]),
        sa.ForeignKeyConstraint(["lead_id"], ["merchant_leads.id"]),
        sa.ForeignKeyConstraint(["task_id"], ["outreach_tasks.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_dm_conversations_account_id"), "dm_conversations", ["account_id"], unique=False)
    op.create_index(op.f("ix_dm_conversations_intent_level"), "dm_conversations", ["intent_level"], unique=False)
    op.create_index(op.f("ix_dm_conversations_lead_id"), "dm_conversations", ["lead_id"], unique=False)
    op.create_index(op.f("ix_dm_conversations_merchant_name"), "dm_conversations", ["merchant_name"], unique=False)
    op.create_index(op.f("ix_dm_conversations_platform"), "dm_conversations", ["platform"], unique=False)
    op.create_index(op.f("ix_dm_conversations_status"), "dm_conversations", ["status"], unique=False)
    op.create_index(op.f("ix_dm_conversations_task_id"), "dm_conversations", ["task_id"], unique=False)

    op.create_table(
        "dm_messages",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("conversation_id", sa.String(length=32), nullable=False),
        sa.Column("direction", sa.String(length=20), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=40), nullable=False),
        sa.Column("external_message_id", sa.String(length=120), nullable=True),
        sa.Column("raw_payload", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["conversation_id"], ["dm_conversations.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_dm_messages_conversation_id"), "dm_messages", ["conversation_id"], unique=False)
    op.create_index(op.f("ix_dm_messages_direction"), "dm_messages", ["direction"], unique=False)
    op.create_index(op.f("ix_dm_messages_status"), "dm_messages", ["status"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_dm_messages_status"), table_name="dm_messages")
    op.drop_index(op.f("ix_dm_messages_direction"), table_name="dm_messages")
    op.drop_index(op.f("ix_dm_messages_conversation_id"), table_name="dm_messages")
    op.drop_table("dm_messages")

    op.drop_index(op.f("ix_dm_conversations_task_id"), table_name="dm_conversations")
    op.drop_index(op.f("ix_dm_conversations_status"), table_name="dm_conversations")
    op.drop_index(op.f("ix_dm_conversations_platform"), table_name="dm_conversations")
    op.drop_index(op.f("ix_dm_conversations_merchant_name"), table_name="dm_conversations")
    op.drop_index(op.f("ix_dm_conversations_lead_id"), table_name="dm_conversations")
    op.drop_index(op.f("ix_dm_conversations_intent_level"), table_name="dm_conversations")
    op.drop_index(op.f("ix_dm_conversations_account_id"), table_name="dm_conversations")
    op.drop_table("dm_conversations")

    op.drop_index(op.f("ix_dm_templates_platform"), table_name="dm_templates")
    op.drop_index(op.f("ix_dm_templates_name"), table_name="dm_templates")
    op.drop_table("dm_templates")

    op.drop_index(op.f("ix_dm_accounts_status"), table_name="dm_accounts")
    op.drop_index(op.f("ix_dm_accounts_platform"), table_name="dm_accounts")
    op.drop_index(op.f("ix_dm_accounts_account_name"), table_name="dm_accounts")
    op.drop_table("dm_accounts")

    op.drop_column("outreach_tasks", "dm_template_id")
    op.drop_column("outreach_tasks", "dm_account_id")

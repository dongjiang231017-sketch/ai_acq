"""add outbound system

Revision ID: 20260629_0002
Revises: 20260628_0001
Create Date: 2026-06-29 10:20:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260629_0002"
down_revision: Union[str, Sequence[str], None] = "20260628_0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "call_scripts",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("opening", sa.Text(), nullable=False),
        sa.Column("qualification", sa.Text(), nullable=False),
        sa.Column("objection", sa.Text(), nullable=False),
        sa.Column("closing", sa.Text(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_call_scripts_name"), "call_scripts", ["name"], unique=False)

    op.add_column("outreach_tasks", sa.Column("completed_count", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("outreach_tasks", sa.Column("connected_count", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("outreach_tasks", sa.Column("intent_count", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("outreach_tasks", sa.Column("failed_count", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("outreach_tasks", sa.Column("concurrency", sa.Integer(), nullable=False, server_default="1"))
    op.add_column("outreach_tasks", sa.Column("script_id", sa.String(length=32), nullable=True))
    op.add_column("outreach_tasks", sa.Column("target_lead_ids", sa.Text(), nullable=False, server_default=""))
    op.add_column("outreach_tasks", sa.Column("started_at", sa.DateTime(), nullable=True))
    op.add_column("outreach_tasks", sa.Column("finished_at", sa.DateTime(), nullable=True))

    op.create_table(
        "call_records",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("task_id", sa.String(length=32), nullable=False),
        sa.Column("lead_id", sa.String(length=32), nullable=False),
        sa.Column("merchant_name", sa.String(length=120), nullable=False),
        sa.Column("phone", sa.String(length=40), nullable=True),
        sa.Column("ai_seat", sa.String(length=40), nullable=False),
        sa.Column("duration_seconds", sa.Integer(), nullable=False),
        sa.Column("intent_level", sa.String(length=20), nullable=False),
        sa.Column("current_node", sa.String(length=80), nullable=False),
        sa.Column("outcome", sa.String(length=40), nullable=False),
        sa.Column("transcript", sa.Text(), nullable=False),
        sa.Column("need_handoff", sa.Boolean(), nullable=False),
        sa.Column("recall_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["lead_id"], ["merchant_leads.id"]),
        sa.ForeignKeyConstraint(["task_id"], ["outreach_tasks.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_call_records_intent_level"), "call_records", ["intent_level"], unique=False)
    op.create_index(op.f("ix_call_records_lead_id"), "call_records", ["lead_id"], unique=False)
    op.create_index(op.f("ix_call_records_merchant_name"), "call_records", ["merchant_name"], unique=False)
    op.create_index(op.f("ix_call_records_outcome"), "call_records", ["outcome"], unique=False)
    op.create_index(op.f("ix_call_records_task_id"), "call_records", ["task_id"], unique=False)

    op.create_table(
        "recall_rules",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("no_answer_interval_minutes", sa.Integer(), nullable=False),
        sa.Column("busy_interval_minutes", sa.Integer(), nullable=False),
        sa.Column("max_attempts", sa.Integer(), nullable=False),
        sa.Column("quiet_start", sa.String(length=8), nullable=False),
        sa.Column("quiet_end", sa.String(length=8), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_recall_rules_name"), "recall_rules", ["name"], unique=False)

def downgrade() -> None:
    op.drop_index(op.f("ix_recall_rules_name"), table_name="recall_rules")
    op.drop_table("recall_rules")

    op.drop_index(op.f("ix_call_records_task_id"), table_name="call_records")
    op.drop_index(op.f("ix_call_records_outcome"), table_name="call_records")
    op.drop_index(op.f("ix_call_records_merchant_name"), table_name="call_records")
    op.drop_index(op.f("ix_call_records_lead_id"), table_name="call_records")
    op.drop_index(op.f("ix_call_records_intent_level"), table_name="call_records")
    op.drop_table("call_records")

    op.drop_column("outreach_tasks", "finished_at")
    op.drop_column("outreach_tasks", "started_at")
    op.drop_column("outreach_tasks", "target_lead_ids")
    op.drop_column("outreach_tasks", "script_id")
    op.drop_column("outreach_tasks", "concurrency")
    op.drop_column("outreach_tasks", "failed_count")
    op.drop_column("outreach_tasks", "intent_count")
    op.drop_column("outreach_tasks", "connected_count")
    op.drop_column("outreach_tasks", "completed_count")

    op.drop_index(op.f("ix_call_scripts_name"), table_name="call_scripts")
    op.drop_table("call_scripts")

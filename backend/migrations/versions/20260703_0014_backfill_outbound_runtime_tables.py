"""backfill outbound runtime tables

Revision ID: 20260703_0014
Revises: 20260703_0013
Create Date: 2026-07-03 16:28:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

from typing import Sequence, Union

revision: str = "20260703_0014"
down_revision: Union[str, Sequence[str], None] = "20260703_0013"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)

    outreach_columns = {column["name"] for column in inspector.get_columns("outreach_tasks")}
    outreach_additions = [
        ("completed_count", sa.Column("completed_count", sa.Integer(), nullable=False, server_default="0")),
        ("connected_count", sa.Column("connected_count", sa.Integer(), nullable=False, server_default="0")),
        ("intent_count", sa.Column("intent_count", sa.Integer(), nullable=False, server_default="0")),
        ("failed_count", sa.Column("failed_count", sa.Integer(), nullable=False, server_default="0")),
        ("concurrency", sa.Column("concurrency", sa.Integer(), nullable=False, server_default="1")),
        ("script_id", sa.Column("script_id", sa.String(length=32), nullable=True)),
        ("dm_account_id", sa.Column("dm_account_id", sa.String(length=32), nullable=True)),
        ("dm_template_id", sa.Column("dm_template_id", sa.String(length=32), nullable=True)),
        ("target_lead_ids", sa.Column("target_lead_ids", sa.Text(), nullable=False, server_default="")),
        ("started_at", sa.Column("started_at", sa.DateTime(), nullable=True)),
        ("finished_at", sa.Column("finished_at", sa.DateTime(), nullable=True)),
    ]
    with op.batch_alter_table("outreach_tasks") as batch_op:
        for name, column in outreach_additions:
            if name not in outreach_columns:
                batch_op.add_column(column)

    if not inspector.has_table("call_scripts"):
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
    existing_call_script_indexes = {index["name"] for index in inspector.get_indexes("call_scripts")} if inspector.has_table("call_scripts") else set()
    if "ix_call_scripts_name" not in existing_call_script_indexes:
        op.create_index("ix_call_scripts_name", "call_scripts", ["name"], unique=False)

    if not inspector.has_table("call_records"):
        op.create_table(
            "call_records",
            sa.Column("id", sa.String(length=32), nullable=False),
            sa.Column("task_id", sa.String(length=32), nullable=False),
            sa.Column("lead_id", sa.String(length=32), nullable=False),
            sa.Column("merchant_name", sa.String(length=120), nullable=False),
            sa.Column("phone", sa.String(length=40), nullable=True),
            sa.Column("ai_seat", sa.String(length=40), nullable=False),
            sa.Column("duration_seconds", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("intent_level", sa.String(length=20), nullable=False, server_default="C"),
            sa.Column("current_node", sa.String(length=80), nullable=False, server_default="开场白"),
            sa.Column("outcome", sa.String(length=40), nullable=False, server_default="未接通"),
            sa.Column("transcript", sa.Text(), nullable=False, server_default=""),
            sa.Column("gateway_call_id", sa.String(length=120), nullable=True),
            sa.Column("gateway_status", sa.String(length=40), nullable=False, server_default="completed"),
            sa.Column("raw_payload", sa.Text(), nullable=True),
            sa.Column("need_handoff", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("recall_at", sa.DateTime(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["lead_id"], ["merchant_leads.id"]),
            sa.ForeignKeyConstraint(["task_id"], ["outreach_tasks.id"]),
            sa.PrimaryKeyConstraint("id"),
        )
    else:
        call_record_columns = {column["name"] for column in inspector.get_columns("call_records")}
        call_record_additions = [
            ("gateway_call_id", sa.Column("gateway_call_id", sa.String(length=120), nullable=True)),
            ("gateway_status", sa.Column("gateway_status", sa.String(length=40), nullable=False, server_default="completed")),
            ("raw_payload", sa.Column("raw_payload", sa.Text(), nullable=True)),
        ]
        with op.batch_alter_table("call_records") as batch_op:
            for name, column in call_record_additions:
                if name not in call_record_columns:
                    batch_op.add_column(column)
    existing_call_record_indexes = {index["name"] for index in inspector.get_indexes("call_records")} if inspector.has_table("call_records") else set()
    for index_name, columns in [
        ("ix_call_records_intent_level", ["intent_level"]),
        ("ix_call_records_lead_id", ["lead_id"]),
        ("ix_call_records_merchant_name", ["merchant_name"]),
        ("ix_call_records_outcome", ["outcome"]),
        ("ix_call_records_task_id", ["task_id"]),
        ("ix_call_records_gateway_status", ["gateway_status"]),
    ]:
        if index_name not in existing_call_record_indexes:
            op.create_index(index_name, "call_records", columns, unique=False)

    if not inspector.has_table("recall_rules"):
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
    existing_recall_indexes = {index["name"] for index in inspector.get_indexes("recall_rules")} if inspector.has_table("recall_rules") else set()
    if "ix_recall_rules_name" not in existing_recall_indexes:
        op.create_index("ix_recall_rules_name", "recall_rules", ["name"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_recall_rules_name", table_name="recall_rules")
    op.drop_table("recall_rules")

    op.drop_index("ix_call_records_gateway_status", table_name="call_records")
    op.drop_index("ix_call_records_task_id", table_name="call_records")
    op.drop_index("ix_call_records_outcome", table_name="call_records")
    op.drop_index("ix_call_records_merchant_name", table_name="call_records")
    op.drop_index("ix_call_records_lead_id", table_name="call_records")
    op.drop_index("ix_call_records_intent_level", table_name="call_records")
    op.drop_table("call_records")

    op.drop_index("ix_call_scripts_name", table_name="call_scripts")
    op.drop_table("call_scripts")

    with op.batch_alter_table("outreach_tasks") as batch_op:
        for name in [
            "finished_at",
            "started_at",
            "target_lead_ids",
            "dm_template_id",
            "dm_account_id",
            "script_id",
            "concurrency",
            "failed_count",
            "intent_count",
            "connected_count",
            "completed_count",
        ]:
            batch_op.drop_column(name)

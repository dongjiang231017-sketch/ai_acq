"""add reports and system settings

Revision ID: 20260629_0008
Revises: 20260629_0007
Create Date: 2026-06-29 23:55:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260629_0008"
down_revision: Union[str, Sequence[str], None] = "20260629_0007"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "report_exports",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("report_type", sa.String(length=80), nullable=False),
        sa.Column("date_range", sa.String(length=80), nullable=False),
        sa.Column("file_format", sa.String(length=20), nullable=False),
        sa.Column("requester", sa.String(length=80), nullable=False),
        sa.Column("status", sa.String(length=40), nullable=False),
        sa.Column("download_url", sa.String(length=240), nullable=False),
        sa.Column("row_count", sa.Integer(), nullable=False),
        sa.Column("sensitive_fields_included", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("finished_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_report_exports_report_type"), "report_exports", ["report_type"], unique=False)
    op.create_index(op.f("ix_report_exports_requester"), "report_exports", ["requester"], unique=False)
    op.create_index(op.f("ix_report_exports_status"), "report_exports", ["status"], unique=False)

    op.create_table(
        "system_settings",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("group_key", sa.String(length=40), nullable=False),
        sa.Column("item_key", sa.String(length=80), nullable=False),
        sa.Column("label", sa.String(length=120), nullable=False),
        sa.Column("value", sa.Text(), nullable=False),
        sa.Column("value_type", sa.String(length=80), nullable=False),
        sa.Column("status", sa.String(length=40), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("sensitive", sa.Boolean(), nullable=False),
        sa.Column("updated_by", sa.String(length=80), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("group_key", "item_key", name="uq_system_settings_group_item"),
    )
    op.create_index(op.f("ix_system_settings_group_key"), "system_settings", ["group_key"], unique=False)
    op.create_index(op.f("ix_system_settings_item_key"), "system_settings", ["item_key"], unique=False)
    op.create_index(op.f("ix_system_settings_label"), "system_settings", ["label"], unique=False)
    op.create_index(op.f("ix_system_settings_sensitive"), "system_settings", ["sensitive"], unique=False)
    op.create_index(op.f("ix_system_settings_status"), "system_settings", ["status"], unique=False)

    op.create_table(
        "system_audit_logs",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("actor", sa.String(length=80), nullable=False),
        sa.Column("action", sa.String(length=80), nullable=False),
        sa.Column("target_type", sa.String(length=80), nullable=False),
        sa.Column("target_id", sa.String(length=32), nullable=True),
        sa.Column("summary", sa.String(length=240), nullable=False),
        sa.Column("before_value", sa.Text(), nullable=True),
        sa.Column("after_value", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_system_audit_logs_action"), "system_audit_logs", ["action"], unique=False)
    op.create_index(op.f("ix_system_audit_logs_actor"), "system_audit_logs", ["actor"], unique=False)
    op.create_index(op.f("ix_system_audit_logs_target_id"), "system_audit_logs", ["target_id"], unique=False)
    op.create_index(op.f("ix_system_audit_logs_target_type"), "system_audit_logs", ["target_type"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_system_audit_logs_target_type"), table_name="system_audit_logs")
    op.drop_index(op.f("ix_system_audit_logs_target_id"), table_name="system_audit_logs")
    op.drop_index(op.f("ix_system_audit_logs_actor"), table_name="system_audit_logs")
    op.drop_index(op.f("ix_system_audit_logs_action"), table_name="system_audit_logs")
    op.drop_table("system_audit_logs")

    op.drop_index(op.f("ix_system_settings_status"), table_name="system_settings")
    op.drop_index(op.f("ix_system_settings_sensitive"), table_name="system_settings")
    op.drop_index(op.f("ix_system_settings_label"), table_name="system_settings")
    op.drop_index(op.f("ix_system_settings_item_key"), table_name="system_settings")
    op.drop_index(op.f("ix_system_settings_group_key"), table_name="system_settings")
    op.drop_table("system_settings")

    op.drop_index(op.f("ix_report_exports_status"), table_name="report_exports")
    op.drop_index(op.f("ix_report_exports_requester"), table_name="report_exports")
    op.drop_index(op.f("ix_report_exports_report_type"), table_name="report_exports")
    op.drop_table("report_exports")

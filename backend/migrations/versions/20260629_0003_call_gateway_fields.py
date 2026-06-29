"""add call gateway fields

Revision ID: 20260629_0003
Revises: 20260629_0002
Create Date: 2026-06-29 16:20:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260629_0003"
down_revision: Union[str, Sequence[str], None] = "20260629_0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("call_records", sa.Column("gateway_call_id", sa.String(length=120), nullable=True))
    op.add_column("call_records", sa.Column("gateway_status", sa.String(length=40), nullable=False, server_default="completed"))
    op.add_column("call_records", sa.Column("raw_payload", sa.Text(), nullable=True))
    op.create_index(op.f("ix_call_records_gateway_status"), "call_records", ["gateway_status"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_call_records_gateway_status"), table_name="call_records")
    op.drop_column("call_records", "raw_payload")
    op.drop_column("call_records", "gateway_status")
    op.drop_column("call_records", "gateway_call_id")

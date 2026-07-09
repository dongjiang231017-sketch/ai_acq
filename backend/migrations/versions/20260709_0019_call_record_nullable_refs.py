"""call_records.task_id/lead_id 可空：LiveKit 单号试拨无任务上下文也要落库

Revision ID: 20260709_0019
Revises: 0ea9dfe9e60d
Create Date: 2026-07-09
"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "20260709_0019"
down_revision: Union[str, Sequence[str], None] = "0ea9dfe9e60d"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column("call_records", "task_id", existing_type=sa.String(length=32), nullable=True)
    op.alter_column("call_records", "lead_id", existing_type=sa.String(length=32), nullable=True)


def downgrade() -> None:
    op.alter_column("call_records", "lead_id", existing_type=sa.String(length=32), nullable=False)
    op.alter_column("call_records", "task_id", existing_type=sa.String(length=32), nullable=False)

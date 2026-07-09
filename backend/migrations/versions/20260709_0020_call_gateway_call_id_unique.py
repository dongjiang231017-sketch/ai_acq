"""call_records.gateway_call_id 部分唯一索引：保证落库幂等 + 消除全表顺扫

Revision ID: 20260709_0020
Revises: 20260709_0019
Create Date: 2026-07-09

子代理审计 bug B：gateway_call_id 无唯一约束→跨进程重派时 SELECT-then-INSERT
幂等失效双写；无索引→批量 runner 每 3-5s 全表顺扫 COUNT(gateway_call_id IN ...)。
部分唯一索引（仅非空）同时解决两者：唯一保幂等、索引消顺扫。
"""

from typing import Sequence, Union

from alembic import op

revision: str = "20260709_0020"
down_revision: Union[str, Sequence[str], None] = "20260709_0019"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_call_records_gateway_call_id "
        "ON call_records (gateway_call_id) WHERE gateway_call_id IS NOT NULL"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS uq_call_records_gateway_call_id")

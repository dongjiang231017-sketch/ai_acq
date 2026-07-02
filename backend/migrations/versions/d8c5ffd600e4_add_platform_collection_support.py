"""add platform collection support

Revision ID: d8c5ffd600e4
Revises: 56f3c625e544
Create Date: 2026-06-29 21:41:16.740976

"""
from datetime import datetime
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd8c5ffd600e4'
down_revision: Union[str, Sequence[str], None] = '56f3c625e544'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('raw_lead_records', sa.Column('source_url', sa.String(length=500), nullable=True))
    provider_configs = sa.table(
        "lead_provider_configs",
        sa.column("id", sa.String),
        sa.column("provider", sa.String),
        sa.column("name", sa.String),
        sa.column("api_key", sa.String),
        sa.column("secret_key", sa.String),
        sa.column("service_url", sa.String),
        sa.column("enabled", sa.Boolean),
        sa.column("daily_limit", sa.Integer),
        sa.column("qps_limit", sa.Integer),
        sa.column("remark", sa.Text),
        sa.column("created_at", sa.DateTime),
        sa.column("updated_at", sa.DateTime),
    )
    now = datetime.utcnow()
    op.bulk_insert(
        provider_configs,
        [
            {
                "id": "provider_meituan",
                "provider": "meituan",
                "name": "美团团购",
                "api_key": None,
                "secret_key": None,
                "service_url": "https://www.sogou.com/web",
                "enabled": True,
                "daily_limit": None,
                "qps_limit": None,
                "remark": "第一版使用公开搜索结果发现平台页面，再尝试补电话入库。",
                "created_at": now,
                "updated_at": now,
            },
            {
                "id": "provider_shangou",
                "provider": "shangou",
                "name": "美团闪购",
                "api_key": None,
                "secret_key": None,
                "service_url": "https://www.sogou.com/web",
                "enabled": True,
                "daily_limit": None,
                "qps_limit": None,
                "remark": "第一版使用公开搜索结果发现平台页面，再尝试补电话入库。",
                "created_at": now,
                "updated_at": now,
            },
            {
                "id": "provider_douyin",
                "provider": "douyin",
                "name": "抖音生活服务",
                "api_key": None,
                "secret_key": None,
                "service_url": "https://www.sogou.com/web",
                "enabled": True,
                "daily_limit": None,
                "qps_limit": None,
                "remark": "第一版使用公开搜索结果发现平台页面，再尝试补电话入库。",
                "created_at": now,
                "updated_at": now,
            },
        ],
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.execute(
        sa.text(
            """
            DELETE FROM lead_provider_configs
            WHERE provider IN ('meituan', 'shangou', 'douyin')
            """
        ),
    )
    op.drop_column('raw_lead_records', 'source_url')

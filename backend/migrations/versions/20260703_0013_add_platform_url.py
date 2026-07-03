"""add merchant lead platform url

Revision ID: 20260703_0013
Revises: 20260702_0012
Create Date: 2026-07-03 15:48:00.000000

"""

from typing import Sequence, Union

from alembic import op


revision: str = "20260703_0013"
down_revision: Union[str, Sequence[str], None] = "20260702_0012"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TABLE merchant_leads ADD COLUMN IF NOT EXISTS platform_url TEXT")


def downgrade() -> None:
    op.execute("ALTER TABLE merchant_leads DROP COLUMN IF EXISTS platform_url")

"""add structured entries and audio mapping to call scripts

Revision ID: 20260710_0021
Revises: 20260709_0020
Create Date: 2026-07-10
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "20260710_0021"
down_revision: Union[str, Sequence[str], None] = "20260709_0020"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "call_scripts",
        sa.Column("entries", sa.JSON(), server_default=sa.text("'[]'"), nullable=False),
    )
    op.add_column(
        "call_scripts",
        sa.Column("audio_mapping", sa.JSON(), server_default=sa.text("'{}'"), nullable=False),
    )


def downgrade() -> None:
    op.drop_column("call_scripts", "audio_mapping")
    op.drop_column("call_scripts", "entries")

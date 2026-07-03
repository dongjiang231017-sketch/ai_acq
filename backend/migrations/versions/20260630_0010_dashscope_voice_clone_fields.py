"""add dashscope voice clone fields

Revision ID: 20260630_0010
Revises: 20260629_0009
Create Date: 2026-06-30 11:20:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260630_0010"
down_revision: Union[str, Sequence[str], None] = "20260629_0009"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "voice_clone_records",
        sa.Column("external_voice_id", sa.String(length=160), nullable=False, server_default=""),
    )
    op.add_column(
        "voice_clone_records",
        sa.Column("preview_audio_path", sa.Text(), nullable=False, server_default=""),
    )


def downgrade() -> None:
    op.drop_column("voice_clone_records", "preview_audio_path")
    op.drop_column("voice_clone_records", "external_voice_id")

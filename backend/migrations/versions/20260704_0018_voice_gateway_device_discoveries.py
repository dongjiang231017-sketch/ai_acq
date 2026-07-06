"""add voice gateway device discoveries

Revision ID: 20260704_0018
Revises: 20260704_0017
Create Date: 2026-07-04 11:35:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260704_0018"
down_revision: Union[str, Sequence[str], None] = "20260704_0017"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "voice_gateway_device_discoveries",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("owner_user_id", sa.String(length=32), nullable=False),
        sa.Column("reporter_user_id", sa.String(length=32), nullable=True),
        sa.Column("matched_line_id", sa.String(length=32), nullable=True),
        sa.Column("status", sa.String(length=40), nullable=False),
        sa.Column("source", sa.String(length=80), nullable=False),
        sa.Column("gateway_profile_key", sa.String(length=80), nullable=False),
        sa.Column("gateway_label", sa.String(length=160), nullable=False),
        sa.Column("device_admin_url", sa.String(length=240), nullable=False),
        sa.Column("device_ip", sa.String(length=80), nullable=False),
        sa.Column("device_mac", sa.String(length=80), nullable=False),
        sa.Column("device_serial", sa.String(length=120), nullable=False),
        sa.Column("sip_port", sa.Integer(), nullable=False),
        sa.Column("summary", sa.String(length=240), nullable=False),
        sa.Column("detail", sa.Text(), nullable=False),
        sa.Column("evidence_json", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["matched_line_id"], ["voice_gateway_lines.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["owner_user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["reporter_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_voice_gateway_device_discoveries_created_at", "voice_gateway_device_discoveries", ["created_at"])
    op.create_index("ix_voice_gateway_device_discoveries_device_admin_url", "voice_gateway_device_discoveries", ["device_admin_url"])
    op.create_index("ix_voice_gateway_device_discoveries_device_ip", "voice_gateway_device_discoveries", ["device_ip"])
    op.create_index("ix_voice_gateway_device_discoveries_device_mac", "voice_gateway_device_discoveries", ["device_mac"])
    op.create_index("ix_voice_gateway_device_discoveries_device_serial", "voice_gateway_device_discoveries", ["device_serial"])
    op.create_index("ix_voice_gateway_device_discoveries_matched_line_id", "voice_gateway_device_discoveries", ["matched_line_id"])
    op.create_index("ix_voice_gateway_device_discoveries_owner_user_id", "voice_gateway_device_discoveries", ["owner_user_id"])
    op.create_index("ix_voice_gateway_device_discoveries_reporter_user_id", "voice_gateway_device_discoveries", ["reporter_user_id"])
    op.create_index("ix_voice_gateway_device_discoveries_source", "voice_gateway_device_discoveries", ["source"])
    op.create_index("ix_voice_gateway_device_discoveries_status", "voice_gateway_device_discoveries", ["status"])


def downgrade() -> None:
    op.drop_index("ix_voice_gateway_device_discoveries_status", table_name="voice_gateway_device_discoveries")
    op.drop_index("ix_voice_gateway_device_discoveries_source", table_name="voice_gateway_device_discoveries")
    op.drop_index("ix_voice_gateway_device_discoveries_reporter_user_id", table_name="voice_gateway_device_discoveries")
    op.drop_index("ix_voice_gateway_device_discoveries_owner_user_id", table_name="voice_gateway_device_discoveries")
    op.drop_index("ix_voice_gateway_device_discoveries_matched_line_id", table_name="voice_gateway_device_discoveries")
    op.drop_index("ix_voice_gateway_device_discoveries_device_serial", table_name="voice_gateway_device_discoveries")
    op.drop_index("ix_voice_gateway_device_discoveries_device_mac", table_name="voice_gateway_device_discoveries")
    op.drop_index("ix_voice_gateway_device_discoveries_device_ip", table_name="voice_gateway_device_discoveries")
    op.drop_index("ix_voice_gateway_device_discoveries_device_admin_url", table_name="voice_gateway_device_discoveries")
    op.drop_index("ix_voice_gateway_device_discoveries_created_at", table_name="voice_gateway_device_discoveries")
    op.drop_table("voice_gateway_device_discoveries")

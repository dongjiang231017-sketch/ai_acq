"""add per-customer voice gateway delivery lines

Revision ID: 20260703_0013
Revises: 20260702_0012
Create Date: 2026-07-03 18:30:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260703_0013"
down_revision: Union[str, Sequence[str], None] = "20260702_0012"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "voice_gateway_lines",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("owner_user_id", sa.String(length=32), nullable=False),
        sa.Column("created_by_user_id", sa.String(length=32), nullable=True),
        sa.Column("line_name", sa.String(length=120), nullable=False),
        sa.Column("customer_name", sa.String(length=160), nullable=False),
        sa.Column("status", sa.String(length=40), nullable=False),
        sa.Column("gateway_profile_key", sa.String(length=80), nullable=False),
        sa.Column("gateway_label", sa.String(length=160), nullable=False),
        sa.Column("gateway_vendor", sa.String(length=120), nullable=False),
        sa.Column("gateway_model", sa.String(length=120), nullable=False),
        sa.Column("gateway_category", sa.String(length=80), nullable=False),
        sa.Column("deployment_mode", sa.String(length=40), nullable=False),
        sa.Column("sip_server_host", sa.String(length=120), nullable=False),
        sa.Column("sip_server_port", sa.Integer(), nullable=False),
        sa.Column("sip_transport", sa.String(length=20), nullable=False),
        sa.Column("sip_username", sa.String(length=120), nullable=False),
        sa.Column("sip_auth_username", sa.String(length=120), nullable=False),
        sa.Column("sip_password_hash", sa.String(length=255), nullable=False),
        sa.Column("sip_password_secret_alias", sa.String(length=180), nullable=False),
        sa.Column("trunk_name", sa.String(length=120), nullable=False),
        sa.Column("channel_count", sa.Integer(), nullable=False),
        sa.Column("codec_primary", sa.String(length=40), nullable=False),
        sa.Column("codec_secondary", sa.String(length=40), nullable=False),
        sa.Column("dtmf_mode", sa.String(length=40), nullable=False),
        sa.Column("rtp_port_range", sa.String(length=40), nullable=False),
        sa.Column("route_direction", sa.String(length=120), nullable=False),
        sa.Column("device_admin_url", sa.String(length=240), nullable=False),
        sa.Column("device_serial", sa.String(length=120), nullable=False),
        sa.Column("device_mac", sa.String(length=80), nullable=False),
        sa.Column("network_note", sa.Text(), nullable=False),
        sa.Column("registration_status", sa.String(length=40), nullable=False),
        sa.Column("route_status", sa.String(length=40), nullable=False),
        sa.Column("sim_status", sa.String(length=40), nullable=False),
        sa.Column("rtp_status", sa.String(length=40), nullable=False),
        sa.Column("acceptance_status", sa.String(length=40), nullable=False),
        sa.Column("last_registered_at", sa.DateTime(), nullable=True),
        sa.Column("last_preflight_at", sa.DateTime(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["owner_user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("owner_user_id", "line_name", name="uq_voice_gateway_lines_owner_name"),
        sa.UniqueConstraint("sip_username", name="uq_voice_gateway_lines_sip_username"),
        sa.UniqueConstraint("trunk_name", name="uq_voice_gateway_lines_trunk_name"),
    )
    op.create_index("ix_voice_gateway_lines_acceptance_status", "voice_gateway_lines", ["acceptance_status"])
    op.create_index("ix_voice_gateway_lines_created_by_user_id", "voice_gateway_lines", ["created_by_user_id"])
    op.create_index("ix_voice_gateway_lines_customer_name", "voice_gateway_lines", ["customer_name"])
    op.create_index("ix_voice_gateway_lines_deployment_mode", "voice_gateway_lines", ["deployment_mode"])
    op.create_index("ix_voice_gateway_lines_gateway_profile_key", "voice_gateway_lines", ["gateway_profile_key"])
    op.create_index("ix_voice_gateway_lines_line_name", "voice_gateway_lines", ["line_name"])
    op.create_index("ix_voice_gateway_lines_owner_user_id", "voice_gateway_lines", ["owner_user_id"])
    op.create_index("ix_voice_gateway_lines_registration_status", "voice_gateway_lines", ["registration_status"])
    op.create_index("ix_voice_gateway_lines_route_status", "voice_gateway_lines", ["route_status"])
    op.create_index("ix_voice_gateway_lines_rtp_status", "voice_gateway_lines", ["rtp_status"])
    op.create_index("ix_voice_gateway_lines_sim_status", "voice_gateway_lines", ["sim_status"])
    op.create_index("ix_voice_gateway_lines_sip_auth_username", "voice_gateway_lines", ["sip_auth_username"])
    op.create_index("ix_voice_gateway_lines_sip_username", "voice_gateway_lines", ["sip_username"])
    op.create_index("ix_voice_gateway_lines_status", "voice_gateway_lines", ["status"])
    op.create_index("ix_voice_gateway_lines_trunk_name", "voice_gateway_lines", ["trunk_name"])

    op.create_table(
        "voice_gateway_line_events",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("line_id", sa.String(length=32), nullable=False),
        sa.Column("owner_user_id", sa.String(length=32), nullable=False),
        sa.Column("actor_user_id", sa.String(length=32), nullable=True),
        sa.Column("event_type", sa.String(length=80), nullable=False),
        sa.Column("status", sa.String(length=40), nullable=False),
        sa.Column("summary", sa.String(length=240), nullable=False),
        sa.Column("detail", sa.Text(), nullable=False),
        sa.Column("evidence_json", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["actor_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["line_id"], ["voice_gateway_lines.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["owner_user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_voice_gateway_line_events_actor_user_id", "voice_gateway_line_events", ["actor_user_id"])
    op.create_index("ix_voice_gateway_line_events_created_at", "voice_gateway_line_events", ["created_at"])
    op.create_index("ix_voice_gateway_line_events_event_type", "voice_gateway_line_events", ["event_type"])
    op.create_index("ix_voice_gateway_line_events_line_id", "voice_gateway_line_events", ["line_id"])
    op.create_index("ix_voice_gateway_line_events_owner_user_id", "voice_gateway_line_events", ["owner_user_id"])
    op.create_index("ix_voice_gateway_line_events_status", "voice_gateway_line_events", ["status"])


def downgrade() -> None:
    op.drop_index("ix_voice_gateway_line_events_status", table_name="voice_gateway_line_events")
    op.drop_index("ix_voice_gateway_line_events_owner_user_id", table_name="voice_gateway_line_events")
    op.drop_index("ix_voice_gateway_line_events_line_id", table_name="voice_gateway_line_events")
    op.drop_index("ix_voice_gateway_line_events_event_type", table_name="voice_gateway_line_events")
    op.drop_index("ix_voice_gateway_line_events_created_at", table_name="voice_gateway_line_events")
    op.drop_index("ix_voice_gateway_line_events_actor_user_id", table_name="voice_gateway_line_events")
    op.drop_table("voice_gateway_line_events")

    op.drop_index("ix_voice_gateway_lines_trunk_name", table_name="voice_gateway_lines")
    op.drop_index("ix_voice_gateway_lines_status", table_name="voice_gateway_lines")
    op.drop_index("ix_voice_gateway_lines_sip_username", table_name="voice_gateway_lines")
    op.drop_index("ix_voice_gateway_lines_sip_auth_username", table_name="voice_gateway_lines")
    op.drop_index("ix_voice_gateway_lines_sim_status", table_name="voice_gateway_lines")
    op.drop_index("ix_voice_gateway_lines_rtp_status", table_name="voice_gateway_lines")
    op.drop_index("ix_voice_gateway_lines_route_status", table_name="voice_gateway_lines")
    op.drop_index("ix_voice_gateway_lines_registration_status", table_name="voice_gateway_lines")
    op.drop_index("ix_voice_gateway_lines_owner_user_id", table_name="voice_gateway_lines")
    op.drop_index("ix_voice_gateway_lines_line_name", table_name="voice_gateway_lines")
    op.drop_index("ix_voice_gateway_lines_gateway_profile_key", table_name="voice_gateway_lines")
    op.drop_index("ix_voice_gateway_lines_deployment_mode", table_name="voice_gateway_lines")
    op.drop_index("ix_voice_gateway_lines_customer_name", table_name="voice_gateway_lines")
    op.drop_index("ix_voice_gateway_lines_created_by_user_id", table_name="voice_gateway_lines")
    op.drop_index("ix_voice_gateway_lines_acceptance_status", table_name="voice_gateway_lines")
    op.drop_table("voice_gateway_lines")

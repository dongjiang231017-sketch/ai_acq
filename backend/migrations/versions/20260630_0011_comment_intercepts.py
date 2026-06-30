"""add comment intercept workflow

Revision ID: 20260630_0011
Revises: 20260630_0010
Create Date: 2026-06-30 18:35:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260630_0011"
down_revision: Union[str, Sequence[str], None] = "20260630_0010"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "comment_intercept_sources",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("platform", sa.String(length=40), nullable=False),
        sa.Column("source_type", sa.String(length=40), nullable=False),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("keyword", sa.String(length=160), nullable=False),
        sa.Column("video_url", sa.Text(), nullable=False),
        sa.Column("video_title", sa.String(length=240), nullable=False),
        sa.Column("owner_account_id", sa.String(length=32), nullable=True),
        sa.Column("sync_status", sa.String(length=40), nullable=False),
        sa.Column("sync_frequency_minutes", sa.Integer(), nullable=False),
        sa.Column("keyword_rules", sa.Text(), nullable=False),
        sa.Column("auto_reply_enabled", sa.Boolean(), nullable=False),
        sa.Column("human_confirm_required", sa.Boolean(), nullable=False),
        sa.Column("last_sync_at", sa.DateTime(), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["owner_account_id"], ["dm_accounts.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_comment_intercept_sources_platform", "comment_intercept_sources", ["platform"])
    op.create_index("ix_comment_intercept_sources_source_type", "comment_intercept_sources", ["source_type"])
    op.create_index("ix_comment_intercept_sources_name", "comment_intercept_sources", ["name"])
    op.create_index("ix_comment_intercept_sources_sync_status", "comment_intercept_sources", ["sync_status"])
    op.create_index("ix_comment_intercept_sources_owner_account_id", "comment_intercept_sources", ["owner_account_id"])

    op.create_table(
        "social_comments",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("source_id", sa.String(length=32), nullable=False),
        sa.Column("platform", sa.String(length=40), nullable=False),
        sa.Column("external_comment_id", sa.String(length=120), nullable=False),
        sa.Column("video_url", sa.Text(), nullable=False),
        sa.Column("author_name", sa.String(length=120), nullable=False),
        sa.Column("author_profile_url", sa.Text(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("city", sa.String(length=40), nullable=False),
        sa.Column("category", sa.String(length=80), nullable=False),
        sa.Column("like_count", sa.Integer(), nullable=False),
        sa.Column("reply_count", sa.Integer(), nullable=False),
        sa.Column("intent_score", sa.Integer(), nullable=False),
        sa.Column("intent_level", sa.String(length=20), nullable=False),
        sa.Column("status", sa.String(length=40), nullable=False),
        sa.Column("risk_status", sa.String(length=40), nullable=False),
        sa.Column("raw_payload", sa.Text(), nullable=True),
        sa.Column("commented_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["source_id"], ["comment_intercept_sources.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_social_comments_source_id", "social_comments", ["source_id"])
    op.create_index("ix_social_comments_platform", "social_comments", ["platform"])
    op.create_index("ix_social_comments_external_comment_id", "social_comments", ["external_comment_id"])
    op.create_index("ix_social_comments_author_name", "social_comments", ["author_name"])
    op.create_index("ix_social_comments_city", "social_comments", ["city"])
    op.create_index("ix_social_comments_category", "social_comments", ["category"])
    op.create_index("ix_social_comments_intent_score", "social_comments", ["intent_score"])
    op.create_index("ix_social_comments_intent_level", "social_comments", ["intent_level"])
    op.create_index("ix_social_comments_status", "social_comments", ["status"])
    op.create_index("ix_social_comments_risk_status", "social_comments", ["risk_status"])

    op.create_table(
        "comment_lead_conversions",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("comment_id", sa.String(length=32), nullable=False),
        sa.Column("lead_id", sa.String(length=32), nullable=False),
        sa.Column("action", sa.String(length=40), nullable=False),
        sa.Column("status", sa.String(length=40), nullable=False),
        sa.Column("note", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["comment_id"], ["social_comments.id"]),
        sa.ForeignKeyConstraint(["lead_id"], ["merchant_leads.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_comment_lead_conversions_comment_id", "comment_lead_conversions", ["comment_id"])
    op.create_index("ix_comment_lead_conversions_lead_id", "comment_lead_conversions", ["lead_id"])
    op.create_index("ix_comment_lead_conversions_action", "comment_lead_conversions", ["action"])
    op.create_index("ix_comment_lead_conversions_status", "comment_lead_conversions", ["status"])


def downgrade() -> None:
    op.drop_index("ix_comment_lead_conversions_status", table_name="comment_lead_conversions")
    op.drop_index("ix_comment_lead_conversions_action", table_name="comment_lead_conversions")
    op.drop_index("ix_comment_lead_conversions_lead_id", table_name="comment_lead_conversions")
    op.drop_index("ix_comment_lead_conversions_comment_id", table_name="comment_lead_conversions")
    op.drop_table("comment_lead_conversions")

    op.drop_index("ix_social_comments_risk_status", table_name="social_comments")
    op.drop_index("ix_social_comments_status", table_name="social_comments")
    op.drop_index("ix_social_comments_intent_level", table_name="social_comments")
    op.drop_index("ix_social_comments_intent_score", table_name="social_comments")
    op.drop_index("ix_social_comments_category", table_name="social_comments")
    op.drop_index("ix_social_comments_city", table_name="social_comments")
    op.drop_index("ix_social_comments_author_name", table_name="social_comments")
    op.drop_index("ix_social_comments_external_comment_id", table_name="social_comments")
    op.drop_index("ix_social_comments_platform", table_name="social_comments")
    op.drop_index("ix_social_comments_source_id", table_name="social_comments")
    op.drop_table("social_comments")

    op.drop_index("ix_comment_intercept_sources_owner_account_id", table_name="comment_intercept_sources")
    op.drop_index("ix_comment_intercept_sources_sync_status", table_name="comment_intercept_sources")
    op.drop_index("ix_comment_intercept_sources_name", table_name="comment_intercept_sources")
    op.drop_index("ix_comment_intercept_sources_source_type", table_name="comment_intercept_sources")
    op.drop_index("ix_comment_intercept_sources_platform", table_name="comment_intercept_sources")
    op.drop_table("comment_intercept_sources")

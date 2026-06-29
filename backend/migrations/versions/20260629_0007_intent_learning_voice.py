"""add intent learning voice product layers

Revision ID: 20260629_0007
Revises: 20260629_0006
Create Date: 2026-06-29 23:20:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260629_0007"
down_revision: Union[str, Sequence[str], None] = "20260629_0006"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "intent_customers",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("lead_id", sa.String(length=32), nullable=True),
        sa.Column("merchant_name", sa.String(length=120), nullable=False),
        sa.Column("platform", sa.String(length=40), nullable=False),
        sa.Column("city", sa.String(length=40), nullable=False),
        sa.Column("category", sa.String(length=80), nullable=False),
        sa.Column("contact_name", sa.String(length=80), nullable=True),
        sa.Column("phone", sa.String(length=40), nullable=True),
        sa.Column("intent_level", sa.String(length=20), nullable=False),
        sa.Column("intent_score", sa.Integer(), nullable=False),
        sa.Column("source_channels", sa.String(length=120), nullable=False),
        sa.Column("latest_signal", sa.Text(), nullable=False),
        sa.Column("evidence_summary", sa.Text(), nullable=False),
        sa.Column("owner_name", sa.String(length=80), nullable=False),
        sa.Column("follow_status", sa.String(length=40), nullable=False),
        sa.Column("next_follow_at", sa.DateTime(), nullable=True),
        sa.Column("need_handoff", sa.Boolean(), nullable=False),
        sa.Column("dnc_status", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["lead_id"], ["merchant_leads.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_intent_customers_category"), "intent_customers", ["category"], unique=False)
    op.create_index(op.f("ix_intent_customers_city"), "intent_customers", ["city"], unique=False)
    op.create_index(op.f("ix_intent_customers_dnc_status"), "intent_customers", ["dnc_status"], unique=False)
    op.create_index(op.f("ix_intent_customers_follow_status"), "intent_customers", ["follow_status"], unique=False)
    op.create_index(op.f("ix_intent_customers_intent_level"), "intent_customers", ["intent_level"], unique=False)
    op.create_index(op.f("ix_intent_customers_lead_id"), "intent_customers", ["lead_id"], unique=False)
    op.create_index(op.f("ix_intent_customers_merchant_name"), "intent_customers", ["merchant_name"], unique=False)
    op.create_index(op.f("ix_intent_customers_need_handoff"), "intent_customers", ["need_handoff"], unique=False)
    op.create_index(op.f("ix_intent_customers_owner_name"), "intent_customers", ["owner_name"], unique=False)
    op.create_index(op.f("ix_intent_customers_platform"), "intent_customers", ["platform"], unique=False)

    op.create_table(
        "intent_events",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("customer_id", sa.String(length=32), nullable=False),
        sa.Column("lead_id", sa.String(length=32), nullable=True),
        sa.Column("source_type", sa.String(length=40), nullable=False),
        sa.Column("source_record_id", sa.String(length=32), nullable=True),
        sa.Column("channel", sa.String(length=40), nullable=False),
        sa.Column("intent_level", sa.String(length=20), nullable=False),
        sa.Column("summary", sa.String(length=240), nullable=False),
        sa.Column("evidence_text", sa.Text(), nullable=False),
        sa.Column("need_handoff", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["customer_id"], ["intent_customers.id"]),
        sa.ForeignKeyConstraint(["lead_id"], ["merchant_leads.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_intent_events_channel"), "intent_events", ["channel"], unique=False)
    op.create_index(op.f("ix_intent_events_customer_id"), "intent_events", ["customer_id"], unique=False)
    op.create_index(op.f("ix_intent_events_intent_level"), "intent_events", ["intent_level"], unique=False)
    op.create_index(op.f("ix_intent_events_lead_id"), "intent_events", ["lead_id"], unique=False)
    op.create_index(op.f("ix_intent_events_need_handoff"), "intent_events", ["need_handoff"], unique=False)
    op.create_index(op.f("ix_intent_events_source_record_id"), "intent_events", ["source_record_id"], unique=False)
    op.create_index(op.f("ix_intent_events_source_type"), "intent_events", ["source_type"], unique=False)

    op.create_table(
        "follow_up_work_orders",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("customer_id", sa.String(length=32), nullable=False),
        sa.Column("title", sa.String(length=160), nullable=False),
        sa.Column("owner_name", sa.String(length=80), nullable=False),
        sa.Column("status", sa.String(length=40), nullable=False),
        sa.Column("priority", sa.String(length=20), nullable=False),
        sa.Column("sla_due_at", sa.DateTime(), nullable=True),
        sa.Column("last_note", sa.Text(), nullable=False),
        sa.Column("closed_reason", sa.String(length=160), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["customer_id"], ["intent_customers.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_follow_up_work_orders_customer_id"), "follow_up_work_orders", ["customer_id"], unique=False)
    op.create_index(op.f("ix_follow_up_work_orders_owner_name"), "follow_up_work_orders", ["owner_name"], unique=False)
    op.create_index(op.f("ix_follow_up_work_orders_priority"), "follow_up_work_orders", ["priority"], unique=False)
    op.create_index(op.f("ix_follow_up_work_orders_status"), "follow_up_work_orders", ["status"], unique=False)
    op.create_index(op.f("ix_follow_up_work_orders_title"), "follow_up_work_orders", ["title"], unique=False)

    op.create_table(
        "learning_suggestions",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("source_type", sa.String(length=40), nullable=False),
        sa.Column("source_record_id", sa.String(length=32), nullable=True),
        sa.Column("target_type", sa.String(length=60), nullable=False),
        sa.Column("title", sa.String(length=160), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("proposed_content", sa.Text(), nullable=False),
        sa.Column("evidence_text", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=40), nullable=False),
        sa.Column("reviewer", sa.String(length=80), nullable=True),
        sa.Column("review_note", sa.Text(), nullable=True),
        sa.Column("impact_score", sa.Integer(), nullable=False),
        sa.Column("rollback_point", sa.String(length=160), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("reviewed_at", sa.DateTime(), nullable=True),
        sa.Column("published_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_learning_suggestions_source_record_id"), "learning_suggestions", ["source_record_id"], unique=False)
    op.create_index(op.f("ix_learning_suggestions_source_type"), "learning_suggestions", ["source_type"], unique=False)
    op.create_index(op.f("ix_learning_suggestions_status"), "learning_suggestions", ["status"], unique=False)
    op.create_index(op.f("ix_learning_suggestions_target_type"), "learning_suggestions", ["target_type"], unique=False)
    op.create_index(op.f("ix_learning_suggestions_title"), "learning_suggestions", ["title"], unique=False)

    op.create_table(
        "knowledge_base_items",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("title", sa.String(length=160), nullable=False),
        sa.Column("category", sa.String(length=80), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=40), nullable=False),
        sa.Column("version", sa.String(length=40), nullable=False),
        sa.Column("source_suggestion_id", sa.String(length=32), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["source_suggestion_id"], ["learning_suggestions.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_knowledge_base_items_category"), "knowledge_base_items", ["category"], unique=False)
    op.create_index(op.f("ix_knowledge_base_items_source_suggestion_id"), "knowledge_base_items", ["source_suggestion_id"], unique=False)
    op.create_index(op.f("ix_knowledge_base_items_status"), "knowledge_base_items", ["status"], unique=False)
    op.create_index(op.f("ix_knowledge_base_items_title"), "knowledge_base_items", ["title"], unique=False)

    op.create_table(
        "learning_experiments",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("target_type", sa.String(length=60), nullable=False),
        sa.Column("status", sa.String(length=40), nullable=False),
        sa.Column("hypothesis", sa.Text(), nullable=False),
        sa.Column("variant", sa.Text(), nullable=False),
        sa.Column("sample_size", sa.Integer(), nullable=False),
        sa.Column("success_metric", sa.String(length=120), nullable=False),
        sa.Column("result_summary", sa.Text(), nullable=False),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("ended_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_learning_experiments_name"), "learning_experiments", ["name"], unique=False)
    op.create_index(op.f("ix_learning_experiments_status"), "learning_experiments", ["status"], unique=False)
    op.create_index(op.f("ix_learning_experiments_target_type"), "learning_experiments", ["target_type"], unique=False)

    op.create_table(
        "voice_profiles",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("owner_name", sa.String(length=80), nullable=False),
        sa.Column("scenario", sa.String(length=80), nullable=False),
        sa.Column("status", sa.String(length=40), nullable=False),
        sa.Column("authorization_status", sa.String(length=40), nullable=False),
        sa.Column("sample_count", sa.Integer(), nullable=False),
        sa.Column("fallback_voice", sa.String(length=120), nullable=False),
        sa.Column("consent_material", sa.Text(), nullable=False),
        sa.Column("risk_note", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_voice_profiles_authorization_status"), "voice_profiles", ["authorization_status"], unique=False)
    op.create_index(op.f("ix_voice_profiles_name"), "voice_profiles", ["name"], unique=False)
    op.create_index(op.f("ix_voice_profiles_owner_name"), "voice_profiles", ["owner_name"], unique=False)
    op.create_index(op.f("ix_voice_profiles_scenario"), "voice_profiles", ["scenario"], unique=False)
    op.create_index(op.f("ix_voice_profiles_status"), "voice_profiles", ["status"], unique=False)

    op.create_table(
        "voice_training_jobs",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("profile_id", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=40), nullable=False),
        sa.Column("progress", sa.Integer(), nullable=False),
        sa.Column("engine", sa.String(length=80), nullable=False),
        sa.Column("sample_minutes", sa.Integer(), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("finished_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["profile_id"], ["voice_profiles.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_voice_training_jobs_profile_id"), "voice_training_jobs", ["profile_id"], unique=False)
    op.create_index(op.f("ix_voice_training_jobs_status"), "voice_training_jobs", ["status"], unique=False)

    op.create_table(
        "voice_usage_records",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("profile_id", sa.String(length=32), nullable=True),
        sa.Column("task_id", sa.String(length=32), nullable=True),
        sa.Column("merchant_name", sa.String(length=120), nullable=False),
        sa.Column("scenario", sa.String(length=80), nullable=False),
        sa.Column("result", sa.String(length=80), nullable=False),
        sa.Column("fallback_used", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["profile_id"], ["voice_profiles.id"]),
        sa.ForeignKeyConstraint(["task_id"], ["outreach_tasks.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_voice_usage_records_fallback_used"), "voice_usage_records", ["fallback_used"], unique=False)
    op.create_index(op.f("ix_voice_usage_records_profile_id"), "voice_usage_records", ["profile_id"], unique=False)
    op.create_index(op.f("ix_voice_usage_records_result"), "voice_usage_records", ["result"], unique=False)
    op.create_index(op.f("ix_voice_usage_records_scenario"), "voice_usage_records", ["scenario"], unique=False)
    op.create_index(op.f("ix_voice_usage_records_task_id"), "voice_usage_records", ["task_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_voice_usage_records_task_id"), table_name="voice_usage_records")
    op.drop_index(op.f("ix_voice_usage_records_scenario"), table_name="voice_usage_records")
    op.drop_index(op.f("ix_voice_usage_records_result"), table_name="voice_usage_records")
    op.drop_index(op.f("ix_voice_usage_records_profile_id"), table_name="voice_usage_records")
    op.drop_index(op.f("ix_voice_usage_records_fallback_used"), table_name="voice_usage_records")
    op.drop_table("voice_usage_records")

    op.drop_index(op.f("ix_voice_training_jobs_status"), table_name="voice_training_jobs")
    op.drop_index(op.f("ix_voice_training_jobs_profile_id"), table_name="voice_training_jobs")
    op.drop_table("voice_training_jobs")

    op.drop_index(op.f("ix_voice_profiles_status"), table_name="voice_profiles")
    op.drop_index(op.f("ix_voice_profiles_scenario"), table_name="voice_profiles")
    op.drop_index(op.f("ix_voice_profiles_owner_name"), table_name="voice_profiles")
    op.drop_index(op.f("ix_voice_profiles_name"), table_name="voice_profiles")
    op.drop_index(op.f("ix_voice_profiles_authorization_status"), table_name="voice_profiles")
    op.drop_table("voice_profiles")

    op.drop_index(op.f("ix_learning_experiments_target_type"), table_name="learning_experiments")
    op.drop_index(op.f("ix_learning_experiments_status"), table_name="learning_experiments")
    op.drop_index(op.f("ix_learning_experiments_name"), table_name="learning_experiments")
    op.drop_table("learning_experiments")

    op.drop_index(op.f("ix_knowledge_base_items_title"), table_name="knowledge_base_items")
    op.drop_index(op.f("ix_knowledge_base_items_status"), table_name="knowledge_base_items")
    op.drop_index(op.f("ix_knowledge_base_items_source_suggestion_id"), table_name="knowledge_base_items")
    op.drop_index(op.f("ix_knowledge_base_items_category"), table_name="knowledge_base_items")
    op.drop_table("knowledge_base_items")

    op.drop_index(op.f("ix_learning_suggestions_title"), table_name="learning_suggestions")
    op.drop_index(op.f("ix_learning_suggestions_target_type"), table_name="learning_suggestions")
    op.drop_index(op.f("ix_learning_suggestions_status"), table_name="learning_suggestions")
    op.drop_index(op.f("ix_learning_suggestions_source_type"), table_name="learning_suggestions")
    op.drop_index(op.f("ix_learning_suggestions_source_record_id"), table_name="learning_suggestions")
    op.drop_table("learning_suggestions")

    op.drop_index(op.f("ix_follow_up_work_orders_title"), table_name="follow_up_work_orders")
    op.drop_index(op.f("ix_follow_up_work_orders_status"), table_name="follow_up_work_orders")
    op.drop_index(op.f("ix_follow_up_work_orders_priority"), table_name="follow_up_work_orders")
    op.drop_index(op.f("ix_follow_up_work_orders_owner_name"), table_name="follow_up_work_orders")
    op.drop_index(op.f("ix_follow_up_work_orders_customer_id"), table_name="follow_up_work_orders")
    op.drop_table("follow_up_work_orders")

    op.drop_index(op.f("ix_intent_events_source_type"), table_name="intent_events")
    op.drop_index(op.f("ix_intent_events_source_record_id"), table_name="intent_events")
    op.drop_index(op.f("ix_intent_events_need_handoff"), table_name="intent_events")
    op.drop_index(op.f("ix_intent_events_lead_id"), table_name="intent_events")
    op.drop_index(op.f("ix_intent_events_intent_level"), table_name="intent_events")
    op.drop_index(op.f("ix_intent_events_customer_id"), table_name="intent_events")
    op.drop_index(op.f("ix_intent_events_channel"), table_name="intent_events")
    op.drop_table("intent_events")

    op.drop_index(op.f("ix_intent_customers_platform"), table_name="intent_customers")
    op.drop_index(op.f("ix_intent_customers_owner_name"), table_name="intent_customers")
    op.drop_index(op.f("ix_intent_customers_need_handoff"), table_name="intent_customers")
    op.drop_index(op.f("ix_intent_customers_merchant_name"), table_name="intent_customers")
    op.drop_index(op.f("ix_intent_customers_lead_id"), table_name="intent_customers")
    op.drop_index(op.f("ix_intent_customers_intent_level"), table_name="intent_customers")
    op.drop_index(op.f("ix_intent_customers_follow_status"), table_name="intent_customers")
    op.drop_index(op.f("ix_intent_customers_dnc_status"), table_name="intent_customers")
    op.drop_index(op.f("ix_intent_customers_city"), table_name="intent_customers")
    op.drop_index(op.f("ix_intent_customers_category"), table_name="intent_customers")
    op.drop_table("intent_customers")

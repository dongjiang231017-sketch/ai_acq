"""add client auth and lead collection

Revision ID: 20260702_0012
Revises: 20260630_0011
Create Date: 2026-07-02 20:20:00.000000

"""

from datetime import datetime
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260702_0012"
down_revision: Union[str, Sequence[str], None] = "20260630_0011"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "roles",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("code", sa.String(length=80), nullable=False),
        sa.Column("name", sa.String(length=80), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("is_system", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name"),
    )
    op.create_index("ix_roles_code", "roles", ["code"], unique=True)

    op.create_table(
        "users",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("username", sa.String(length=80), nullable=False),
        sa.Column("display_name", sa.String(length=80), nullable=False),
        sa.Column("email", sa.String(length=120), nullable=True),
        sa.Column("phone", sa.String(length=40), nullable=True),
        sa.Column("password_hash", sa.String(length=255), nullable=False),
        sa.Column("status", sa.String(length=40), nullable=False),
        sa.Column("is_superuser", sa.Boolean(), nullable=False),
        sa.Column("last_login_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("email"),
        sa.UniqueConstraint("phone"),
    )
    op.create_index("ix_users_status", "users", ["status"])
    op.create_index("ix_users_username", "users", ["username"], unique=True)

    op.create_table(
        "admin_users",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("username", sa.String(length=80), nullable=False),
        sa.Column("display_name", sa.String(length=80), nullable=False),
        sa.Column("email", sa.String(length=120), nullable=True),
        sa.Column("phone", sa.String(length=40), nullable=True),
        sa.Column("password_hash", sa.String(length=255), nullable=False),
        sa.Column("status", sa.String(length=40), nullable=False),
        sa.Column("is_superuser", sa.Boolean(), nullable=False),
        sa.Column("last_login_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("email"),
        sa.UniqueConstraint("phone"),
    )
    op.create_index("ix_admin_users_status", "admin_users", ["status"])
    op.create_index("ix_admin_users_username", "admin_users", ["username"], unique=True)

    op.create_table(
        "audit_logs",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("actor_user_id", sa.String(length=32), nullable=True),
        sa.Column("actor_username", sa.String(length=80), nullable=True),
        sa.Column("action", sa.String(length=80), nullable=False),
        sa.Column("resource_type", sa.String(length=80), nullable=False),
        sa.Column("resource_id", sa.String(length=80), nullable=True),
        sa.Column("ip_address", sa.String(length=80), nullable=True),
        sa.Column("user_agent", sa.String(length=255), nullable=True),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["actor_user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_audit_logs_action", "audit_logs", ["action"])
    op.create_index("ix_audit_logs_actor_user_id", "audit_logs", ["actor_user_id"])
    op.create_index("ix_audit_logs_created_at", "audit_logs", ["created_at"])
    op.create_index("ix_audit_logs_resource_id", "audit_logs", ["resource_id"])
    op.create_index("ix_audit_logs_resource_type", "audit_logs", ["resource_type"])

    op.create_table(
        "user_roles",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("user_id", sa.String(length=32), nullable=False),
        sa.Column("role_id", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["role_id"], ["roles.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "role_id", name="uq_user_roles_user_role"),
    )
    op.create_index("ix_user_roles_role_id", "user_roles", ["role_id"])
    op.create_index("ix_user_roles_user_id", "user_roles", ["user_id"])

    op.create_table(
        "registration_requests",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("project_name", sa.String(length=120), nullable=False),
        sa.Column("company_name", sa.String(length=160), nullable=False),
        sa.Column("contact_name", sa.String(length=80), nullable=True),
        sa.Column("contact_phone", sa.String(length=40), nullable=False),
        sa.Column("contact_email", sa.String(length=120), nullable=True),
        sa.Column("desired_username", sa.String(length=80), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=40), nullable=False),
        sa.Column("reviewer_user_id", sa.String(length=32), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["reviewer_user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_registration_requests_contact_email", "registration_requests", ["contact_email"])
    op.create_index("ix_registration_requests_contact_phone", "registration_requests", ["contact_phone"])
    op.create_index("ix_registration_requests_created_at", "registration_requests", ["created_at"])
    op.create_index("ix_registration_requests_desired_username", "registration_requests", ["desired_username"])
    op.create_index("ix_registration_requests_reviewer_user_id", "registration_requests", ["reviewer_user_id"])
    op.create_index("ix_registration_requests_status", "registration_requests", ["status"])

    op.add_column("merchant_leads", sa.Column("contact_title", sa.String(length=80), nullable=True))
    op.add_column("merchant_leads", sa.Column("wechat_id", sa.String(length=80), nullable=True))
    op.add_column("merchant_leads", sa.Column("platform_homepage_url", sa.String(length=500), nullable=True))
    op.add_column("merchant_leads", sa.Column("source_poi_id", sa.String(length=120), nullable=True))
    op.add_column("merchant_leads", sa.Column("province", sa.String(length=40), nullable=True))
    op.add_column("merchant_leads", sa.Column("district", sa.String(length=80), nullable=True))
    op.add_column("merchant_leads", sa.Column("address", sa.String(length=255), nullable=True))
    op.add_column("merchant_leads", sa.Column("longitude", sa.String(length=40), nullable=True))
    op.add_column("merchant_leads", sa.Column("latitude", sa.String(length=40), nullable=True))
    op.add_column(
        "merchant_leads",
        sa.Column("follow_up_status", sa.String(length=40), server_default="未跟进", nullable=False),
    )
    op.add_column("merchant_leads", sa.Column("remark", sa.Text(), nullable=True))
    op.add_column("merchant_leads", sa.Column("owner_user_id", sa.String(length=32), nullable=True))
    op.add_column("merchant_leads", sa.Column("created_by_user_id", sa.String(length=32), nullable=True))
    op.add_column("merchant_leads", sa.Column("last_contact_at", sa.DateTime(), nullable=True))
    op.add_column("merchant_leads", sa.Column("next_follow_up_at", sa.DateTime(), nullable=True))
    with op.batch_alter_table("merchant_leads") as batch_op:
        batch_op.add_column(sa.Column("updated_at", sa.DateTime(), nullable=True))
    op.execute("UPDATE merchant_leads SET updated_at = created_at WHERE updated_at IS NULL")
    with op.batch_alter_table("merchant_leads") as batch_op:
        batch_op.alter_column("updated_at", existing_type=sa.DateTime(), nullable=False)
    op.create_index("ix_merchant_leads_follow_up_status", "merchant_leads", ["follow_up_status"])
    op.create_index("ix_merchant_leads_owner_user_id", "merchant_leads", ["owner_user_id"])
    op.create_index("ix_merchant_leads_source_poi_id", "merchant_leads", ["source_poi_id"])
    with op.batch_alter_table("merchant_leads") as batch_op:
        batch_op.create_foreign_key("fk_merchant_leads_owner_user_id_users", "users", ["owner_user_id"], ["id"])
        batch_op.create_foreign_key(
            "fk_merchant_leads_created_by_user_id_users",
            "users",
            ["created_by_user_id"],
            ["id"],
        )

    op.create_table(
        "lead_provider_configs",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("provider", sa.String(length=40), nullable=False),
        sa.Column("name", sa.String(length=80), nullable=False),
        sa.Column("api_key", sa.String(length=255), nullable=True),
        sa.Column("secret_key", sa.String(length=255), nullable=True),
        sa.Column("service_url", sa.String(length=500), nullable=True),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("daily_limit", sa.Integer(), nullable=True),
        sa.Column("qps_limit", sa.Integer(), nullable=True),
        sa.Column("remark", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_lead_provider_configs_enabled", "lead_provider_configs", ["enabled"])
    op.create_index("ix_lead_provider_configs_provider", "lead_provider_configs", ["provider"], unique=True)
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
                "id": "provider_amap",
                "provider": "amap",
                "name": "高德地图",
                "api_key": None,
                "secret_key": None,
                "service_url": "https://restapi.amap.com/v3/place/text",
                "enabled": True,
                "daily_limit": None,
                "qps_limit": None,
                "remark": "服务端配置高德地图密钥后用于地图点位采集。",
                "created_at": now,
                "updated_at": now,
            },
            {
                "id": "provider_baidu",
                "provider": "baidu",
                "name": "百度地图",
                "api_key": None,
                "secret_key": None,
                "service_url": "https://api.map.baidu.com/place/v3/region",
                "enabled": True,
                "daily_limit": None,
                "qps_limit": None,
                "remark": "服务端配置百度地图密钥后用于地图点位采集。",
                "created_at": now,
                "updated_at": now,
            },
            {
                "id": "provider_tencent",
                "provider": "tencent",
                "name": "腾讯位置服务",
                "api_key": None,
                "secret_key": None,
                "service_url": "https://apis.map.qq.com/ws/place/v1/search",
                "enabled": False,
                "daily_limit": None,
                "qps_limit": None,
                "remark": "已预留，确认配额和签名策略后启用。",
                "created_at": now,
                "updated_at": now,
            },
        ],
    )

    op.create_table(
        "lead_collection_tasks",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("provider", sa.String(length=40), nullable=False),
        sa.Column("cities", sa.JSON(), nullable=False),
        sa.Column("categories", sa.JSON(), nullable=False),
        sa.Column("keywords", sa.JSON(), nullable=False),
        sa.Column("target_per_keyword", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=40), nullable=False),
        sa.Column("last_run_status", sa.String(length=40), nullable=True),
        sa.Column("remark", sa.Text(), nullable=True),
        sa.Column("owner_user_id", sa.String(length=32), nullable=True),
        sa.Column("created_by_user_id", sa.String(length=32), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["owner_user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_lead_collection_tasks_created_at", "lead_collection_tasks", ["created_at"])
    op.create_index("ix_lead_collection_tasks_name", "lead_collection_tasks", ["name"])
    op.create_index("ix_lead_collection_tasks_owner_user_id", "lead_collection_tasks", ["owner_user_id"])
    op.create_index("ix_lead_collection_tasks_provider", "lead_collection_tasks", ["provider"])
    op.create_index("ix_lead_collection_tasks_status", "lead_collection_tasks", ["status"])

    op.create_table(
        "lead_collection_runs",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("task_id", sa.String(length=32), nullable=False),
        sa.Column("provider", sa.String(length=40), nullable=False),
        sa.Column("status", sa.String(length=40), nullable=False),
        sa.Column("requested_count", sa.Integer(), nullable=False),
        sa.Column("fetched_count", sa.Integer(), nullable=False),
        sa.Column("inserted_count", sa.Integer(), nullable=False),
        sa.Column("duplicate_count", sa.Integer(), nullable=False),
        sa.Column("failed_count", sa.Integer(), nullable=False),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(), nullable=False),
        sa.Column("finished_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["task_id"], ["lead_collection_tasks.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_lead_collection_runs_provider", "lead_collection_runs", ["provider"])
    op.create_index("ix_lead_collection_runs_started_at", "lead_collection_runs", ["started_at"])
    op.create_index("ix_lead_collection_runs_status", "lead_collection_runs", ["status"])
    op.create_index("ix_lead_collection_runs_task_id", "lead_collection_runs", ["task_id"])

    op.create_table(
        "raw_lead_records",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("task_id", sa.String(length=32), nullable=False),
        sa.Column("run_id", sa.String(length=32), nullable=False),
        sa.Column("lead_id", sa.String(length=32), nullable=True),
        sa.Column("owner_user_id", sa.String(length=32), nullable=True),
        sa.Column("provider", sa.String(length=40), nullable=False),
        sa.Column("source_poi_id", sa.String(length=120), nullable=False),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("city", sa.String(length=40), nullable=True),
        sa.Column("district", sa.String(length=80), nullable=True),
        sa.Column("category", sa.String(length=120), nullable=True),
        sa.Column("phone", sa.String(length=120), nullable=True),
        sa.Column("address", sa.String(length=255), nullable=True),
        sa.Column("source_url", sa.String(length=500), nullable=True),
        sa.Column("longitude", sa.String(length=40), nullable=True),
        sa.Column("latitude", sa.String(length=40), nullable=True),
        sa.Column("import_status", sa.String(length=40), nullable=False),
        sa.Column("raw_payload", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["lead_id"], ["merchant_leads.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["owner_user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["run_id"], ["lead_collection_runs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["task_id"], ["lead_collection_tasks.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("owner_user_id", "provider", "source_poi_id", name="uq_raw_lead_records_owner_provider_poi"),
    )
    op.create_index("ix_raw_lead_records_city", "raw_lead_records", ["city"])
    op.create_index("ix_raw_lead_records_created_at", "raw_lead_records", ["created_at"])
    op.create_index("ix_raw_lead_records_import_status", "raw_lead_records", ["import_status"])
    op.create_index("ix_raw_lead_records_name", "raw_lead_records", ["name"])
    op.create_index("ix_raw_lead_records_owner_user_id", "raw_lead_records", ["owner_user_id"])
    op.create_index("ix_raw_lead_records_provider", "raw_lead_records", ["provider"])
    op.create_index("ix_raw_lead_records_run_id", "raw_lead_records", ["run_id"])
    op.create_index("ix_raw_lead_records_source_poi_id", "raw_lead_records", ["source_poi_id"])
    op.create_index("ix_raw_lead_records_task_id", "raw_lead_records", ["task_id"])

    op.create_table(
        "platform_browser_sessions",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("provider", sa.String(length=40), nullable=False),
        sa.Column("name", sa.String(length=80), nullable=False),
        sa.Column("login_url", sa.String(length=500), nullable=False),
        sa.Column("home_url", sa.String(length=500), nullable=False),
        sa.Column("profile_dir", sa.String(length=255), nullable=False),
        sa.Column("status", sa.String(length=40), nullable=False),
        sa.Column("login_process_id", sa.Integer(), nullable=True),
        sa.Column("last_login_started_at", sa.DateTime(), nullable=True),
        sa.Column("last_login_finished_at", sa.DateTime(), nullable=True),
        sa.Column("last_validated_at", sa.DateTime(), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_platform_browser_sessions_provider", "platform_browser_sessions", ["provider"], unique=True)
    op.create_index("ix_platform_browser_sessions_status", "platform_browser_sessions", ["status"])


def downgrade() -> None:
    op.drop_index("ix_platform_browser_sessions_status", table_name="platform_browser_sessions")
    op.drop_index("ix_platform_browser_sessions_provider", table_name="platform_browser_sessions")
    op.drop_table("platform_browser_sessions")

    op.drop_index("ix_raw_lead_records_task_id", table_name="raw_lead_records")
    op.drop_index("ix_raw_lead_records_source_poi_id", table_name="raw_lead_records")
    op.drop_index("ix_raw_lead_records_run_id", table_name="raw_lead_records")
    op.drop_index("ix_raw_lead_records_provider", table_name="raw_lead_records")
    op.drop_index("ix_raw_lead_records_owner_user_id", table_name="raw_lead_records")
    op.drop_index("ix_raw_lead_records_name", table_name="raw_lead_records")
    op.drop_index("ix_raw_lead_records_import_status", table_name="raw_lead_records")
    op.drop_index("ix_raw_lead_records_created_at", table_name="raw_lead_records")
    op.drop_index("ix_raw_lead_records_city", table_name="raw_lead_records")
    op.drop_table("raw_lead_records")

    op.drop_index("ix_lead_collection_runs_task_id", table_name="lead_collection_runs")
    op.drop_index("ix_lead_collection_runs_status", table_name="lead_collection_runs")
    op.drop_index("ix_lead_collection_runs_started_at", table_name="lead_collection_runs")
    op.drop_index("ix_lead_collection_runs_provider", table_name="lead_collection_runs")
    op.drop_table("lead_collection_runs")

    op.drop_index("ix_lead_collection_tasks_status", table_name="lead_collection_tasks")
    op.drop_index("ix_lead_collection_tasks_provider", table_name="lead_collection_tasks")
    op.drop_index("ix_lead_collection_tasks_owner_user_id", table_name="lead_collection_tasks")
    op.drop_index("ix_lead_collection_tasks_name", table_name="lead_collection_tasks")
    op.drop_index("ix_lead_collection_tasks_created_at", table_name="lead_collection_tasks")
    op.drop_table("lead_collection_tasks")

    op.drop_index("ix_lead_provider_configs_provider", table_name="lead_provider_configs")
    op.drop_index("ix_lead_provider_configs_enabled", table_name="lead_provider_configs")
    op.drop_table("lead_provider_configs")

    with op.batch_alter_table("merchant_leads") as batch_op:
        batch_op.drop_constraint("fk_merchant_leads_created_by_user_id_users", type_="foreignkey")
        batch_op.drop_constraint("fk_merchant_leads_owner_user_id_users", type_="foreignkey")
    op.drop_index("ix_merchant_leads_source_poi_id", table_name="merchant_leads")
    op.drop_index("ix_merchant_leads_owner_user_id", table_name="merchant_leads")
    op.drop_index("ix_merchant_leads_follow_up_status", table_name="merchant_leads")
    op.drop_column("merchant_leads", "updated_at")
    op.drop_column("merchant_leads", "next_follow_up_at")
    op.drop_column("merchant_leads", "last_contact_at")
    op.drop_column("merchant_leads", "created_by_user_id")
    op.drop_column("merchant_leads", "owner_user_id")
    op.drop_column("merchant_leads", "remark")
    op.drop_column("merchant_leads", "follow_up_status")
    op.drop_column("merchant_leads", "latitude")
    op.drop_column("merchant_leads", "longitude")
    op.drop_column("merchant_leads", "address")
    op.drop_column("merchant_leads", "district")
    op.drop_column("merchant_leads", "province")
    op.drop_column("merchant_leads", "source_poi_id")
    op.drop_column("merchant_leads", "platform_homepage_url")
    op.drop_column("merchant_leads", "wechat_id")
    op.drop_column("merchant_leads", "contact_title")

    op.drop_index("ix_registration_requests_status", table_name="registration_requests")
    op.drop_index("ix_registration_requests_reviewer_user_id", table_name="registration_requests")
    op.drop_index("ix_registration_requests_desired_username", table_name="registration_requests")
    op.drop_index("ix_registration_requests_created_at", table_name="registration_requests")
    op.drop_index("ix_registration_requests_contact_phone", table_name="registration_requests")
    op.drop_index("ix_registration_requests_contact_email", table_name="registration_requests")
    op.drop_table("registration_requests")

    op.drop_index("ix_user_roles_user_id", table_name="user_roles")
    op.drop_index("ix_user_roles_role_id", table_name="user_roles")
    op.drop_table("user_roles")
    op.drop_index("ix_audit_logs_resource_type", table_name="audit_logs")
    op.drop_index("ix_audit_logs_resource_id", table_name="audit_logs")
    op.drop_index("ix_audit_logs_created_at", table_name="audit_logs")
    op.drop_index("ix_audit_logs_actor_user_id", table_name="audit_logs")
    op.drop_index("ix_audit_logs_action", table_name="audit_logs")
    op.drop_table("audit_logs")
    op.drop_index("ix_admin_users_username", table_name="admin_users")
    op.drop_index("ix_admin_users_status", table_name="admin_users")
    op.drop_table("admin_users")
    op.drop_index("ix_users_username", table_name="users")
    op.drop_index("ix_users_status", table_name="users")
    op.drop_table("users")
    op.drop_index("ix_roles_code", table_name="roles")
    op.drop_table("roles")

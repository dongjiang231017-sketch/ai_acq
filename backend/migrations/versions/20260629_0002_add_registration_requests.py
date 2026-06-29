"""add registration requests

Revision ID: 20260629_0002
Revises: b8538627302e
Create Date: 2026-06-29 11:10:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260629_0002"
down_revision: Union[str, Sequence[str], None] = "b8538627302e"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
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
    op.create_index(op.f("ix_registration_requests_contact_email"), "registration_requests", ["contact_email"], unique=False)
    op.create_index(op.f("ix_registration_requests_contact_phone"), "registration_requests", ["contact_phone"], unique=False)
    op.create_index(op.f("ix_registration_requests_created_at"), "registration_requests", ["created_at"], unique=False)
    op.create_index(op.f("ix_registration_requests_desired_username"), "registration_requests", ["desired_username"], unique=False)
    op.create_index(op.f("ix_registration_requests_reviewer_user_id"), "registration_requests", ["reviewer_user_id"], unique=False)
    op.create_index(op.f("ix_registration_requests_status"), "registration_requests", ["status"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_registration_requests_status"), table_name="registration_requests")
    op.drop_index(op.f("ix_registration_requests_reviewer_user_id"), table_name="registration_requests")
    op.drop_index(op.f("ix_registration_requests_desired_username"), table_name="registration_requests")
    op.drop_index(op.f("ix_registration_requests_created_at"), table_name="registration_requests")
    op.drop_index(op.f("ix_registration_requests_contact_phone"), table_name="registration_requests")
    op.drop_index(op.f("ix_registration_requests_contact_email"), table_name="registration_requests")
    op.drop_table("registration_requests")

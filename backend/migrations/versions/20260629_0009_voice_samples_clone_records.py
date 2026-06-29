"""add voice samples and clone records

Revision ID: 20260629_0009
Revises: 20260629_0008
Create Date: 2026-06-29 23:59:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260629_0009"
down_revision: Union[str, Sequence[str], None] = "20260629_0008"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "voice_samples",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("profile_id", sa.String(length=32), nullable=False),
        sa.Column("file_name", sa.String(length=240), nullable=False),
        sa.Column("content_type", sa.String(length=120), nullable=False),
        sa.Column("storage_path", sa.Text(), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("duration_seconds", sa.Integer(), nullable=False),
        sa.Column("quality_status", sa.String(length=40), nullable=False),
        sa.Column("transcript", sa.Text(), nullable=False),
        sa.Column("uploaded_by", sa.String(length=80), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["profile_id"], ["voice_profiles.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_voice_samples_profile_id"), "voice_samples", ["profile_id"], unique=False)
    op.create_index(op.f("ix_voice_samples_quality_status"), "voice_samples", ["quality_status"], unique=False)

    op.create_table(
        "voice_clone_records",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("profile_id", sa.String(length=32), nullable=False),
        sa.Column("training_job_id", sa.String(length=32), nullable=True),
        sa.Column("cloned_voice_name", sa.String(length=120), nullable=False),
        sa.Column("engine", sa.String(length=80), nullable=False),
        sa.Column("status", sa.String(length=40), nullable=False),
        sa.Column("sample_count", sa.Integer(), nullable=False),
        sa.Column("sample_minutes", sa.Integer(), nullable=False),
        sa.Column("result", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["profile_id"], ["voice_profiles.id"]),
        sa.ForeignKeyConstraint(["training_job_id"], ["voice_training_jobs.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_voice_clone_records_profile_id"), "voice_clone_records", ["profile_id"], unique=False)
    op.create_index(
        op.f("ix_voice_clone_records_training_job_id"), "voice_clone_records", ["training_job_id"], unique=False
    )
    op.create_index(op.f("ix_voice_clone_records_status"), "voice_clone_records", ["status"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_voice_clone_records_status"), table_name="voice_clone_records")
    op.drop_index(op.f("ix_voice_clone_records_training_job_id"), table_name="voice_clone_records")
    op.drop_index(op.f("ix_voice_clone_records_profile_id"), table_name="voice_clone_records")
    op.drop_table("voice_clone_records")

    op.drop_index(op.f("ix_voice_samples_quality_status"), table_name="voice_samples")
    op.drop_index(op.f("ix_voice_samples_profile_id"), table_name="voice_samples")
    op.drop_table("voice_samples")

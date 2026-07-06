"""add registration request password hash

Revision ID: 20260704_0017
Revises: 20260704_0016
Create Date: 2026-07-04 10:45:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260704_0017"
down_revision: Union[str, Sequence[str], None] = "20260704_0016"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("registration_requests", sa.Column("password_hash", sa.String(length=255), nullable=True))


def downgrade() -> None:
    op.drop_column("registration_requests", "password_hash")

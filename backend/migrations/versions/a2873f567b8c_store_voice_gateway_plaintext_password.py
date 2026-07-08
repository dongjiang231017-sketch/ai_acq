"""store voice gateway plaintext password

Revision ID: a2873f567b8c
Revises: 20260704_0018
Create Date: 2026-07-06 14:34:42.457328

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a2873f567b8c'
down_revision: Union[str, Sequence[str], None] = '20260704_0018'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "voice_gateway_lines",
        sa.Column("sip_password_plaintext", sa.String(length=120), nullable=False, server_default=""),
    )
    op.alter_column("voice_gateway_lines", "sip_password_plaintext", server_default=None)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("voice_gateway_lines", "sip_password_plaintext")

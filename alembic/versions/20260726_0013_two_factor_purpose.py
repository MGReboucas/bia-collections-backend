"""add purpose and pending value to two-factor challenges

Revision ID: 20260726_0013
Revises: 20260726_0012
Create Date: 2026-07-26
"""

import sqlalchemy as sa
from alembic import op

revision = "20260726_0013"
down_revision = "20260726_0012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "login_2fa_challenges",
        sa.Column("finalidade", sa.String(length=40), server_default="login", nullable=False),
    )
    op.add_column(
        "login_2fa_challenges",
        sa.Column("valor_pendente", sa.String(length=255), nullable=True),
    )
    op.create_index(
        "ix_login_2fa_challenges_finalidade",
        "login_2fa_challenges",
        ["finalidade"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_login_2fa_challenges_finalidade",
        table_name="login_2fa_challenges",
    )
    op.drop_column("login_2fa_challenges", "valor_pendente")
    op.drop_column("login_2fa_challenges", "finalidade")

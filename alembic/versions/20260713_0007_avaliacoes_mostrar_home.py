"""add featured home flag to reviews

Revision ID: 20260713_0007
Revises: 20260713_0006
Create Date: 2026-07-13
"""

from alembic import op
import sqlalchemy as sa

revision = "20260713_0007"
down_revision = "20260713_0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "avaliacoes",
        sa.Column("mostrar_home", sa.Boolean(), nullable=False, server_default=sa.false()),
    )


def downgrade() -> None:
    op.drop_column("avaliacoes", "mostrar_home")

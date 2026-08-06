"""add product soft delete column

Revision ID: 20260806_0019
Revises: 20260806_0018
Create Date: 2026-08-06
"""

from alembic import op
import sqlalchemy as sa


revision = "20260806_0019"
down_revision = "20260806_0018"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "produtos",
        sa.Column("deletado_em", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("produtos", "deletado_em")

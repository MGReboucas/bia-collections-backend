"""add coupon soft delete column

Revision ID: 20260711_0004
Revises: 20260708_0003
Create Date: 2026-07-11
"""

from alembic import op
import sqlalchemy as sa

revision = "20260711_0004"
down_revision = "20260708_0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("cupons", sa.Column("deletado_em", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("cupons", "deletado_em")

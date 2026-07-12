"""add banner timestamps

Revision ID: 20260712_0005
Revises: 20260711_0004
Create Date: 2026-07-12
"""

from alembic import op
import sqlalchemy as sa

revision = "20260712_0005"
down_revision = "20260711_0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("banners", sa.Column("criado_em", sa.DateTime(timezone=True), nullable=True))
    op.add_column("banners", sa.Column("atualizado_em", sa.DateTime(timezone=True), nullable=True))
    op.execute("UPDATE banners SET criado_em = CURRENT_TIMESTAMP WHERE criado_em IS NULL")
    op.execute("UPDATE banners SET atualizado_em = CURRENT_TIMESTAMP WHERE atualizado_em IS NULL")


def downgrade() -> None:
    op.drop_column("banners", "atualizado_em")
    op.drop_column("banners", "criado_em")

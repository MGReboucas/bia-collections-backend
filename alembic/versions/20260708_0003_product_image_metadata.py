"""add product image metadata

Revision ID: 20260708_0003
Revises: 20260708_0002
Create Date: 2026-07-08
"""

from alembic import op
import sqlalchemy as sa

revision = "20260708_0003"
down_revision = "20260708_0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("produto_imagens", sa.Column("modelo_nome", sa.String(length=120), nullable=True))
    op.add_column("produto_imagens", sa.Column("modelo_cor", sa.String(length=120), nullable=True))
    op.add_column("produto_imagens", sa.Column("cor_nome", sa.String(length=120), nullable=True))


def downgrade() -> None:
    op.drop_column("produto_imagens", "cor_nome")
    op.drop_column("produto_imagens", "modelo_cor")
    op.drop_column("produto_imagens", "modelo_nome")

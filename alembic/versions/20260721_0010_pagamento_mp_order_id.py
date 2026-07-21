"""add mercado pago order id to payments

Revision ID: 20260721_0010
Revises: 20260715_0009
Create Date: 2026-07-21
"""

from alembic import op
import sqlalchemy as sa

revision = "20260721_0010"
down_revision = "20260715_0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("pagamentos", sa.Column("mp_order_id", sa.String(length=100), nullable=True))
    op.create_index(op.f("ix_pagamentos_mp_order_id"), "pagamentos", ["mp_order_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_pagamentos_mp_order_id"), table_name="pagamentos")
    op.drop_column("pagamentos", "mp_order_id")

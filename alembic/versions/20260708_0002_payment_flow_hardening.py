"""harden payment flow and order totals

Revision ID: 20260708_0002
Revises: 20260707_0001
Create Date: 2026-07-08
"""

from alembic import op
import sqlalchemy as sa

revision = "20260708_0002"
down_revision = "20260707_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("pedidos", sa.Column("subtotal", sa.Float(), nullable=True))
    op.add_column(
        "pedidos",
        sa.Column("valor_frete", sa.Float(), server_default="0", nullable=False),
    )
    op.add_column("pedidos", sa.Column("tipo_frete", sa.String(length=50), nullable=True))
    op.add_column("pedidos", sa.Column("prazo_frete", sa.String(length=100), nullable=True))
    op.execute("UPDATE pedidos SET subtotal = total WHERE subtotal IS NULL")

    op.add_column(
        "pagamentos",
        sa.Column("tipo", sa.String(length=30), server_default="pix", nullable=False),
    )
    op.add_column("pagamentos", sa.Column("valor", sa.Float(), nullable=True))
    op.add_column("pagamentos", sa.Column("idempotency_key", sa.String(length=120), nullable=True))
    op.add_column("pagamentos", sa.Column("mp_status", sa.String(length=50), nullable=True))
    op.create_index(op.f("ix_pagamentos_idempotency_key"), "pagamentos", ["idempotency_key"], unique=False)
    op.execute(
        """
        UPDATE pagamentos
        SET tipo = 'checkout_pro'
        WHERE mp_preference_id IS NOT NULL
        """
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_pagamentos_idempotency_key"), table_name="pagamentos")
    op.drop_column("pagamentos", "mp_status")
    op.drop_column("pagamentos", "idempotency_key")
    op.drop_column("pagamentos", "valor")
    op.drop_column("pagamentos", "tipo")

    op.drop_column("pedidos", "prazo_frete")
    op.drop_column("pedidos", "tipo_frete")
    op.drop_column("pedidos", "valor_frete")
    op.drop_column("pedidos", "subtotal")

"""add Meta Conversions API fields to orders

Revision ID: 20260802_0016
Revises: 20260729_0015
Create Date: 2026-08-02
"""

from alembic import op
import sqlalchemy as sa


revision = "20260802_0016"
down_revision = "20260729_0015"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("pedidos", sa.Column("meta_event_id", sa.String(length=120), nullable=True))
    op.add_column("pedidos", sa.Column("meta_fbp", sa.String(length=255), nullable=True))
    op.add_column("pedidos", sa.Column("meta_fbc", sa.String(length=255), nullable=True))
    op.add_column("pedidos", sa.Column("meta_source_url", sa.String(length=2048), nullable=True))
    op.add_column("pedidos", sa.Column("client_user_agent", sa.String(length=1024), nullable=True))
    op.add_column("pedidos", sa.Column("meta_purchase_enviado_em", sa.DateTime(timezone=True), nullable=True))
    op.add_column("pedidos", sa.Column("meta_purchase_payment_id", sa.String(length=100), nullable=True))
    op.create_index(
        "ix_pedidos_meta_purchase_payment_id",
        "pedidos",
        ["meta_purchase_payment_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_pedidos_meta_purchase_payment_id", table_name="pedidos")
    op.drop_column("pedidos", "meta_purchase_payment_id")
    op.drop_column("pedidos", "meta_purchase_enviado_em")
    op.drop_column("pedidos", "client_user_agent")
    op.drop_column("pedidos", "meta_source_url")
    op.drop_column("pedidos", "meta_fbc")
    op.drop_column("pedidos", "meta_fbp")
    op.drop_column("pedidos", "meta_event_id")

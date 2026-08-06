"""align review uniqueness with order number

Revision ID: 20260806_0018
Revises: 20260803_0017
Create Date: 2026-08-06
"""

from alembic import op


revision = "20260806_0018"
down_revision = "20260803_0017"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("avaliacoes") as batch_op:
        batch_op.drop_constraint("uq_avaliacoes_produto_usuario_pedido", type_="unique")
        batch_op.create_unique_constraint(
            "uq_avaliacoes_produto_usuario_pedido",
            ["produto_id", "usuario_id", "pedido_numero"],
        )


def downgrade() -> None:
    with op.batch_alter_table("avaliacoes") as batch_op:
        batch_op.drop_constraint("uq_avaliacoes_produto_usuario_pedido", type_="unique")
        batch_op.create_unique_constraint(
            "uq_avaliacoes_produto_usuario_pedido",
            ["produto_id", "usuario_id", "pedido_id"],
        )

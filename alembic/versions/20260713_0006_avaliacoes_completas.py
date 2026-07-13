"""complete product reviews

Revision ID: 20260713_0006
Revises: 20260712_0005
Create Date: 2026-07-13
"""

from alembic import op
import sqlalchemy as sa

revision = "20260713_0006"
down_revision = "20260712_0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("avaliacoes", sa.Column("pedido_id", sa.Integer(), nullable=True))
    op.add_column("avaliacoes", sa.Column("pedido_numero", sa.String(length=20), nullable=True))
    op.add_column("avaliacoes", sa.Column("atualizado_em", sa.DateTime(timezone=True), nullable=True))
    op.create_index(op.f("ix_avaliacoes_pedido_id"), "avaliacoes", ["pedido_id"], unique=False)
    op.create_index(op.f("ix_avaliacoes_pedido_numero"), "avaliacoes", ["pedido_numero"], unique=False)
    op.create_foreign_key("fk_avaliacoes_pedido_id_pedidos", "avaliacoes", "pedidos", ["pedido_id"], ["id"])
    op.create_unique_constraint(
        "uq_avaliacoes_produto_usuario_pedido",
        "avaliacoes",
        ["produto_id", "usuario_id", "pedido_id"],
    )
    op.create_table(
        "avaliacao_fotos",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("avaliacao_id", sa.Integer(), nullable=False),
        sa.Column("imagem_url", sa.String(length=500), nullable=False),
        sa.Column("ordem", sa.Integer(), nullable=False),
        sa.Column("criado_em", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=True),
        sa.ForeignKeyConstraint(["avaliacao_id"], ["avaliacoes.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_avaliacao_fotos_avaliacao_id"), "avaliacao_fotos", ["avaliacao_id"], unique=False)
    op.create_index(op.f("ix_avaliacao_fotos_id"), "avaliacao_fotos", ["id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_avaliacao_fotos_id"), table_name="avaliacao_fotos")
    op.drop_index(op.f("ix_avaliacao_fotos_avaliacao_id"), table_name="avaliacao_fotos")
    op.drop_table("avaliacao_fotos")
    op.drop_constraint("uq_avaliacoes_produto_usuario_pedido", "avaliacoes", type_="unique")
    op.drop_constraint("fk_avaliacoes_pedido_id_pedidos", "avaliacoes", type_="foreignkey")
    op.drop_index(op.f("ix_avaliacoes_pedido_numero"), table_name="avaliacoes")
    op.drop_index(op.f("ix_avaliacoes_pedido_id"), table_name="avaliacoes")
    op.drop_column("avaliacoes", "atualizado_em")
    op.drop_column("avaliacoes", "pedido_numero")
    op.drop_column("avaliacoes", "pedido_id")

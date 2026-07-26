"""add post-sale requests, order documents and refunds

Revision ID: 20260726_0012
Revises: 20260721_0011
Create Date: 2026-07-26
"""

import sqlalchemy as sa
from alembic import op

revision = "20260726_0012"
down_revision = "20260721_0011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "solicitacoes_pos_venda",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("protocolo", sa.String(length=40), nullable=False),
        sa.Column("pedido_id", sa.Integer(), nullable=False),
        sa.Column("usuario_id", sa.Integer(), nullable=False),
        sa.Column("tipo", sa.String(length=20), nullable=False),
        sa.Column("motivo", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("motivo_recusa", sa.Text(), nullable=True),
        sa.Column("criado_em", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("atualizado_em", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["pedido_id"], ["pedidos.id"]),
        sa.ForeignKeyConstraint(["usuario_id"], ["usuarios.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("protocolo", name="uq_solicitacoes_pos_venda_protocolo"),
    )
    op.create_index("ix_solicitacoes_pos_venda_pedido_id", "solicitacoes_pos_venda", ["pedido_id"])
    op.create_index("ix_solicitacoes_pos_venda_usuario_id", "solicitacoes_pos_venda", ["usuario_id"])
    op.create_index("ix_solicitacoes_pos_venda_status", "solicitacoes_pos_venda", ["status"])

    op.create_table(
        "documentos_pedido",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("pedido_id", sa.Integer(), nullable=False),
        sa.Column("tipo", sa.String(length=20), nullable=False),
        sa.Column("numero", sa.String(length=80), nullable=True),
        sa.Column("url", sa.String(length=1000), nullable=False),
        sa.Column("criado_em", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["pedido_id"], ["pedidos.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("pedido_id", "tipo", name="uq_documentos_pedido_tipo"),
    )
    op.create_index("ix_documentos_pedido_pedido_id", "documentos_pedido", ["pedido_id"])

    op.create_table(
        "reembolsos_pedido",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("pedido_id", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("valor", sa.Float(), nullable=False),
        sa.Column("prazo_dias_uteis", sa.Integer(), nullable=True),
        sa.Column("criado_em", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("atualizado_em", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["pedido_id"], ["pedidos.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_reembolsos_pedido_pedido_id", "reembolsos_pedido", ["pedido_id"])
    op.create_index("ix_reembolsos_pedido_status", "reembolsos_pedido", ["status"])


def downgrade() -> None:
    op.drop_index("ix_reembolsos_pedido_status", table_name="reembolsos_pedido")
    op.drop_index("ix_reembolsos_pedido_pedido_id", table_name="reembolsos_pedido")
    op.drop_table("reembolsos_pedido")
    op.drop_index("ix_documentos_pedido_pedido_id", table_name="documentos_pedido")
    op.drop_table("documentos_pedido")
    op.drop_index("ix_solicitacoes_pos_venda_status", table_name="solicitacoes_pos_venda")
    op.drop_index("ix_solicitacoes_pos_venda_usuario_id", table_name="solicitacoes_pos_venda")
    op.drop_index("ix_solicitacoes_pos_venda_pedido_id", table_name="solicitacoes_pos_venda")
    op.drop_table("solicitacoes_pos_venda")

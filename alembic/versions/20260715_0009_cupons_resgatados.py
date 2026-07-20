"""add claimed coupons per customer

Revision ID: 20260715_0009
Revises: 20260713_0008
Create Date: 2026-07-15
"""

from alembic import op
import sqlalchemy as sa

revision = "20260715_0009"
down_revision = "20260713_0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "cupons_resgatados",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("cupom_id", sa.Integer(), nullable=False),
        sa.Column("usuario_id", sa.Integer(), nullable=False),
        sa.Column("resgatado_em", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.ForeignKeyConstraint(["cupom_id"], ["cupons.id"]),
        sa.ForeignKeyConstraint(["usuario_id"], ["usuarios.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("cupom_id", "usuario_id", name="uq_cupom_resgatado_usuario"),
    )
    op.create_index(op.f("ix_cupons_resgatados_id"), "cupons_resgatados", ["id"], unique=False)
    op.create_index(op.f("ix_cupons_resgatados_cupom_id"), "cupons_resgatados", ["cupom_id"], unique=False)
    op.create_index(op.f("ix_cupons_resgatados_usuario_id"), "cupons_resgatados", ["usuario_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_cupons_resgatados_usuario_id"), table_name="cupons_resgatados")
    op.drop_index(op.f("ix_cupons_resgatados_cupom_id"), table_name="cupons_resgatados")
    op.drop_index(op.f("ix_cupons_resgatados_id"), table_name="cupons_resgatados")
    op.drop_table("cupons_resgatados")

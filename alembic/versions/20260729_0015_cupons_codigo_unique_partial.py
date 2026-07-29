"""allow coupon code reuse after soft delete

Revision ID: 20260729_0015
Revises: 20260726_0014
Create Date: 2026-07-29
"""

from alembic import op

revision = "20260729_0015"
down_revision = "20260726_0014"
branch_labels = None
depends_on = None


def upgrade() -> None:
    dialect = op.get_bind().dialect.name
    if dialect == "postgresql":
        for constraint_name in ("cupons_codigo_key", "uq_cupons_codigo", "ix_cupons_codigo"):
            op.execute(f"ALTER TABLE cupons DROP CONSTRAINT IF EXISTS {constraint_name}")
        op.execute("DROP INDEX IF EXISTS ix_cupons_codigo")
        op.execute("DROP INDEX IF EXISTS uq_cupons_codigo")
        op.execute("DROP INDEX IF EXISTS ix_cupons_codigo_nao_deletado")
        op.execute(
            "CREATE UNIQUE INDEX ix_cupons_codigo_nao_deletado "
            "ON cupons (codigo) WHERE deletado_em IS NULL"
        )
        return

    if dialect == "sqlite":
        op.execute("DROP INDEX IF EXISTS ix_cupons_codigo")
        op.execute("DROP INDEX IF EXISTS ix_cupons_codigo_nao_deletado")
        op.execute(
            "CREATE UNIQUE INDEX ix_cupons_codigo_nao_deletado "
            "ON cupons (codigo) WHERE deletado_em IS NULL"
        )
        return

    raise NotImplementedError("Partial unique coupon code index is supported for PostgreSQL and SQLite.")


def downgrade() -> None:
    dialect = op.get_bind().dialect.name
    if dialect in {"postgresql", "sqlite"}:
        op.execute("DROP INDEX IF EXISTS ix_cupons_codigo_nao_deletado")
        op.execute("CREATE UNIQUE INDEX ix_cupons_codigo ON cupons (codigo)")
        return

    raise NotImplementedError("Coupon code uniqueness downgrade is supported for PostgreSQL and SQLite.")

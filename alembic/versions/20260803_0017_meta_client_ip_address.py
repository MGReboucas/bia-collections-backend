"""add client IP address for Meta Conversions API

Revision ID: 20260803_0017
Revises: 20260802_0016
Create Date: 2026-08-03
"""

from alembic import op
import sqlalchemy as sa


revision = "20260803_0017"
down_revision = "20260802_0016"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("pedidos", sa.Column("client_ip_address", sa.String(length=64), nullable=True))


def downgrade() -> None:
    op.drop_column("pedidos", "client_ip_address")

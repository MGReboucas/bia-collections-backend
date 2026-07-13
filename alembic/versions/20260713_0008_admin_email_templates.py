"""add admin email template fields

Revision ID: 20260713_0008
Revises: 20260713_0007
Create Date: 2026-07-13
"""

from alembic import op
import sqlalchemy as sa

revision = "20260713_0008"
down_revision = "20260713_0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("email_templates", sa.Column("nome", sa.String(length=120), nullable=True))
    op.add_column("email_templates", sa.Column("evento", sa.String(length=80), nullable=True))
    op.add_column("email_templates", sa.Column("status", sa.String(length=20), nullable=True))
    op.add_column("email_templates", sa.Column("html", sa.Text(), nullable=True))
    op.create_index(op.f("ix_email_templates_nome"), "email_templates", ["nome"], unique=False)
    op.create_index(op.f("ix_email_templates_evento"), "email_templates", ["evento"], unique=False)
    op.create_index(op.f("ix_email_templates_status"), "email_templates", ["status"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_email_templates_status"), table_name="email_templates")
    op.drop_index(op.f("ix_email_templates_evento"), table_name="email_templates")
    op.drop_index(op.f("ix_email_templates_nome"), table_name="email_templates")
    op.drop_column("email_templates", "html")
    op.drop_column("email_templates", "status")
    op.drop_column("email_templates", "evento")
    op.drop_column("email_templates", "nome")

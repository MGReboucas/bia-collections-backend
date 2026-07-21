"""normalize email log statuses

Revision ID: 20260721_0011
Revises: 20260721_0010
Create Date: 2026-07-21
"""

from alembic import op

revision = "20260721_0011"
down_revision = "20260721_0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("UPDATE email_logs SET status = 'pendente' WHERE status IN ('queued', 'scheduled')")
    op.execute("UPDATE email_logs SET status = 'enviado' WHERE status = 'sent'")
    op.execute("UPDATE email_logs SET status = 'erro' WHERE status = 'failed'")


def downgrade() -> None:
    op.execute("UPDATE email_logs SET status = 'queued' WHERE status = 'pendente'")
    op.execute("UPDATE email_logs SET status = 'sent' WHERE status = 'enviado'")
    op.execute("UPDATE email_logs SET status = 'failed' WHERE status = 'erro'")

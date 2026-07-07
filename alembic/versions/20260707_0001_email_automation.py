"""create email automation tables

Revision ID: 20260707_0001
Revises:
Create Date: 2026-07-07
"""

from alembic import op
import sqlalchemy as sa

revision = "20260707_0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "email_templates",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("slug", sa.String(length=120), nullable=False),
        sa.Column("category", sa.String(length=80), nullable=False),
        sa.Column("subject", sa.String(length=255), nullable=False),
        sa.Column("preheader", sa.String(length=255), nullable=True),
        sa.Column("html_template", sa.Text(), nullable=False),
        sa.Column("text_template", sa.Text(), nullable=False),
        sa.Column("variables_schema", sa.Text(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("slug"),
    )
    op.create_index(op.f("ix_email_templates_category"), "email_templates", ["category"], unique=False)
    op.create_index(op.f("ix_email_templates_id"), "email_templates", ["id"], unique=False)
    op.create_index(op.f("ix_email_templates_slug"), "email_templates", ["slug"], unique=True)

    op.create_table(
        "email_automations",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("event_key", sa.String(length=120), nullable=False),
        sa.Column("email_template_id", sa.Integer(), nullable=False),
        sa.Column("channel", sa.String(length=40), nullable=False),
        sa.Column("delay_minutes", sa.Integer(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=True),
        sa.ForeignKeyConstraint(["email_template_id"], ["email_templates.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_email_automations_email_template_id"), "email_automations", ["email_template_id"], unique=False)
    op.create_index(op.f("ix_email_automations_event_key"), "email_automations", ["event_key"], unique=False)
    op.create_index(op.f("ix_email_automations_id"), "email_automations", ["id"], unique=False)

    op.create_table(
        "email_logs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=True),
        sa.Column("order_id", sa.Integer(), nullable=True),
        sa.Column("email", sa.String(length=255), nullable=False),
        sa.Column("template_slug", sa.String(length=120), nullable=False),
        sa.Column("event_key", sa.String(length=120), nullable=False),
        sa.Column("dedupe_key", sa.String(length=255), nullable=True),
        sa.Column("status", sa.String(length=40), nullable=False),
        sa.Column("provider", sa.String(length=60), nullable=True),
        sa.Column("provider_message_id", sa.String(length=255), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("subject", sa.String(length=255), nullable=True),
        sa.Column("html_snapshot", sa.Text(), nullable=True),
        sa.Column("text_snapshot", sa.Text(), nullable=True),
        sa.Column("payload_json", sa.Text(), nullable=True),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=True),
        sa.ForeignKeyConstraint(["order_id"], ["pedidos.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["usuarios.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_email_logs_dedupe_key"), "email_logs", ["dedupe_key"], unique=False)
    op.create_index(op.f("ix_email_logs_email"), "email_logs", ["email"], unique=False)
    op.create_index(op.f("ix_email_logs_event_key"), "email_logs", ["event_key"], unique=False)
    op.create_index(op.f("ix_email_logs_id"), "email_logs", ["id"], unique=False)
    op.create_index(op.f("ix_email_logs_next_attempt_at"), "email_logs", ["next_attempt_at"], unique=False)
    op.create_index(op.f("ix_email_logs_order_id"), "email_logs", ["order_id"], unique=False)
    op.create_index(op.f("ix_email_logs_status"), "email_logs", ["status"], unique=False)
    op.create_index(op.f("ix_email_logs_template_slug"), "email_logs", ["template_slug"], unique=False)
    op.create_index(op.f("ix_email_logs_user_id"), "email_logs", ["user_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_email_logs_user_id"), table_name="email_logs")
    op.drop_index(op.f("ix_email_logs_template_slug"), table_name="email_logs")
    op.drop_index(op.f("ix_email_logs_status"), table_name="email_logs")
    op.drop_index(op.f("ix_email_logs_order_id"), table_name="email_logs")
    op.drop_index(op.f("ix_email_logs_next_attempt_at"), table_name="email_logs")
    op.drop_index(op.f("ix_email_logs_id"), table_name="email_logs")
    op.drop_index(op.f("ix_email_logs_event_key"), table_name="email_logs")
    op.drop_index(op.f("ix_email_logs_email"), table_name="email_logs")
    op.drop_index(op.f("ix_email_logs_dedupe_key"), table_name="email_logs")
    op.drop_table("email_logs")

    op.drop_index(op.f("ix_email_automations_id"), table_name="email_automations")
    op.drop_index(op.f("ix_email_automations_event_key"), table_name="email_automations")
    op.drop_index(op.f("ix_email_automations_email_template_id"), table_name="email_automations")
    op.drop_table("email_automations")

    op.drop_index(op.f("ix_email_templates_slug"), table_name="email_templates")
    op.drop_index(op.f("ix_email_templates_id"), table_name="email_templates")
    op.drop_index(op.f("ix_email_templates_category"), table_name="email_templates")
    op.drop_table("email_templates")


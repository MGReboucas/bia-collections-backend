"""add complete marketing automation platform

Revision ID: 20260726_0014
Revises: 20260726_0013
Create Date: 2026-07-26
"""

from alembic import op
import sqlalchemy as sa

revision = "20260726_0014"
down_revision = "20260726_0013"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "marketing_preferences",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("usuarios.id", ondelete="CASCADE"), nullable=False),
        sa.Column("email_consent", sa.Boolean(), server_default="1", nullable=False),
        sa.Column("consent_source", sa.String(60), nullable=False),
        sa.Column("consented_at", sa.DateTime(timezone=True)),
        sa.Column("unsubscribed_at", sa.DateTime(timezone=True)),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("user_id"),
    )
    op.create_index("ix_marketing_preferences_user_id", "marketing_preferences", ["user_id"], unique=True)
    op.create_table(
        "email_campaigns",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(160), nullable=False),
        sa.Column("template_a_id", sa.Integer(), sa.ForeignKey("email_templates.id"), nullable=False),
        sa.Column("template_b_id", sa.Integer(), sa.ForeignKey("email_templates.id")),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("segment", sa.String(40), nullable=False),
        sa.Column("ab_percentage", sa.Integer(), nullable=False),
        sa.Column("frequency_cap_days", sa.Integer(), nullable=False),
        sa.Column("payload_json", sa.Text()),
        sa.Column("scheduled_at", sa.DateTime(timezone=True)),
        sa.Column("approved_at", sa.DateTime(timezone=True)),
        sa.Column("approved_by_id", sa.Integer(), sa.ForeignKey("usuarios.id")),
        sa.Column("created_by_id", sa.Integer(), sa.ForeignKey("usuarios.id"), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_email_campaigns_status", "email_campaigns", ["status"])
    op.create_index("ix_email_campaigns_scheduled_at", "email_campaigns", ["scheduled_at"])
    op.create_table(
        "email_campaign_recipients",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("campaign_id", sa.Integer(), sa.ForeignKey("email_campaigns.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("usuarios.id", ondelete="CASCADE"), nullable=False),
        sa.Column("email", sa.String(255), nullable=False),
        sa.Column("variant", sa.String(1), nullable=False),
        sa.Column("email_log_id", sa.Integer(), sa.ForeignKey("email_logs.id")),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("converted_order_id", sa.Integer(), sa.ForeignKey("pedidos.id")),
        sa.Column("converted_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("campaign_id", "user_id", name="uq_campaign_recipient_user"),
    )
    op.create_index("ix_campaign_recipients_campaign", "email_campaign_recipients", ["campaign_id"])
    op.create_index("ix_campaign_recipients_user", "email_campaign_recipients", ["user_id"])
    op.create_table(
        "email_tracking_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("email_log_id", sa.Integer(), sa.ForeignKey("email_logs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("campaign_id", sa.Integer(), sa.ForeignKey("email_campaigns.id", ondelete="CASCADE")),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("usuarios.id", ondelete="SET NULL")),
        sa.Column("event_type", sa.String(30), nullable=False),
        sa.Column("target_url", sa.Text()),
        sa.Column("ip_hash", sa.String(64)),
        sa.Column("user_agent", sa.String(500)),
        sa.Column("occurred_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_tracking_log", "email_tracking_events", ["email_log_id"])
    op.create_index("ix_tracking_campaign", "email_tracking_events", ["campaign_id"])
    op.create_index("ix_tracking_type", "email_tracking_events", ["event_type"])
    op.create_table(
        "product_stock_interests",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("usuarios.id", ondelete="CASCADE"), nullable=False),
        sa.Column("product_id", sa.Integer(), sa.ForeignKey("produtos.id", ondelete="CASCADE"), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default="1", nullable=False),
        sa.Column("notified_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("user_id", "product_id", name="uq_stock_interest_user_product"),
    )
    op.create_index("ix_stock_interest_product", "product_stock_interests", ["product_id"])
    op.create_index("ix_stock_interest_user", "product_stock_interests", ["user_id"])


def downgrade() -> None:
    op.drop_table("product_stock_interests")
    op.drop_table("email_tracking_events")
    op.drop_table("email_campaign_recipients")
    op.drop_table("email_campaigns")
    op.drop_table("marketing_preferences")

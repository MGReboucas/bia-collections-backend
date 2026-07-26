from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.database import Base


class EmailTemplate(Base):
    __tablename__ = "email_templates"

    id = Column(Integer, primary_key=True, index=True)
    nome = Column(String(120), nullable=True, index=True)
    evento = Column(String(80), nullable=True, index=True)
    status = Column(String(20), nullable=True, index=True)
    html = Column(Text, nullable=True)
    name = Column(String(120), nullable=False)
    slug = Column(String(120), nullable=False, unique=True, index=True)
    category = Column(String(80), nullable=False, index=True)
    subject = Column(String(255), nullable=False)
    preheader = Column(String(255), nullable=True)
    html_template = Column(Text, nullable=False)
    text_template = Column(Text, nullable=False)
    variables_schema = Column(Text, nullable=False, default="{}")
    is_active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    automations = relationship("EmailAutomation", back_populates="template")


class EmailAutomation(Base):
    __tablename__ = "email_automations"

    id = Column(Integer, primary_key=True, index=True)
    event_key = Column(String(120), nullable=False, index=True)
    email_template_id = Column(Integer, ForeignKey("email_templates.id"), nullable=False, index=True)
    channel = Column(String(40), nullable=False, default="email")
    delay_minutes = Column(Integer, nullable=False, default=0)
    is_active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    template = relationship("EmailTemplate", back_populates="automations")


class EmailLog(Base):
    __tablename__ = "email_logs"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("usuarios.id"), nullable=True, index=True)
    order_id = Column(Integer, ForeignKey("pedidos.id"), nullable=True, index=True)
    email = Column(String(255), nullable=False, index=True)
    template_slug = Column(String(120), nullable=False, index=True)
    event_key = Column(String(120), nullable=False, index=True)
    dedupe_key = Column(String(255), nullable=True, index=True)
    status = Column(String(40), nullable=False, default="pendente", index=True)
    provider = Column(String(60), nullable=True)
    provider_message_id = Column(String(255), nullable=True)
    error_message = Column(Text, nullable=True)
    subject = Column(String(255), nullable=True)
    html_snapshot = Column(Text, nullable=True)
    text_snapshot = Column(Text, nullable=True)
    payload_json = Column(Text, nullable=True)
    attempts = Column(Integer, nullable=False, default=0)
    next_attempt_at = Column(DateTime(timezone=True), nullable=True, index=True)
    sent_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class MarketingPreference(Base):
    __tablename__ = "marketing_preferences"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("usuarios.id", ondelete="CASCADE"), nullable=False, unique=True, index=True)
    email_consent = Column(Boolean, nullable=False, default=True, server_default="1")
    consent_source = Column(String(60), nullable=False, default="cadastro")
    consented_at = Column(DateTime(timezone=True), nullable=True)
    unsubscribed_at = Column(DateTime(timezone=True), nullable=True)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class EmailCampaign(Base):
    __tablename__ = "email_campaigns"

    id = Column(Integer, primary_key=True)
    name = Column(String(160), nullable=False)
    template_a_id = Column(Integer, ForeignKey("email_templates.id"), nullable=False, index=True)
    template_b_id = Column(Integer, ForeignKey("email_templates.id"), nullable=True, index=True)
    status = Column(String(30), nullable=False, default="rascunho", index=True)
    segment = Column(String(40), nullable=False, default="todos")
    ab_percentage = Column(Integer, nullable=False, default=50)
    frequency_cap_days = Column(Integer, nullable=False, default=7)
    payload_json = Column(Text, nullable=True)
    scheduled_at = Column(DateTime(timezone=True), nullable=True, index=True)
    approved_at = Column(DateTime(timezone=True), nullable=True)
    approved_by_id = Column(Integer, ForeignKey("usuarios.id"), nullable=True)
    created_by_id = Column(Integer, ForeignKey("usuarios.id"), nullable=False)
    started_at = Column(DateTime(timezone=True), nullable=True)
    completed_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    template_a = relationship("EmailTemplate", foreign_keys=[template_a_id])
    template_b = relationship("EmailTemplate", foreign_keys=[template_b_id])


class EmailCampaignRecipient(Base):
    __tablename__ = "email_campaign_recipients"
    __table_args__ = (UniqueConstraint("campaign_id", "user_id", name="uq_campaign_recipient_user"),)

    id = Column(Integer, primary_key=True)
    campaign_id = Column(Integer, ForeignKey("email_campaigns.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("usuarios.id", ondelete="CASCADE"), nullable=False, index=True)
    email = Column(String(255), nullable=False, index=True)
    variant = Column(String(1), nullable=False, default="A")
    email_log_id = Column(Integer, ForeignKey("email_logs.id"), nullable=True, index=True)
    status = Column(String(30), nullable=False, default="pendente", index=True)
    converted_order_id = Column(Integer, ForeignKey("pedidos.id"), nullable=True)
    converted_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class EmailTrackingEvent(Base):
    __tablename__ = "email_tracking_events"

    id = Column(Integer, primary_key=True)
    email_log_id = Column(Integer, ForeignKey("email_logs.id", ondelete="CASCADE"), nullable=False, index=True)
    campaign_id = Column(Integer, ForeignKey("email_campaigns.id", ondelete="CASCADE"), nullable=True, index=True)
    user_id = Column(Integer, ForeignKey("usuarios.id", ondelete="SET NULL"), nullable=True, index=True)
    event_type = Column(String(30), nullable=False, index=True)
    target_url = Column(Text, nullable=True)
    ip_hash = Column(String(64), nullable=True)
    user_agent = Column(String(500), nullable=True)
    occurred_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)


class ProductStockInterest(Base):
    __tablename__ = "product_stock_interests"
    __table_args__ = (UniqueConstraint("user_id", "product_id", name="uq_stock_interest_user_product"),)

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("usuarios.id", ondelete="CASCADE"), nullable=False, index=True)
    product_id = Column(Integer, ForeignKey("produtos.id", ondelete="CASCADE"), nullable=False, index=True)
    is_active = Column(Boolean, nullable=False, default=True, server_default="1")
    notified_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

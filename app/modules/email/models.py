from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.database import Base


class EmailTemplate(Base):
    __tablename__ = "email_templates"

    id = Column(Integer, primary_key=True, index=True)
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
    status = Column(String(40), nullable=False, default="queued", index=True)
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

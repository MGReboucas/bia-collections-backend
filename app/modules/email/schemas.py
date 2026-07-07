from datetime import datetime
from typing import Optional

from pydantic import BaseModel, field_validator


class EmailTemplateBase(BaseModel):
    name: str
    slug: str
    category: str
    subject: str
    preheader: Optional[str] = None
    html_template: str
    text_template: str
    variables_schema: str = "{}"
    is_active: bool = True

    @field_validator("name", "slug", "category", "subject")
    @classmethod
    def required_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Campo obrigatorio.")
        return value

    @field_validator("slug")
    @classmethod
    def slug_format(cls, value: str) -> str:
        return value.strip().lower().replace(" ", "-")


class EmailTemplateCreate(EmailTemplateBase):
    pass


class EmailTemplateUpdate(BaseModel):
    name: Optional[str] = None
    slug: Optional[str] = None
    category: Optional[str] = None
    subject: Optional[str] = None
    preheader: Optional[str] = None
    html_template: Optional[str] = None
    text_template: Optional[str] = None
    variables_schema: Optional[str] = None
    is_active: Optional[bool] = None


class EmailTemplateOut(EmailTemplateBase):
    id: int
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


class EmailTemplateStatusUpdate(BaseModel):
    is_active: bool


class EmailAutomationCreate(BaseModel):
    event_key: str
    email_template_id: int
    channel: str = "email"
    delay_minutes: int = 0
    is_active: bool = True

    @field_validator("event_key", "channel")
    @classmethod
    def required_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Campo obrigatorio.")
        return value

    @field_validator("delay_minutes")
    @classmethod
    def delay_valid(cls, value: int) -> int:
        if value < 0:
            raise ValueError("Delay nao pode ser negativo.")
        return value


class EmailAutomationUpdate(BaseModel):
    event_key: Optional[str] = None
    email_template_id: Optional[int] = None
    channel: Optional[str] = None
    delay_minutes: Optional[int] = None
    is_active: Optional[bool] = None


class EmailAutomationStatusUpdate(BaseModel):
    is_active: bool


class EmailAutomationOut(BaseModel):
    id: int
    event_key: str
    email_template_id: int
    channel: str
    delay_minutes: int
    is_active: bool
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    template_slug: Optional[str] = None
    template_name: Optional[str] = None

    model_config = {"from_attributes": True}


class EmailLogOut(BaseModel):
    id: int
    user_id: Optional[int] = None
    order_id: Optional[int] = None
    email: str
    template_slug: str
    event_key: str
    dedupe_key: Optional[str] = None
    status: str
    provider: Optional[str] = None
    provider_message_id: Optional[str] = None
    error_message: Optional[str] = None
    attempts: int
    next_attempt_at: Optional[datetime] = None
    sent_at: Optional[datetime] = None
    created_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


class RetryEmailResponse(BaseModel):
    id: int
    status: str
    message: str

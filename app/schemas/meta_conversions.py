from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field, field_validator, model_validator


MetaWebEventName = Literal["PageView", "ViewContent", "AddToCart", "InitiateCheckout"]


class MetaEventUserData(BaseModel):
    email: Optional[str] = None
    phone: Optional[str] = None
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    city: Optional[str] = None
    state: Optional[str] = None
    zip_code: Optional[str] = None
    country: Optional[str] = "br"
    external_id: Optional[str] = None
    fbp: Optional[str] = None
    fbc: Optional[str] = None
    client_user_agent: Optional[str] = None
    client_ip_address: Optional[str] = None

    @field_validator("*", mode="before")
    @classmethod
    def texto_opcional(cls, value: Any) -> str | None:
        if value is None:
            return None
        value = str(value).strip()
        return value or None


class MetaEventContent(BaseModel):
    id: str
    quantity: int = Field(1, ge=1)
    item_price: Optional[float] = Field(None, ge=0)
    title: Optional[str] = None

    @field_validator("id", "title", mode="before")
    @classmethod
    def texto_opcional(cls, value: Any) -> str | None:
        if value is None:
            return None
        value = str(value).strip()
        return value or None


class MetaEventCustomData(BaseModel):
    currency: Optional[str] = "BRL"
    value: Optional[float] = Field(None, ge=0)
    content_type: Optional[str] = "product"
    content_ids: list[str] = Field(default_factory=list)
    contents: list[MetaEventContent] = Field(default_factory=list)
    content_name: Optional[str] = None
    num_items: Optional[float] = Field(None, ge=0)
    search_string: Optional[str] = None
    order_id: Optional[str] = None

    @field_validator("currency")
    @classmethod
    def moeda_maiuscula(cls, value: Optional[str]) -> Optional[str]:
        value = str(value or "").strip().upper()
        return value or None

    @field_validator("content_type", "content_name", "search_string", "order_id", mode="before")
    @classmethod
    def texto_opcional(cls, value: Any) -> str | None:
        if value is None:
            return None
        value = str(value).strip()
        return value or None

    @field_validator("content_ids", mode="before")
    @classmethod
    def ids_opcionais(cls, value: Any) -> list[str]:
        if value is None:
            return []
        if not isinstance(value, list):
            return [str(value).strip()]
        return [str(item).strip() for item in value if str(item).strip()]

    @model_validator(mode="after")
    def preencher_ids_e_quantidade(self):
        if self.contents and not self.content_ids:
            self.content_ids = [content.id for content in self.contents]
        if self.contents and self.num_items is None:
            self.num_items = sum(content.quantity for content in self.contents)
        return self


class MetaEventRequest(BaseModel):
    event_name: MetaWebEventName
    event_id: str = Field(..., min_length=1, max_length=120)
    event_source_url: str = Field(..., min_length=8, max_length=2048)
    event_time: Optional[int] = None
    fbp: Optional[str] = None
    fbc: Optional[str] = None
    client_user_agent: Optional[str] = None
    user_data: Optional[MetaEventUserData] = None
    custom_data: Optional[MetaEventCustomData] = None

    @field_validator("event_id", "event_source_url", "fbp", "fbc", "client_user_agent", mode="before")
    @classmethod
    def texto_opcional(cls, value: Any) -> str | None:
        if value is None:
            return None
        value = str(value).strip()
        return value or None

    @field_validator("event_source_url")
    @classmethod
    def url_http(cls, value: str) -> str:
        if not value.startswith(("http://", "https://")):
            raise ValueError("event_source_url deve comecar com http:// ou https://.")
        return value

    @field_validator("event_time")
    @classmethod
    def event_time_recente(cls, value: Optional[int]) -> Optional[int]:
        if value is None:
            return None
        now = int(datetime.now(timezone.utc).timestamp())
        if value > now + 300:
            raise ValueError("event_time nao pode estar no futuro.")
        if value < now - 7 * 24 * 60 * 60:
            raise ValueError("event_time nao pode ter mais de 7 dias.")
        return value


class MetaEventResponse(BaseModel):
    event_name: str
    event_id: str
    sent_to_meta: bool
    configured: bool

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, HttpUrl, field_validator, model_validator


class SolicitacaoPosVendaCreate(BaseModel):
    pedido_numero: str
    tipo: Literal["troca", "devolucao"]
    motivo: str = Field(min_length=10, max_length=2000)

    @field_validator("pedido_numero", "motivo")
    @classmethod
    def limpar_texto(cls, value: str) -> str:
        return value.strip()


class SolicitacaoPosVendaUpdate(BaseModel):
    status: Literal["aprovada", "recusada"]
    motivo_recusa: str | None = Field(default=None, max_length=2000)

    @model_validator(mode="after")
    def validar_motivo_recusa(self):
        if self.status == "recusada" and not (self.motivo_recusa or "").strip():
            raise ValueError("Motivo da recusa e obrigatorio.")
        self.motivo_recusa = (self.motivo_recusa or "").strip() or None
        return self


class SolicitacaoPosVendaOut(BaseModel):
    id: int
    protocolo: str
    pedido_numero: str
    usuario_id: int
    tipo: str
    motivo: str
    status: str
    motivo_recusa: str | None = None
    criado_em: datetime
    atualizado_em: datetime


class DocumentoPedidoCreate(BaseModel):
    tipo: Literal["nota_fiscal", "recibo"]
    numero: str | None = Field(default=None, max_length=80)
    url: HttpUrl

    @field_validator("numero")
    @classmethod
    def limpar_numero(cls, value: str | None) -> str | None:
        return (value or "").strip() or None


class DocumentoPedidoOut(BaseModel):
    id: int
    pedido_numero: str
    tipo: str
    numero: str | None
    url: str
    criado_em: datetime


class ReembolsoAprovarPayload(BaseModel):
    valor: float = Field(gt=0)
    prazo_dias_uteis: int = Field(default=7, ge=1, le=90)


class ReembolsoOut(BaseModel):
    id: int
    pedido_numero: str
    status: str
    valor: float
    prazo_dias_uteis: int | None
    criado_em: datetime
    atualizado_em: datetime

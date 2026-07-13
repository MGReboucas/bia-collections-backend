from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator


EmailEvento = Literal[
    "pedido_criado",
    "pagamento_aprovado",
    "pedido_enviado",
    "recuperacao_senha",
    "codigo_acesso",
    "cupom_disponivel",
    "manual",
]
EmailStatus = Literal["ativo", "rascunho"]


class AdminEmailTemplatePayload(BaseModel):
    nome: str
    assunto: str
    evento: EmailEvento
    status: EmailStatus
    html: str

    @field_validator("nome", "assunto", "evento", "status", "html")
    @classmethod
    def campo_obrigatorio(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Campo obrigatorio.")
        return value


class AdminEmailTemplateOut(BaseModel):
    id: int
    nome: str
    assunto: str
    evento: EmailEvento
    status: EmailStatus
    html: str
    atualizado_em: datetime | None = None


class AdminEmailTestePayload(BaseModel):
    email_destino: str
    variaveis: dict[str, str] = Field(default_factory=dict)

    @field_validator("email_destino")
    @classmethod
    def email_destino_obrigatorio(cls, value: str) -> str:
        value = value.strip().lower()
        if not value:
            raise ValueError("Email de destino e obrigatorio.")
        if "@" not in value:
            raise ValueError("Email de destino invalido.")
        return value

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator


EmailEvento = Literal[
    "boas_vindas",
    "pedido_criado",
    "pagamento_aprovado",
    "pagamento_recusado",
    "pagamento_pendente",
    "pagamento_expirado",
    "pedido_preparando",
    "pedido_enviado",
    "pedido_entregue",
    "pedido_cancelado",
    "reembolso_aprovado",
    "reembolso_processado",
    "nota_fiscal_recibo",
    "troca_devolucao_recebida",
    "troca_devolucao_aprovada",
    "troca_devolucao_recusada",
    "recuperacao_senha",
    "codigo_acesso",
    "senha_alterada",
    "dados_sensiveis_alterados",
    "produto_voltou_estoque",
    "carrinho_abandonado",
    "cupom_disponivel",
    "avaliacao_pedido",
    "interno_novo_pedido",
    "interno_pagamento_confirmado",
    "interno_estoque_baixo",
    "interno_troca_devolucao",
    "interno_falha_operacional",
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
    criado_em: datetime | None = None
    atualizado_em: datetime | None = None


class AdminEmailTestePayload(BaseModel):
    email_destino: str
    variaveis: dict[str, Any] = Field(default_factory=dict)

    @field_validator("email_destino")
    @classmethod
    def email_destino_obrigatorio(cls, value: str) -> str:
        value = value.strip().lower()
        if not value:
            raise ValueError("Email de destino e obrigatorio.")
        if "@" not in value:
            raise ValueError("Email de destino invalido.")
        return value


class AdminEmailManualRecipient(BaseModel):
    email: str
    user_id: int | None = None
    variaveis: dict[str, Any] = Field(default_factory=dict)

    @field_validator("email")
    @classmethod
    def email_obrigatorio(cls, value: str) -> str:
        value = value.strip().lower()
        if not value:
            raise ValueError("Email e obrigatorio.")
        if "@" not in value:
            raise ValueError("Email invalido.")
        return value


class AdminEmailEnviarManualPayload(BaseModel):
    destinatarios: list[AdminEmailManualRecipient] = Field(default_factory=list)
    usuario_ids: list[int] = Field(default_factory=list)
    variaveis: dict[str, Any] = Field(default_factory=dict)

    @field_validator("usuario_ids")
    @classmethod
    def usuario_ids_validos(cls, value: list[int]) -> list[int]:
        if any(item < 1 for item in value):
            raise ValueError("IDs de usuarios devem ser positivos.")
        return value

    @model_validator(mode="after")
    def ao_menos_um_destinatario(self):
        if not self.destinatarios and not self.usuario_ids:
            raise ValueError("Informe ao menos um destinatario.")
        return self


class AdminEmailManualLogOut(BaseModel):
    id: int
    email: str
    status: str


class AdminEmailManualSendResponse(BaseModel):
    message: str
    total: int
    enviados: int
    falhas: int
    logs: list[AdminEmailManualLogOut]

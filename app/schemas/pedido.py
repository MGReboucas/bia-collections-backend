from pydantic import BaseModel, Field, field_validator
from typing import Optional, List


class EnderecoSnapshot(BaseModel):
    cep: str
    rua: str
    numero: str
    complemento: Optional[str] = None
    bairro: str
    cidade: str
    estado: str


class ItemPedidoRequest(BaseModel):
    produto_id: int
    quantidade: int = Field(..., ge=1)
    tamanho: Optional[str] = None
    cor: Optional[str] = None


class FretePedidoRequest(BaseModel):
    nome: Optional[str] = None
    prazo: Optional[str] = None
    valor: float = 0.0

    @field_validator("valor")
    @classmethod
    def valor_nao_negativo(cls, value: float) -> float:
        if value < 0:
            raise ValueError("Valor do frete não pode ser negativo.")
        return value


class CriarPedidoRequest(BaseModel):
    itens: List[ItemPedidoRequest]
    endereco: EnderecoSnapshot
    forma_pagamento: str
    frete: Optional[FretePedidoRequest] = None
    cupom_codigo: Optional[str] = None


class CriarPedidoResponse(BaseModel):
    numero_pedido: str
    subtotal: float
    total: float
    total_formatado: str
    valor_frete: float
    valor_frete_formatado: str
    desconto_aplicado: float
    forma_pagamento: str
    status: str


class PagamentoCartaoIdentificacao(BaseModel):
    type: str
    number: str

    @field_validator("type", "number")
    @classmethod
    def campo_obrigatorio(cls, value: str) -> str:
        value = str(value or "").strip()
        if not value:
            raise ValueError("Identificacao do pagador e obrigatoria.")
        return value


class PagamentoCartaoPagador(BaseModel):
    email: str
    identification: PagamentoCartaoIdentificacao

    @field_validator("email")
    @classmethod
    def email_obrigatorio(cls, value: str) -> str:
        value = str(value or "").strip()
        if not value:
            raise ValueError("Email do pagador e obrigatorio.")
        return value


class PagamentoCartaoRequest(BaseModel):
    token: str
    payment_method_id: str
    issuer_id: str
    installments: int = Field(..., ge=1)
    transaction_amount: float = Field(..., gt=0)
    payer: PagamentoCartaoPagador

    @field_validator("token", "payment_method_id", "issuer_id")
    @classmethod
    def campo_obrigatorio(cls, value: str) -> str:
        value = str(value or "").strip()
        if not value:
            raise ValueError("Dados do cartao incompletos.")
        return value


class PagamentoCartaoResponse(BaseModel):
    payment_id: str
    status: str
    mp_status: str
    status_detail: Optional[str] = None
    status_pedido: str
    payment_method_id: str


class PedidoListItem(BaseModel):
    numero: str
    data: str
    status: str
    total_formatado: str
    total_itens: int


class ItemPedidoDetalhe(BaseModel):
    produto_id: int
    nome_produto: str
    preco_unitario: float
    preco_formatado: str
    tamanho: Optional[str] = None
    cor: Optional[str] = None
    quantidade: int


class PedidoDetalhe(BaseModel):
    numero: str
    data: str
    status: str
    forma_pagamento: str
    subtotal: float
    total: float
    total_formatado: str
    valor_frete: float
    valor_frete_formatado: str
    tipo_frete: Optional[str] = None
    prazo_frete: Optional[str] = None
    desconto_aplicado: float
    endereco: EnderecoSnapshot
    itens: List[ItemPedidoDetalhe]

from pydantic import BaseModel
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
    quantidade: int
    tamanho: Optional[str] = None
    cor: Optional[str] = None


class CriarPedidoRequest(BaseModel):
    itens: List[ItemPedidoRequest]
    endereco: EnderecoSnapshot
    forma_pagamento: str
    cupom_codigo: Optional[str] = None


class CriarPedidoResponse(BaseModel):
    numero_pedido: str
    total: float
    total_formatado: str
    desconto_aplicado: float
    forma_pagamento: str
    status: str


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
    total: float
    total_formatado: str
    desconto_aplicado: float
    endereco: EnderecoSnapshot
    itens: List[ItemPedidoDetalhe]

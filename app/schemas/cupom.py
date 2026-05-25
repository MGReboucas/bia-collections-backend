from pydantic import BaseModel
from typing import Optional, List


class CupomAtivo(BaseModel):
    codigo: str
    descricao: str
    tipo: str
    valor: str
    validade: str


class CupomUsadoResponse(BaseModel):
    codigo: str
    descricao: str
    tipo: str
    valor: str
    validade: str
    pedido: str


class CuponsResponse(BaseModel):
    ativos: List[CupomAtivo]
    usados: List[CupomUsadoResponse]


class ValidarCupomRequest(BaseModel):
    codigo: str
    total_pedido: float


class ValidarCupomResponse(BaseModel):
    valido: bool
    tipo: Optional[str] = None
    valor_desconto: Optional[float] = None
    mensagem: str

from pydantic import AliasChoices, BaseModel, Field, field_validator
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
    pedido: str
    usado_em: str


class CuponsResponse(BaseModel):
    ativos: List[CupomAtivo]
    usados: List[CupomUsadoResponse]


class ValidarCupomRequest(BaseModel):
    codigo: str
    total: float = Field(..., validation_alias=AliasChoices("total", "total_pedido"))
    valor_frete: float = 0.0

    @field_validator("codigo")
    @classmethod
    def codigo_obrigatorio(cls, value: str) -> str:
        value = value.strip().upper()
        if not value:
            raise ValueError("Codigo do cupom e obrigatorio.")
        return value

    @field_validator("total", "valor_frete")
    @classmethod
    def valores_nao_negativos(cls, value: float) -> float:
        if value < 0:
            raise ValueError("Valor nao pode ser negativo.")
        return value


class ValidarCupomResponse(BaseModel):
    valido: bool
    codigo: str = ""
    descricao: str = ""
    tipo: str = ""
    valor_desconto: float = 0.0
    desconto_formatado: str = ""
    total_com_desconto: float = 0.0
    total_formatado: str = ""
    mensagem: Optional[str] = None

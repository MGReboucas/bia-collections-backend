from pydantic import AliasChoices, BaseModel, Field, field_validator
from typing import Optional, List


class CupomAtivo(BaseModel):
    codigo: str
    descricao: str
    tipo: str
    valor: str
    validade: str
    valor_minimo_pedido: float = 0.0
    resgatado_em: Optional[str] = None


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


class AdicionarCupomRequest(BaseModel):
    codigo: str

    @field_validator("codigo")
    @classmethod
    def normalizar_codigo(cls, value: str) -> str:
        value = value.strip().upper()
        if not value:
            raise ValueError("Código do cupom é obrigatório.")
        return value


class AdicionarCupomResponse(BaseModel):
    mensagem: str
    ja_adicionado: bool = False
    cupom: CupomAtivo


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

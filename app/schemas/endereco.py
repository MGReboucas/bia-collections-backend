from pydantic import BaseModel, field_validator
from typing import Optional


class EnderecoCreate(BaseModel):
    apelido: str
    cep: str
    rua: str
    numero: str
    complemento: Optional[str] = None
    bairro: str
    cidade: str
    estado: str

    @field_validator("apelido")
    @classmethod
    def apelido_valido(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("Apelido não pode ser vazio.")
        if len(v) > 50:
            raise ValueError("Apelido deve ter no máximo 50 caracteres.")
        return v

    @field_validator("cep")
    @classmethod
    def cep_valido(cls, v: str) -> str:
        cep = v.strip().replace("-", "").replace(".", "")
        if not cep.isdigit() or len(cep) != 8:
            raise ValueError("CEP inválido. Use o formato 00000-000.")
        return cep

    @field_validator("rua")
    @classmethod
    def rua_valida(cls, v: str) -> str:
        v = v.strip()
        if not v or len(v) > 200:
            raise ValueError("Rua inválida (máx 200 caracteres).")
        return v

    @field_validator("numero")
    @classmethod
    def numero_valido(cls, v: str) -> str:
        v = v.strip()
        if not v or len(v) > 20:
            raise ValueError("Número inválido (máx 20 caracteres).")
        return v

    @field_validator("complemento")
    @classmethod
    def complemento_valido(cls, v: Optional[str]) -> Optional[str]:
        if v is not None:
            v = v.strip()
            if len(v) > 100:
                raise ValueError("Complemento deve ter no máximo 100 caracteres.")
            return v or None
        return v

    @field_validator("bairro")
    @classmethod
    def bairro_valido(cls, v: str) -> str:
        v = v.strip()
        if not v or len(v) > 100:
            raise ValueError("Bairro inválido (máx 100 caracteres).")
        return v

    @field_validator("cidade")
    @classmethod
    def cidade_valida(cls, v: str) -> str:
        v = v.strip()
        if not v or len(v) > 100:
            raise ValueError("Cidade inválida (máx 100 caracteres).")
        return v

    @field_validator("estado")
    @classmethod
    def estado_valido(cls, v: str) -> str:
        v = v.strip().upper()
        estados_br = {
            "AC", "AL", "AP", "AM", "BA", "CE", "DF", "ES", "GO",
            "MA", "MT", "MS", "MG", "PA", "PB", "PR", "PE", "PI",
            "RJ", "RN", "RS", "RO", "RR", "SC", "SP", "SE", "TO",
        }
        if v not in estados_br:
            raise ValueError("Estado inválido. Use a sigla (ex: SP).")
        return v


class EnderecoResponse(BaseModel):
    id: int
    apelido: str
    rua: str
    numero: str
    complemento: Optional[str] = None
    bairro: str
    cidade: str
    estado: str
    cep: str

    model_config = {"from_attributes": True}

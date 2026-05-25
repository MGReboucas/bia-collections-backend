from pydantic import BaseModel, field_validator
from typing import Optional
from datetime import datetime


class DuvidaCreate(BaseModel):
    produto_id: Optional[int] = None
    produto_nome: Optional[str] = None
    pergunta: str

    @field_validator("pergunta")
    @classmethod
    def pergunta_nao_vazia(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("A pergunta não pode ser vazia.")
        if len(v) > 1000:
            raise ValueError("A pergunta deve ter no máximo 1000 caracteres.")
        return v


class DuvidaOut(BaseModel):
    id: int
    produto_id: Optional[int] = None
    produto_nome: Optional[str] = None
    pergunta: str
    resposta: Optional[str] = None
    status: str
    criado_em: datetime
    respondida_em: Optional[datetime] = None

    model_config = {"from_attributes": True}

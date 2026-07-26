from pydantic import BaseModel, field_validator
from typing import Optional


class UsuarioPerfil(BaseModel):
    id: int
    username: str
    email: str
    nome_completo: Optional[str] = None
    telefone: Optional[str] = None
    foto_url: Optional[str] = None
    is_admin: bool = False

    model_config = {"from_attributes": True}


class AtualizarPerfil(BaseModel):
    nome_completo: Optional[str] = None
    email: Optional[str] = None
    telefone: Optional[str] = None


class SolicitarAlteracaoEmail(BaseModel):
    novo_email: str

    @field_validator("novo_email")
    @classmethod
    def validar_email(cls, value: str) -> str:
        value = value.strip().lower()
        if "@" not in value or len(value) > 255:
            raise ValueError("E-mail inválido.")
        return value


class ConfirmarAlteracaoEmail(BaseModel):
    token: str
    codigo: str

    @field_validator("token", "codigo")
    @classmethod
    def campo_obrigatorio(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Campo obrigatório.")
        return value

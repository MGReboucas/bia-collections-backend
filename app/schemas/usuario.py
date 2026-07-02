from pydantic import BaseModel
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

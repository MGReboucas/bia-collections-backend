from pydantic import BaseModel, EmailStr
from typing import Optional
from datetime import datetime


class ClientRegister(BaseModel):
    nome_cliente: str
    email: EmailStr
    telefone: str
    cpf: str
    senha: str
    aceitou_politica_privacidade: bool
    aceitou_termos_uso: bool


class ClientLogin(BaseModel):
    email: EmailStr
    senha: str


class ClientResponse(BaseModel):
    id: int
    nome_cliente: str
    email: str
    telefone: Optional[str] = None
    cpf: Optional[str] = None
    email_verificado: bool
    status: str
    created_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    client: ClientResponse

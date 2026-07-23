from pydantic import BaseModel, field_validator
from typing import Optional


class LoginRequest(BaseModel):
    login: str
    senha: str

    @field_validator("login")
    @classmethod
    def login_max(cls, v: str) -> str:
        if len(v) > 255:
            raise ValueError("Login muito longo.")
        return v.strip()

    @field_validator("senha")
    @classmethod
    def senha_max(cls, v: str) -> str:
        if len(v) > 128:
            raise ValueError("Senha muito longa.")
        return v


class CadastroRequest(BaseModel):
    username: str
    email: str
    senha: str
    confirma_senha: str

    @field_validator("username")
    @classmethod
    def username_valido(cls, v: str) -> str:
        v = v.strip()
        if len(v) < 3:
            raise ValueError("Username deve ter pelo menos 3 caracteres.")
        if len(v) > 50:
            raise ValueError("Username deve ter no máximo 50 caracteres.")
        return v

    @field_validator("email")
    @classmethod
    def email_valido(cls, v: str) -> str:
        v = v.strip()
        if "@" not in v or len(v) > 255:
            raise ValueError("Email inválido.")
        return v

    @field_validator("senha")
    @classmethod
    def senha_minima(cls, v: str) -> str:
        if len(v) < 8:
            raise ValueError("Senha deve ter pelo menos 8 caracteres.")
        if len(v) > 128:
            raise ValueError("Senha muito longa.")
        return v


class RecuperarSenhaRequest(BaseModel):
    email: str


class SolicitarRedefinicaoRequest(BaseModel):
    email: str


class VerificarCodigoRequest(BaseModel):
    email: str
    codigo: str


class RedefinirSenhaRequest(BaseModel):
    email: str
    codigo: str
    nova_senha: str
    confirma_senha: str

    @field_validator("nova_senha")
    @classmethod
    def senha_minima(cls, v: str) -> str:
        if len(v) < 8:
            raise ValueError("Senha deve ter pelo menos 8 caracteres.")
        if len(v) > 128:
            raise ValueError("Senha muito longa.")
        return v


class UsuarioBasico(BaseModel):
    id: int
    username: str
    email: str
    nome_completo: Optional[str] = None
    is_admin: bool = False
    foto_url: Optional[str] = None

    model_config = {"from_attributes": True}


class TokenResponse(BaseModel):
    access_token: Optional[str] = None
    token_type: str = "bearer"
    csrf_token: Optional[str] = None
    usuario: UsuarioBasico


class TwoFactorChallengeResponse(BaseModel):
    requires_2fa: bool = True
    two_factor_token: str
    email: str
    expires_in: int
    resend_cooldown_seconds: int
    message: str


class VerifyTwoFactorRequest(BaseModel):
    two_factor_token: str
    codigo: str

    @field_validator("two_factor_token")
    @classmethod
    def token_valido(cls, v: str) -> str:
        v = v.strip()
        if not v or len(v) > 255:
            raise ValueError("Token de desafio invalido.")
        return v

    @field_validator("codigo")
    @classmethod
    def codigo_valido(cls, v: str) -> str:
        v = v.strip()
        if len(v) != 6 or not v.isdigit():
            raise ValueError("Codigo invalido.")
        return v


class ResendTwoFactorRequest(BaseModel):
    two_factor_token: str

    @field_validator("two_factor_token")
    @classmethod
    def token_valido(cls, v: str) -> str:
        v = v.strip()
        if not v or len(v) > 255:
            raise ValueError("Token de desafio invalido.")
        return v


class ResendTwoFactorResponse(BaseModel):
    two_factor_token: str
    email: str
    expires_in: int
    resend_cooldown_seconds: int
    message: str

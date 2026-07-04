from typing import List
from pydantic import field_validator
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    DATABASE_URL: str = "sqlite:///./curadobem.db"
    SECRET_KEY: str  # obrigatório — deve estar no .env
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_DAYS: int = 7
    # kept for backward compatibility
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 10080  # 7 days
    MASTER_ADMIN_EMAIL: str = "reboucas444@gmail.com"

    # CORS — lista de origens permitidas (separadas por vírgula no .env)
    # Ex: ALLOWED_ORIGINS=http://localhost:3000,https://meusite.com
    ALLOWED_ORIGINS: List[str] = ["*"]

    # SMTP — configure in .env
    SMTP_HOST: str = "smtp.gmail.com"
    SMTP_PORT: int = 587
    SMTP_USER: str = ""
    SMTP_PASSWORD: str = ""
    SMTP_FROM: str = ""
    EMAIL_FROM: str = ""

    TWO_FACTOR_CODE_EXPIRE_SECONDS: int = 600
    TWO_FACTOR_MAX_ATTEMPTS: int = 5
    TWO_FACTOR_RESEND_COOLDOWN_SECONDS: int = 60
    TWO_FACTOR_RESEND_HOURLY_LIMIT: int = 5

    # Mercado Pago — configure in .env
    MP_ACCESS_TOKEN: str = ""
    # URL pública do backend para receber webhooks do MP (ex: https://api.seusite.com)
    MP_NOTIFICATION_URL: str = ""
    # URL pública do frontend (ex: https://seusite.com ou https://seusite.vercel.app)
    FRONTEND_URL: str = "http://localhost:3000"

    # Cloudinary — configure in .env para storage persistente em produção
    # Obtenha em: https://cloudinary.com (free tier)
    CLOUDINARY_CLOUD_NAME: str = ""
    CLOUDINARY_API_KEY: str = ""
    CLOUDINARY_API_SECRET: str = ""

    @field_validator("SECRET_KEY")
    @classmethod
    def secret_key_forte(cls, v: str) -> str:
        if len(v) < 32:
            raise ValueError(
                "SECRET_KEY deve ter pelo menos 32 caracteres. "
                "Gere uma com: python -c \"import secrets; print(secrets.token_hex(32))\""
            )
        return v

    @field_validator("MASTER_ADMIN_EMAIL")
    @classmethod
    def master_admin_email_valido(cls, v: str) -> str:
        v = v.strip().lower()
        if "@" not in v or len(v) > 255:
            raise ValueError("MASTER_ADMIN_EMAIL inválido.")
        return v

    @property
    def email_from_address(self) -> str:
        return self.SMTP_FROM or self.EMAIL_FROM or self.SMTP_USER or "no-reply@bia-collections.com"

    model_config = {"env_file": ".env"}


settings = Settings()

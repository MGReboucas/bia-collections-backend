import json
from typing import Any, List, Optional
from pydantic import field_validator
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    APP_ENV: str = "development"
    ENVIRONMENT: str = ""
    DATABASE_URL: str = "sqlite:///./curadobem.db"
    SECRET_KEY: str  # obrigatório — deve estar no .env
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_DAYS: int = 7
    # kept for backward compatibility
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 10080  # 7 days
    MASTER_ADMIN_EMAIL: str = "reboucas444@gmail.com"
    ADMIN_ORDER_NOTIFICATION_EMAIL: str = ""

    # CORS — lista de origens permitidas (separadas por vírgula no .env)
    # Ex: ALLOWED_ORIGINS=http://localhost:3000,https://meusite.com
    ALLOWED_ORIGINS: List[str] = [
        "https://www.biacollections.com",
        "https://biacollections.com",
        "http://localhost:3000",
        "http://127.0.0.1:3000",
    ]

    SESSION_COOKIE_NAME: str = "cb_token"
    CSRF_COOKIE_NAME: str = "cb_csrf"
    COOKIE_DOMAIN: str = ""
    COOKIE_SAMESITE: str = "lax"
    COOKIE_SECURE: Optional[bool] = None
    AUTH_RETURN_ACCESS_TOKEN: bool = True
    RATE_LIMIT_ENABLED: Optional[bool] = None

    # Email — configure in .env / Render
    EMAIL_PROVIDER: str = "auto"  # auto, resend, brevo, smtp
    EMAIL_FROM_NAME: str = "Bia Collections"
    EMAIL_FROM: str = ""
    EMAIL_LOGO_URL: str = ""
    STORE_NAME: str = "Bia Collections"
    STORE_URL: str = ""

    # HTTP email APIs
    RESEND_API_KEY: str = ""
    RESEND_API_URL: str = "https://api.resend.com/emails"
    BREVO_API_KEY: str = ""
    BREVO_API_URL: str = "https://api.brevo.com/v3/smtp/email"

    # SMTP fallback
    SMTP_HOST: str = "smtp.gmail.com"
    SMTP_PORT: int = 587
    SMTP_USER: str = ""
    SMTP_PASSWORD: str = ""
    SMTP_FROM: str = ""

    TWO_FACTOR_CODE_EXPIRE_SECONDS: int = 600
    TWO_FACTOR_MAX_ATTEMPTS: int = 5
    TWO_FACTOR_RESEND_COOLDOWN_SECONDS: int = 60
    TWO_FACTOR_RESEND_HOURLY_LIMIT: int = 5

    # Email queue. Use REDIS_URL + EMAIL_QUEUE_BACKEND=rq for RQ workers.
    REDIS_URL: str = ""
    EMAIL_QUEUE_BACKEND: str = "auto"  # auto, rq, thread
    EMAIL_QUEUE_NAME: str = "bia-email"

    # Mercado Pago — configure in .env
    MP_ACCESS_TOKEN: str = ""
    # URL pública do backend para receber webhooks do MP (ex: https://api.seusite.com)
    MP_NOTIFICATION_URL: str = ""
    MP_WEBHOOK_SECRET: str = ""
    REQUIRE_MP_WEBHOOK_SECRET: Optional[bool] = None
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

    @field_validator("ALLOWED_ORIGINS", mode="before")
    @classmethod
    def allowed_origins_validas(cls, value: Any) -> list[str]:
        if value is None or value == "":
            return []
        if isinstance(value, str):
            raw = value.strip()
            if raw == "*":
                return ["*"]
            if raw.startswith("["):
                parsed = json.loads(raw)
                if not isinstance(parsed, list):
                    raise ValueError("ALLOWED_ORIGINS deve ser uma lista de origens.")
                value = parsed
            else:
                value = raw.split(",")

        origins = []
        for origin in value:
            origin = str(origin).strip().rstrip("/")
            if origin:
                origins.append(origin)
        return origins

    @field_validator("COOKIE_SAMESITE")
    @classmethod
    def cookie_samesite_valido(cls, value: str) -> str:
        value = value.strip().lower()
        if value not in {"lax", "strict", "none"}:
            raise ValueError("COOKIE_SAMESITE deve ser lax, strict ou none.")
        return value

    @field_validator("MASTER_ADMIN_EMAIL")
    @classmethod
    def master_admin_email_valido(cls, v: str) -> str:
        v = v.strip().lower()
        if "@" not in v or len(v) > 255:
            raise ValueError("MASTER_ADMIN_EMAIL inválido.")
        return v

    @field_validator("ADMIN_ORDER_NOTIFICATION_EMAIL")
    @classmethod
    def admin_order_notification_email_valido(cls, v: str) -> str:
        v = v.strip().lower()
        if v and ("@" not in v or len(v) > 255):
            raise ValueError("ADMIN_ORDER_NOTIFICATION_EMAIL invalido.")
        return v

    @property
    def email_from_address(self) -> str:
        return self.SMTP_FROM or self.EMAIL_FROM or self.SMTP_USER

    @property
    def admin_order_notification_email(self) -> str:
        return self.ADMIN_ORDER_NOTIFICATION_EMAIL or self.MASTER_ADMIN_EMAIL

    @property
    def environment_name(self) -> str:
        return (self.ENVIRONMENT or self.APP_ENV or "development").strip().lower()

    @property
    def is_production(self) -> bool:
        return self.environment_name in {"prod", "production"}

    @property
    def cookie_secure(self) -> bool:
        if self.COOKIE_SECURE is not None:
            return self.COOKIE_SECURE
        return self.is_production

    @property
    def cookie_domain(self) -> str | None:
        return self.COOKIE_DOMAIN.strip() or None

    @property
    def cookie_samesite(self) -> str:
        if self.COOKIE_SAMESITE == "none" and not self.cookie_secure:
            return "lax"
        return self.COOKIE_SAMESITE

    @property
    def rate_limit_enabled(self) -> bool:
        if self.RATE_LIMIT_ENABLED is not None:
            return self.RATE_LIMIT_ENABLED
        return self.is_production

    @property
    def require_mp_webhook_secret(self) -> bool:
        if self.REQUIRE_MP_WEBHOOK_SECRET is not None:
            return self.REQUIRE_MP_WEBHOOK_SECRET
        return self.is_production

    @property
    def allowed_origins(self) -> list[str]:
        if self.is_production and "*" in self.ALLOWED_ORIGINS:
            raise ValueError("ALLOWED_ORIGINS nao pode usar * em producao.")
        return self.ALLOWED_ORIGINS

    model_config = {"env_file": ".env", "extra": "ignore"}


settings = Settings()

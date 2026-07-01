import os
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded

import app.models  # noqa: F401 — registers all models with Base before create_all()
from app.core.database import Base, engine, SessionLocal
from app.core.config import settings
from app.core.security import get_password_hash, verify_password
from app.routers import admin, auth, produtos, categorias, cep, frete, pedidos, usuario, enderecos, cupons, duvidas, pagamentos
from app.models.usuario import Usuario
from sqlalchemy import text

Base.metadata.create_all(bind=engine)

# ── Startup migrations ────────────────────────────────────────────────────────
with engine.connect() as _conn:
    _conn.execute(text(
        "ALTER TABLE usuarios ADD COLUMN IF NOT EXISTS is_admin BOOLEAN NOT NULL DEFAULT FALSE"
    ))
    _conn.commit()

# ── Garante usuário admin via .env ────────────────────────────────────────────
if settings.ADMIN_USERNAME and settings.ADMIN_PASSWORD:
    _db = SessionLocal()
    try:
        _admin = _db.query(Usuario).filter(Usuario.username == settings.ADMIN_USERNAME).first()
        if not _admin:
            _admin = Usuario(
                username=settings.ADMIN_USERNAME,
                email=f"{settings.ADMIN_USERNAME}@curadobem.com",
                senha_hash=get_password_hash(settings.ADMIN_PASSWORD),
                nome_completo="Admin",
                is_admin=True,
            )
            _db.add(_admin)
        else:
            if not verify_password(settings.ADMIN_PASSWORD, _admin.senha_hash):
                _admin.senha_hash = get_password_hash(settings.ADMIN_PASSWORD)
            _admin.is_admin = True
        _db.commit()
    finally:
        _db.close()

os.makedirs("uploads", exist_ok=True)

limiter = Limiter(key_func=get_remote_address)

app = FastAPI(title="Bia Collections API", version="1.0.0")
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

app.mount("/uploads", StaticFiles(directory="uploads"), name="uploads")

# CORS — usamos Bearer token no header Authorization, não cookies.
# allow_credentials=False é correto para esse modelo de auth.
# Em produção, restrinja ALLOWED_ORIGINS no .env.
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.ALLOWED_ORIGINS,
    allow_credentials=False,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
)

app.include_router(auth, prefix="/api/v1")
app.include_router(produtos, prefix="/api/v1")
app.include_router(categorias, prefix="/api/v1")
app.include_router(cep, prefix="/api/v1")
app.include_router(frete, prefix="/api/v1")
app.include_router(pedidos, prefix="/api/v1")
app.include_router(usuario, prefix="/api/v1")
app.include_router(enderecos, prefix="/api/v1")
app.include_router(cupons, prefix="/api/v1")
app.include_router(duvidas, prefix="/api/v1")
app.include_router(pagamentos, prefix="/api/v1")
app.include_router(admin, prefix="/api/v1")


@app.get("/")
def root():
    return {"message": "Bia Collections API is running"}


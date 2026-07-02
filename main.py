import os
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded

import app.models  # noqa: F401 — registers all models with Base before create_all()
from app.core.database import Base, engine
from app.core.config import settings
from app.routers import admin, auth, produtos, categorias, cep, frete, pedidos, usuario, enderecos, cupons, duvidas, pagamentos
from sqlalchemy import inspect, text

Base.metadata.create_all(bind=engine)

# ── Startup migrations ────────────────────────────────────────────────────────
_inspector = inspect(engine)
if "is_admin" not in {column["name"] for column in _inspector.get_columns("usuarios")}:
    default_value = "0" if engine.dialect.name == "sqlite" else "FALSE"
    with engine.connect() as _conn:
        _conn.execute(text(
            f"ALTER TABLE usuarios ADD COLUMN is_admin BOOLEAN NOT NULL DEFAULT {default_value}"
        ))
        _conn.commit()

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


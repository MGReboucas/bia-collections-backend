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
from app.routers import admin, auth, produtos, categorias, cep, frete, pedidos, usuario, enderecos, cupons, duvidas, pagamentos, banners, avaliacoes
from app.modules.email.routes import router as email_admin_router
from app.modules.email.seeds import seed_email_automation
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

if "imagem_url" not in {column["name"] for column in inspect(engine).get_columns("categorias")}:
    with engine.connect() as _conn:
        _conn.execute(text("ALTER TABLE categorias ADD COLUMN imagem_url VARCHAR(500)"))
        _conn.commit()

# ── New column migrations ─────────────────────────────────────────────────────
_pedidos_cols = {col["name"] for col in inspect(engine).get_columns("pedidos")}
if "codigo_rastreio" not in _pedidos_cols:
    with engine.connect() as _conn:
        _conn.execute(text("ALTER TABLE pedidos ADD COLUMN codigo_rastreio VARCHAR(100)"))
        _conn.commit()
for _column_name, _definition in {
    "subtotal": "FLOAT",
    "valor_frete": "FLOAT NOT NULL DEFAULT 0",
    "tipo_frete": "VARCHAR(50)",
    "prazo_frete": "VARCHAR(100)",
}.items():
    if _column_name not in _pedidos_cols:
        with engine.connect() as _conn:
            _conn.execute(text(f"ALTER TABLE pedidos ADD COLUMN {_column_name} {_definition}"))
            if _column_name == "subtotal":
                _conn.execute(text("UPDATE pedidos SET subtotal = total WHERE subtotal IS NULL"))
            _conn.commit()

if "pagamentos" in set(inspect(engine).get_table_names()):
    _pagamentos_cols = {col["name"] for col in inspect(engine).get_columns("pagamentos")}
    for _column_name, _definition in {
        "tipo": "VARCHAR(30) NOT NULL DEFAULT 'pix'",
        "valor": "FLOAT",
        "idempotency_key": "VARCHAR(120)",
        "mp_status": "VARCHAR(50)",
    }.items():
        if _column_name not in _pagamentos_cols:
            with engine.connect() as _conn:
                _conn.execute(text(f"ALTER TABLE pagamentos ADD COLUMN {_column_name} {_definition}"))
                if _column_name == "tipo":
                    _conn.execute(
                        text(
                            """
                            UPDATE pagamentos
                            SET tipo = 'checkout_pro'
                            WHERE mp_preference_id IS NOT NULL
                            """
                        )
                    )
                _conn.commit()

_cupons_cols = {col["name"] for col in inspect(engine).get_columns("cupons")}
if "max_usos" not in _cupons_cols:
    with engine.connect() as _conn:
        _conn.execute(text("ALTER TABLE cupons ADD COLUMN max_usos INTEGER"))
        _conn.commit()
if "total_usos" not in _cupons_cols:
    with engine.connect() as _conn:
        _conn.execute(text("ALTER TABLE cupons ADD COLUMN total_usos INTEGER NOT NULL DEFAULT 0"))
        _conn.commit()
if "deletado_em" not in _cupons_cols:
    deletado_em_type = "DATETIME" if engine.dialect.name == "sqlite" else "TIMESTAMP WITH TIME ZONE"
    with engine.connect() as _conn:
        _conn.execute(text(f"ALTER TABLE cupons ADD COLUMN deletado_em {deletado_em_type}"))
        _conn.commit()

if "banners" in set(inspect(engine).get_table_names()):
    _banners_cols = {col["name"] for col in inspect(engine).get_columns("banners")}
    banner_datetime_type = "DATETIME" if engine.dialect.name == "sqlite" else "TIMESTAMP WITH TIME ZONE"
    for _column_name in ("criado_em", "atualizado_em"):
        if _column_name not in _banners_cols:
            with engine.connect() as _conn:
                _conn.execute(text(f"ALTER TABLE banners ADD COLUMN {_column_name} {banner_datetime_type}"))
                _conn.execute(text(f"UPDATE banners SET {_column_name} = CURRENT_TIMESTAMP WHERE {_column_name} IS NULL"))
                _conn.commit()

_produtos_cols = {col["name"] for col in inspect(engine).get_columns("produtos")}
if "preco_promocional" not in _produtos_cols:
    with engine.connect() as _conn:
        _conn.execute(text("ALTER TABLE produtos ADD COLUMN preco_promocional DECIMAL(10,2)"))
        _conn.commit()
if "estoque" not in _produtos_cols:
    with engine.connect() as _conn:
        _conn.execute(text("ALTER TABLE produtos ADD COLUMN estoque INTEGER"))
        _conn.commit()

if "produto_imagens" in set(inspect(engine).get_table_names()):
    _produto_imagens_cols = {col["name"] for col in inspect(engine).get_columns("produto_imagens")}
    for _column_name in ("modelo_nome", "modelo_cor", "cor_nome"):
        if _column_name not in _produto_imagens_cols:
            with engine.connect() as _conn:
                _conn.execute(text(f"ALTER TABLE produto_imagens ADD COLUMN {_column_name} VARCHAR(120)"))
                _conn.commit()

    with engine.begin() as _conn:
        _conn.execute(
            text(
                """
                INSERT INTO produto_imagens (produto_id, imagem_url, ordem, principal)
                SELECT p.id, p.imagem_url, 0, :principal
                FROM produtos p
                WHERE p.imagem_url IS NOT NULL
                  AND trim(p.imagem_url) != ''
                  AND NOT EXISTS (
                    SELECT 1
                    FROM produto_imagens pi
                    WHERE pi.produto_id = p.id
                  )
                """
            ),
            {"principal": True},
        )
        _conn.execute(
            text(
                """
                UPDATE produtos
                SET imagem_url = (
                    SELECT pi.imagem_url
                    FROM produto_imagens pi
                    WHERE pi.produto_id = produtos.id
                    ORDER BY pi.principal DESC, pi.ordem ASC, pi.id ASC
                    LIMIT 1
                )
                WHERE (imagem_url IS NULL OR trim(imagem_url) = '')
                  AND EXISTS (
                    SELECT 1
                    FROM produto_imagens pi
                    WHERE pi.produto_id = produtos.id
                  )
                """
            )
        )

_table_names = set(inspect(engine).get_table_names())
if "avaliacoes" in _table_names:
    _avaliacoes_cols = {col["name"] for col in inspect(engine).get_columns("avaliacoes")}
    avaliacao_datetime_type = "DATETIME" if engine.dialect.name == "sqlite" else "TIMESTAMP WITH TIME ZONE"
    for _column_name, _definition in {
        "pedido_id": "INTEGER",
        "pedido_numero": "VARCHAR(20)",
        "atualizado_em": avaliacao_datetime_type,
        "mostrar_home": "BOOLEAN NOT NULL DEFAULT 0",
    }.items():
        if _column_name not in _avaliacoes_cols:
            with engine.connect() as _conn:
                _conn.execute(text(f"ALTER TABLE avaliacoes ADD COLUMN {_column_name} {_definition}"))
                _conn.commit()

with engine.begin() as _conn:
    _conn.execute(
        text("UPDATE usuarios SET is_admin = :is_admin WHERE lower(trim(email)) = :email"),
        {"is_admin": True, "email": settings.MASTER_ADMIN_EMAIL.strip().lower()},
    )

seed_email_automation()

os.makedirs("uploads", exist_ok=True)

limiter = Limiter(key_func=get_remote_address)

app = FastAPI(title="Bia Collections API", version="1.0.0")
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

app.mount("/uploads", StaticFiles(directory="uploads"), name="uploads")

# CORS — when using httpOnly cookies, allow_credentials must be True and
# ALLOWED_ORIGINS must NOT be ["*"]. Set ALLOWED_ORIGINS in .env for production.
_origins = settings.ALLOWED_ORIGINS
_allow_credentials = "*" not in _origins

app.add_middleware(
    CORSMiddleware,
    allow_origins=_origins,
    allow_credentials=_allow_credentials,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "Cookie"],
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
app.include_router(banners, prefix="/api/v1")
app.include_router(avaliacoes, prefix="/api/v1")
app.include_router(admin, prefix="/api/v1")
app.include_router(email_admin_router, prefix="/api/v1")


@app.get("/")
def root():
    return {"message": "Bia Collections API is running"}


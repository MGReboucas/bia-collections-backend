import sys, os
sys.path.insert(0, os.path.dirname(__file__))

from app.core.config import settings
from app.core.database import engine
from sqlalchemy import text

MASTER_ADMIN_EMAIL = settings.MASTER_ADMIN_EMAIL.strip().lower()

# Step 1: add column in its own transaction
with engine.connect() as conn:
    try:
        conn.execute(text("ALTER TABLE usuarios ADD COLUMN is_admin BOOLEAN NOT NULL DEFAULT FALSE"))
        conn.commit()
        print("Coluna is_admin adicionada")
    except Exception:
        conn.rollback()
        print("Coluna is_admin ja existe")

# Step 2: set admin flag in a fresh transaction
with engine.connect() as conn:
    conn.execute(
        text("UPDATE usuarios SET is_admin = TRUE WHERE lower(trim(email)) = :email"),
        {"email": MASTER_ADMIN_EMAIL},
    )
    conn.commit()
    row = conn.execute(
        text("SELECT username, email, is_admin FROM usuarios WHERE lower(trim(email)) = :email"),
        {"email": MASTER_ADMIN_EMAIL},
    ).fetchone()
    if row:
        print("DB: username=" + str(row[0]) + " email=" + str(row[1]) + " is_admin=" + str(row[2]))
    else:
        print("Usuario mestre nao encontrado: " + MASTER_ADMIN_EMAIL)

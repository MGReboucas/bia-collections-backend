import sys, os
sys.path.insert(0, os.path.dirname(__file__))

from app.core.database import engine
from sqlalchemy import text

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
    conn.execute(text("UPDATE usuarios SET is_admin = TRUE WHERE username = 'matheus-bia'"))
    conn.commit()
    row = conn.execute(text("SELECT username, is_admin FROM usuarios WHERE username = 'matheus-bia'")).fetchone()
    print("DB: username=" + str(row[0]) + " is_admin=" + str(row[1]))

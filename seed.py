"""
seed.py — Populate the database with initial data for development.

Usage:
    python seed.py
"""
import json
import shutil
import sys
from datetime import date
from pathlib import Path

# Ensure the backend folder is on sys.path when running from project root
import os

sys.path.insert(0, os.path.dirname(__file__))

import app.models  # noqa: F401 — registers all models with Base
from sqlalchemy import func

from app.core.config import settings
from app.core.database import Base, engine, SessionLocal
from app.core.security import get_password_hash
from app.models.usuario import Usuario
from app.models.produto import Categoria, Produto
from app.models.cupom import Cupom
from app.models.banner import Banner


BACKEND_DIR = Path(__file__).resolve().parent
PROJECT_DIR = BACKEND_DIR.parents[1]
FRONTEND_BANNER_DIR = (
    PROJECT_DIR
    / "nextjs"
    / "bia-collections-nextjs"
    / "public"
    / "images"
    / "banners"
    / "novos-banners"
)
BANNER_UPLOAD_DIR = BACKEND_DIR / "uploads" / "banners"


def seed_initial_banners(db) -> None:
    banners_data = [
        ("Banner 1", "Banner-1.png", 1),
        ("Banner 2", "Banner-2.png", 2),
        ("Banner 3", "Banner-3.png", 3),
    ]

    BANNER_UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

    for title, filename, ordem in banners_data:
        source = FRONTEND_BANNER_DIR / filename
        destination = BANNER_UPLOAD_DIR / filename
        imagem_url = f"/uploads/banners/{filename}"

        if source.exists():
            shutil.copy2(source, destination)
        elif not destination.exists():
            print(f"[!!] Imagem do banner nao encontrada: {source}")
            print(f"     Coloque o arquivo em: {destination}")
            continue

        banner = db.query(Banner).filter(Banner.titulo == title).first()
        if not banner:
            db.add(
                Banner(
                    titulo=title,
                    imagem_url=imagem_url,
                    link="/produtos",
                    ativo=True,
                    ordem=ordem,
                )
            )
            print(f"[OK] Banner inicial '{title}' criado.")
        else:
            banner.imagem_url = imagem_url
            banner.link = "/produtos"
            banner.ativo = True
            banner.ordem = ordem
            print(f"[--] Banner inicial '{title}' atualizado.")


def seed():
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()

    try:
        # ── Usuário admin ─────────────────────────────────────────────────────
        master_admin_email = settings.MASTER_ADMIN_EMAIL.strip().lower()
        admin = (
            db.query(Usuario)
            .filter(func.lower(func.trim(Usuario.email)) == master_admin_email)
            .first()
        )
        if not admin:
            username_base = master_admin_email.split("@", 1)[0]
            username = username_base
            suffix = 2
            while db.query(Usuario).filter(Usuario.username == username).first():
                username = f"{username_base}-{suffix}"
                suffix += 1
            db.add(
                Usuario(
                    username=username,
                    email=master_admin_email,
                    senha_hash=get_password_hash("Mb171017"),
                    nome_completo="Matheus",
                    is_admin=True,
                )
            )
            print("[OK] Usuario admin mestre criado.")
        elif not admin.is_admin:
            admin.is_admin = True
            print("[OK] Usuario admin mestre atualizado.")
        else:
            print("[--] Usuario admin mestre ja existe.")

        # ── Categorias ────────────────────────────────────────────────────────
        nomes_categorias = ["Blusas", "Vestidos", "Calças", "Oculos", "Bijuteria"]
        categorias: dict[str, Categoria] = {}
        for nome in nomes_categorias:
            cat = db.query(Categoria).filter(Categoria.nome == nome).first()
            if not cat:
                cat = Categoria(nome=nome)
                db.add(cat)
                db.flush()
                print(f"✓ Categoria '{nome}' criada.")
            else:
                print(f"· Categoria '{nome}' já existe.")
            categorias[nome] = cat

        # ── Produtos ──────────────────────────────────────────────────────────
        produtos_data = [
            {
                "nome": "Blusa Feminina Azul com Detalhes Bordados",
                "descricao": "Blusa leve em viscose com detalhes bordados nas mangas. Perfeita para o dia a dia.",
                "preco": 99.90,
                "categoria": "Blusas",
                "tamanhos": ["P", "M", "G", "GG"],
                "cores": ["Azul", "Branco"],
                "imagem_url": "https://images.unsplash.com/photo-1564257631407-4deb1f99d992?w=600&h=800&fit=crop&q=80",
            },
            {
                "nome": "Blusa Cropped Listrada",
                "descricao": "Blusa cropped com listras horizontais, tecido strech confortável.",
                "preco": 99.90,
                "categoria": "Blusas",
                "tamanhos": ["P", "M", "G"],
                "cores": ["Preto/Branco", "Rosa/Branco"],
                "imagem_url": "https://images.unsplash.com/photo-1596755094514-f87e34085b2c?w=600&h=800&fit=crop&q=80",
            },
            {
                "nome": "Blusa Off-Shoulder Floral",
                "descricao": "Blusa ombro a ombro com estampa floral delicada. Ideal para passeios e encontros.",
                "preco": 99.90,
                "categoria": "Blusas",
                "tamanhos": ["P", "M", "G", "GG"],
                "cores": ["Floral Rosa", "Floral Azul"],
                "imagem_url": "https://images.unsplash.com/photo-1515886657613-9f3515b0c78f?w=600&h=800&fit=crop&q=80",
            },
            {
                "nome": "Blusa de Malha Canelada",
                "descricao": "Blusa em malha canelada com manga longa. Elegante e versátil.",
                "preco": 99.90,
                "categoria": "Blusas",
                "tamanhos": ["P", "M", "G", "GG"],
                "cores": ["Nude", "Preto", "Verde"],
                "imagem_url": "https://images.unsplash.com/photo-1571945153237-4929e783af4a?w=600&h=800&fit=crop&q=80",
            },
            {
                "nome": "Vestido Midi Floral com Cinto",
                "descricao": "Vestido midi em chiffon com estampa floral e cinto ajustável. Elegância para qualquer ocasião.",
                "preco": 149.90,
                "categoria": "Vestidos",
                "tamanhos": ["P", "M", "G"],
                "cores": ["Floral Rosa", "Floral Terracota"],
                "imagem_url": "https://images.unsplash.com/photo-1572804013427-4d7ca7268217?w=600&h=800&fit=crop&q=80",
            },
            {
                "nome": "Vestido Longo Boho",
                "descricao": "Vestido longo estilo boho com decote V e mangas fluídas. Perfeito para festas ao ar livre.",
                "preco": 149.90,
                "categoria": "Vestidos",
                "tamanhos": ["P", "M", "G", "GG"],
                "cores": ["Bordô", "Azul Marinho"],
                "imagem_url": "https://images.unsplash.com/photo-1509631179647-0177331693ae?w=600&h=800&fit=crop&q=80",
            },
            {
                "nome": "Calça Wide Leg Cintura Alta",
                "descricao": "Calça wide leg em tecido de alfaiataria com cintura alta. Moderna e confortável.",
                "preco": 129.90,
                "categoria": "Calças",
                "tamanhos": ["36", "38", "40", "42", "44"],
                "cores": ["Bege", "Preto", "Caramelo"],
                "imagem_url": "https://images.unsplash.com/photo-1584370848010-d7fe6bc767ec?w=600&h=800&fit=crop&q=80",
            },
            {
                "nome": "Óculos de Sol Redondo Retrô",
                "descricao": "Óculos de sol redondo com armação metálica dourada e lentes degradê. Proteção UV400.",
                "preco": 79.90,
                "categoria": "Oculos",
                "tamanhos": ["Único"],
                "cores": ["Dourado/Rosa", "Dourado/Verde"],
                "imagem_url": "https://images.unsplash.com/photo-1511499767150-a48a237f0083?w=600&h=800&fit=crop&q=80",
            },
        ]

        for pd in produtos_data:
            if not db.query(Produto).filter(Produto.nome == pd["nome"]).first():
                cat = categorias.get(pd["categoria"])
                db.add(
                    Produto(
                        nome=pd["nome"],
                        descricao=pd["descricao"],
                        preco=pd["preco"],
                        categoria_id=cat.id if cat else None,
                        imagem_url=pd.get("imagem_url"),
                        tamanhos=json.dumps(pd["tamanhos"], ensure_ascii=False),
                        cores=json.dumps(pd["cores"], ensure_ascii=False),
                        ativo=True,
                    )
                )
                print(f"✓ Produto '{pd['nome']}' criado.")
            else:
                print(f"· Produto '{pd['nome']}' já existe.")

        # ── Cupons ────────────────────────────────────────────────────────────
        cupons_data = [
            {
                "codigo": "BOAS-VINDAS10",
                "descricao": "10% de desconto na primeira compra",
                "tipo": "porcentagem",
                "valor": 10.0,
                "validade": date(2026, 12, 31),
                "ativo": True,
                "valor_minimo_pedido": 0.0,
            },
            {
                "codigo": "FRETE-GRATIS",
                "descricao": "Frete grátis em qualquer pedido",
                "tipo": "frete",
                "valor": 0.0,
                "validade": date(2026, 6, 30),
                "ativo": True,
                "valor_minimo_pedido": 0.0,
            },
            {
                "codigo": "VERAO25",
                "descricao": "R$ 25 de desconto no verão",
                "tipo": "valor",
                "valor": 25.0,
                "validade": date(2026, 7, 15),
                "ativo": True,
                "valor_minimo_pedido": 150.0,
            },
            {
                "codigo": "NATAL15",
                "descricao": "15% de desconto no Natal",
                "tipo": "porcentagem",
                "valor": 15.0,
                "validade": date(2026, 1, 31),
                "ativo": False,
                "valor_minimo_pedido": 0.0,
            },
        ]

        for cd in cupons_data:
            if not db.query(Cupom).filter(Cupom.codigo == cd["codigo"]).first():
                db.add(Cupom(**cd))
                print(f"✓ Cupom '{cd['codigo']}' criado.")
            else:
                print(f"· Cupom '{cd['codigo']}' já existe.")

        seed_initial_banners(db)

        db.commit()
        print("\n✅ Seed concluído com sucesso!")

    except Exception as exc:
        db.rollback()
        print(f"\n❌ Erro durante o seed: {exc}")
        raise
    finally:
        db.close()


if __name__ == "__main__":
    seed()

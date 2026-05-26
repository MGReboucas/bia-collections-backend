"""
add_product_images.py — Baixa imagens de moda do Unsplash e atualiza os produtos no banco.

Usage:
    python add_product_images.py
"""
import os
import sys
import uuid
import requests

sys.path.insert(0, os.path.dirname(__file__))

import app.models  # noqa: F401
from app.core.database import SessionLocal
from app.models.produto import Produto

# Imagens do Unsplash — IDs de fotos públicas de moda/acessórios
# Formato: (nome_parcial_produto, unsplash_photo_id)
PRODUCT_IMAGES = [
    ("Blusa Feminina Azul",        "photo-1564257631407-4deb1f99d992"),  # blusa azul feminina
    ("Blusa Cropped Listrada",     "photo-1596755094514-f87e34085b2c"),  # cropped listrado
    ("Blusa Off-Shoulder Floral",  "photo-1515886657613-9f3515b0c78f"),  # floral off-shoulder
    ("Blusa de Malha Canelada",    "photo-1571945153237-4929e783af4a"),  # malha canelada
    ("Vestido Midi Floral",        "photo-1572804013427-4d7ca7268217"),  # vestido midi floral
    ("Vestido Longo Boho",         "photo-1509631179647-0177331693ae"),  # vestido longo boho
    ("Calça Wide Leg",             "photo-1584370848010-d7fe6bc767ec"),  # calça wide leg
    ("Óculos de Sol",              "photo-1511499767150-a48a237f0083"),  # óculos de sol
]

UPLOAD_DIR = os.path.join(os.path.dirname(__file__), "uploads", "produtos")
os.makedirs(UPLOAD_DIR, exist_ok=True)

HEADERS = {"User-Agent": "CuradoBemBot/1.0"}
TIMEOUT = 20


def download_image(photo_id: str, filename: str) -> bool:
    url = f"https://images.unsplash.com/{photo_id}?w=600&h=800&fit=crop&q=80"
    try:
        resp = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
        if resp.status_code == 200 and "image" in resp.headers.get("Content-Type", ""):
            with open(filename, "wb") as f:
                f.write(resp.content)
            return True
        print(f"  ✗ HTTP {resp.status_code} para {photo_id}")
        return False
    except Exception as e:
        print(f"  ✗ Erro ao baixar {photo_id}: {e}")
        return False


def main():
    db = SessionLocal()
    try:
        for nome_parcial, photo_id in PRODUCT_IMAGES:
            # Encontra o produto pelo nome parcial
            produto = (
                db.query(Produto)
                .filter(Produto.nome.ilike(f"%{nome_parcial}%"))
                .first()
            )
            if not produto:
                print(f"· Produto '{nome_parcial}' não encontrado no banco.")
                continue

            # Gera nome de arquivo único
            ext = "jpeg"
            filename_base = f"produto_{produto.id}_{uuid.uuid4().hex[:8]}.{ext}"
            filepath = os.path.join(UPLOAD_DIR, filename_base)

            print(f"⬇  Baixando imagem para '{produto.nome}'...")
            if download_image(photo_id, filepath):
                produto.imagem_url = f"/uploads/produtos/{filename_base}"
                db.add(produto)
                print(f"  ✓ Salvo em {produto.imagem_url}")
            else:
                # Fallback: usa picsum.photos com seed fixo
                seed = produto.id * 13
                fallback_url = f"https://picsum.photos/seed/{seed}/600/800"
                try:
                    resp = requests.get(fallback_url, headers=HEADERS, timeout=TIMEOUT)
                    if resp.status_code == 200:
                        with open(filepath, "wb") as f:
                            f.write(resp.content)
                        produto.imagem_url = f"/uploads/produtos/{filename_base}"
                        db.add(produto)
                        print(f"  ✓ Fallback picsum salvo em {produto.imagem_url}")
                    else:
                        print(f"  ✗ Fallback também falhou ({resp.status_code})")
                except Exception as e:
                    print(f"  ✗ Fallback erro: {e}")

        db.commit()
        print("\n✅ Imagens adicionadas com sucesso!")
    except Exception as e:
        db.rollback()
        print(f"\n❌ Erro: {e}")
        raise
    finally:
        db.close()


if __name__ == "__main__":
    main()

from fastapi import APIRouter, Depends, Response
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.banner import Banner

router = APIRouter(prefix="/banners", tags=["banners"])


@router.get("")
def listar_banners_publico(response: Response, db: Session = Depends(get_db)):
    response.headers["Cache-Control"] = "public, max-age=60"
    banners = (
        db.query(Banner)
        .filter(Banner.ativo.is_(True))
        .order_by(Banner.ordem)
        .all()
    )
    return [
        {
            "id": b.id,
            "titulo": b.titulo,
            "imagem_url": b.imagem_url,
            "link": b.link,
            "ativo": b.ativo,
            "ordem": b.ordem,
        }
        for b in banners
    ]

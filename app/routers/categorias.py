from fastapi import APIRouter, Depends, Response
from sqlalchemy.orm import Session
from app.database import get_db
from app.models.produto import Categoria

router = APIRouter(prefix="/categorias", tags=["categorias"])


@router.get("")
def listar_categorias(response: Response, db: Session = Depends(get_db)):
    response.headers["Cache-Control"] = "public, max-age=300"
    return [
        {"id": categoria.id, "nome": categoria.nome}
        for categoria in db.query(Categoria).order_by(Categoria.nome.asc()).all()
    ]

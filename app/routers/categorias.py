from fastapi import APIRouter, Depends, Response
from sqlalchemy.orm import Session
from typing import List

from app.database import get_db
from app.models.produto import Categoria

router = APIRouter(prefix="/categorias", tags=["categorias"])


@router.get("", response_model=List[str])
def listar_categorias(response: Response, db: Session = Depends(get_db)):
    response.headers["Cache-Control"] = "public, max-age=300"
    return [c.nome for c in db.query(Categoria).all()]

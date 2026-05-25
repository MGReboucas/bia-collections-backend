from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import List

from app.database import get_db
from app.models.produto import Produto
from app.services.frete_service import calcular_frete

router = APIRouter(prefix="/frete", tags=["frete"])


class ItemFreteRequest(BaseModel):
    produto_id: int
    quantidade: int


class FreteRequest(BaseModel):
    cep_destino: str
    itens: List[ItemFreteRequest]


@router.post("/calcular")
def calcular(data: FreteRequest, db: Session = Depends(get_db)):
    for item in data.itens:
        produto = db.query(Produto).filter(Produto.id == item.produto_id).first()
        if not produto:
            raise HTTPException(
                status_code=404,
                detail=f"Produto {item.produto_id} não encontrado.",
            )
    return calcular_frete(data.cep_destino)

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import List, Optional

from app.database import get_db
from app.dependencies import get_current_user
from app.models.usuario import Usuario
from app.models.duvida import Duvida
from app.schemas.duvida import DuvidaCreate, DuvidaOut

router = APIRouter(prefix="/duvidas", tags=["duvidas"])


@router.get("", response_model=List[DuvidaOut])
def listar_duvidas(
    status_filtro: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
):
    query = db.query(Duvida).filter(Duvida.usuario_id == current_user.id)
    if status_filtro in ("pendente", "respondida"):
        query = query.filter(Duvida.status == status_filtro)
    return query.order_by(Duvida.criado_em.desc()).all()


@router.post("", response_model=DuvidaOut, status_code=status.HTTP_201_CREATED)
def criar_duvida(
    data: DuvidaCreate,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
):
    duvida = Duvida(
        usuario_id=current_user.id,
        produto_id=data.produto_id,
        produto_nome=data.produto_nome,
        pergunta=data.pergunta.strip(),
    )
    db.add(duvida)
    db.commit()
    db.refresh(duvida)
    return duvida


@router.delete("/{duvida_id}", status_code=status.HTTP_204_NO_CONTENT)
def deletar_duvida(
    duvida_id: int,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
):
    duvida = db.query(Duvida).filter(
        Duvida.id == duvida_id,
        Duvida.usuario_id == current_user.id,
        Duvida.status == "pendente",
    ).first()
    if not duvida:
        raise HTTPException(
            status_code=404,
            detail="Dúvida não encontrada ou já respondida.",
        )
    db.delete(duvida)
    db.commit()

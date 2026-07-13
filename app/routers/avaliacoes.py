from typing import List, Optional

from fastapi import APIRouter, Depends, File, Form, Query, UploadFile, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import get_current_user
from app.models.avaliacao import Avaliacao
from app.models.usuario import Usuario
from app.services.avaliacao_service import (
    AVALIACAO_STATUS_PUBLICO,
    avaliacao_query,
    avaliacao_response,
    create_avaliacao,
    uploaded_files,
)

router = APIRouter(prefix="/avaliacoes", tags=["avaliacoes"])


@router.get("")
def listar_avaliacoes_publico(
    status: Optional[str] = Query(None),
    produto_id: Optional[int] = Query(None),
    limit: Optional[int] = Query(None, ge=1, le=100),
    mostrar_home: Optional[bool] = Query(None),
    db: Session = Depends(get_db),
):
    query = (
        avaliacao_query(db)
        .filter(Avaliacao.status == AVALIACAO_STATUS_PUBLICO)
        .order_by(Avaliacao.criado_em.desc())
    )
    if status is not None and status != AVALIACAO_STATUS_PUBLICO:
        return []
    if produto_id is not None:
        query = query.filter(Avaliacao.produto_id == produto_id)
    if mostrar_home is True:
        query = query.filter(Avaliacao.mostrar_home.is_(True))
    elif mostrar_home is False:
        query = query.filter(Avaliacao.mostrar_home.is_(False))
    if limit is not None:
        query = query.limit(limit)
    return [avaliacao_response(avaliacao) for avaliacao in query.all()]


@router.post("", status_code=status.HTTP_201_CREATED)
async def criar_avaliacao(
    produto_id: int = Form(...),
    nota: int = Form(...),
    pedido_numero: Optional[str] = Form(None),
    comentario: Optional[str] = Form(None),
    fotos: List[UploadFile] | None = File(None),
    imagens: List[UploadFile] | None = File(None),
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
):
    avaliacao = await create_avaliacao(
        db=db,
        current_user=current_user,
        produto_id=produto_id,
        pedido_numero=pedido_numero,
        nota=nota,
        comentario=comentario,
        files=uploaded_files(fotos, imagens),
    )
    return avaliacao_response(avaliacao)

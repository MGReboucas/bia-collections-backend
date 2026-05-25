import json

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy.orm import Session, joinedload
from typing import Optional

from app.database import get_db
from app.models.produto import Produto, Categoria
from app.schemas.produto import ProdutoListResponse, ProdutoDetalhe, ProdutoListItem
from app.services.frete_service import formatar_preco

router = APIRouter(prefix="/produtos", tags=["produtos"])


@router.get("", response_model=ProdutoListResponse)
def listar_produtos(
    response: Response,
    busca: Optional[str] = Query(None),
    categoria: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
):
    # Cache for 60s when no search query, otherwise no-store
    if not busca:
        response.headers["Cache-Control"] = "public, max-age=60"
    else:
        response.headers["Cache-Control"] = "no-store"

    query = (
        db.query(Produto)
        .options(joinedload(Produto.categoria))
        .filter(Produto.ativo.is_(True))
    )

    if busca:
        query = query.filter(Produto.nome.ilike(f"%{busca}%"))

    if categoria:
        cat = db.query(Categoria).filter(Categoria.nome == categoria).first()
        if cat:
            query = query.filter(Produto.categoria_id == cat.id)

    total = query.count()
    produtos = query.offset((page - 1) * limit).limit(limit).all()

    itens = [
        ProdutoListItem(
            id=p.id,
            nome=p.nome,
            preco=p.preco,
            preco_formatado=formatar_preco(p.preco),
            categoria=p.categoria.nome if p.categoria else None,
            imagem_url=p.imagem_url,
            tamanhos=json.loads(p.tamanhos) if p.tamanhos else [],
            cores=json.loads(p.cores) if p.cores else [],
        )
        for p in produtos
    ]
    return ProdutoListResponse(total=total, page=page, limit=limit, itens=itens)


@router.get("/{produto_id}", response_model=ProdutoDetalhe)
def detalhe_produto(produto_id: int, db: Session = Depends(get_db)):
    p = (
        db.query(Produto)
        .options(joinedload(Produto.categoria))
        .filter(Produto.id == produto_id, Produto.ativo.is_(True))
        .first()
    )
    if not p:
        raise HTTPException(status_code=404, detail="Produto não encontrado.")
    return ProdutoDetalhe(
        id=p.id,
        nome=p.nome,
        descricao=p.descricao,
        preco=p.preco,
        preco_formatado=formatar_preco(p.preco),
        categoria=p.categoria.nome if p.categoria else None,
        imagem_url=p.imagem_url,
        tamanhos=json.loads(p.tamanhos) if p.tamanhos else [],
        cores=json.loads(p.cores) if p.cores else [],
    )

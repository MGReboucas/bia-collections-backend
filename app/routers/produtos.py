import json
import unicodedata

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy.orm import Session, joinedload
from typing import Optional

from app.database import get_db
from app.models.produto import Produto, Categoria
from app.schemas.produto import ProdutoListResponse, ProdutoDetalhe, ProdutoListItem
from app.services.frete_service import formatar_preco

router = APIRouter(prefix="/produtos", tags=["produtos"])


def _produto_imagens_response(produto: Produto) -> list[dict]:
    imagens = sorted(
        produto.imagens or [],
        key=lambda imagem: (
            not bool(imagem.principal),
            imagem.ordem if imagem.ordem is not None else 0,
            imagem.id or 0,
        ),
    )
    return [
        {
            "id": imagem.id,
            "imagem_url": imagem.imagem_url,
            "ordem": imagem.ordem,
            "principal": imagem.principal,
            "modelo_nome": imagem.modelo_nome,
            "modelo_cor": imagem.modelo_cor,
            "cor_nome": imagem.cor_nome,
            "modelo": imagem.modelo_nome,
            "cor": imagem.cor_nome or imagem.modelo_cor,
        }
        for imagem in imagens
    ]


def _produto_imagem_url(produto: Produto, imagens: list[dict]) -> str | None:
    if produto.imagem_url:
        return produto.imagem_url
    if imagens:
        return imagens[0]["imagem_url"]
    return None


def _normalize_category(value: str | None) -> str:
    return "".join(
        char
        for char in unicodedata.normalize("NFD", value or "")
        if unicodedata.category(char) != "Mn"
    ).lower()


def _find_category_by_slug(db: Session, value: str) -> Categoria | None:
    normalized = _normalize_category(value)
    return next(
        (
            category
            for category in db.query(Categoria).all()
            if _normalize_category(category.nome) == normalized
        ),
        None,
    )


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
        .options(joinedload(Produto.categoria), joinedload(Produto.imagens))
        .filter(Produto.ativo.is_(True))
    )

    if busca:
        query = query.filter(Produto.nome.ilike(f"%{busca}%"))

    if categoria:
        cat = _find_category_by_slug(db, categoria)
        if not cat:
            return ProdutoListResponse(total=0, page=page, limit=limit, itens=[])
        query = query.filter(Produto.categoria_id == cat.id)

    total = query.count()
    produtos = query.offset((page - 1) * limit).limit(limit).all()

    itens = []
    for p in produtos:
        imagens = _produto_imagens_response(p)
        itens.append(
            ProdutoListItem(
                id=p.id,
                nome=p.nome,
                preco=p.preco,
                preco_formatado=formatar_preco(p.preco),
                preco_promocional=p.preco_promocional,
                estoque=p.estoque,
                categoria=p.categoria.nome if p.categoria else None,
                imagem_url=_produto_imagem_url(p, imagens),
                imagens=imagens,
                tamanhos=json.loads(p.tamanhos) if p.tamanhos else [],
                cores=json.loads(p.cores) if p.cores else [],
            )
        )
    return ProdutoListResponse(total=total, page=page, limit=limit, itens=itens)


@router.get("/{produto_id}", response_model=ProdutoDetalhe)
def detalhe_produto(produto_id: int, db: Session = Depends(get_db)):
    p = (
        db.query(Produto)
        .options(joinedload(Produto.categoria), joinedload(Produto.imagens))
        .filter(Produto.id == produto_id, Produto.ativo.is_(True))
        .first()
    )
    if not p:
        raise HTTPException(status_code=404, detail="Produto não encontrado.")
    imagens = _produto_imagens_response(p)
    return ProdutoDetalhe(
        id=p.id,
        nome=p.nome,
        descricao=p.descricao,
        preco=p.preco,
        preco_formatado=formatar_preco(p.preco),
        preco_promocional=p.preco_promocional,
        estoque=p.estoque,
        categoria=p.categoria.nome if p.categoria else None,
        imagem_url=_produto_imagem_url(p, imagens),
        imagens=imagens,
        tamanhos=json.loads(p.tamanhos) if p.tamanhos else [],
        cores=json.loads(p.cores) if p.cores else [],
    )

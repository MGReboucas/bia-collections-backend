from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import Response
from sqlalchemy.orm import Session, joinedload
from typing import List

from app.database import get_db
from app.dependencies import get_current_user
from app.models.usuario import Usuario
from app.models.produto import Produto
from app.models.pedido import Pedido, ItemPedido
from app.models.cupom import Cupom
from app.schemas.pedido import (
    CriarPedidoRequest,
    CriarPedidoResponse,
    PedidoListItem,
    PedidoDetalhe,
    EnderecoSnapshot,
    ItemPedidoDetalhe,
)
from app.services.pedido_service import gerar_numero_pedido
from app.services.frete_service import formatar_preco
from app.services.payment_status import ORDER_STATUS_AGUARDANDO, ORDER_STATUSES_OPERACIONAIS

router = APIRouter(prefix="/pedidos", tags=["pedidos"])


def _subtotal_pedido(pedido: Pedido) -> float:
    if pedido.subtotal is not None:
        return pedido.subtotal
    return max((pedido.total or 0.0) - (pedido.valor_frete or 0.0), 0.0)


def _preco_venda(produto: Produto) -> float:
    if produto.preco_promocional is not None and produto.preco_promocional > 0:
        return produto.preco_promocional
    return produto.preco


@router.post("", response_model=CriarPedidoResponse, status_code=status.HTTP_201_CREATED)
def criar_pedido(
    data: CriarPedidoRequest,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
):
    # Validate products and compute subtotal
    subtotal = 0.0
    itens_data = []
    for item in data.itens:
        produto = db.query(Produto).filter(
            Produto.id == item.produto_id, Produto.ativo.is_(True)
        ).first()
        if not produto:
            raise HTTPException(
                status_code=404,
                detail=f"Produto {item.produto_id} não encontrado.",
            )
        preco_unitario = _preco_venda(produto)
        subtotal += preco_unitario * item.quantidade
        itens_data.append(
            {
                "produto": produto,
                "quantidade": item.quantidade,
                "tamanho": item.tamanho,
                "cor": item.cor,
                "preco_unitario": preco_unitario,
            }
        )

    subtotal = round(subtotal, 2)
    frete = data.frete
    valor_frete_original = round(frete.valor if frete else 0.0, 2)
    tipo_frete = frete.nome.strip() if frete and frete.nome else None
    prazo_frete = frete.prazo.strip() if frete and frete.prazo else None

    # Apply coupon
    desconto_produtos = 0.0
    desconto_frete = 0.0
    cupom_codigo_aplicado: str | None = None

    if data.cupom_codigo:
        cupom = db.query(Cupom).filter(
            Cupom.codigo == data.cupom_codigo.upper(),
            Cupom.ativo.is_(True),
        ).first()
        if not cupom:
            raise HTTPException(status_code=422, detail="Cupom inválido ou inativo.")
        if cupom.validade < date.today():
            raise HTTPException(status_code=422, detail="Cupom expirado.")
        if subtotal < cupom.valor_minimo_pedido:
            raise HTTPException(
                status_code=422,
                detail=f"Pedido mínimo de {formatar_preco(cupom.valor_minimo_pedido)} para este cupom.",
            )
        ja_usado = db.query(CupomUsado).filter(
            CupomUsado.cupom_id == cupom.id,
            CupomUsado.usuario_id == current_user.id,
        ).first()
        if ja_usado:
            raise HTTPException(status_code=422, detail="Cupom já utilizado.")

        if cupom.max_usos is not None and cupom.total_usos >= cupom.max_usos:
            raise HTTPException(status_code=422, detail="Cupom esgotado.")

        if cupom.tipo == "porcentagem":
            desconto_produtos = round(subtotal * (cupom.valor / 100), 2)
        elif cupom.tipo == "valor":
            desconto_produtos = min(cupom.valor, subtotal)
        elif cupom.tipo == "frete":
            desconto_frete = valor_frete_original
        cupom_codigo_aplicado = cupom.codigo

    valor_frete_cobrado = round(max(valor_frete_original - desconto_frete, 0.0), 2)
    desconto = round(desconto_produtos + desconto_frete, 2)
    total_final = round(max(subtotal - desconto_produtos, 0.0) + valor_frete_cobrado, 2)

    # Create order
    numero = gerar_numero_pedido(db)
    pedido = Pedido(
        numero=numero,
        usuario_id=current_user.id,
        status=ORDER_STATUS_AGUARDANDO,
        forma_pagamento=data.forma_pagamento,
        subtotal=subtotal,
        valor_frete=valor_frete_cobrado,
        tipo_frete=tipo_frete,
        prazo_frete=prazo_frete,
        total=total_final,
        endereco_cep=data.endereco.cep,
        endereco_rua=data.endereco.rua,
        endereco_numero=data.endereco.numero,
        endereco_complemento=data.endereco.complemento,
        endereco_bairro=data.endereco.bairro,
        endereco_cidade=data.endereco.cidade,
        endereco_estado=data.endereco.estado,
        cupom_codigo=cupom_codigo_aplicado,
        desconto_aplicado=desconto,
    )
    db.add(pedido)
    db.flush()  # get pedido.id before commit

    for item in itens_data:
        db.add(
            ItemPedido(
                pedido_id=pedido.id,
                produto_id=item["produto"].id,
                nome_produto=item["produto"].nome,
                preco_unitario=item["preco_unitario"],
                tamanho=item["tamanho"],
                cor=item["cor"],
                quantidade=item["quantidade"],
            )
        )

    db.commit()
    db.refresh(pedido)

    return CriarPedidoResponse(
        numero_pedido=pedido.numero,
        subtotal=pedido.subtotal or 0.0,
        total=pedido.total,
        total_formatado=formatar_preco(pedido.total),
        valor_frete=pedido.valor_frete or 0.0,
        valor_frete_formatado=formatar_preco(pedido.valor_frete or 0.0),
        desconto_aplicado=desconto,
        forma_pagamento=pedido.forma_pagamento,
        status=pedido.status,
    )


@router.get("", response_model=List[PedidoListItem])
def listar_pedidos(
    incluir_pendentes: bool = Query(False),
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
):
    query = (
        db.query(Pedido)
        .options(joinedload(Pedido.itens))
        .filter(Pedido.usuario_id == current_user.id)
        .order_by(Pedido.criado_em.desc())
    )
    if not incluir_pendentes:
        query = query.filter(Pedido.status.in_(list(ORDER_STATUSES_OPERACIONAIS)))
    pedidos = query.offset((page - 1) * limit).limit(limit).all()
    return [
        PedidoListItem(
            numero=p.numero,
            data=p.criado_em.strftime("%d/%m/%Y"),
            status=p.status,
            total_formatado=formatar_preco(p.total),
            total_itens=sum(i.quantidade for i in p.itens),
        )
        for p in pedidos
    ]


@router.get("/{numero}", response_model=PedidoDetalhe)
def detalhe_pedido(
    numero: str,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
):
    pedido = db.query(Pedido).filter(
        Pedido.numero == numero,
        Pedido.usuario_id == current_user.id,
    ).first()
    if not pedido:
        raise HTTPException(status_code=404, detail="Pedido não encontrado.")

    endereco = EnderecoSnapshot(
        cep=pedido.endereco_cep,
        rua=pedido.endereco_rua,
        numero=pedido.endereco_numero,
        complemento=pedido.endereco_complemento,
        bairro=pedido.endereco_bairro,
        cidade=pedido.endereco_cidade,
        estado=pedido.endereco_estado,
    )
    itens = [
        ItemPedidoDetalhe(
            produto_id=i.produto_id,
            nome_produto=i.nome_produto,
            preco_unitario=i.preco_unitario,
            preco_formatado=formatar_preco(i.preco_unitario),
            tamanho=i.tamanho,
            cor=i.cor,
            quantidade=i.quantidade,
        )
        for i in pedido.itens
    ]
    return PedidoDetalhe(
        numero=pedido.numero,
        data=pedido.criado_em.strftime("%d/%m/%Y"),
        status=pedido.status,
        forma_pagamento=pedido.forma_pagamento,
        subtotal=_subtotal_pedido(pedido),
        total=pedido.total,
        total_formatado=formatar_preco(pedido.total),
        valor_frete=pedido.valor_frete or 0.0,
        valor_frete_formatado=formatar_preco(pedido.valor_frete or 0.0),
        tipo_frete=pedido.tipo_frete,
        prazo_frete=pedido.prazo_frete,
        desconto_aplicado=pedido.desconto_aplicado,
        endereco=endereco,
        itens=itens,
    )

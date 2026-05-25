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
from app.models.cupom import Cupom, CupomUsado
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

router = APIRouter(prefix="/pedidos", tags=["pedidos"])


@router.post("", response_model=CriarPedidoResponse, status_code=status.HTTP_201_CREATED)
def criar_pedido(
    data: CriarPedidoRequest,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
):
    # Validate products and compute total
    total = 0.0
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
        total += produto.preco * item.quantidade
        itens_data.append(
            {
                "produto": produto,
                "quantidade": item.quantidade,
                "tamanho": item.tamanho,
                "cor": item.cor,
                "preco_unitario": produto.preco,
            }
        )

    # Apply coupon
    desconto = 0.0
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
        if total < cupom.valor_minimo_pedido:
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

        if cupom.tipo == "porcentagem":
            desconto = round(total * (cupom.valor / 100), 2)
        elif cupom.tipo == "valor":
            desconto = min(cupom.valor, total)
        # tipo == 'frete': desconto no frete, não no total do produto
        cupom_codigo_aplicado = cupom.codigo

    total_final = round(total - desconto, 2)

    # Create order
    numero = gerar_numero_pedido(db)
    pedido = Pedido(
        numero=numero,
        usuario_id=current_user.id,
        status="Aguardando pagamento",
        forma_pagamento=data.forma_pagamento,
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

    if cupom_codigo_aplicado:
        cupom_obj = db.query(Cupom).filter(Cupom.codigo == cupom_codigo_aplicado).first()
        if cupom_obj:
            db.add(
                CupomUsado(
                    cupom_id=cupom_obj.id,
                    usuario_id=current_user.id,
                    pedido_id=pedido.id,
                )
            )

    db.commit()
    db.refresh(pedido)

    return CriarPedidoResponse(
        numero_pedido=pedido.numero,
        total=pedido.total,
        total_formatado=formatar_preco(pedido.total),
        desconto_aplicado=desconto,
        forma_pagamento=pedido.forma_pagamento,
        status=pedido.status,
    )


@router.get("", response_model=List[PedidoListItem])
def listar_pedidos(
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
):
    pedidos = (
        db.query(Pedido)
        .options(joinedload(Pedido.itens))
        .filter(Pedido.usuario_id == current_user.id)
        .order_by(Pedido.criado_em.desc())
        .offset((page - 1) * limit)
        .limit(limit)
        .all()
    )
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
        total=pedido.total,
        total_formatado=formatar_preco(pedido.total),
        desconto_aplicado=pedido.desconto_aplicado,
        endereco=endereco,
        itens=itens,
    )

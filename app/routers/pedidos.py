from fastapi import APIRouter, Depends, HTTPException, Query, status
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
from app.services.cupom_service import (
    validar_cupom_para_total,
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
    subtotal = 0.0
    itens_data = []
    for item in data.itens:
        produto = db.query(Produto).filter(
            Produto.id == item.produto_id, Produto.ativo.is_(True)
        ).first()
        if not produto:
            raise HTTPException(
                status_code=404,
                detail=f"Produto {item.produto_id} nao encontrado.",
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
    total_antes_desconto = round(subtotal + valor_frete_original, 2)

    desconto_produtos = 0.0
    desconto_frete = 0.0
    cupom_codigo_aplicado: str | None = None
    cupom_aplicado: Cupom | None = None

    if data.cupom_codigo:
        cupom_aplicado, valor_desconto = validar_cupom_para_total(
            db=db,
            usuario=current_user,
            codigo=data.cupom_codigo,
            total=total_antes_desconto,
            valor_frete=valor_frete_original,
        )
        if cupom_aplicado.tipo == "frete":
            desconto_frete = valor_desconto
        else:
            desconto_produtos = valor_desconto
        cupom_codigo_aplicado = cupom_aplicado.codigo

    valor_frete_cobrado = round(max(valor_frete_original - desconto_frete, 0.0), 2)
    desconto = round(desconto_produtos + desconto_frete, 2)
    total_final = round(max(total_antes_desconto - desconto, 0.0), 2)

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
    db.flush()

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
        raise HTTPException(status_code=404, detail="Pedido nao encontrado.")

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

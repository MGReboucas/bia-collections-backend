from __future__ import annotations

import hashlib
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session, joinedload

from app.core.config import settings
from app.database import get_db
from app.dependencies import get_current_master_admin_user, get_current_user
from app.models.pedido import Pedido
from app.models.pos_venda import DocumentoPedido, ReembolsoPedido, SolicitacaoPosVenda
from app.models.usuario import Usuario
from app.modules.email.service import (
    EmailAutomationService,
    build_order_email_payload,
    trigger_order_email_event,
)
from app.schemas.pos_venda import (
    DocumentoPedidoCreate,
    DocumentoPedidoOut,
    ReembolsoAprovarPayload,
    ReembolsoOut,
    SolicitacaoPosVendaCreate,
    SolicitacaoPosVendaOut,
    SolicitacaoPosVendaUpdate,
)

router = APIRouter(prefix="/pos-venda", tags=["pos-venda"])
admin_router = APIRouter(
    prefix="/admin/pos-venda",
    tags=["admin-pos-venda"],
    dependencies=[Depends(get_current_master_admin_user)],
)

PEDIDO_POS_VENDA_STATUS = {"Enviado", "Entregue"}


def _solicitacao_out(item: SolicitacaoPosVenda) -> SolicitacaoPosVendaOut:
    return SolicitacaoPosVendaOut(
        id=item.id,
        protocolo=item.protocolo,
        pedido_numero=item.pedido.numero,
        usuario_id=item.usuario_id,
        tipo=item.tipo,
        motivo=item.motivo,
        status=item.status,
        motivo_recusa=item.motivo_recusa,
        criado_em=item.criado_em,
        atualizado_em=item.atualizado_em,
    )


def _documento_out(item: DocumentoPedido) -> DocumentoPedidoOut:
    return DocumentoPedidoOut(
        id=item.id,
        pedido_numero=item.pedido.numero,
        tipo=item.tipo,
        numero=item.numero,
        url=item.url,
        criado_em=item.criado_em,
    )


def _reembolso_out(item: ReembolsoPedido) -> ReembolsoOut:
    return ReembolsoOut(
        id=item.id,
        pedido_numero=item.pedido.numero,
        status=item.status,
        valor=item.valor,
        prazo_dias_uteis=item.prazo_dias_uteis,
        criado_em=item.criado_em,
        atualizado_em=item.atualizado_em,
    )


def _trigger_internal_return_email(
    db: Session,
    pedido: Pedido,
    solicitacao: SolicitacaoPosVenda,
) -> None:
    payload = build_order_email_payload(
        db,
        pedido,
        event_key="internal_return_exchange_requested",
        extra={
            "to": settings.admin_order_notification_email,
            "email": settings.admin_order_notification_email,
            "cliente_email": pedido.usuario.email if pedido.usuario else "",
            "protocolo_troca": solicitacao.protocolo,
            "link_solicitacao_admin": (
                f"{settings.FRONTEND_URL.rstrip('/')}/admin/pos-venda/{solicitacao.id}"
            ),
        },
    )
    EmailAutomationService(db).trigger_event("internal_return_exchange_requested", payload)


@router.post(
    "/trocas-devolucoes",
    response_model=SolicitacaoPosVendaOut,
    status_code=status.HTTP_201_CREATED,
)
def criar_solicitacao(
    data: SolicitacaoPosVendaCreate,
    db: Session = Depends(get_db),
    usuario: Usuario = Depends(get_current_user),
):
    pedido = (
        db.query(Pedido)
        .options(joinedload(Pedido.usuario))
        .filter(Pedido.numero == data.pedido_numero, Pedido.usuario_id == usuario.id)
        .first()
    )
    if not pedido:
        raise HTTPException(status_code=404, detail="Pedido nao encontrado.")
    if pedido.status not in PEDIDO_POS_VENDA_STATUS:
        raise HTTPException(
            status_code=409,
            detail="Troca ou devolucao disponivel apenas para pedidos enviados ou entregues.",
        )
    existente = (
        db.query(SolicitacaoPosVenda)
        .filter(
            SolicitacaoPosVenda.pedido_id == pedido.id,
            SolicitacaoPosVenda.status.in_(["recebida", "aprovada"]),
        )
        .first()
    )
    if existente:
        raise HTTPException(status_code=409, detail="Ja existe uma solicitacao ativa para este pedido.")

    solicitacao = SolicitacaoPosVenda(
        protocolo=f"TD-{pedido.numero}-{uuid4().hex[:6].upper()}",
        pedido_id=pedido.id,
        usuario_id=usuario.id,
        tipo=data.tipo,
        motivo=data.motivo,
    )
    db.add(solicitacao)
    db.commit()
    db.refresh(solicitacao)
    solicitacao.pedido = pedido

    extra = {
        "protocolo_troca": solicitacao.protocolo,
        "tipo_solicitacao": solicitacao.tipo,
        "motivo_solicitacao": solicitacao.motivo,
    }
    trigger_order_email_event(db, "return_exchange_requested", pedido, extra=extra)
    _trigger_internal_return_email(db, pedido, solicitacao)
    return _solicitacao_out(solicitacao)


@router.get("/trocas-devolucoes", response_model=list[SolicitacaoPosVendaOut])
def listar_minhas_solicitacoes(
    db: Session = Depends(get_db),
    usuario: Usuario = Depends(get_current_user),
):
    items = (
        db.query(SolicitacaoPosVenda)
        .options(joinedload(SolicitacaoPosVenda.pedido))
        .filter(SolicitacaoPosVenda.usuario_id == usuario.id)
        .order_by(SolicitacaoPosVenda.criado_em.desc())
        .all()
    )
    return [_solicitacao_out(item) for item in items]


@admin_router.get("/trocas-devolucoes", response_model=list[SolicitacaoPosVendaOut])
def listar_solicitacoes_admin(db: Session = Depends(get_db)):
    items = (
        db.query(SolicitacaoPosVenda)
        .options(joinedload(SolicitacaoPosVenda.pedido))
        .order_by(SolicitacaoPosVenda.criado_em.desc())
        .all()
    )
    return [_solicitacao_out(item) for item in items]


@admin_router.patch(
    "/trocas-devolucoes/{solicitacao_id}",
    response_model=SolicitacaoPosVendaOut,
)
def decidir_solicitacao(
    solicitacao_id: int,
    data: SolicitacaoPosVendaUpdate,
    db: Session = Depends(get_db),
):
    item = (
        db.query(SolicitacaoPosVenda)
        .options(joinedload(SolicitacaoPosVenda.pedido).joinedload(Pedido.usuario))
        .filter(SolicitacaoPosVenda.id == solicitacao_id)
        .first()
    )
    if not item:
        raise HTTPException(status_code=404, detail="Solicitacao nao encontrada.")
    if item.status != "recebida":
        raise HTTPException(status_code=409, detail="Solicitacao ja analisada.")
    item.status = data.status
    item.motivo_recusa = data.motivo_recusa
    db.commit()
    db.refresh(item)
    trigger_order_email_event(
        db,
        "return_exchange_approved" if data.status == "aprovada" else "return_exchange_refused",
        item.pedido,
        extra={
            "protocolo_troca": item.protocolo,
            "motivo_recusa": item.motivo_recusa or "",
        },
    )
    return _solicitacao_out(item)


@admin_router.post(
    "/pedidos/{pedido_numero}/documentos",
    response_model=DocumentoPedidoOut,
    status_code=status.HTTP_201_CREATED,
)
def registrar_documento(
    pedido_numero: str,
    data: DocumentoPedidoCreate,
    db: Session = Depends(get_db),
):
    pedido = (
        db.query(Pedido)
        .options(joinedload(Pedido.usuario))
        .filter(Pedido.numero == pedido_numero)
        .first()
    )
    if not pedido:
        raise HTTPException(status_code=404, detail="Pedido nao encontrado.")
    documento = (
        db.query(DocumentoPedido)
        .filter(DocumentoPedido.pedido_id == pedido.id, DocumentoPedido.tipo == data.tipo)
        .first()
    )
    if documento:
        documento.numero = data.numero
        documento.url = str(data.url)
    else:
        documento = DocumentoPedido(
            pedido_id=pedido.id,
            tipo=data.tipo,
            numero=data.numero,
            url=str(data.url),
        )
        db.add(documento)
    db.commit()
    db.refresh(documento)
    documento.pedido = pedido

    documentos = {item.tipo: item.url for item in pedido.documentos}
    document_version = hashlib.sha256(documento.url.encode("utf-8")).hexdigest()[:12]
    trigger_order_email_event(
        db,
        "invoice_receipt_available",
        pedido,
        extra={
            "invoice_url": documentos.get("nota_fiscal", ""),
            "receipt_url": documentos.get("recibo", ""),
            "link_nota_fiscal": documentos.get("nota_fiscal", ""),
            "link_recibo": documentos.get("recibo", ""),
            "documento_url": documento.url,
            "documento_tipo": "nota fiscal" if documento.tipo == "nota_fiscal" else "recibo",
            "dedupe_key": (
                f"nota_fiscal_recibo:{pedido.numero}:{data.tipo}:{documento.id}:{document_version}"
            ),
        },
    )
    return _documento_out(documento)


@admin_router.post(
    "/pedidos/{pedido_numero}/reembolsos/aprovar",
    response_model=ReembolsoOut,
    status_code=status.HTTP_201_CREATED,
)
def aprovar_reembolso(
    pedido_numero: str,
    data: ReembolsoAprovarPayload,
    db: Session = Depends(get_db),
):
    pedido = (
        db.query(Pedido)
        .options(joinedload(Pedido.usuario))
        .filter(Pedido.numero == pedido_numero)
        .first()
    )
    if not pedido:
        raise HTTPException(status_code=404, detail="Pedido nao encontrado.")
    if data.valor > pedido.total:
        raise HTTPException(status_code=422, detail="Reembolso nao pode superar o total do pedido.")
    existente = (
        db.query(ReembolsoPedido)
        .filter(ReembolsoPedido.pedido_id == pedido.id, ReembolsoPedido.status == "aprovado")
        .first()
    )
    if existente:
        raise HTTPException(status_code=409, detail="Ja existe um reembolso aprovado.")
    item = ReembolsoPedido(
        pedido_id=pedido.id,
        status="aprovado",
        valor=data.valor,
        prazo_dias_uteis=data.prazo_dias_uteis,
    )
    db.add(item)
    db.commit()
    db.refresh(item)
    item.pedido = pedido
    trigger_order_email_event(
        db,
        "refund_approved",
        pedido,
        extra={
            "refund_amount": f"R$ {data.valor:,.2f}".replace(",", "X").replace(".", ",").replace("X", "."),
            "refund_deadline": f"{data.prazo_dias_uteis} dias uteis",
            "valor_reembolso": f"R$ {data.valor:,.2f}".replace(",", "X").replace(".", ",").replace("X", "."),
            "prazo_reembolso": f"{data.prazo_dias_uteis} dias uteis",
        },
    )
    return _reembolso_out(item)

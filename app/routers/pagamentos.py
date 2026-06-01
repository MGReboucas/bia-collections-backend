"""
Router de pagamentos via Mercado Pago.

Fluxo PIX:
  POST /pagamentos/pix/{numero_pedido}
  → cria payment no MP com method=pix
  → retorna qr_code (texto) e qr_code_base64 (imagem)
  → frontend exibe QR Code

Fluxo Cartão/Boleto (Checkout Pro):
  POST /pagamentos/preferencia/{numero_pedido}
  → cria preference no MP
  → retorna checkout_url (sandbox) ou checkout_url_prod
  → frontend abre no navegador

Webhook (MP notifica quando pago):
  POST /pagamentos/webhook
  → valida o pagamento
  → atualiza status do pedido para "Pago"

Status:
  GET /pagamentos/status/{numero_pedido}
  → retorna status atual do pagamento
"""
from datetime import datetime, timedelta, timezone

import mercadopago
from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.core.config import settings
from app.database import get_db
from app.dependencies import get_current_user
from app.models.pagamento import Pagamento
from app.models.pedido import Pedido
from app.models.usuario import Usuario

router = APIRouter(prefix="/pagamentos", tags=["pagamentos"])


def _get_sdk() -> mercadopago.SDK:
    if not settings.MP_ACCESS_TOKEN:
        raise HTTPException(
            status_code=503,
            detail="Pagamentos ainda não configurados. Contate o suporte.",
        )
    return mercadopago.SDK(settings.MP_ACCESS_TOKEN)


# ── PIX ──────────────────────────────────────────────────────────────────────

@router.post("/pix/{numero_pedido}")
def criar_pagamento_pix(
    numero_pedido: str,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
):
    """Gera QR Code PIX para o pedido."""
    pedido = db.query(Pedido).filter(
        Pedido.numero == numero_pedido,
        Pedido.usuario_id == current_user.id,
    ).first()
    if not pedido:
        raise HTTPException(status_code=404, detail="Pedido não encontrado.")

    # Reutiliza pagamento PIX já existente se ainda válido
    pag_existente = db.query(Pagamento).filter(
        Pagamento.pedido_numero == numero_pedido,
        Pagamento.mp_payment_id.isnot(None),
    ).first()
    if pag_existente and pag_existente.status == "pendente":
        return {
            "qr_code": pag_existente.pix_qr_code,
            "qr_code_base64": pag_existente.pix_qr_code_base64,
            "payment_id": pag_existente.mp_payment_id,
            "expiracao": pag_existente.pix_expiracao,
        }

    sdk = _get_sdk()

    nome_partes = (current_user.nome_completo or current_user.username).split(" ", 1)
    payment_data = {
        "transaction_amount": float(pedido.total),
        "description": f"Bia Collections — Pedido {pedido.numero}",
        "payment_method_id": "pix",
        "payer": {
            "email": current_user.email,
            "first_name": nome_partes[0],
            "last_name": nome_partes[1] if len(nome_partes) > 1 else "",
        },
        "date_of_expiration": (
            datetime.now(timezone.utc) + timedelta(hours=24)
        ).strftime("%Y-%m-%dT%H:%M:%S.000-03:00"),
        "external_reference": pedido.numero,
        "notification_url": (
            f"{settings.MP_NOTIFICATION_URL}/api/v1/pagamentos/webhook"
            if settings.MP_NOTIFICATION_URL
            else None
        ),
    }
    # Remove notification_url se não configurado
    if not payment_data["notification_url"]:
        payment_data.pop("notification_url")

    result = sdk.payment().create(payment_data)
    response = result.get("response", {})

    if result.get("status") not in (200, 201):
        raise HTTPException(
            status_code=502,
            detail=f"Erro ao gerar PIX: {response.get('message', 'Erro desconhecido')}",
        )

    tx_data = response.get("point_of_interaction", {}).get("transaction_data", {})
    qr_code = tx_data.get("qr_code", "")
    qr_code_base64 = tx_data.get("qr_code_base64", "")
    payment_id = str(response.get("id", ""))
    expiracao = datetime.now(timezone.utc) + timedelta(hours=24)

    pagamento = Pagamento(
        pedido_numero=numero_pedido,
        mp_payment_id=payment_id,
        pix_qr_code=qr_code,
        pix_qr_code_base64=qr_code_base64,
        pix_expiracao=expiracao,
        status="pendente",
    )
    db.add(pagamento)
    db.commit()

    return {
        "qr_code": qr_code,
        "qr_code_base64": qr_code_base64,
        "payment_id": payment_id,
        "expiracao": expiracao,
    }


# ── Checkout Pro (cartão / boleto) ───────────────────────────────────────────

@router.post("/preferencia/{numero_pedido}")
def criar_preferencia(
    numero_pedido: str,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
):
    """Cria preferência de pagamento (cartão/boleto) no Checkout Pro do MP."""
    pedido = db.query(Pedido).filter(
        Pedido.numero == numero_pedido,
        Pedido.usuario_id == current_user.id,
    ).first()
    if not pedido:
        raise HTTPException(status_code=404, detail="Pedido não encontrado.")

    # Reutiliza preference já existente
    pag_existente = db.query(Pagamento).filter(
        Pagamento.pedido_numero == numero_pedido,
        Pagamento.mp_preference_id.isnot(None),
    ).first()
    if pag_existente:
        return {
            "checkout_url": pag_existente.checkout_url,
            "checkout_url_prod": pag_existente.checkout_url_prod,
            "preference_id": pag_existente.mp_preference_id,
        }

    sdk = _get_sdk()

    itens_mp = [
        {
            "id": str(item.produto_id),
            "title": item.nome_produto,
            "quantity": item.quantidade,
            "unit_price": float(item.preco_unitario),
            "currency_id": "BRL",
        }
        for item in pedido.itens
    ]

    preference_data = {
        "items": itens_mp,
        "payer": {"email": current_user.email},
        "external_reference": pedido.numero,
        "back_urls": {
            "success": f"{settings.FRONTEND_URL}/meus-pedidos",
            "failure": f"{settings.FRONTEND_URL}/checkout",
            "pending": f"{settings.FRONTEND_URL}/meus-pedidos",
        },
        "auto_return": "approved",
    }
    if settings.MP_NOTIFICATION_URL:
        preference_data["notification_url"] = (
            f"{settings.MP_NOTIFICATION_URL}/api/v1/pagamentos/webhook"
        )

    result = sdk.preference().create(preference_data)
    response = result.get("response", {})

    if result.get("status") not in (200, 201):
        raise HTTPException(
            status_code=502,
            detail=f"Erro ao criar preferência: {response.get('message', 'Erro desconhecido')}",
        )

    preference_id = response.get("id", "")
    checkout_url = response.get("sandbox_init_point", "")       # teste
    checkout_url_prod = response.get("init_point", "")          # produção

    pagamento = Pagamento(
        pedido_numero=numero_pedido,
        mp_preference_id=preference_id,
        checkout_url=checkout_url,
        checkout_url_prod=checkout_url_prod,
        status="pendente",
    )
    db.add(pagamento)
    db.commit()

    return {
        "checkout_url": checkout_url,
        "checkout_url_prod": checkout_url_prod,
        "preference_id": preference_id,
    }


# ── Webhook ───────────────────────────────────────────────────────────────────

@router.post("/webhook", status_code=status.HTTP_200_OK)
async def webhook(request: Request, db: Session = Depends(get_db)):
    """
    Recebe notificações do Mercado Pago e atualiza o status do pedido.
    MP envia POST com {type: 'payment', data: {id: '...'}}
    """
    try:
        data = await request.json()
    except Exception:
        return {"status": "ignored"}

    if data.get("type") != "payment":
        return {"status": "ignored"}

    payment_id = str(data.get("data", {}).get("id", ""))
    if not payment_id or not settings.MP_ACCESS_TOKEN:
        return {"status": "ignored"}

    sdk = mercadopago.SDK(settings.MP_ACCESS_TOKEN)
    result = sdk.payment().get(payment_id)
    response = result.get("response", {})

    mp_status = response.get("status", "")
    external_ref = response.get("external_reference", "")

    if not external_ref:
        return {"status": "ignored"}

    # Mapeia status do MP para status interno
    status_map = {
        "approved": "Pago",
        "pending": "Aguardando pagamento",
        "in_process": "Aguardando pagamento",
        "rejected": "Pagamento recusado",
        "cancelled": "Cancelado",
        "refunded": "Reembolsado",
    }
    novo_status_pedido = status_map.get(mp_status)
    novo_status_pagamento = "aprovado" if mp_status == "approved" else mp_status

    pedido = db.query(Pedido).filter(Pedido.numero == external_ref).first()
    if pedido and novo_status_pedido:
        pedido.status = novo_status_pedido

    pagamento = db.query(Pagamento).filter(
        Pagamento.pedido_numero == external_ref
    ).first()
    if pagamento:
        pagamento.mp_payment_id = pagamento.mp_payment_id or payment_id
        pagamento.status = novo_status_pagamento

    db.commit()
    return {"status": "ok"}


# ── Status ────────────────────────────────────────────────────────────────────

@router.get("/status/{numero_pedido}")
def status_pagamento(
    numero_pedido: str,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
):
    """Retorna o status atual do pagamento de um pedido."""
    pedido = db.query(Pedido).filter(
        Pedido.numero == numero_pedido,
        Pedido.usuario_id == current_user.id,
    ).first()
    if not pedido:
        raise HTTPException(status_code=404, detail="Pedido não encontrado.")

    return {
        "numero_pedido": numero_pedido,
        "status_pedido": pedido.status,
        "pago": pedido.status == "Pago",
    }

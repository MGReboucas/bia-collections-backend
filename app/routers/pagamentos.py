from datetime import datetime, timedelta, timezone
import hashlib
import hmac
from uuid import uuid4

import mercadopago
from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.core.config import settings
from app.database import get_db
from app.dependencies import get_current_user
from app.models.pagamento import Pagamento
from app.models.pedido import Pedido
from app.models.usuario import Usuario
from app.modules.email.service import trigger_order_email_event
from app.services.payment_status import (
    MP_TO_ORDER_STATUS,
    MP_TO_PAYMENT_STATUS,
    ORDER_STATUS_CANCELADO,
    ORDER_STATUS_PAGO,
    ORDER_STATUS_REEMBOLSADO,
    PAYMENT_EMAIL_EVENTS,
)

router = APIRouter(prefix="/pagamentos", tags=["pagamentos"])

PAGAMENTOS_REABRIVEIS = {"pendente", "em_analise"}
PEDIDOS_SEM_NOVO_PAGAMENTO = {
    ORDER_STATUS_PAGO,
    ORDER_STATUS_CANCELADO,
    ORDER_STATUS_REEMBOLSADO,
}


def _get_sdk() -> mercadopago.SDK:
    if not settings.MP_ACCESS_TOKEN:
        raise HTTPException(
            status_code=503,
            detail="Pagamentos ainda nao configurados. Contate o suporte.",
        )
    return mercadopago.SDK(settings.MP_ACCESS_TOKEN)


def _notification_url() -> str | None:
    if not settings.MP_NOTIFICATION_URL:
        return None
    return f"{settings.MP_NOTIFICATION_URL.rstrip('/')}/api/v1/pagamentos/webhook"


def _data_expiracao_pix() -> datetime:
    return datetime.now(timezone(timedelta(hours=-3))) + timedelta(hours=24)


def _formatar_data_mp(data: datetime) -> str:
    return data.strftime("%Y-%m-%dT%H:%M:%S.000-03:00")


def _normalizar_datetime(data: datetime | None) -> datetime | None:
    if data is None:
        return None
    if data.tzinfo is None:
        return data.replace(tzinfo=timezone.utc)
    return data


def _pagamento_pix_reutilizavel(pagamento: Pagamento) -> bool:
    if pagamento.status not in PAGAMENTOS_REABRIVEIS:
        return False
    expiracao = _normalizar_datetime(pagamento.pix_expiracao)
    return expiracao is None or expiracao > datetime.now(timezone.utc)


def _validar_pedido_para_novo_pagamento(pedido: Pedido) -> None:
    if pedido.status in PEDIDOS_SEM_NOVO_PAGAMENTO:
        raise HTTPException(
            status_code=409,
            detail=f"Pedido com status '{pedido.status}' nao aceita novo pagamento.",
        )
    if pedido.total <= 0:
        raise HTTPException(
            status_code=422,
            detail="Pedido sem valor a pagar.",
        )


def _idempotency_key(numero_pedido: str, tipo: str) -> str:
    return f"bia-{tipo}-{numero_pedido}-{uuid4().hex}"


def _criar_recurso_mp(resource, payload: dict, idempotency_key: str):
    try:
        from mercadopago.config import RequestOptions

        options = RequestOptions(
            custom_headers={"x-idempotency-key": idempotency_key}
        )
        return resource.create(payload, options)
    except (ImportError, AttributeError, TypeError):
        return resource.create(payload)


def _parse_x_signature(value: str | None) -> dict[str, str]:
    parts: dict[str, str] = {}
    for item in (value or "").split(","):
        key, separator, part_value = item.strip().partition("=")
        if separator:
            parts[key] = part_value
    return parts


def _validar_assinatura_fallback(
    x_signature: str,
    x_request_id: str,
    data_id: str,
    secret: str,
) -> bool:
    signature_parts = _parse_x_signature(x_signature)
    ts = signature_parts.get("ts")
    received = signature_parts.get("v1")
    if not ts or not received:
        return False

    manifest = f"id:{data_id};request-id:{x_request_id};ts:{ts};"
    expected = hmac.new(
        secret.encode("utf-8"),
        manifest.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(expected, received)


def _extrair_payment_id(request: Request, data: dict) -> str:
    return str(
        request.query_params.get("data.id")
        or request.query_params.get("data_id")
        or data.get("data", {}).get("id")
        or data.get("id")
        or ""
    )


def _validar_assinatura_webhook(request: Request, data: dict, payment_id: str) -> None:
    if not settings.MP_WEBHOOK_SECRET:
        return

    x_signature = request.headers.get("x-signature")
    x_request_id = request.headers.get("x-request-id")
    if not x_signature or not x_request_id or not payment_id:
        raise HTTPException(status_code=401, detail="Assinatura do webhook ausente.")

    try:
        from mercadopago.webhook import (
            InvalidWebhookSignatureError,
            WebhookSignatureValidator,
        )

        try:
            WebhookSignatureValidator.validate(
                x_signature,
                x_request_id,
                payment_id,
                settings.MP_WEBHOOK_SECRET,
            )
            return
        except InvalidWebhookSignatureError:
            raise HTTPException(status_code=401, detail="Assinatura do webhook invalida.")
        except Exception:
            if _validar_assinatura_fallback(
                x_signature,
                x_request_id,
                payment_id,
                settings.MP_WEBHOOK_SECRET,
            ):
                return
            raise HTTPException(status_code=401, detail="Assinatura do webhook invalida.")
    except ImportError:
        if _validar_assinatura_fallback(
            x_signature,
            x_request_id,
            payment_id,
            settings.MP_WEBHOOK_SECRET,
        ):
            return
        raise HTTPException(status_code=401, detail="Assinatura do webhook invalida.")


def _tipo_pagamento_mp(response: dict) -> str:
    metadata = response.get("metadata") or {}
    if metadata.get("payment_flow") in {"pix", "checkout_pro"}:
        return metadata["payment_flow"]
    if response.get("payment_method_id") == "pix":
        return "pix"
    return "checkout_pro"


def _pagamento_payload(pagamento: Pagamento | None) -> dict | None:
    if not pagamento:
        return None
    return {
        "id": pagamento.id,
        "tipo": pagamento.tipo,
        "status": pagamento.status,
        "mp_status": pagamento.mp_status,
        "payment_id": pagamento.mp_payment_id,
        "preference_id": pagamento.mp_preference_id,
        "pix_expiracao": pagamento.pix_expiracao,
        "checkout_url": pagamento.checkout_url,
        "checkout_url_prod": pagamento.checkout_url_prod,
    }


@router.post("/pix/{numero_pedido}")
def criar_pagamento_pix(
    numero_pedido: str,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
):
    pedido = db.query(Pedido).filter(
        Pedido.numero == numero_pedido,
        Pedido.usuario_id == current_user.id,
    ).first()
    if not pedido:
        raise HTTPException(status_code=404, detail="Pedido nao encontrado.")
    _validar_pedido_para_novo_pagamento(pedido)

    pag_existente = (
        db.query(Pagamento)
        .filter(
            Pagamento.pedido_numero == numero_pedido,
            Pagamento.tipo == "pix",
            Pagamento.mp_payment_id.isnot(None),
        )
        .order_by(Pagamento.id.desc())
        .first()
    )
    if pag_existente and _pagamento_pix_reutilizavel(pag_existente):
        return {
            "qr_code": pag_existente.pix_qr_code,
            "qr_code_base64": pag_existente.pix_qr_code_base64,
            "payment_id": pag_existente.mp_payment_id,
            "expiracao": pag_existente.pix_expiracao,
            "status": pag_existente.status,
        }
    if pag_existente and pag_existente.status in PAGAMENTOS_REABRIVEIS:
        pag_existente.status = "expirado"
        pag_existente.mp_status = pag_existente.mp_status or "expired"
        db.flush()

    sdk = _get_sdk()
    expiracao = _data_expiracao_pix()
    idempotency_key = _idempotency_key(numero_pedido, "pix")
    nome_partes = (current_user.nome_completo or current_user.username).split(" ", 1)

    payment_data = {
        "transaction_amount": float(pedido.total),
        "description": f"Bia Collections - Pedido {pedido.numero}",
        "payment_method_id": "pix",
        "payer": {
            "email": current_user.email,
            "first_name": nome_partes[0],
            "last_name": nome_partes[1] if len(nome_partes) > 1 else "",
        },
        "date_of_expiration": _formatar_data_mp(expiracao),
        "external_reference": pedido.numero,
        "metadata": {
            "pedido_numero": pedido.numero,
            "payment_flow": "pix",
        },
    }
    notification_url = _notification_url()
    if notification_url:
        payment_data["notification_url"] = notification_url

    result = _criar_recurso_mp(sdk.payment(), payment_data, idempotency_key)
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

    pagamento = Pagamento(
        pedido_numero=numero_pedido,
        tipo="pix",
        valor=float(pedido.total),
        idempotency_key=idempotency_key,
        mp_payment_id=payment_id,
        pix_qr_code=qr_code,
        pix_qr_code_base64=qr_code_base64,
        pix_expiracao=expiracao,
        status=MP_TO_PAYMENT_STATUS.get(response.get("status", "pending"), "pendente"),
        mp_status=response.get("status"),
    )
    db.add(pagamento)
    db.commit()
    trigger_order_email_event(db, "pix_generated", pedido, extra={"pix_code": qr_code})

    return {
        "qr_code": qr_code,
        "qr_code_base64": qr_code_base64,
        "payment_id": payment_id,
        "expiracao": expiracao,
        "status": pagamento.status,
    }


@router.post("/preferencia/{numero_pedido}")
def criar_preferencia(
    numero_pedido: str,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
):
    pedido = db.query(Pedido).filter(
        Pedido.numero == numero_pedido,
        Pedido.usuario_id == current_user.id,
    ).first()
    if not pedido:
        raise HTTPException(status_code=404, detail="Pedido nao encontrado.")
    _validar_pedido_para_novo_pagamento(pedido)

    pag_existente = (
        db.query(Pagamento)
        .filter(
            Pagamento.pedido_numero == numero_pedido,
            Pagamento.tipo == "checkout_pro",
            Pagamento.mp_preference_id.isnot(None),
            Pagamento.status.in_(list(PAGAMENTOS_REABRIVEIS)),
        )
        .order_by(Pagamento.id.desc())
        .first()
    )
    if pag_existente:
        return {
            "checkout_url": pag_existente.checkout_url,
            "checkout_url_prod": pag_existente.checkout_url_prod,
            "preference_id": pag_existente.mp_preference_id,
            "status": pag_existente.status,
        }

    sdk = _get_sdk()
    idempotency_key = _idempotency_key(numero_pedido, "checkout")
    preference_data = {
        "items": [
            {
                "id": pedido.numero,
                "title": f"Bia Collections - Pedido {pedido.numero}",
                "quantity": 1,
                "unit_price": float(pedido.total),
                "currency_id": "BRL",
            }
        ],
        "payer": {"email": current_user.email},
        "external_reference": pedido.numero,
        "metadata": {
            "pedido_numero": pedido.numero,
            "payment_flow": "checkout_pro",
        },
        "back_urls": {
            "success": f"{settings.FRONTEND_URL}/meus-pedidos",
            "failure": f"{settings.FRONTEND_URL}/checkout",
            "pending": f"{settings.FRONTEND_URL}/meus-pedidos",
        },
        "auto_return": "approved",
    }
    notification_url = _notification_url()
    if notification_url:
        preference_data["notification_url"] = notification_url

    result = _criar_recurso_mp(sdk.preference(), preference_data, idempotency_key)
    response = result.get("response", {})
    if result.get("status") not in (200, 201):
        raise HTTPException(
            status_code=502,
            detail=f"Erro ao criar preferencia: {response.get('message', 'Erro desconhecido')}",
        )

    preference_id = response.get("id", "")
    checkout_url = response.get("sandbox_init_point", "")
    checkout_url_prod = response.get("init_point", "")

    pagamento = Pagamento(
        pedido_numero=numero_pedido,
        tipo="checkout_pro",
        valor=float(pedido.total),
        idempotency_key=idempotency_key,
        mp_preference_id=preference_id,
        checkout_url=checkout_url,
        checkout_url_prod=checkout_url_prod,
        status="pendente",
    )
    db.add(pagamento)
    db.commit()
    trigger_order_email_event(
        db,
        "payment_pending",
        pedido,
        extra={"payment_link": checkout_url_prod or checkout_url},
    )

    return {
        "checkout_url": checkout_url,
        "checkout_url_prod": checkout_url_prod,
        "preference_id": preference_id,
        "status": pagamento.status,
    }


@router.post("/webhook", status_code=status.HTTP_200_OK)
async def webhook(request: Request, db: Session = Depends(get_db)):
    try:
        data = await request.json()
    except Exception:
        data = {}

    payment_id = _extrair_payment_id(request, data)
    if data and data.get("type") not in (None, "payment"):
        return {"status": "ignored"}
    if not payment_id:
        return {"status": "ignored"}

    _validar_assinatura_webhook(request, data, payment_id)
    if not settings.MP_ACCESS_TOKEN:
        return {"status": "ignored"}

    sdk = mercadopago.SDK(settings.MP_ACCESS_TOKEN)
    result = sdk.payment().get(payment_id)
    response = result.get("response", {})
    if result.get("status") not in (200, 201):
        raise HTTPException(status_code=502, detail="Erro ao consultar pagamento.")

    mp_status = response.get("status", "")
    metadata = response.get("metadata") or {}
    external_ref = response.get("external_reference") or metadata.get("pedido_numero")
    if not external_ref:
        return {"status": "ignored"}

    novo_status_pedido = MP_TO_ORDER_STATUS.get(mp_status)
    novo_status_pagamento = MP_TO_PAYMENT_STATUS.get(mp_status, mp_status or "pendente")
    tipo = _tipo_pagamento_mp(response)

    pedido = db.query(Pedido).filter(Pedido.numero == external_ref).first()
    if pedido and novo_status_pedido:
        if not (pedido.status == ORDER_STATUS_PAGO and novo_status_pedido != ORDER_STATUS_PAGO):
            pedido.status = novo_status_pedido

    pagamento = db.query(Pagamento).filter(Pagamento.mp_payment_id == payment_id).first()
    if not pagamento:
        pagamento = (
            db.query(Pagamento)
            .filter(Pagamento.pedido_numero == external_ref, Pagamento.tipo == tipo)
            .order_by(Pagamento.id.desc())
            .first()
        )
    if not pagamento:
        pagamento = Pagamento(
            pedido_numero=external_ref,
            tipo=tipo,
            mp_payment_id=payment_id,
        )
        db.add(pagamento)

    pagamento.mp_payment_id = payment_id
    pagamento.status = novo_status_pagamento
    pagamento.mp_status = mp_status
    pagamento.valor = float(response.get("transaction_amount") or pagamento.valor or 0.0)

    db.commit()
    event_key = PAYMENT_EMAIL_EVENTS.get(mp_status)
    if pedido and event_key:
        db.refresh(pedido)
        trigger_order_email_event(db, event_key, pedido)
    return {"status": "ok"}


@router.get("/status/{numero_pedido}")
def status_pagamento(
    numero_pedido: str,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
):
    pedido = db.query(Pedido).filter(
        Pedido.numero == numero_pedido,
        Pedido.usuario_id == current_user.id,
    ).first()
    if not pedido:
        raise HTTPException(status_code=404, detail="Pedido nao encontrado.")

    pagamento = (
        db.query(Pagamento)
        .filter(Pagamento.pedido_numero == numero_pedido)
        .order_by(Pagamento.id.desc())
        .first()
    )
    return {
        "numero_pedido": numero_pedido,
        "status_pedido": pedido.status,
        "pago": pedido.status == ORDER_STATUS_PAGO,
        "pagamento": _pagamento_payload(pagamento),
    }

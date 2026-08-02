from datetime import datetime, timedelta, timezone
from decimal import Decimal
import hashlib
import hmac
import logging
from uuid import uuid4

import httpx
import mercadopago
from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.core.config import settings
from app.database import get_db
from app.dependencies import get_current_user
from app.models.cupom import Cupom, CupomUsado
from app.models.pagamento import Pagamento
from app.models.pedido import Pedido
from app.models.pos_venda import ReembolsoPedido
from app.models.usuario import Usuario
from app.modules.email.service import (
    schedule_abandoned_checkout_email_events,
    trigger_admin_order_paid_email,
    trigger_order_email_event,
)
from app.modules.email.marketing import attribute_order_conversion
from app.schemas.pedido import PagamentoCartaoRequest, PagamentoCartaoResponse
from app.services.cupom_service import reservar_uso_cupom
from app.services.meta_conversions import send_meta_purchase_for_paid_order
from app.services.payment_status import (
    MP_TO_ORDER_STATUS,
    MP_TO_PAYMENT_STATUS,
    ORDER_STATUS_CANCELADO,
    ORDER_STATUS_PAGO,
    ORDER_STATUS_REEMBOLSADO,
    ORDER_STATUSES_PAGOS,
    PAYMENT_EMAIL_EVENTS,
)

router = APIRouter(prefix="/pagamentos", tags=["pagamentos"])
logger = logging.getLogger(__name__)

PAGAMENTOS_REABRIVEIS = {"pendente", "em_analise"}
PEDIDOS_SEM_NOVO_PAGAMENTO = set(ORDER_STATUSES_PAGOS) | {
    ORDER_STATUS_CANCELADO,
    ORDER_STATUS_REEMBOLSADO,
}
MP_ORDERS_URL = "https://api.mercadopago.com/v1/orders"
MP_LIVE_CREDENTIALS_ERROR = "Unauthorized use of live credentials"


def _require_mp_access_token() -> str:
    if not settings.MP_ACCESS_TOKEN:
        raise HTTPException(
            status_code=503,
            detail="Pagamentos ainda nao configurados. Contate o suporte.",
        )
    return settings.MP_ACCESS_TOKEN.strip()


def _get_sdk() -> mercadopago.SDK:
    return mercadopago.SDK(_require_mp_access_token())


def _notification_url() -> str | None:
    if not settings.MP_NOTIFICATION_URL:
        return None
    return f"{settings.MP_NOTIFICATION_URL.rstrip('/')}/api/v1/pagamentos/webhook"


def _adicionar_notification_url(payload: dict) -> None:
    notification_url = _notification_url()
    if notification_url:
        payload["notification_url"] = notification_url


def _separar_nome_completo(nome_completo: str | None) -> tuple[str, str]:
    partes = str(nome_completo or "").strip().split()
    if not partes:
        return "", ""
    return partes[0], " ".join(partes[1:])


def _payer_preferencia(usuario: Usuario, pedido: Pedido) -> dict:
    payer: dict = {"email": usuario.email}
    nome, sobrenome = _separar_nome_completo(usuario.nome_completo)
    if nome:
        payer["name"] = nome
    if sobrenome:
        payer["surname"] = sobrenome

    address = {
        "zip_code": pedido.endereco_cep,
        "street_name": pedido.endereco_rua,
        "street_number": pedido.endereco_numero,
    }
    if all(address.values()):
        payer["address"] = address
    return payer


def _preferencia_mp_reutilizavel(sdk: mercadopago.SDK, pagamento: Pagamento) -> bool:
    try:
        result = sdk.preference().get(pagamento.mp_preference_id)
    except Exception:
        logger.exception(
            "Falha ao validar preferencia existente do Mercado Pago. preference_id=%s",
            pagamento.mp_preference_id,
        )
        return False

    if result.get("status") not in (200, 201):
        return False
    preference = result.get("response") or {}
    items = preference.get("items") or []
    return bool(
        preference.get("notification_url") == _notification_url()
        and items
        and all(str(item.get("description") or "").strip() for item in items)
    )


def _data_expiracao_pix() -> datetime:
    return datetime.now(timezone(timedelta(hours=-3))) + timedelta(hours=24)


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


def _formatar_valor_mp(valor: float) -> str:
    return f"{float(valor):.2f}"


def _validar_valor_pagamento(valor_enviado: float, valor_pedido: float) -> None:
    diferenca = abs(Decimal(str(valor_enviado)) - Decimal(str(valor_pedido)))
    if diferenca > Decimal("0.01"):
        raise HTTPException(
            status_code=422,
            detail="valor divergente entre pagamento e pedido. Recalcule o pedido antes de pagar.",
        )


def _mensagem_erro_mp(response: dict, fluxo: str = "pagamento") -> str:
    if not isinstance(response, dict):
        return "Erro desconhecido"
    message = response.get("message") or response.get("error") or response.get("status_detail")
    cause = response.get("cause") or response.get("errors")
    if not message and isinstance(cause, list) and cause:
        first = cause[0]
        if isinstance(first, dict):
            message = str(first.get("description") or first.get("message") or first.get("code") or "Erro desconhecido")
        else:
            message = str(first)
    message = str(message or "")
    if message == MP_LIVE_CREDENTIALS_ERROR:
        if fluxo == "pix":
            return (
                "Mercado Pago recusou as credenciais de producao para gerar PIX. "
                "Confira se a conta vendedora tem Pix/chave Pix liberados e teste com "
                "um comprador real diferente da conta Mercado Pago vendedora. "
                f"Mensagem original: {MP_LIVE_CREDENTIALS_ERROR}"
            )
        if fluxo == "cartao":
            return (
                "Mercado Pago recusou a credencial ao criar a order de cartao. "
                "Confira se o Access Token pertence a aplicacao Checkout Transparente via Orders "
                "e ao mesmo ambiente usado para gerar o token do cartao. "
                f"Mensagem original: {MP_LIVE_CREDENTIALS_ERROR}"
            )
        return (
            "Mercado Pago recusou as credenciais de producao. "
            "Confira se as credenciais pertencem a uma aplicacao ativa e se "
            "o ambiente de teste/producao esta correto. "
            f"Mensagem original: {MP_LIVE_CREDENTIALS_ERROR}"
        )
    return message or "Erro desconhecido"


def _criar_order_mp(
    payload: dict,
    idempotency_key: str,
    *,
    fluxo: str,
) -> tuple[int, dict]:
    headers = {
        "accept": "application/json",
        "content-type": "application/json",
        "Authorization": f"Bearer {_require_mp_access_token()}",
        "X-Idempotency-Key": idempotency_key,
    }
    try:
        with httpx.Client(timeout=20.0) as client:
            response = client.post(MP_ORDERS_URL, headers=headers, json=payload)
    except httpx.HTTPError:
        logger.exception(
            "Erro de comunicacao ao criar order %s no Mercado Pago",
            fluxo,
        )
        raise HTTPException(
            status_code=502,
            detail=f"Erro de comunicacao com o Mercado Pago ao processar {fluxo}.",
        )

    try:
        body = response.json()
    except ValueError:
        body = {}
    if response.status_code not in (200, 201):
        logger.warning(
            "Mercado Pago recusou order %s: status=%s message=%s request_id=%s",
            fluxo,
            response.status_code,
            _mensagem_erro_mp(body, fluxo=fluxo),
            response.headers.get("x-request-id") or response.headers.get("x-correlation-id") or "",
        )
    return response.status_code, body


def _criar_order_pix_mp(payload: dict, idempotency_key: str) -> tuple[int, dict]:
    return _criar_order_mp(payload, idempotency_key, fluxo="pix")


def _criar_order_cartao_mp(payload: dict, idempotency_key: str) -> tuple[int, dict]:
    return _criar_order_mp(payload, idempotency_key, fluxo="cartao")


def _consultar_order_mp(order_id: str) -> tuple[int, dict]:
    headers = {
        "accept": "application/json",
        "Authorization": f"Bearer {settings.MP_ACCESS_TOKEN}",
    }
    try:
        with httpx.Client(timeout=20.0) as client:
            response = client.get(f"{MP_ORDERS_URL}/{order_id}", headers=headers)
    except httpx.HTTPError:
        logger.exception("Erro de comunicacao ao consultar order no Mercado Pago")
        raise HTTPException(
            status_code=502,
            detail="Erro de comunicacao com o Mercado Pago ao consultar pagamento.",
        )

    try:
        body = response.json()
    except ValueError:
        body = {}
    return response.status_code, body


def _formatar_data_mp(data: datetime) -> str:
    return data.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _buscar_order_mp_por_referencia(external_reference: str, criado_em: datetime | None) -> dict | None:
    data_base = _normalizar_datetime(criado_em) or datetime.now(timezone.utc)
    inicio = data_base.astimezone(timezone.utc) - timedelta(days=1)
    fim = datetime.now(timezone.utc) + timedelta(days=1)
    headers = {
        "accept": "application/json",
        "Authorization": f"Bearer {settings.MP_ACCESS_TOKEN}",
    }
    params = {
        "external_reference": external_reference,
        "begin_date": _formatar_data_mp(inicio),
        "end_date": _formatar_data_mp(fim),
        "type": "online",
    }
    try:
        with httpx.Client(timeout=20.0) as client:
            response = client.get(MP_ORDERS_URL, headers=headers, params=params)
    except httpx.HTTPError:
        logger.exception("Erro de comunicacao ao buscar order no Mercado Pago")
        return None

    try:
        body = response.json()
    except ValueError:
        body = {}
    if response.status_code not in (200, 201):
        logger.warning(
            "Mercado Pago recusou busca de order: status=%s message=%s",
            response.status_code,
            _mensagem_erro_mp(body),
        )
        return None
    data = body.get("data") or body.get("results") or []
    return data[0] if data else None


def _extrair_order(response: dict) -> dict:
    payments = response.get("transactions", {}).get("payments") or []
    payment = payments[0] if payments else {}
    payment_method = payment.get("payment_method") or {}
    return {
        "order_id": str(response.get("id") or ""),
        "payment_id": str(payment.get("id") or response.get("id") or ""),
        "status": payment.get("status") or response.get("status") or "pending",
        "status_detail": payment.get("status_detail") or response.get("status_detail") or "",
        "payment_method_id": payment_method.get("id") or "",
        "payment_method_type": payment_method.get("type") or "",
        "amount": payment.get("amount") or response.get("total_amount") or 0.0,
        "qr_code": payment_method.get("qr_code") or "",
        "qr_code_base64": (
            payment_method.get("qr_code_base64")
            or payment_method.get("qr_code_based64")
            or ""
        ),
        "ticket_url": payment_method.get("ticket_url") or "",
    }


def _extrair_pix_order(response: dict) -> dict:
    return _extrair_order(response)


def _extrair_payment_from_order(response: dict) -> dict:
    order_data = _extrair_order(response)
    payment_flow = "pix" if order_data["payment_method_id"] == "pix" else "cartao"
    return {
        "order_id": order_data["order_id"],
        "payment_id": order_data["payment_id"],
        "status": order_data["status"],
        "mp_status": order_data["status"],
        "status_detail": order_data["status_detail"],
        "external_reference": response.get("external_reference") or "",
        "transaction_amount": order_data["amount"],
        "payment_method_id": order_data["payment_method_id"],
        "metadata": {
            "pedido_numero": response.get("external_reference") or "",
            "payment_flow": payment_flow,
        },
    }


def _status_pix_local(mp_status: str) -> str:
    if mp_status == "action_required":
        return "pendente"
    return MP_TO_PAYMENT_STATUS.get(mp_status or "pending", "pendente")


def _criar_recurso_mp(
    resource,
    payload: dict,
    idempotency_key: str,
):
    request_options = mercadopago.config.RequestOptions()
    request_options.custom_headers = {
        "x-idempotency-key": idempotency_key,
    }

    try:
        return resource.create(payload, request_options)
    except Exception:
        logger.exception(
            "Falha ao criar recurso no Mercado Pago. "
            "idempotency_key=%s",
            idempotency_key,
        )
        raise


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

    # A documentacao do Mercado Pago exige IDs alfanumericos em minusculas
    # para a montagem do manifesto assinado (Orders usa IDs alfanumericos).
    manifest = f"id:{data_id.lower()};request-id:{x_request_id};ts:{ts};"
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


def _extrair_notification_type(request: Request, data: dict) -> str | None:
    value = (
        request.query_params.get("type")
        or request.query_params.get("topic")
        or (data.get("type") if data else None)
        or (data.get("topic") if data else None)
    )
    return str(value) if value else None


def _validar_assinatura_webhook(request: Request, data: dict, payment_id: str) -> None:
    if not settings.MP_WEBHOOK_SECRET:
        if settings.require_mp_webhook_secret:
            raise HTTPException(status_code=503, detail="Webhook secret nao configurado.")
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
    if metadata.get("payment_flow") in {"pix", "checkout_pro", "cartao"}:
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
        "order_id": pagamento.mp_order_id,
        "preference_id": pagamento.mp_preference_id,
        "valor": pagamento.valor,
        "atualizado_em": pagamento.atualizado_em,
        "pix_expiracao": pagamento.pix_expiracao,
        "checkout_url": pagamento.checkout_url,
        "checkout_url_prod": pagamento.checkout_url_prod,
    }


def _buscar_pagamento_existente(db: Session, response: dict, payment_id: str) -> Pagamento | None:
    pagamento = None
    if payment_id:
        pagamento = db.query(Pagamento).filter(Pagamento.mp_payment_id == payment_id).first()
    if pagamento:
        return pagamento

    order_id = response.get("order_id")
    if order_id:
        pagamento = db.query(Pagamento).filter(Pagamento.mp_order_id == str(order_id)).first()
    if pagamento:
        return pagamento

    preference_id = response.get("preference_id")
    if preference_id:
        pagamento = db.query(Pagamento).filter(Pagamento.mp_preference_id == preference_id).first()
    return pagamento


def _external_reference_pagamento(response: dict, pagamento: Pagamento | None) -> str:
    metadata = response.get("metadata") or {}
    return str(
        response.get("external_reference")
        or metadata.get("pedido_numero")
        or (pagamento.pedido_numero if pagamento else "")
        or ""
    )


def _registrar_cupom_pagamento_aprovado(db: Session, pedido: Pedido) -> None:
    if not pedido.cupom_codigo:
        return
    cupom = (
        db.query(Cupom)
        .filter(Cupom.codigo == pedido.cupom_codigo, Cupom.deletado_em.is_(None))
        .first()
    )
    if not cupom:
        return
    ja_registrado = (
        db.query(CupomUsado)
        .filter(
            CupomUsado.cupom_id == cupom.id,
            CupomUsado.usuario_id == pedido.usuario_id,
            CupomUsado.pedido_id == pedido.id,
        )
        .first()
    )
    if ja_registrado:
        return
    reservar_uso_cupom(db, cupom)
    db.add(
        CupomUsado(
            cupom_id=cupom.id,
            usuario_id=pedido.usuario_id,
            pedido_id=pedido.id,
        )
    )


def _trigger_payment_email_event(
    db: Session,
    event_key: str,
    pedido: Pedido,
    *,
    pagamento: Pagamento | None = None,
) -> None:
    extra = None
    if event_key == "refund_completed":
        refund_value = float((pagamento.valor if pagamento else None) or pedido.total)
        formatted = f"R$ {refund_value:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
        extra = {
            "refund_amount": formatted,
            "valor_reembolso": formatted,
        }
    if extra:
        trigger_order_email_event(db, event_key, pedido, extra=extra)
    else:
        trigger_order_email_event(db, event_key, pedido)
    if event_key == "payment_pending":
        schedule_abandoned_checkout_email_events(db, pedido)
    if event_key == "payment_approved":
        attribute_order_conversion(db, pedido)
        trigger_admin_order_paid_email(db, pedido, pagamento=pagamento)
        send_meta_purchase_for_paid_order(db, pedido, pagamento=pagamento)


def _atualizar_pagamento_local(
    db: Session,
    response: dict,
    payment_id: str = "",
    pagamento: Pagamento | None = None,
    pedido: Pedido | None = None,
) -> tuple[Pedido | None, Pagamento | None, str | None, bool]:
    payment_id = str(payment_id or response.get("payment_id") or response.get("id") or "")
    pagamento = pagamento or _buscar_pagamento_existente(db, response, payment_id)
    external_ref = _external_reference_pagamento(response, pagamento)
    if not external_ref:
        return None, pagamento, None, False

    mp_status = str(response.get("status") or response.get("mp_status") or "")
    novo_status_pedido = MP_TO_ORDER_STATUS.get(mp_status)
    novo_status_pagamento = MP_TO_PAYMENT_STATUS.get(mp_status, mp_status or "pendente")
    tipo = _tipo_pagamento_mp(response)
    order_id = str(response.get("order_id") or "")
    changed = False

    pedido = pedido or db.query(Pedido).filter(Pedido.numero == external_ref).first()
    if pedido and novo_status_pedido:
        status_anterior = pedido.status
        if not (pedido.status in ORDER_STATUSES_PAGOS and novo_status_pedido != ORDER_STATUS_PAGO):
            pedido.status = novo_status_pedido
        if pedido.status != status_anterior:
            changed = True
        if novo_status_pedido == ORDER_STATUS_PAGO:
            _registrar_cupom_pagamento_aprovado(db, pedido)
        if novo_status_pedido == ORDER_STATUS_REEMBOLSADO:
            reembolso = (
                db.query(ReembolsoPedido)
                .filter(ReembolsoPedido.pedido_id == pedido.id)
                .order_by(ReembolsoPedido.id.desc())
                .first()
            )
            valor_reembolso = float(response.get("transaction_amount") or pedido.total)
            if reembolso:
                reembolso.status = "processado"
                reembolso.valor = valor_reembolso
            else:
                db.add(
                    ReembolsoPedido(
                        pedido_id=pedido.id,
                        status="processado",
                        valor=valor_reembolso,
                    )
                )

    if not pagamento:
        pagamento = (
            db.query(Pagamento)
            .filter(Pagamento.pedido_numero == external_ref, Pagamento.tipo == tipo)
            .order_by(Pagamento.id.desc())
            .first()
        )
    if not pagamento:
        changed = True
        pagamento = Pagamento(
            pedido_numero=external_ref,
            tipo=tipo,
        )
        db.add(pagamento)

    if payment_id:
        changed = changed or pagamento.mp_payment_id != payment_id
        pagamento.mp_payment_id = payment_id
    if order_id:
        changed = changed or pagamento.mp_order_id != order_id
        pagamento.mp_order_id = order_id
    changed = changed or pagamento.status != novo_status_pagamento or pagamento.mp_status != mp_status
    pagamento.status = novo_status_pagamento
    pagamento.mp_status = mp_status
    pagamento.valor = float(response.get("transaction_amount") or pagamento.valor or 0.0)
    return pedido, pagamento, mp_status, changed


def _sincronizar_pix_pendente(db: Session, pedido: Pedido, pagamento: Pagamento | None) -> Pagamento | None:
    if not pagamento or pagamento.tipo != "pix" or pedido.status in ORDER_STATUSES_PAGOS:
        return pagamento
    if pagamento.status not in PAGAMENTOS_REABRIVEIS and pagamento.status != "expirado":
        return pagamento
    if not settings.MP_ACCESS_TOKEN:
        return pagamento

    order_response = None
    if pagamento.mp_order_id:
        result_status, order_response = _consultar_order_mp(pagamento.mp_order_id)
        if result_status not in (200, 201):
            logger.warning(
                "Mercado Pago recusou consulta de order PIX: status=%s order_id=%s",
                result_status,
                pagamento.mp_order_id,
            )
            return pagamento
    else:
        order_response = _buscar_order_mp_por_referencia(pedido.numero, pedido.criado_em)
        if not order_response:
            return pagamento

    response = _extrair_payment_from_order(order_response)
    response["external_reference"] = response.get("external_reference") or pedido.numero
    _, pagamento_atualizado, _, _ = _atualizar_pagamento_local(
        db,
        response,
        response.get("payment_id") or "",
        pagamento=pagamento,
        pedido=pedido,
    )
    db.commit()
    return pagamento_atualizado


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

    if not settings.MP_ACCESS_TOKEN:
        raise HTTPException(
            status_code=503,
            detail="Pagamentos ainda nao configurados. Contate o suporte.",
        )
    expiracao = _data_expiracao_pix()
    idempotency_key = _idempotency_key(numero_pedido, "pix")
    valor = _formatar_valor_mp(pedido.total)

    order_data = {
        "type": "online",
        "total_amount": valor,
        "external_reference": pedido.numero,
        "processing_mode": "automatic",
        "transactions": {
            "payments": [
                {
                    "amount": valor,
                    "payment_method": {
                        "id": "pix",
                        "type": "bank_transfer",
                    },
                }
            ]
        },
        "payer": {
            "email": current_user.email,
        },
    }
    result_status, response = _criar_order_pix_mp(order_data, idempotency_key)
    if result_status not in (200, 201):
        raise HTTPException(
            status_code=502,
            detail=f"Erro ao gerar PIX: {_mensagem_erro_mp(response, fluxo='pix')}",
        )

    pix_data = _extrair_pix_order(response)
    qr_code = pix_data["qr_code"]
    qr_code_base64 = pix_data["qr_code_base64"]
    payment_id = pix_data["payment_id"]
    if not qr_code:
        logger.warning(
            "Mercado Pago criou order PIX sem QR Code: order_id=%s payment_id=%s status=%s",
            pix_data["order_id"],
            payment_id,
            pix_data["status"],
        )
        raise HTTPException(
            status_code=502,
            detail="Mercado Pago criou o pagamento, mas nao retornou o QR Code PIX.",
        )

    pagamento = Pagamento(
        pedido_numero=numero_pedido,
        tipo="pix",
        valor=float(pedido.total),
        idempotency_key=idempotency_key,
        mp_payment_id=payment_id,
        mp_order_id=pix_data["order_id"],
        pix_qr_code=qr_code,
        pix_qr_code_base64=qr_code_base64,
        pix_expiracao=expiracao,
        status=_status_pix_local(pix_data["status"]),
        mp_status=pix_data["status"],
    )
    novo_status_pedido = MP_TO_ORDER_STATUS.get(pix_data["status"])
    if novo_status_pedido:
        pedido.status = novo_status_pedido
        if novo_status_pedido == ORDER_STATUS_PAGO:
            _registrar_cupom_pagamento_aprovado(db, pedido)
    db.add(pagamento)
    db.commit()
    event_key = PAYMENT_EMAIL_EVENTS.get(pix_data["status"])
    if event_key:
        db.refresh(pedido)
        _trigger_payment_email_event(db, event_key, pedido, pagamento=pagamento)

    return {
        "qr_code": qr_code,
        "qr_code_base64": qr_code_base64,
        "payment_id": payment_id,
        "expiracao": expiracao,
        "status": pagamento.status,
    }


@router.post("/cartao/{numero_pedido}", response_model=PagamentoCartaoResponse)
def criar_pagamento_cartao(
    numero_pedido: str,
    data: PagamentoCartaoRequest,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
):
    pedido = (
        db.query(Pedido)
        .filter(
            Pedido.numero == numero_pedido,
            Pedido.usuario_id == current_user.id,
        )
        .first()
    )

    if not pedido:
        raise HTTPException(
            status_code=404,
            detail="Pedido nao encontrado.",
        )

    _validar_pedido_para_novo_pagamento(pedido)
    _validar_valor_pagamento(
        data.transaction_amount,
        pedido.total,
    )

    _require_mp_access_token()
    idempotency_key = _idempotency_key(
        numero_pedido,
        "cartao",
    )
    valor = _formatar_valor_mp(pedido.total)

    order_data = {
        "type": "online",
        "processing_mode": "automatic",
        "capture_mode": "automatic",
        "total_amount": valor,
        "external_reference": pedido.numero,
        "description": f"Bia Collections - Pedido {pedido.numero}",
        "payer": {
            "email": data.payer.email,
            "identification": (
                data.payer.identification.model_dump()
            ),
        },
        "transactions": {
            "payments": [
                {
                    "amount": valor,
                    "payment_method": {
                        "id": data.payment_method_id,
                        "type": "credit_card",
                        "token": data.token,
                        "installments": data.installments,
                    },
                }
            ]
        },
    }
    mp_http_status, response = _criar_order_cartao_mp(order_data, idempotency_key)
    order_result = _extrair_order(response)
    transacao_criada = bool(order_result["order_id"] and order_result["payment_id"])

    if mp_http_status not in (200, 201) and not (
        mp_http_status == 402 and transacao_criada
    ):
        mensagem = _mensagem_erro_mp(response, fluxo="cartao")

        logger.error(
            "Mercado Pago recusou order de cartao: "
            "pedido=%s status_http=%s message=%s error=%s cause=%s",
            numero_pedido,
            mp_http_status,
            mensagem,
            response.get("error"),
            response.get("cause") or response.get("errors"),
        )

        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Mercado Pago recusou o pagamento: {mensagem}",
        )

    payment_id = order_result["payment_id"]
    order_id = order_result["order_id"]
    mp_status = str(order_result["status"] or "pending")

    status_pagamento = MP_TO_PAYMENT_STATUS.get(
        mp_status,
        mp_status or "pendente",
    )

    novo_status_pedido = MP_TO_ORDER_STATUS.get(mp_status)

    if novo_status_pedido:
        pedido.status = novo_status_pedido

        if novo_status_pedido == ORDER_STATUS_PAGO:
            _registrar_cupom_pagamento_aprovado(
                db,
                pedido,
            )

    pagamento = Pagamento(
        pedido_numero=numero_pedido,
        tipo="cartao",
        valor=float(pedido.total),
        idempotency_key=idempotency_key,
        mp_payment_id=payment_id,
        mp_order_id=order_id,
        status=status_pagamento,
        mp_status=mp_status,
    )

    db.add(pagamento)
    db.commit()
    db.refresh(pagamento)
    db.refresh(pedido)

    event_key = PAYMENT_EMAIL_EVENTS.get(mp_status)

    if event_key:
        _trigger_payment_email_event(
            db,
            event_key,
            pedido,
            pagamento=pagamento,
        )

    return PagamentoCartaoResponse(
        payment_id=payment_id,
        status=status_pagamento,
        mp_status=mp_status,
        status_detail=order_result["status_detail"],
        status_pedido=pedido.status,
        payment_method_id=str(
            order_result["payment_method_id"]
            or data.payment_method_id
        ),
    )


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
    sdk = _get_sdk()
    if pag_existente and _preferencia_mp_reutilizavel(sdk, pag_existente):
        return {
            "checkout_url": pag_existente.checkout_url,
            "checkout_url_prod": pag_existente.checkout_url_prod,
            "preference_id": pag_existente.mp_preference_id,
            "status": pag_existente.status,
        }

    idempotency_key = _idempotency_key(numero_pedido, "checkout")
    preference_data = {
        "items": [
            {
                "id": pedido.numero,
                "title": f"Bia Collections - Pedido {pedido.numero}",
                "description": f"Compra na Bia Collections - Pedido {pedido.numero}",
                "quantity": 1,
                "unit_price": float(pedido.total),
                "currency_id": "BRL",
            }
        ],
        "payer": _payer_preferencia(current_user, pedido),
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
    _adicionar_notification_url(preference_data)

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

    notification_type = _extrair_notification_type(request, data)
    payment_id = _extrair_payment_id(request, data)
    if notification_type not in (None, "payment", "order", "orders", "merchant_order"):
        return {"status": "ignored"}
    if not payment_id:
        return {"status": "ignored"}

    _validar_assinatura_webhook(request, data, payment_id)
    if not settings.MP_ACCESS_TOKEN:
        return {"status": "ignored"}

    if notification_type in {"order", "orders"}:
        result_status, order_response = _consultar_order_mp(payment_id)
        if result_status not in (200, 201):
            raise HTTPException(status_code=502, detail="Erro ao consultar pagamento.")
        response = _extrair_payment_from_order(order_response)
        payment_id = response["payment_id"]
    elif notification_type == "merchant_order":
        sdk = mercadopago.SDK(settings.MP_ACCESS_TOKEN)
        merchant_result = sdk.merchant_order().get(payment_id)
        merchant_order = merchant_result.get("response", {})
        if merchant_result.get("status") not in (200, 201):
            raise HTTPException(status_code=502, detail="Erro ao consultar pagamento.")
        payments = merchant_order.get("payments") or []
        if not payments:
            return {"status": "ignored"}
        payment_id = str(payments[-1].get("id") or "")
        if not payment_id:
            return {"status": "ignored"}
        payment_result = sdk.payment().get(payment_id)
        response = payment_result.get("response", {})
        if payment_result.get("status") not in (200, 201):
            raise HTTPException(status_code=502, detail="Erro ao consultar pagamento.")
    else:
        sdk = mercadopago.SDK(settings.MP_ACCESS_TOKEN)
        result = sdk.payment().get(payment_id)
        response = result.get("response", {})
        if result.get("status") not in (200, 201):
            raise HTTPException(status_code=502, detail="Erro ao consultar pagamento.")

    pedido, pagamento, mp_status, changed = _atualizar_pagamento_local(db, response, payment_id)
    if not mp_status:
        return {"status": "ignored"}

    db.commit()
    event_key = PAYMENT_EMAIL_EVENTS.get(mp_status)
    if changed and pedido and event_key:
        db.refresh(pedido)
        _trigger_payment_email_event(db, event_key, pedido, pagamento=pagamento)
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
    old_status = pedido.status

    pagamento = (
        db.query(Pagamento)
        .filter(Pagamento.pedido_numero == numero_pedido)
        .order_by(Pagamento.id.desc())
        .first()
    )
    try:
        pagamento = _sincronizar_pix_pendente(db, pedido, pagamento)
    except HTTPException:
        logger.exception("Erro ao sincronizar PIX pendente do pedido %s", numero_pedido)
    db.refresh(pedido)
    if old_status not in ORDER_STATUSES_PAGOS and pedido.status in ORDER_STATUSES_PAGOS:
        _trigger_payment_email_event(db, "payment_approved", pedido, pagamento=pagamento)
    return {
        "numero_pedido": numero_pedido,
        "status_pedido": pedido.status,
        "pago": pedido.status in ORDER_STATUSES_PAGOS,
        "pagamento": _pagamento_payload(pagamento),
    }

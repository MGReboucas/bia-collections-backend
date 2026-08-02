from __future__ import annotations

from datetime import datetime, timezone
import logging
from typing import Any

import httpx
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.pagamento import Pagamento
from app.models.pedido import Pedido
from app.services.payment_status import ORDER_STATUSES_PAGOS

logger = logging.getLogger(__name__)

META_EVENTS_TIMEOUT_SECONDS = 15.0


def _texto_opcional(value: Any) -> str | None:
    value = str(value or "").strip()
    return value or None


def _meta_graph_version() -> str:
    version = _texto_opcional(settings.META_GRAPH_API_VERSION) or "v20.0"
    return version if version.startswith("v") else f"v{version}"


def _meta_events_url(pixel_id: str) -> str:
    return f"https://graph.facebook.com/{_meta_graph_version()}/{pixel_id}/events"


def _valor_confirmado(pedido: Pedido, pagamento: Pagamento | None) -> float:
    raw_value = pagamento.valor if pagamento and pagamento.valor is not None else pedido.total
    return round(float(raw_value or 0.0), 2)


def _payment_id(pagamento: Pagamento | None) -> str | None:
    if not pagamento:
        return None
    return _texto_opcional(pagamento.mp_payment_id) or _texto_opcional(pagamento.mp_order_id)


def _user_data(pedido: Pedido) -> dict[str, str]:
    user_data: dict[str, str] = {}
    if pedido.meta_fbp:
        user_data["fbp"] = pedido.meta_fbp
    if pedido.meta_fbc:
        user_data["fbc"] = pedido.meta_fbc
    if pedido.client_user_agent:
        user_data["client_user_agent"] = pedido.client_user_agent
    return user_data


def _custom_data(pedido: Pedido, pagamento: Pagamento | None) -> dict[str, Any]:
    contents = [
        {
            "id": str(item.produto_id),
            "quantity": int(item.quantidade or 0),
            "item_price": round(float(item.preco_unitario or 0.0), 2),
        }
        for item in pedido.itens
    ]
    return {
        "currency": "BRL",
        "value": _valor_confirmado(pedido, pagamento),
        "content_type": "product",
        "content_ids": [content["id"] for content in contents],
        "contents": contents,
    }


def build_purchase_payload(pedido: Pedido, pagamento: Pagamento | None) -> dict[str, Any]:
    event: dict[str, Any] = {
        "event_name": "Purchase",
        "event_time": int(datetime.now(timezone.utc).timestamp()),
        "action_source": "website",
        "user_data": _user_data(pedido),
        "custom_data": _custom_data(pedido, pagamento),
    }
    if pedido.meta_event_id:
        event["event_id"] = pedido.meta_event_id
    if pedido.meta_source_url:
        event["event_source_url"] = pedido.meta_source_url
    return {"data": [event]}


def _meta_error_summary(body: dict[str, Any]) -> str:
    error = body.get("error") if isinstance(body, dict) else None
    if not isinstance(error, dict):
        return "erro desconhecido"
    message = error.get("message") or error.get("error_user_msg") or "erro desconhecido"
    code = error.get("code")
    subcode = error.get("error_subcode")
    return f"{message} code={code or ''} subcode={subcode or ''}".strip()


def _post_meta_events(pixel_id: str, access_token: str, payload: dict[str, Any]) -> bool:
    try:
        with httpx.Client(timeout=META_EVENTS_TIMEOUT_SECONDS) as client:
            response = client.post(
                _meta_events_url(pixel_id),
                params={"access_token": access_token},
                json=payload,
            )
    except httpx.HTTPError:
        logger.exception("Falha de comunicacao com Meta CAPI pixel_id=%s", pixel_id)
        return False

    try:
        body = response.json()
    except ValueError:
        body = {}

    if response.status_code >= 400:
        logger.warning(
            "Meta CAPI recusou Purchase: status=%s pixel_id=%s erro=%s fbtrace_id=%s",
            response.status_code,
            pixel_id,
            _meta_error_summary(body),
            body.get("fbtrace_id") if isinstance(body, dict) else "",
        )
        return False
    return True


def send_meta_purchase_for_paid_order(
    db: Session,
    pedido: Pedido,
    pagamento: Pagamento | None = None,
) -> bool:
    if pedido.status not in ORDER_STATUSES_PAGOS:
        return False

    pixel_id = _texto_opcional(settings.META_PIXEL_ID)
    access_token = _texto_opcional(settings.META_ACCESS_TOKEN)
    if not pixel_id or not access_token:
        logger.info(
            "Meta CAPI Purchase ignorado: credenciais ausentes pedido=%s",
            pedido.numero,
        )
        return False

    try:
        pedido_atual = (
            db.query(Pedido)
            .filter(Pedido.id == pedido.id)
            .with_for_update()
            .one()
        )
    except Exception:
        logger.exception("Falha ao bloquear pedido para Meta CAPI pedido=%s", pedido.numero)
        return False

    if pedido_atual.meta_purchase_enviado_em:
        logger.info(
            "Meta CAPI Purchase ja enviado pedido=%s payment_id=%s",
            pedido_atual.numero,
            pedido_atual.meta_purchase_payment_id,
        )
        return False

    payload = build_purchase_payload(pedido_atual, pagamento)
    try:
        enviado = _post_meta_events(pixel_id, access_token, payload)
    except Exception:
        logger.exception("Falha inesperada ao enviar Meta CAPI Purchase pedido=%s", pedido.numero)
        return False
    if not enviado:
        logger.warning("Meta CAPI Purchase nao enviado pedido=%s", pedido_atual.numero)
        return False

    pedido_atual.meta_purchase_enviado_em = datetime.now(timezone.utc)
    pedido_atual.meta_purchase_payment_id = _payment_id(pagamento)
    try:
        db.commit()
        db.refresh(pedido_atual)
        if pedido is not pedido_atual:
            db.refresh(pedido)
    except Exception:
        db.rollback()
        logger.exception(
            "Meta CAPI Purchase enviado, mas nao foi possivel persistir idempotencia pedido=%s",
            pedido_atual.numero,
        )
        return True

    logger.info(
        "Meta CAPI Purchase enviado pedido=%s event_id=%s payment_id=%s",
        pedido_atual.numero,
        pedido_atual.meta_event_id,
        pedido_atual.meta_purchase_payment_id,
    )
    return True

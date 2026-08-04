from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import logging
import re
import unicodedata
from typing import Any, Mapping

import httpx
from fastapi import Request
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.pagamento import Pagamento
from app.models.pedido import Pedido
from app.services.payment_status import ORDER_STATUSES_PAGOS

logger = logging.getLogger(__name__)

META_EVENTS_TIMEOUT_SECONDS = 15.0
META_WEB_EVENT_NAMES = {"PageView", "ViewContent", "AddToCart", "InitiateCheckout"}
META_ECOMMERCE_EVENT_NAMES = META_WEB_EVENT_NAMES | {"Purchase"}


def _texto_opcional(value: Any) -> str | None:
    value = str(value or "").strip()
    return value or None


def _meta_graph_version() -> str:
    version = _texto_opcional(settings.META_GRAPH_API_VERSION) or "v20.0"
    return version if version.startswith("v") else f"v{version}"


def _meta_events_url(pixel_id: str) -> str:
    return f"https://graph.facebook.com/{_meta_graph_version()}/{pixel_id}/events"


def meta_credentials_configured() -> bool:
    return bool(_texto_opcional(settings.META_PIXEL_ID) and _texto_opcional(settings.META_ACCESS_TOKEN))


def client_ip_from_request(request: Request) -> str | None:
    forwarded_for = _texto_opcional(request.headers.get("x-forwarded-for"))
    if forwarded_for:
        return _texto_opcional(forwarded_for.split(",", 1)[0])
    real_ip = _texto_opcional(request.headers.get("x-real-ip"))
    if real_ip:
        return real_ip
    return _texto_opcional(request.client.host if request.client else None)


def _normalizar_texto_hash(value: Any) -> str | None:
    value = _texto_opcional(value)
    if not value:
        return None
    value = "".join(
        char
        for char in unicodedata.normalize("NFD", value)
        if unicodedata.category(char) != "Mn"
    )
    return re.sub(r"\s+", " ", value.lower()).strip()


def _normalizar_email(value: Any) -> str | None:
    return _normalizar_texto_hash(value)


def _normalizar_telefone(value: Any) -> str | None:
    value = _texto_opcional(value)
    if not value:
        return None
    digits = re.sub(r"\D+", "", value)
    return digits or None


def _normalizar_cep(value: Any) -> str | None:
    value = _texto_opcional(value)
    if not value:
        return None
    return re.sub(r"\s+", "", value.lower())


def _sha256(value: str | None) -> str | None:
    if not value:
        return None
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _add_hashed(
    user_data: dict[str, str],
    key: str,
    value: Any,
    normalizer=_normalizar_texto_hash,
) -> None:
    hashed = _sha256(normalizer(value))
    if hashed:
        user_data[key] = hashed


def _separar_nome_completo(nome_completo: str | None) -> tuple[str | None, str | None]:
    partes = str(nome_completo or "").strip().split()
    if not partes:
        return None, None
    return partes[0], " ".join(partes[1:]) or None


def _user_data_from_usuario(usuario: Any | None) -> dict[str, str]:
    user_data: dict[str, str] = {}
    if not usuario:
        return user_data

    _add_hashed(user_data, "em", getattr(usuario, "email", None), _normalizar_email)
    _add_hashed(user_data, "ph", getattr(usuario, "telefone", None), _normalizar_telefone)
    primeiro_nome, sobrenome = _separar_nome_completo(getattr(usuario, "nome_completo", None))
    _add_hashed(user_data, "fn", primeiro_nome)
    _add_hashed(user_data, "ln", sobrenome)
    _add_hashed(user_data, "external_id", getattr(usuario, "id", None), _normalizar_texto_hash)
    return user_data


def _user_data_from_mapping(raw: Mapping[str, Any] | None) -> dict[str, str]:
    user_data: dict[str, str] = {}
    if not raw:
        return user_data

    _add_hashed(user_data, "em", raw.get("email"), _normalizar_email)
    _add_hashed(user_data, "ph", raw.get("phone"), _normalizar_telefone)
    _add_hashed(user_data, "fn", raw.get("first_name"))
    _add_hashed(user_data, "ln", raw.get("last_name"))
    _add_hashed(user_data, "ct", raw.get("city"))
    _add_hashed(user_data, "st", raw.get("state"))
    _add_hashed(user_data, "zp", raw.get("zip_code"), _normalizar_cep)
    _add_hashed(user_data, "country", raw.get("country"))
    _add_hashed(user_data, "external_id", raw.get("external_id"), _normalizar_texto_hash)

    for key in ("fbp", "fbc", "client_user_agent", "client_ip_address"):
        value = _texto_opcional(raw.get(key))
        if value:
            user_data[key] = value
    return user_data


def _user_data(pedido: Pedido) -> dict[str, str]:
    user_data = _user_data_from_usuario(getattr(pedido, "usuario", None))
    _add_hashed(user_data, "ct", pedido.endereco_cidade)
    _add_hashed(user_data, "st", pedido.endereco_estado)
    _add_hashed(user_data, "zp", pedido.endereco_cep, _normalizar_cep)
    _add_hashed(user_data, "country", "br")

    for source, key in (
        (pedido.meta_fbp, "fbp"),
        (pedido.meta_fbc, "fbc"),
        (pedido.client_user_agent, "client_user_agent"),
        (getattr(pedido, "client_ip_address", None), "client_ip_address"),
    ):
        value = _texto_opcional(source)
        if value:
            user_data[key] = value
    return user_data


def _valor_confirmado(pedido: Pedido, pagamento: Pagamento | None) -> float:
    raw_value = pagamento.valor if pagamento and pagamento.valor is not None else pedido.total
    return round(float(raw_value or 0.0), 2)


def _payment_id(pagamento: Pagamento | None) -> str | None:
    if not pagamento:
        return None
    return _texto_opcional(pagamento.mp_payment_id) or _texto_opcional(pagamento.mp_order_id)


def _clean_content(content: Mapping[str, Any]) -> dict[str, Any]:
    cleaned: dict[str, Any] = {}
    content_id = _texto_opcional(content.get("id") or content.get("produto_id") or content.get("product_id"))
    if content_id:
        cleaned["id"] = content_id

    quantity = content.get("quantity") if "quantity" in content else content.get("quantidade")
    if quantity is not None:
        try:
            cleaned["quantity"] = max(int(quantity), 1)
        except (TypeError, ValueError):
            pass

    item_price = content.get("item_price") if "item_price" in content else content.get("preco_unitario")
    if item_price is not None:
        try:
            cleaned["item_price"] = round(float(item_price), 2)
        except (TypeError, ValueError):
            pass

    title = _texto_opcional(content.get("title") or content.get("name") or content.get("nome_produto"))
    if title:
        cleaned["title"] = title
    return cleaned


def _clean_contents(contents: Any) -> list[dict[str, Any]]:
    if not isinstance(contents, list):
        return []
    return [
        cleaned
        for content in contents
        if isinstance(content, Mapping)
        for cleaned in [_clean_content(content)]
        if cleaned.get("id")
    ]


def _limpar_custom_data(event_name: str, raw: Mapping[str, Any] | None) -> dict[str, Any]:
    custom_data: dict[str, Any] = {}
    if raw:
        for key, value in raw.items():
            if value is None or value == "" or value == []:
                continue
            if key == "contents":
                contents = _clean_contents(value)
                if contents:
                    custom_data["contents"] = contents
                continue
            if key == "content_ids" and isinstance(value, list):
                ids = [_texto_opcional(item) for item in value]
                custom_data[key] = [item for item in ids if item]
                continue
            if key in {"value", "num_items"}:
                try:
                    custom_data[key] = round(float(value), 2)
                except (TypeError, ValueError):
                    continue
                continue
            if key == "currency":
                custom_data[key] = str(value).strip().upper()
                continue
            custom_data[key] = value

    contents = custom_data.get("contents") or []
    if contents and not custom_data.get("content_ids"):
        custom_data["content_ids"] = [content["id"] for content in contents if content.get("id")]
    if contents and "num_items" not in custom_data:
        custom_data["num_items"] = sum(int(content.get("quantity") or 1) for content in contents)
    if event_name in META_ECOMMERCE_EVENT_NAMES and (
        contents or custom_data.get("content_ids") or custom_data.get("content_name")
    ):
        custom_data.setdefault("content_type", "product")
    if event_name in META_ECOMMERCE_EVENT_NAMES and (
        "value" in custom_data or contents or custom_data.get("content_ids")
    ):
        custom_data.setdefault("currency", "BRL")
    return custom_data


def _custom_data(pedido: Pedido, pagamento: Pagamento | None) -> dict[str, Any]:
    contents = [
        {
            "id": str(item.produto_id),
            "quantity": int(item.quantidade or 0),
            "item_price": round(float(item.preco_unitario or 0.0), 2),
            "title": item.nome_produto,
        }
        for item in pedido.itens
    ]
    return _limpar_custom_data(
        "Purchase",
        {
            "currency": "BRL",
            "value": _valor_confirmado(pedido, pagamento),
            "content_type": "product",
            "content_ids": [content["id"] for content in contents],
            "contents": contents,
            "order_id": pedido.numero,
        },
    )


def _default_event_source_url(path: str = "/") -> str:
    base_url = _texto_opcional(settings.FRONTEND_URL) or "https://www.biacollections.com"
    return f"{base_url.rstrip('/')}/{path.lstrip('/')}"


def _with_test_event_code(payload: dict[str, Any]) -> dict[str, Any]:
    test_event_code = _texto_opcional(getattr(settings, "META_TEST_EVENT_CODE", ""))
    if test_event_code:
        payload["test_event_code"] = test_event_code
    return payload


def build_purchase_payload(pedido: Pedido, pagamento: Pagamento | None) -> dict[str, Any]:
    event: dict[str, Any] = {
        "event_name": "Purchase",
        "event_time": int(datetime.now(timezone.utc).timestamp()),
        "event_id": _texto_opcional(pedido.meta_event_id) or f"purchase-{pedido.numero}",
        "action_source": "website",
        "event_source_url": _texto_opcional(pedido.meta_source_url) or _default_event_source_url("/checkout"),
        "user_data": _user_data(pedido),
        "custom_data": _custom_data(pedido, pagamento),
    }
    return _with_test_event_code({"data": [event]})


def build_web_event_payload(
    *,
    event_name: str,
    event_id: str,
    event_source_url: str,
    client_user_agent: str | None = None,
    client_ip_address: str | None = None,
    fbp: str | None = None,
    fbc: str | None = None,
    user_data: Mapping[str, Any] | None = None,
    custom_data: Mapping[str, Any] | None = None,
    current_user: Any | None = None,
    event_time: int | None = None,
) -> dict[str, Any]:
    event_user_data = _user_data_from_usuario(current_user)
    event_user_data.update(_user_data_from_mapping(user_data))

    for source, key in (
        (fbp, "fbp"),
        (fbc, "fbc"),
        (client_user_agent, "client_user_agent"),
        (client_ip_address, "client_ip_address"),
    ):
        value = _texto_opcional(source)
        if value:
            event_user_data[key] = value

    event: dict[str, Any] = {
        "event_name": event_name,
        "event_time": int(event_time or datetime.now(timezone.utc).timestamp()),
        "event_id": event_id,
        "action_source": "website",
        "event_source_url": event_source_url,
        "user_data": event_user_data,
    }

    event_custom_data = _limpar_custom_data(event_name, custom_data)
    if event_custom_data:
        event["custom_data"] = event_custom_data
    return _with_test_event_code({"data": [event]})


def _meta_error_summary(body: dict[str, Any]) -> str:
    error = body.get("error") if isinstance(body, dict) else None
    if not isinstance(error, dict):
        return "erro desconhecido"
    message = error.get("message") or error.get("error_user_msg") or "erro desconhecido"
    code = error.get("code")
    subcode = error.get("error_subcode")
    return f"{message} code={code or ''} subcode={subcode or ''}".strip()


def _post_meta_events(pixel_id: str, access_token: str, payload: dict[str, Any]) -> bool:
    event_name = ""
    try:
        event_name = str((payload.get("data") or [{}])[0].get("event_name") or "")
    except (AttributeError, IndexError, TypeError):
        event_name = ""

    try:
        with httpx.Client(timeout=META_EVENTS_TIMEOUT_SECONDS) as client:
            response = client.post(
                _meta_events_url(pixel_id),
                params={"access_token": access_token},
                json=payload,
            )
    except httpx.HTTPError:
        logger.exception("Falha de comunicacao com Meta CAPI pixel_id=%s event_name=%s", pixel_id, event_name)
        return False

    try:
        body = response.json()
    except ValueError:
        body = {}

    if response.status_code >= 400:
        logger.warning(
            "Meta CAPI recusou evento: status=%s pixel_id=%s event_name=%s erro=%s fbtrace_id=%s",
            response.status_code,
            pixel_id,
            event_name,
            _meta_error_summary(body),
            body.get("fbtrace_id") if isinstance(body, dict) else "",
        )
        return False

    logger.info(
        "Meta CAPI aceitou evento pixel_id=%s event_name=%s events_received=%s fbtrace_id=%s",
        pixel_id,
        event_name,
        body.get("events_received") if isinstance(body, dict) else "",
        body.get("fbtrace_id") if isinstance(body, dict) else "",
    )
    return True


def send_meta_web_event(
    *,
    event_name: str,
    event_id: str,
    event_source_url: str,
    client_user_agent: str | None = None,
    client_ip_address: str | None = None,
    fbp: str | None = None,
    fbc: str | None = None,
    user_data: Mapping[str, Any] | None = None,
    custom_data: Mapping[str, Any] | None = None,
    current_user: Any | None = None,
    event_time: int | None = None,
) -> bool:
    if event_name not in META_WEB_EVENT_NAMES:
        logger.warning("Meta CAPI evento web ignorado: event_name invalido=%s", event_name)
        return False

    pixel_id = _texto_opcional(settings.META_PIXEL_ID)
    access_token = _texto_opcional(settings.META_ACCESS_TOKEN)
    if not pixel_id or not access_token:
        logger.info("Meta CAPI %s ignorado: credenciais ausentes", event_name)
        return False

    payload = build_web_event_payload(
        event_name=event_name,
        event_id=event_id,
        event_source_url=event_source_url,
        client_user_agent=client_user_agent,
        client_ip_address=client_ip_address,
        fbp=fbp,
        fbc=fbc,
        user_data=user_data,
        custom_data=custom_data,
        current_user=current_user,
        event_time=event_time,
    )
    return _post_meta_events(pixel_id, access_token, payload)


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

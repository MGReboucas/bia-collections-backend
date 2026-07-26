from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import re
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import quote

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.pedido import Pedido
from app.models.produto import Produto
from app.models.usuario import Usuario
from app.modules.email.models import (
    EmailCampaign,
    EmailCampaignRecipient,
    EmailLog,
    EmailTemplate,
    EmailTrackingEvent,
    MarketingPreference,
    ProductStockInterest,
)
from app.modules.email.service import EMAIL_STATUS_PENDING, EmailAutomationService, _email_public_url, _store_url

logger = logging.getLogger(__name__)
MARKETING_EVENT_KEY = "marketing_campaign"
TRACKING_TOKEN_TTL_DAYS = 90
ATTRIBUTION_DAYS = 7
_LINK_RE = re.compile(r'href="(https?://[^"]+)"', re.IGNORECASE)
_PIXEL = base64.b64decode("R0lGODlhAQABAIAAAAAAAP///ywAAAAAAQABAAACAUwAOw==")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _backend_url(path: str) -> str:
    base = (settings.MP_NOTIFICATION_URL or "").strip().rstrip("/")
    return f"{base}{path}" if base else path


def sign_tracking_token(payload: dict[str, Any]) -> str:
    body = base64.urlsafe_b64encode(
        json.dumps(payload, separators=(",", ":"), default=str).encode()
    ).decode().rstrip("=")
    signature = hmac.new(settings.SECRET_KEY.encode(), body.encode(), hashlib.sha256).hexdigest()
    return f"{body}.{signature}"


def verify_tracking_token(token: str) -> dict[str, Any] | None:
    try:
        body, signature = token.split(".", 1)
        expected = hmac.new(settings.SECRET_KEY.encode(), body.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(signature, expected):
            return None
        padded = body + "=" * (-len(body) % 4)
        payload = json.loads(base64.urlsafe_b64decode(padded).decode())
        issued = datetime.fromtimestamp(int(payload["iat"]), tz=timezone.utc)
        if payload.get("kind") != "unsubscribe" and issued < _now() - timedelta(days=TRACKING_TOKEN_TTL_DAYS):
            return None
        return payload
    except Exception:
        return None


def preference_for(db: Session, user_id: int) -> MarketingPreference | None:
    return db.query(MarketingPreference).filter(MarketingPreference.user_id == user_id).first()


def set_marketing_consent(
    db: Session,
    user: Usuario,
    consent: bool,
    *,
    source: str,
) -> MarketingPreference:
    preference = preference_for(db, user.id)
    now = _now()
    if not preference:
        preference = MarketingPreference(user_id=user.id, consent_source=source)
        db.add(preference)
    preference.email_consent = consent
    preference.consent_source = source[:60]
    preference.consented_at = now if consent else preference.consented_at
    preference.unsubscribed_at = None if consent else now
    db.commit()
    db.refresh(preference)
    return preference


def has_marketing_consent(db: Session, user_id: int) -> bool:
    preference = preference_for(db, user_id)
    return bool(preference and preference.email_consent)


def unsubscribe_token(user: Usuario) -> str:
    return sign_tracking_token({"kind": "unsubscribe", "uid": user.id, "email": user.email, "iat": int(_now().timestamp())})


def _segment_users(db: Session, segment: str) -> list[Usuario]:
    query = db.query(Usuario).filter(Usuario.is_admin.isnot(True))
    if segment == "com_pedidos":
        query = query.filter(db.query(Pedido.id).filter(Pedido.usuario_id == Usuario.id).exists())
    elif segment == "sem_pedidos":
        query = query.filter(~db.query(Pedido.id).filter(Pedido.usuario_id == Usuario.id).exists())
    elif segment == "clientes_vip":
        query = (
            query.join(Pedido, Pedido.usuario_id == Usuario.id)
            .group_by(Usuario.id)
            .having(func.coalesce(func.sum(Pedido.total), 0) >= 500)
        )
    elif segment == "inativos_90d":
        cutoff = _now() - timedelta(days=90)
        query = query.filter(
            ~db.query(Pedido.id)
            .filter(Pedido.usuario_id == Usuario.id, Pedido.criado_em >= cutoff)
            .exists()
        )
    return query.order_by(Usuario.id.asc()).all()


def _under_frequency_cap(db: Session, user_id: int, days: int) -> bool:
    cutoff = _now() - timedelta(days=max(1, days))
    recent = (
        db.query(EmailCampaignRecipient.id)
        .filter(
            EmailCampaignRecipient.user_id == user_id,
            EmailCampaignRecipient.created_at >= cutoff,
            EmailCampaignRecipient.status.in_(["pendente", "enviado"]),
        )
        .first()
    )
    return recent is None


def _variant_for(campaign: EmailCampaign, user_id: int) -> str:
    if not campaign.template_b_id:
        return "A"
    bucket = int(hashlib.sha256(f"{campaign.id}:{user_id}".encode()).hexdigest()[:8], 16) % 100
    return "B" if bucket < max(0, min(100, campaign.ab_percentage)) else "A"


def _decorate_campaign_html(
    html_content: str,
    *,
    log_id: int,
    campaign_id: int,
    user: Usuario,
) -> str:
    base_payload = {"lid": log_id, "cid": campaign_id, "uid": user.id, "iat": int(_now().timestamp())}

    def replace_link(match: re.Match[str]) -> str:
        target = match.group(1)
        token = sign_tracking_token({**base_payload, "kind": "click", "url": target})
        return f'href="{_backend_url(f"/api/v1/marketing/click/{quote(token)}")}"'

    decorated = _LINK_RE.sub(replace_link, html_content)
    pixel_token = sign_tracking_token({**base_payload, "kind": "open"})
    pixel = (
        f'<img src="{_backend_url(f"/api/v1/marketing/open/{quote(pixel_token)}.gif")}" '
        'width="1" height="1" alt="" style="display:none!important;">'
    )
    unsubscribe = _backend_url(f"/api/v1/marketing/unsubscribe/{quote(unsubscribe_token(user))}")
    footer = (
        '<p style="margin:18px 0 0;text-align:center;font:11px Arial;color:#8a8178;">'
        f'Você recebeu este e-mail porque aceitou novidades. <a href="{unsubscribe}">Descadastrar</a>.</p>'
    )
    if "</body>" in decorated:
        return decorated.replace("</body>", f"{footer}{pixel}</body>", 1)
    return decorated + footer + pixel


def dispatch_campaign(db: Session, campaign: EmailCampaign) -> int:
    if campaign.status not in {"aprovada", "agendada"}:
        raise ValueError("Campanha precisa estar aprovada ou agendada.")
    now = _now()
    if campaign.scheduled_at:
        scheduled_at = campaign.scheduled_at
        if scheduled_at.tzinfo is None:
            scheduled_at = scheduled_at.replace(tzinfo=timezone.utc)
        if scheduled_at.astimezone(timezone.utc) > now:
            return 0

    campaign.status = "enviando"
    campaign.started_at = now
    db.commit()
    service = EmailAutomationService(db)
    campaign_payload = json.loads(campaign.payload_json or "{}")
    queued = 0
    for user in _segment_users(db, campaign.segment):
        if not has_marketing_consent(db, user.id):
            continue
        if not _under_frequency_cap(db, user.id, campaign.frequency_cap_days):
            continue
        if db.query(EmailCampaignRecipient.id).filter(
            EmailCampaignRecipient.campaign_id == campaign.id,
            EmailCampaignRecipient.user_id == user.id,
        ).first():
            continue
        variant = _variant_for(campaign, user.id)
        template = campaign.template_b if variant == "B" else campaign.template_a
        if not template or not template.is_active:
            continue
        payload = {
            "to": user.email,
            "email": user.email,
            "user_id": user.id,
            "customer_name": user.nome_completo or user.username,
            "cliente_nome": user.nome_completo or user.username,
            "store_url": settings.STORE_URL or settings.FRONTEND_URL,
            "loja_url": settings.STORE_URL or settings.FRONTEND_URL,
            "dedupe_key": f"campaign:{campaign.id}:{user.id}",
        }
        payload.update(campaign_payload)
        rendered = service.render_template(template.slug, payload, template=template)
        log = service.save_email_log(
            user_id=user.id,
            email=user.email.strip().lower(),
            template_slug=template.slug,
            event_key=MARKETING_EVENT_KEY,
            dedupe_key=payload["dedupe_key"],
            status=EMAIL_STATUS_PENDING,
            subject=rendered.subject,
            html_snapshot=rendered.html,
            text_snapshot=rendered.text,
            payload_json=json.dumps(payload, ensure_ascii=False),
            next_attempt_at=None,
        )
        log.html_snapshot = _decorate_campaign_html(
            rendered.html, log_id=log.id, campaign_id=campaign.id, user=user
        )
        recipient = EmailCampaignRecipient(
            campaign_id=campaign.id,
            user_id=user.id,
            email=user.email.strip().lower(),
            variant=variant,
            email_log_id=log.id,
            status="pendente",
        )
        db.add(recipient)
        db.commit()
        from app.modules.email.tasks import enqueue_email_log

        enqueue_email_log(log.id)
        queued += 1
    campaign.status = "concluida"
    campaign.completed_at = _now()
    db.commit()
    return queued


def process_due_campaigns(db: Session, limit: int = 20) -> int:
    campaigns = (
        db.query(EmailCampaign)
        .filter(
            EmailCampaign.status == "agendada",
            EmailCampaign.scheduled_at.isnot(None),
            EmailCampaign.scheduled_at <= _now(),
        )
        .order_by(EmailCampaign.scheduled_at.asc())
        .limit(limit)
        .all()
    )
    return sum(dispatch_campaign(db, campaign) for campaign in campaigns)


def record_tracking_event(
    db: Session,
    payload: dict[str, Any],
    event_type: str,
    *,
    target_url: str | None = None,
    ip: str = "",
    user_agent: str = "",
) -> bool:
    log = db.query(EmailLog).filter(EmailLog.id == int(payload.get("lid", 0))).first()
    if not log:
        return False
    duplicate = db.query(EmailTrackingEvent.id).filter(
        EmailTrackingEvent.email_log_id == log.id,
        EmailTrackingEvent.event_type == event_type,
    ).first()
    if event_type == "open" and duplicate:
        return True
    db.add(
        EmailTrackingEvent(
            email_log_id=log.id,
            campaign_id=int(payload.get("cid", 0)) or None,
            user_id=int(payload.get("uid", 0)) or None,
            event_type=event_type,
            target_url=target_url,
            ip_hash=hashlib.sha256(f"{settings.SECRET_KEY}:{ip}".encode()).hexdigest() if ip else None,
            user_agent=user_agent[:500] or None,
        )
    )
    recipient = db.query(EmailCampaignRecipient).filter(
        EmailCampaignRecipient.email_log_id == log.id
    ).first()
    if recipient and event_type in {"open", "click"}:
        recipient.status = event_type
    db.commit()
    return True


def attribute_order_conversion(db: Session, pedido: Pedido) -> bool:
    cutoff = _now() - timedelta(days=ATTRIBUTION_DAYS)
    recipient = (
        db.query(EmailCampaignRecipient)
        .join(EmailTrackingEvent, EmailTrackingEvent.email_log_id == EmailCampaignRecipient.email_log_id)
        .filter(
            EmailCampaignRecipient.user_id == pedido.usuario_id,
            EmailCampaignRecipient.converted_order_id.is_(None),
            EmailTrackingEvent.event_type == "click",
            EmailTrackingEvent.occurred_at >= cutoff,
        )
        .order_by(EmailTrackingEvent.occurred_at.desc())
        .first()
    )
    if not recipient:
        return False
    recipient.converted_order_id = pedido.id
    recipient.converted_at = _now()
    recipient.status = "convertido"
    db.add(
        EmailTrackingEvent(
            email_log_id=recipient.email_log_id,
            campaign_id=recipient.campaign_id,
            user_id=pedido.usuario_id,
            event_type="conversion",
            target_url=f"pedido:{pedido.numero}",
        )
    )
    db.commit()
    return True


def campaign_metrics(db: Session, campaign_id: int) -> dict[str, Any]:
    recipients = db.query(EmailCampaignRecipient).filter(
        EmailCampaignRecipient.campaign_id == campaign_id
    )
    total = recipients.count()
    event_counts = dict(
        db.query(EmailTrackingEvent.event_type, func.count(func.distinct(EmailTrackingEvent.email_log_id)))
        .filter(EmailTrackingEvent.campaign_id == campaign_id)
        .group_by(EmailTrackingEvent.event_type)
        .all()
    )
    variants: dict[str, Any] = {}
    for variant in ("A", "B"):
        variant_total = recipients.filter(EmailCampaignRecipient.variant == variant).count()
        variants[variant] = {
            "destinatarios": variant_total,
            "conversoes": recipients.filter(
                EmailCampaignRecipient.variant == variant,
                EmailCampaignRecipient.converted_order_id.isnot(None),
            ).count(),
        }
    opens = int(event_counts.get("open", 0))
    clicks = int(event_counts.get("click", 0))
    conversions = int(event_counts.get("conversion", 0))
    return {
        "campanha_id": campaign_id,
        "destinatarios": total,
        "aberturas": opens,
        "cliques": clicks,
        "conversoes": conversions,
        "taxa_abertura": round(opens / total * 100, 2) if total else 0,
        "taxa_clique": round(clicks / total * 100, 2) if total else 0,
        "taxa_conversao": round(conversions / total * 100, 2) if total else 0,
        "variantes": variants,
    }


def notify_product_back_in_stock(db: Session, produto: Produto) -> int:
    interests = db.query(ProductStockInterest).filter(
        ProductStockInterest.product_id == produto.id,
        ProductStockInterest.is_active.is_(True),
    ).all()
    service = EmailAutomationService(db)
    queued = 0
    for interest in interests:
        user = db.query(Usuario).filter(Usuario.id == interest.user_id).first()
        if not user or not has_marketing_consent(db, user.id):
            continue
        payload = {
            "to": user.email,
            "email": user.email,
            "user_id": user.id,
            "customer_name": user.nome_completo or user.username,
            "cliente_nome": user.nome_completo or user.username,
            "product_name": produto.nome,
            "produto_nome": produto.nome,
            "product_url": _store_url(f"produtos/{produto.id}"),
            "produto_url": _store_url(f"produtos/{produto.id}"),
            "store_url": settings.STORE_URL or settings.FRONTEND_URL,
            "loja_url": settings.STORE_URL or settings.FRONTEND_URL,
            "dedupe_key": f"back_in_stock:{produto.id}:{user.id}:{int(_now().timestamp())}",
        }
        queued += len(service.trigger_event("product_back_in_stock", payload))
        interest.is_active = False
        interest.notified_at = _now()
    db.commit()
    return queued


TRACKING_PIXEL = _PIXEL

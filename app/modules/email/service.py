from __future__ import annotations

import html
import json
import logging
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy.orm import Session, joinedload

from app.core.config import settings
from app.models.cupom import Cupom
from app.models.pagamento import Pagamento
from app.models.pedido import Pedido
from app.models.usuario import Usuario
from app.modules.email.models import EmailAutomation, EmailLog, EmailTemplate
from app.modules.email.provider import EmailProvider
from app.modules.email.templates import brand_email_html, ensure_brand_logo_html

try:
    from jinja2 import BaseLoader, Environment
except Exception:  # pragma: no cover - optional dependency fallback
    BaseLoader = None
    Environment = None


logger = logging.getLogger(__name__)

EMAIL_STATUS_PENDING = "pendente"
EMAIL_STATUS_SENT = "enviado"
EMAIL_STATUS_ERROR = "erro"
LEGACY_PENDING_STATUSES = {"queued", "scheduled"}
LEGACY_SENT_STATUSES = {"sent"}
LEGACY_ERROR_STATUSES = {"failed"}
PENDING_STATUSES = {EMAIL_STATUS_PENDING, *LEGACY_PENDING_STATUSES}
SENT_STATUSES = {EMAIL_STATUS_SENT, *LEGACY_SENT_STATUSES}
ERROR_STATUSES = {EMAIL_STATUS_ERROR, *LEGACY_ERROR_STATUSES}
RETRYABLE_STATUSES = PENDING_STATUSES | ERROR_STATUSES
DEDUPE_STATUSES = PENDING_STATUSES | SENT_STATUSES | ERROR_STATUSES
MAX_ATTEMPTS = 3
ADMIN_ORDER_PAID_EVENT_KEY = "admin_order_paid"
ADMIN_ORDER_PAID_TEMPLATE_SLUG = "admin-order-paid"
_VAR_PATTERN = re.compile(r"{{\s*([a-zA-Z0-9_.]+)\s*}}")
ADMIN_EVENT_TO_AUTOMATION_EVENT = {
    "pedido_criado": "order_created",
    "pagamento_aprovado": "payment_approved",
    "pedido_enviado": "order_shipped",
    "recuperacao_senha": "password_reset",
    "codigo_acesso": "two_factor_code",
    "cupom_disponivel": "coupon_available",
}
AUTOMATION_EVENT_TO_ADMIN_EVENT = {
    event_key: admin_event for admin_event, event_key in ADMIN_EVENT_TO_AUTOMATION_EVENT.items()
}
AUTOMATION_EVENT_TO_ADMIN_EVENT.update(
    {admin_event: admin_event for admin_event in ADMIN_EVENT_TO_AUTOMATION_EVENT}
)
AUTOMATION_EVENT_TO_ADMIN_EVENT["tracking_code_available"] = "pedido_enviado"
AUTOMATION_EVENT_TO_ADMIN_EVENT["manual"] = "manual"


@dataclass(frozen=True)
class RenderedEmail:
    subject: str
    preheader: str | None
    html: str
    text: str


class EmailAutomationService:
    def __init__(self, db: Session, provider: EmailProvider | None = None):
        self.db = db
        self.provider = provider or EmailProvider()

    def trigger_event(self, event_key: str, payload: dict[str, Any]) -> list[EmailLog]:
        admin_event = self._admin_event_for_key(event_key)
        admin_templates = self._active_admin_templates_for_event(event_key)
        if admin_templates:
            admin_event_key, admin_payload = self._admin_event_payload(event_key, payload)
            return self._enqueue_templates(
                admin_event_key,
                admin_payload,
                [(template, 0) for template in admin_templates],
            )
        if admin_event and admin_event != "manual":
            logger.warning("Email event %s ignored: no active admin template configured.", admin_event)
            return []

        automations = (
            self.db.query(EmailAutomation)
            .options(joinedload(EmailAutomation.template))
            .filter(
                EmailAutomation.event_key == event_key,
                EmailAutomation.channel == "email",
                EmailAutomation.is_active.is_(True),
            )
            .all()
        )

        if not automations:
            logger.warning("Email event %s ignored: no active template configured.", event_key)

        return self._enqueue_templates(
            event_key,
            payload,
            [(automation.template, automation.delay_minutes) for automation in automations],
        )

    def send_event_now(
        self,
        event_key: str,
        payload: dict[str, Any],
        *,
        raise_on_failure: bool = True,
    ) -> EmailLog | None:
        admin_event = self._admin_event_for_key(event_key)
        templates = self._active_admin_templates_for_event(event_key)
        send_event_key = event_key
        send_payload = payload
        if templates:
            send_event_key, send_payload = self._admin_event_payload(event_key, payload)
        elif admin_event and admin_event != "manual":
            logger.warning("Email event %s ignored: no active admin template configured.", admin_event)
            return None
        if not templates:
            automations = (
                self.db.query(EmailAutomation)
                .options(joinedload(EmailAutomation.template))
                .filter(
                    EmailAutomation.event_key == event_key,
                    EmailAutomation.channel == "email",
                    EmailAutomation.is_active.is_(True),
                )
                .order_by(EmailAutomation.id.asc())
                .all()
            )
            templates = [automation.template for automation in automations if automation.template]
        if not templates:
            logger.warning("Email event %s ignored: no active template configured.", event_key)
            return None

        for template in templates:
            if not template or not template.is_active:
                continue
            to = self._recipient_from_payload(send_payload)
            if not to:
                logger.warning("Email event %s ignored: missing recipient.", send_event_key)
                return None
            return self.send_template_now(
                template,
                send_payload,
                event_key=send_event_key,
                raise_on_failure=raise_on_failure,
            )
        return None

    def _admin_event_for_key(self, event_key: str) -> str | None:
        return AUTOMATION_EVENT_TO_ADMIN_EVENT.get(event_key)

    def send_template_now(
        self,
        template: EmailTemplate,
        payload: dict[str, Any],
        *,
        event_key: str | None = None,
        raise_on_failure: bool = True,
    ) -> EmailLog:
        to = self._recipient_from_payload(payload)
        if not to:
            raise ValueError("Destinatario de email ausente.")

        log_event_key = event_key or template.evento or "manual"
        rendered = self.render_template(template.slug, payload, template=template)
        log = self.save_email_log(
            user_id=self._safe_int(payload.get("user_id")),
            order_id=self._safe_int(payload.get("order_id")),
            email=to,
            template_slug=template.slug,
            event_key=log_event_key,
            dedupe_key=self._optional_text(payload.get("dedupe_key")),
            status=EMAIL_STATUS_PENDING,
            subject=rendered.subject,
            html_snapshot=rendered.html,
            text_snapshot=rendered.text,
            payload_json=json.dumps(payload, ensure_ascii=False, default=str),
            next_attempt_at=datetime.now(timezone.utc),
        )
        try:
            result = self.provider.send(
                to=to,
                subject=rendered.subject,
                html=rendered.html,
                text=rendered.text,
            )
            log.status = EMAIL_STATUS_SENT
            log.provider = getattr(result, "provider", None) or "mock"
            log.provider_message_id = getattr(result, "provider_message_id", None)
            log.sent_at = datetime.now(timezone.utc)
            log.attempts = 1
            log.next_attempt_at = None
            self.db.commit()
            self.db.refresh(log)
            return log
        except Exception as exc:
            log.status = EMAIL_STATUS_ERROR
            log.error_message = str(exc)[:2000]
            log.attempts = 1
            log.next_attempt_at = None
            self.db.commit()
            self.db.refresh(log)
            if raise_on_failure:
                raise
            return log

    def send_transactional_email_now(
        self,
        *,
        to: str,
        subject: str,
        html_content: str,
        text_content: str,
        template_slug: str,
        event_key: str,
        payload: dict[str, Any],
        raise_on_failure: bool = True,
    ) -> EmailLog:
        normalized_to = to.strip().lower()
        if not normalized_to:
            raise ValueError("Destinatario de email ausente.")

        duplicate = self._find_duplicate_log(normalized_to, event_key, template_slug, payload)
        if duplicate:
            return duplicate

        log = self.save_email_log(
            user_id=self._safe_int(payload.get("user_id")),
            order_id=self._safe_int(payload.get("order_id")),
            email=normalized_to,
            template_slug=template_slug,
            event_key=event_key,
            dedupe_key=self._optional_text(payload.get("dedupe_key")),
            status=EMAIL_STATUS_PENDING,
            subject=subject,
            html_snapshot=ensure_brand_logo_html(html_content) or "",
            text_snapshot=text_content,
            payload_json=json.dumps(payload, ensure_ascii=False, default=str),
            next_attempt_at=datetime.now(timezone.utc),
        )
        try:
            result = self.provider.send(
                to=normalized_to,
                subject=subject,
                html=log.html_snapshot,
                text=text_content,
            )
            log.status = EMAIL_STATUS_SENT
            log.provider = getattr(result, "provider", None) or "mock"
            log.provider_message_id = getattr(result, "provider_message_id", None)
            log.sent_at = datetime.now(timezone.utc)
            log.attempts = 1
            log.next_attempt_at = None
            self.db.commit()
            self.db.refresh(log)
            return log
        except Exception as exc:
            log.status = EMAIL_STATUS_ERROR
            log.error_message = str(exc)[:2000]
            log.attempts = 1
            log.next_attempt_at = None
            self.db.commit()
            self.db.refresh(log)
            if raise_on_failure:
                raise
            return log

    def _active_admin_templates_for_event(self, event_key: str) -> list[EmailTemplate]:
        admin_event = AUTOMATION_EVENT_TO_ADMIN_EVENT.get(event_key)
        if not admin_event or admin_event == "manual":
            return []
        templates = (
            self.db.query(EmailTemplate)
            .filter(
                EmailTemplate.evento == admin_event,
                EmailTemplate.status == "ativo",
                EmailTemplate.is_active.is_(True),
            )
            .order_by(EmailTemplate.updated_at.desc(), EmailTemplate.id.desc())
            .all()
        )
        if len(templates) > 1:
            logger.warning(
                "Email event %s has %s active admin templates; using the most recent one.",
                admin_event,
                len(templates),
            )
            return templates[:1]
        return templates

    def _admin_event_payload(self, event_key: str, payload: dict[str, Any]) -> tuple[str, dict[str, Any]]:
        admin_event = AUTOMATION_EVENT_TO_ADMIN_EVENT.get(event_key)
        if not admin_event:
            return event_key, payload

        admin_payload = dict(payload)
        order_number = self._optional_text(
            admin_payload.get("pedido_numero") or admin_payload.get("order_number")
        )
        if order_number:
            if admin_event == "pedido_enviado":
                tracking_code = self._optional_text(
                    admin_payload.get("codigo_rastreio") or admin_payload.get("tracking_code")
                )
                tracking_part = tracking_code or "sem-rastreio"
                admin_payload["dedupe_key"] = f"{admin_event}:{order_number}:{tracking_part}"
            else:
                admin_payload["dedupe_key"] = f"{admin_event}:{order_number}"
        return admin_event, admin_payload

    def _enqueue_templates(
        self,
        event_key: str,
        payload: dict[str, Any],
        templates_with_delay: list[tuple[EmailTemplate | None, int]],
    ) -> list[EmailLog]:
        logs: list[EmailLog] = []
        for template, delay_minutes in templates_with_delay:
            if not template or not template.is_active:
                continue

            to = self._recipient_from_payload(payload)
            if not to:
                logger.warning("Email event %s ignored: missing recipient.", event_key)
                continue

            rendered = self.render_template(template.slug, payload, template=template)
            log = self.enqueue_email(
                to=to,
                subject=rendered.subject,
                html_content=rendered.html,
                text_content=rendered.text,
                template_slug=template.slug,
                event_key=event_key,
                payload=payload,
                delay_minutes=delay_minutes,
            )
            logs.append(log)
        if not logs and templates_with_delay:
            logger.warning("Email event %s ignored: no sendable active template.", event_key)
        return logs

    def render_template(
        self,
        template_slug: str,
        payload: dict[str, Any],
        *,
        template: EmailTemplate | None = None,
    ) -> RenderedEmail:
        template = template or self.db.query(EmailTemplate).filter(EmailTemplate.slug == template_slug).first()
        if not template:
            raise ValueError(f"Template de email nao encontrado: {template_slug}")

        html_content = self._render_string(template.html_template, payload, html_escape=True)
        html_content = ensure_brand_logo_html(html_content) or ""

        return RenderedEmail(
            subject=self._render_string(template.subject, payload, html_escape=False),
            preheader=self._render_string(template.preheader or "", payload, html_escape=False) or None,
            html=html_content,
            text=self._render_string(template.text_template, payload, html_escape=False),
        )

    def enqueue_email(
        self,
        to: str,
        subject: str,
        html_content: str,
        text_content: str,
        *,
        template_slug: str = "custom",
        event_key: str = "custom",
        payload: dict[str, Any] | None = None,
        delay_minutes: int = 0,
    ) -> EmailLog:
        payload = payload or {}
        duplicate = self._find_duplicate_log(to, event_key, template_slug, payload)
        if duplicate:
            if duplicate.status in PENDING_STATUSES:
                duplicate.template_slug = template_slug
                duplicate.subject = subject
                duplicate.html_snapshot = html_content
                duplicate.text_snapshot = text_content
                duplicate.payload_json = json.dumps(payload, ensure_ascii=False, default=str)
                duplicate.dedupe_key = self._optional_text(payload.get("dedupe_key"))
                self.db.commit()
                self.db.refresh(duplicate)
            return duplicate

        now = datetime.now(timezone.utc)
        log = EmailLog(
            user_id=self._safe_int(payload.get("user_id")),
            order_id=self._safe_int(payload.get("order_id")),
            email=to,
            template_slug=template_slug,
            event_key=event_key,
            dedupe_key=self._optional_text(payload.get("dedupe_key")),
            status=EMAIL_STATUS_PENDING,
            subject=subject,
            html_snapshot=html_content,
            text_snapshot=text_content,
            payload_json=json.dumps(payload, ensure_ascii=False, default=str),
            next_attempt_at=now + timedelta(minutes=delay_minutes) if delay_minutes > 0 else None,
        )
        self.db.add(log)
        self.db.commit()
        self.db.refresh(log)

        from app.modules.email.tasks import enqueue_email_log

        enqueue_email_log(log.id, delay_minutes=delay_minutes)
        return log

    def send_email(self, to: str, subject: str, html_content: str, text_content: str) -> None:
        html_content = ensure_brand_logo_html(html_content) or ""
        self.provider.send(to=to, subject=subject, html=html_content, text=text_content)

    def save_email_log(self, **values: Any) -> EmailLog:
        log = EmailLog(**values)
        self.db.add(log)
        self.db.commit()
        self.db.refresh(log)
        return log

    def retry_failed_email(self, log_id: int) -> EmailLog:
        log = self.db.query(EmailLog).filter(EmailLog.id == log_id).first()
        if not log:
            raise ValueError("Log de email nao encontrado.")
        if log.status not in RETRYABLE_STATUSES:
            raise ValueError("Apenas emails pendentes ou com falha podem ser reenviados.")

        log.status = EMAIL_STATUS_PENDING
        log.error_message = None
        log.next_attempt_at = None
        self.db.commit()
        self.db.refresh(log)

        from app.modules.email.tasks import enqueue_email_log

        enqueue_email_log(log.id)
        return log

    def process_queued_email(self, log_id: int) -> EmailLog | None:
        log = self.db.query(EmailLog).filter(EmailLog.id == log_id).first()
        if not log or log.status not in RETRYABLE_STATUSES:
            return log

        now = datetime.now(timezone.utc)
        if log.next_attempt_at and self._as_aware_utc(log.next_attempt_at) > now:
            return log

        try:
            log.attempts = (log.attempts or 0) + 1
            log.html_snapshot = ensure_brand_logo_html(log.html_snapshot)
            result = self.provider.send(
                to=log.email,
                subject=log.subject or "",
                html=log.html_snapshot,
                text=log.text_snapshot,
            )
            log.status = EMAIL_STATUS_SENT
            log.provider = getattr(result, "provider", None) or "mock"
            log.provider_message_id = getattr(result, "provider_message_id", None)
            log.sent_at = now
            log.error_message = None
            log.next_attempt_at = None
            self.db.commit()
            self.db.refresh(log)
            return log
        except Exception as exc:
            log.error_message = str(exc)[:2000]
            if log.attempts < MAX_ATTEMPTS:
                retry_delay = min(30, 2 ** log.attempts)
                log.status = EMAIL_STATUS_PENDING
                log.next_attempt_at = now + timedelta(minutes=retry_delay)
            else:
                log.status = EMAIL_STATUS_ERROR
                log.next_attempt_at = None
            self.db.commit()
            self.db.refresh(log)
            if log.status == EMAIL_STATUS_PENDING:
                from app.modules.email.tasks import enqueue_email_log

                enqueue_email_log(log.id, delay_minutes=retry_delay)
            logger.exception("Falha ao enviar email log_id=%s", log.id)
            return log

    def process_due_scheduled_emails(self, limit: int = 50) -> int:
        now = datetime.now(timezone.utc)
        logs = (
            self.db.query(EmailLog)
            .filter(
                EmailLog.status.in_(list(PENDING_STATUSES)),
                EmailLog.next_attempt_at.isnot(None),
                EmailLog.next_attempt_at <= now,
            )
            .order_by(EmailLog.next_attempt_at.asc())
            .limit(limit)
            .all()
        )
        for log in logs:
            log.status = EMAIL_STATUS_PENDING
        self.db.commit()

        from app.modules.email.tasks import enqueue_email_log

        for log in logs:
            enqueue_email_log(log.id)
        return len(logs)

    def _render_string(self, template: str, payload: dict[str, Any], *, html_escape: bool) -> str:
        if Environment is not None and BaseLoader is not None:
            env = Environment(loader=BaseLoader(), autoescape=html_escape)
            return env.from_string(template).render(**payload)

        def replace(match: re.Match[str]) -> str:
            value = self._resolve_payload_value(payload, match.group(1))
            rendered = "" if value is None else str(value)
            return html.escape(rendered) if html_escape else rendered

        return _VAR_PATTERN.sub(replace, template)

    def _resolve_payload_value(self, payload: dict[str, Any], key: str) -> Any:
        value: Any = payload
        for part in key.split("."):
            if isinstance(value, dict):
                value = value.get(part)
            else:
                value = getattr(value, part, None)
            if value is None:
                return None
        return value

    def _recipient_from_payload(self, payload: dict[str, Any]) -> str | None:
        for key in ("to", "email", "customer_email"):
            value = payload.get(key)
            if value:
                return str(value).strip().lower()
        return None

    def _find_duplicate_log(
        self,
        email: str,
        event_key: str,
        template_slug: str,
        payload: dict[str, Any],
    ) -> EmailLog | None:
        dedupe_key = self._optional_text(payload.get("dedupe_key"))
        order_id = self._safe_int(payload.get("order_id"))
        if not dedupe_key and not order_id:
            return None

        query = self.db.query(EmailLog).filter(
            EmailLog.email == email,
            EmailLog.event_key == event_key,
            EmailLog.status.in_(list(DEDUPE_STATUSES)),
        )
        if dedupe_key:
            query = query.filter(EmailLog.dedupe_key == dedupe_key)
        elif order_id:
            query = query.filter(EmailLog.order_id == order_id)
        return query.first()

    def _safe_int(self, value: Any) -> int | None:
        if value is None or value == "":
            return None
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    def _optional_text(self, value: Any) -> str | None:
        if value is None:
            return None
        text = str(value).strip()
        return text or None

    def _as_aware_utc(self, value: datetime) -> datetime:
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)


def build_order_email_payload(
    db: Session,
    pedido: Pedido,
    *,
    event_key: str,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    user = pedido.usuario
    if user is None:
        user = db.query(Usuario).filter(Usuario.id == pedido.usuario_id).first()

    customer_name = ""
    customer_email = ""
    if user:
        customer_name = user.nome_completo or user.username or ""
        customer_email = user.email

    order_total = f"R$ {pedido.total:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    payload: dict[str, Any] = {
        "to": customer_email,
        "email": customer_email,
        "customer_name": customer_name or "cliente",
        "cliente_nome": customer_name or "cliente",
        "user_id": user.id if user else pedido.usuario_id,
        "order_id": pedido.id,
        "order_number": pedido.numero,
        "pedido_numero": pedido.numero,
        "order_total": order_total,
        "pedido_total": order_total,
        "order_status": pedido.status,
        "pedido_status": pedido.status,
        "tracking_code": pedido.codigo_rastreio or "",
        "codigo_rastreio": pedido.codigo_rastreio or "",
        "tracking_url": "",
        "link_rastreio": "",
        "store_name": settings.STORE_NAME,
        "loja_nome": settings.STORE_NAME,
        "store_url": settings.STORE_URL or settings.FRONTEND_URL,
        "loja_url": settings.STORE_URL or settings.FRONTEND_URL,
        "payment_link": "",
        "link_pagamento": "",
        "pix_code": "",
        "codigo_pix": "",
        "boleto_url": "",
        "coupon_code": pedido.cupom_codigo or "",
        "cupom_codigo": pedido.cupom_codigo or "",
        "dedupe_key": f"{event_key}:{pedido.numero}",
    }
    if extra:
        payload.update(extra)
    return payload


def _latest_order_payment(db: Session, pedido: Pedido) -> Pagamento | None:
    return (
        db.query(Pagamento)
        .filter(Pagamento.pedido_numero == pedido.numero)
        .order_by(Pagamento.id.desc())
        .first()
    )


def _admin_order_url(pedido: Pedido) -> str:
    base_url = (settings.FRONTEND_URL or settings.STORE_URL or "").strip().rstrip("/")
    path = f"/admin/pedidos/{pedido.numero}"
    return f"{base_url}{path}" if base_url else path


def _payment_status_label(pedido: Pedido, pagamento: Pagamento | None) -> str:
    values: list[str] = []
    for value in (
        pagamento.status if pagamento else None,
        pagamento.mp_status if pagamento else None,
        pedido.status,
    ):
        text = str(value or "").strip()
        if text and text not in values:
            values.append(text)
    return " / ".join(values) or "Pagamento aprovado"


def _payment_method_label(pedido: Pedido, pagamento: Pagamento | None) -> str:
    return str((pagamento.tipo if pagamento else None) or pedido.forma_pagamento or "").strip() or "nao informado"


def build_admin_order_paid_email_payload(
    db: Session,
    pedido: Pedido,
    *,
    pagamento: Pagamento | None = None,
) -> dict[str, Any]:
    payload = build_order_email_payload(db, pedido, event_key=ADMIN_ORDER_PAID_EVENT_KEY)
    pagamento = pagamento or _latest_order_payment(db, pedido)
    admin_order_url = _admin_order_url(pedido)
    admin_email = settings.admin_order_notification_email.strip().lower()
    customer_email = str(payload.get("email") or payload.get("to") or "").strip().lower()
    payload.update(
        {
            "to": admin_email,
            "email": admin_email,
            "customer_email": customer_email,
            "cliente_email": customer_email,
            "admin_order_url": admin_order_url,
            "link_pedido_admin": admin_order_url,
            "payment_method": _payment_method_label(pedido, pagamento),
            "forma_pagamento": _payment_method_label(pedido, pagamento),
            "payment_status": _payment_status_label(pedido, pagamento),
            "status_pagamento": _payment_status_label(pedido, pagamento),
            "mp_payment_id": pagamento.mp_payment_id if pagamento else "",
            "dedupe_key": f"{ADMIN_ORDER_PAID_EVENT_KEY}:{pedido.numero}",
        }
    )
    return payload


def _admin_order_paid_email_content(payload: dict[str, Any]) -> tuple[str, str, str]:
    pedido_numero = str(payload.get("pedido_numero") or payload.get("order_number") or "")
    subject = f"Novo pedido pago #{pedido_numero}"
    rows = [
        ("Pedido", pedido_numero),
        ("Cliente", f"{payload.get('cliente_nome') or payload.get('customer_name')} ({payload.get('customer_email')})"),
        ("Total", str(payload.get("pedido_total") or payload.get("order_total") or "")),
        ("Forma de pagamento", str(payload.get("forma_pagamento") or payload.get("payment_method") or "")),
        ("Status do pagamento", str(payload.get("status_pagamento") or payload.get("payment_status") or "")),
        ("Pagamento Mercado Pago", str(payload.get("mp_payment_id") or "nao informado")),
        ("Painel admin", str(payload.get("link_pedido_admin") or payload.get("admin_order_url") or "")),
    ]
    body_html = (
        '<table role="presentation" width="100%" cellspacing="0" cellpadding="0" border="0" '
        'style="border-collapse: collapse; margin: 0 0 18px;">'
        + "".join(
            "<tr>"
            f'<td style="padding: 8px 0; color: #6f675f; font-size: 13px;">{html.escape(label)}</td>'
            f'<td style="padding: 8px 0; color: #111111; font-size: 14px; text-align: right;">{html.escape(value)}</td>'
            "</tr>"
            for label, value in rows
        )
        + "</table>"
    )
    admin_order_url = str(payload.get("admin_order_url") or "")
    html_content = brand_email_html(
        title="Novo pedido pago",
        preheader=f"Pedido {pedido_numero} confirmado pelo Mercado Pago.",
        intro=f"O pedido {pedido_numero} teve pagamento confirmado.",
        body_html=body_html,
        cta_label="Abrir pedido" if admin_order_url.startswith(("http://", "https://")) else None,
        cta_url=admin_order_url if admin_order_url.startswith(("http://", "https://")) else None,
        footer_note="Mensagem interna da loja Bia Collections.",
    )
    text_content = "\n".join(
        [
            f"Novo pedido pago #{pedido_numero}",
            f"Cliente: {payload.get('cliente_nome') or payload.get('customer_name')} ({payload.get('customer_email')})",
            f"Total: {payload.get('pedido_total') or payload.get('order_total')}",
            f"Forma de pagamento: {payload.get('forma_pagamento') or payload.get('payment_method')}",
            f"Status do pagamento: {payload.get('status_pagamento') or payload.get('payment_status')}",
            f"Pagamento Mercado Pago: {payload.get('mp_payment_id') or 'nao informado'}",
            f"Abrir no painel admin: {admin_order_url}",
        ]
    )
    return subject, html_content, text_content


def trigger_admin_order_paid_email(
    db: Session,
    pedido: Pedido,
    *,
    pagamento: Pagamento | None = None,
) -> None:
    try:
        payload = build_admin_order_paid_email_payload(db, pedido, pagamento=pagamento)
        admin_email = str(payload.get("to") or "").strip().lower()
        if not admin_email:
            logger.warning(
                "Notificacao admin de pedido pago ignorada: destinatario ausente pedido=%s",
                pedido.numero,
            )
            return

        service = EmailAutomationService(db)
        duplicate = service._find_duplicate_log(
            admin_email,
            ADMIN_ORDER_PAID_EVENT_KEY,
            ADMIN_ORDER_PAID_TEMPLATE_SLUG,
            payload,
        )
        if duplicate:
            logger.info(
                "Notificacao admin de pedido pago ja registrada pedido=%s email=%s log_id=%s status=%s",
                pedido.numero,
                admin_email,
                duplicate.id,
                duplicate.status,
            )
            return

        subject, html_content, text_content = _admin_order_paid_email_content(payload)
        log = service.send_transactional_email_now(
            to=admin_email,
            subject=subject,
            html_content=html_content,
            text_content=text_content,
            template_slug=ADMIN_ORDER_PAID_TEMPLATE_SLUG,
            event_key=ADMIN_ORDER_PAID_EVENT_KEY,
            payload=payload,
            raise_on_failure=False,
        )
        if log.status == EMAIL_STATUS_SENT:
            logger.info(
                "Notificacao admin de pedido pago enviada pedido=%s email=%s log_id=%s",
                pedido.numero,
                admin_email,
                log.id,
            )
        else:
            logger.warning(
                "Falha ao enviar notificacao admin de pedido pago pedido=%s email=%s log_id=%s status=%s erro=%s",
                pedido.numero,
                admin_email,
                log.id,
                log.status,
                log.error_message,
            )
    except Exception:
        logger.exception("Falha ao disparar notificacao admin de pedido pago pedido=%s", pedido.numero)


def build_coupon_email_payload(
    cupom: Cupom,
    usuario: Usuario,
) -> dict[str, Any]:
    customer_name = usuario.nome_completo or usuario.username or "cliente"
    if cupom.tipo == "porcentagem":
        coupon_value = f"{int(cupom.valor)}%"
    elif cupom.tipo == "frete":
        coupon_value = "Frete gratis"
    else:
        coupon_value = f"R$ {cupom.valor:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")

    return {
        "to": usuario.email,
        "email": usuario.email,
        "customer_name": customer_name,
        "cliente_nome": customer_name,
        "user_id": usuario.id,
        "coupon_code": cupom.codigo,
        "cupom_codigo": cupom.codigo,
        "coupon_description": cupom.descricao,
        "cupom_descricao": cupom.descricao,
        "coupon_value": coupon_value,
        "cupom_valor": coupon_value,
        "coupon_expires_at": cupom.validade.isoformat(),
        "cupom_validade": cupom.validade.isoformat(),
        "store_name": settings.STORE_NAME,
        "loja_nome": settings.STORE_NAME,
        "store_url": settings.STORE_URL or settings.FRONTEND_URL,
        "loja_url": settings.STORE_URL or settings.FRONTEND_URL,
        "dedupe_key": f"cupom_disponivel:{cupom.id}:{usuario.id}",
    }


def trigger_coupon_available_email_event(
    db: Session,
    cupom: Cupom,
    usuario: Usuario,
) -> None:
    try:
        EmailAutomationService(db).trigger_event(
            "coupon_available",
            build_coupon_email_payload(cupom, usuario),
        )
    except Exception:
        logger.exception(
            "Falha ao disparar automacao de email cupom_disponivel cupom=%s usuario=%s",
            cupom.codigo,
            usuario.id,
        )


def trigger_order_email_event(
    db: Session,
    event_key: str,
    pedido: Pedido,
    *,
    extra: dict[str, Any] | None = None,
) -> None:
    try:
        payload = build_order_email_payload(db, pedido, event_key=event_key, extra=extra)
        EmailAutomationService(db).trigger_event(event_key, payload)
    except Exception:
        logger.exception("Falha ao disparar automacao de email event_key=%s pedido=%s", event_key, pedido.numero)

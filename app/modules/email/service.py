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
from app.models.pedido import Pedido
from app.models.usuario import Usuario
from app.modules.email.models import EmailAutomation, EmailLog, EmailTemplate
from app.modules.email.provider import EmailProvider

try:
    from jinja2 import BaseLoader, Environment
except Exception:  # pragma: no cover - optional dependency fallback
    BaseLoader = None
    Environment = None


logger = logging.getLogger(__name__)

QUEUED_STATUSES = {"queued", "scheduled", "sent"}
MAX_ATTEMPTS = 3
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
AUTOMATION_EVENT_TO_ADMIN_EVENT["tracking_code_available"] = "pedido_enviado"


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
        admin_templates = self._active_admin_templates_for_event(event_key)
        if admin_templates:
            return self._enqueue_templates(event_key, payload, [(template, 0) for template in admin_templates])

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

        return self._enqueue_templates(
            event_key,
            payload,
            [(automation.template, automation.delay_minutes) for automation in automations],
        )

    def send_event_now(self, event_key: str, payload: dict[str, Any]) -> EmailLog | None:
        templates = self._active_admin_templates_for_event(event_key)
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

        for template in templates:
            if not template or not template.is_active:
                continue
            to = self._recipient_from_payload(payload)
            if not to:
                logger.warning("Email event %s ignored: missing recipient.", event_key)
                return None

            rendered = self.render_template(template.slug, payload, template=template)
            log = self.save_email_log(
                user_id=self._safe_int(payload.get("user_id")),
                order_id=self._safe_int(payload.get("order_id")),
                email=to,
                template_slug=template.slug,
                event_key=event_key,
                dedupe_key=self._optional_text(payload.get("dedupe_key")),
                status="queued",
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
                log.status = "sent"
                log.provider = result.provider
                log.provider_message_id = result.provider_message_id
                log.sent_at = datetime.now(timezone.utc)
                log.attempts = 1
                log.next_attempt_at = None
                self.db.commit()
                self.db.refresh(log)
                return log
            except Exception as exc:
                log.status = "failed"
                log.error_message = str(exc)[:2000]
                log.attempts = 1
                log.next_attempt_at = None
                self.db.commit()
                self.db.refresh(log)
                raise
        return None

    def _active_admin_templates_for_event(self, event_key: str) -> list[EmailTemplate]:
        admin_event = AUTOMATION_EVENT_TO_ADMIN_EVENT.get(event_key)
        if not admin_event:
            return []
        return (
            self.db.query(EmailTemplate)
            .filter(
                EmailTemplate.evento == admin_event,
                EmailTemplate.status == "ativo",
                EmailTemplate.is_active.is_(True),
            )
            .order_by(EmailTemplate.updated_at.desc(), EmailTemplate.id.desc())
            .all()
        )

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

        return RenderedEmail(
            subject=self._render_string(template.subject, payload, html_escape=False),
            preheader=self._render_string(template.preheader or "", payload, html_escape=False) or None,
            html=self._render_string(template.html_template, payload, html_escape=True),
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
            return duplicate

        now = datetime.now(timezone.utc)
        status = "scheduled" if delay_minutes > 0 else "queued"
        log = EmailLog(
            user_id=self._safe_int(payload.get("user_id")),
            order_id=self._safe_int(payload.get("order_id")),
            email=to,
            template_slug=template_slug,
            event_key=event_key,
            dedupe_key=self._optional_text(payload.get("dedupe_key")),
            status=status,
            subject=subject,
            html_snapshot=html_content,
            text_snapshot=text_content,
            payload_json=json.dumps(payload, ensure_ascii=False, default=str),
            next_attempt_at=now + timedelta(minutes=delay_minutes) if delay_minutes > 0 else now,
        )
        self.db.add(log)
        self.db.commit()
        self.db.refresh(log)

        from app.modules.email.tasks import enqueue_email_log

        enqueue_email_log(log.id, delay_minutes=delay_minutes)
        return log

    def send_email(self, to: str, subject: str, html_content: str, text_content: str) -> None:
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
        if log.status not in {"failed", "scheduled", "queued"}:
            raise ValueError("Apenas emails pendentes ou com falha podem ser reenviados.")

        log.status = "queued"
        log.error_message = None
        log.next_attempt_at = datetime.now(timezone.utc)
        self.db.commit()
        self.db.refresh(log)

        from app.modules.email.tasks import enqueue_email_log

        enqueue_email_log(log.id)
        return log

    def process_queued_email(self, log_id: int) -> EmailLog | None:
        log = self.db.query(EmailLog).filter(EmailLog.id == log_id).first()
        if not log or log.status not in {"queued", "scheduled", "failed"}:
            return log

        now = datetime.now(timezone.utc)
        if log.next_attempt_at and self._as_aware_utc(log.next_attempt_at) > now:
            return log

        try:
            log.attempts = (log.attempts or 0) + 1
            result = self.provider.send(
                to=log.email,
                subject=log.subject or "",
                html=log.html_snapshot,
                text=log.text_snapshot,
            )
            log.status = "sent"
            log.provider = result.provider
            log.provider_message_id = result.provider_message_id
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
                log.status = "scheduled"
                log.next_attempt_at = now + timedelta(minutes=retry_delay)
            else:
                log.status = "failed"
                log.next_attempt_at = None
            self.db.commit()
            self.db.refresh(log)
            if log.status == "scheduled":
                from app.modules.email.tasks import enqueue_email_log

                enqueue_email_log(log.id, delay_minutes=retry_delay)
            logger.exception("Falha ao enviar email log_id=%s", log.id)
            return log

    def process_due_scheduled_emails(self, limit: int = 50) -> int:
        now = datetime.now(timezone.utc)
        logs = (
            self.db.query(EmailLog)
            .filter(
                EmailLog.status == "scheduled",
                EmailLog.next_attempt_at.isnot(None),
                EmailLog.next_attempt_at <= now,
            )
            .order_by(EmailLog.next_attempt_at.asc())
            .limit(limit)
            .all()
        )
        for log in logs:
            log.status = "queued"
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
            EmailLog.template_slug == template_slug,
            EmailLog.status.in_(QUEUED_STATUSES),
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

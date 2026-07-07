import smtplib
import ssl
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import parseaddr

import httpx

from app.core.config import settings
from app.modules.email.templates import password_reset_code_email, two_factor_code_email


EMAIL_TIMEOUT_SECONDS = 15


def _clean(value: str | None) -> str:
    return (value or "").strip()


def _sender() -> str:
    return _clean(settings.email_from_address)


def _sender_name() -> str:
    return _clean(settings.EMAIL_FROM_NAME) or "Bia Collections"


def _sender_email() -> str:
    sender = _sender()
    _, parsed_email = parseaddr(sender)
    return parsed_email or sender


def _sender_header() -> str:
    sender = _sender()
    if not sender:
        return ""
    if "<" in sender and ">" in sender:
        return sender
    return f"{_sender_name()} <{sender}>"


def _provider() -> str:
    provider = _clean(settings.EMAIL_PROVIDER).lower() or "auto"
    if provider == "auto":
        if _clean(settings.RESEND_API_KEY):
            return "resend"
        if _clean(settings.BREVO_API_KEY):
            return "brevo"
        return "smtp"
    return provider


def _raise_for_http_response(provider: str, response: httpx.Response) -> None:
    if 200 <= response.status_code < 300:
        return
    detail = _clean(response.text)
    if detail:
        detail = detail[:500]
        raise RuntimeError(
            f"Falha ao enviar email via {provider}: HTTP {response.status_code}. Resposta: {detail}"
        )
    raise RuntimeError(f"Falha ao enviar email via {provider}: HTTP {response.status_code}.")


def _smtp_config() -> tuple[str, str, str]:
    smtp_user = _clean(settings.SMTP_USER)
    smtp_password = _clean(settings.SMTP_PASSWORD)
    sender = _sender()

    if not settings.SMTP_HOST or not settings.SMTP_PORT or not smtp_user or not smtp_password or not sender:
        raise RuntimeError("Configuracao SMTP incompleta.")

    return smtp_user, smtp_password, sender


def _send_message(destinatario: str, msg: MIMEMultipart) -> None:
    smtp_user, smtp_password, sender = _smtp_config()
    context = ssl.create_default_context()
    with smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT, timeout=EMAIL_TIMEOUT_SECONDS) as server:
        server.ehlo()
        server.starttls(context=context)
        server.ehlo()
        server.login(smtp_user, smtp_password)
        server.sendmail(sender, [destinatario], msg.as_string())


def _send_smtp_email(destinatario: str, subject: str, text: str | None = None, html: str | None = None) -> None:
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = _sender_header()
    msg["To"] = destinatario
    if text:
        msg.attach(MIMEText(text, "plain", "utf-8"))
    if html:
        msg.attach(MIMEText(html, "html", "utf-8"))
    _send_message(destinatario, msg)


def _send_resend_email(destinatario: str, subject: str, text: str | None = None, html: str | None = None) -> None:
    api_key = _clean(settings.RESEND_API_KEY)
    sender = _sender_header()
    if not api_key or not sender:
        raise RuntimeError("Configuracao Resend incompleta.")

    payload: dict[str, object] = {
        "from": sender,
        "to": [destinatario],
        "subject": subject,
    }
    if html:
        payload["html"] = html
    if text:
        payload["text"] = text

    with httpx.Client(timeout=EMAIL_TIMEOUT_SECONDS) as client:
        response = client.post(
            _clean(settings.RESEND_API_URL),
            headers={"Authorization": f"Bearer {api_key}"},
            json=payload,
        )
    _raise_for_http_response("Resend", response)


def _send_brevo_email(destinatario: str, subject: str, text: str | None = None, html: str | None = None) -> None:
    api_key = _clean(settings.BREVO_API_KEY)
    sender_email = _sender_email()
    if not api_key or not sender_email:
        raise RuntimeError("Configuracao Brevo incompleta.")

    payload: dict[str, object] = {
        "sender": {"name": _sender_name(), "email": sender_email},
        "to": [{"email": destinatario}],
        "subject": subject,
    }
    if html:
        payload["htmlContent"] = html
    if text:
        payload["textContent"] = text

    with httpx.Client(timeout=EMAIL_TIMEOUT_SECONDS) as client:
        response = client.post(
            _clean(settings.BREVO_API_URL),
            headers={"api-key": api_key},
            json=payload,
        )
    _raise_for_http_response("Brevo", response)


def _send_email(destinatario: str, subject: str, text: str | None = None, html: str | None = None) -> None:
    provider = _provider()
    if provider == "resend":
        _send_resend_email(destinatario, subject, text=text, html=html)
        return
    if provider == "brevo":
        _send_brevo_email(destinatario, subject, text=text, html=html)
        return
    if provider == "smtp":
        _send_smtp_email(destinatario, subject, text=text, html=html)
        return
    raise RuntimeError(f"Provedor de email invalido: {provider}.")


def enviar_email_reset(destinatario: str, codigo: str) -> None:
    """Envia o codigo de redefinicao de senha por email."""
    message = password_reset_code_email(codigo)

    _send_email(
        destinatario,
        message.subject,
        text=message.text,
        html=message.html,
    )


def enviar_email_codigo_acesso(destinatario: str, codigo: str) -> None:
    message = two_factor_code_email(codigo)

    _send_email(
        destinatario,
        message.subject,
        text=message.text,
        html=message.html,
    )

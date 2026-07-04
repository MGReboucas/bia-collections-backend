import smtplib
import ssl
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import parseaddr

import httpx

from app.core.config import settings


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
    html = f"""
    <html>
      <body style="font-family: Arial, sans-serif; background: #F5F5F5; padding: 32px;">
        <div style="max-width: 480px; margin: auto; background: #fff;
                    border-radius: 16px; padding: 40px; text-align: center;">
          <h2 style="color: #111111; margin-bottom: 8px;">Redefinição de Senha</h2>
          <p style="color: #555; font-size: 15px; margin-bottom: 28px;">
            Use o código abaixo para redefinir sua senha.<br>
            Ele expira em <strong>15 minutos</strong>.
          </p>
          <div style="background: #F5F5F5; border-radius: 12px;
                      padding: 20px 32px; display: inline-block; margin-bottom: 28px;">
            <span style="font-size: 36px; font-weight: 900;
                         letter-spacing: 12px; color: #111111;">{codigo}</span>
          </div>
          <p style="color: #999; font-size: 13px;">
            Se você não solicitou isso, ignore este e-mail.
          </p>
        </div>
      </body>
    </html>
    """
    text = (
        f"Use o codigo {codigo} para redefinir sua senha.\n"
        "Ele expira em 15 minutos.\n\n"
        "Se voce nao solicitou isso, ignore este e-mail."
    )

    _send_email(
        destinatario,
        "Redefinição de senha — Bia Collections",
        text=text,
        html=html,
    )


def enviar_email_codigo_acesso(destinatario: str, codigo: str) -> None:
    corpo = (
        f"Seu codigo de acesso e: {codigo}\n\n"
        "Ele expira em 10 minutos. Se voce nao tentou entrar, ignore este e-mail."
    )

    _send_email(
        destinatario,
        "Seu codigo de acesso - Bia Collections",
        text=corpo,
    )

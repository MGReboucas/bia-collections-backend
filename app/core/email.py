import smtplib
import ssl
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from app.core.config import settings


def enviar_email_reset(destinatario: str, codigo: str) -> None:
    """Envia o codigo de redefinicao de senha por email."""
    smtp_user = settings.SMTP_USER.strip()
    smtp_password = settings.SMTP_PASSWORD.strip()
    remetente = (settings.EMAIL_FROM or smtp_user).strip()

    if not settings.SMTP_HOST or not settings.SMTP_PORT or not smtp_user or not smtp_password or not remetente:
        raise RuntimeError("Configuracao SMTP incompleta.")

    msg = MIMEMultipart("alternative")
    msg["Subject"] = "Redefinição de senha — Bia Collections"
    msg["From"] = f"Bia Collections <{remetente}>"
    msg["To"] = destinatario

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
    msg.attach(MIMEText(html, "html"))

    context = ssl.create_default_context()
    with smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT, timeout=15) as server:
        server.ehlo()
        server.starttls(context=context)
        server.ehlo()
        server.login(smtp_user, smtp_password)
        server.sendmail(remetente, [destinatario], msg.as_string())

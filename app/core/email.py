import smtplib
import ssl
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from app.core.config import settings


def enviar_email_reset(destinatario: str, codigo: str) -> None:
    """Envia o código de redefinição de senha por e-mail."""
    msg = MIMEMultipart("alternative")
    msg["Subject"] = "Redefinição de senha — Curado Bem"
    msg["From"] = f"Curado Bem <{settings.EMAIL_FROM}>"
    msg["To"] = destinatario

    html = f"""
    <html>
      <body style="font-family: Arial, sans-serif; background: #F3EBD6; padding: 32px;">
        <div style="max-width: 480px; margin: auto; background: #fff;
                    border-radius: 16px; padding: 40px; text-align: center;">
          <h2 style="color: #627348; margin-bottom: 8px;">Redefinição de Senha</h2>
          <p style="color: #555; font-size: 15px; margin-bottom: 28px;">
            Use o código abaixo para redefinir sua senha.<br>
            Ele expira em <strong>15 minutos</strong>.
          </p>
          <div style="background: #F3EBD6; border-radius: 12px;
                      padding: 20px 32px; display: inline-block; margin-bottom: 28px;">
            <span style="font-size: 36px; font-weight: 900;
                         letter-spacing: 12px; color: #627348;">{codigo}</span>
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
    with smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT) as server:
        server.ehlo()
        server.starttls(context=context)
        server.ehlo()
        server.login(settings.SMTP_USER, settings.SMTP_PASSWORD)
        server.sendmail(settings.EMAIL_FROM, destinatario, msg.as_string())

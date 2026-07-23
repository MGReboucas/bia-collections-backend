from __future__ import annotations

import html as html_lib
import re
from dataclasses import dataclass


BRAND_COLORS = {
    "black": "#111111",
    "white": "#FFFFFF",
    "off_white": "#F5F5F5",
    "nude": "#E7D2BB",
    "gold": "#C8A96B",
}

BRAND_EMAIL_LOGO_PATH = "/uploads/email/bia-collections-logooficial.png"
BRAND_EMAIL_LOGO_FILENAME = "bia-collections-logooficial.png"
BRAND_INSTAGRAM_URL = "https://www.instagram.com/biacollectionstore"

_LEGACY_HEADER_LOGO_RE = re.compile(
    r'<td align="center" style="padding: 38px 28px 18px; border-bottom: 1px solid #eee8df;">\s*'
    r'<div style="font-family: Georgia,[\s\S]*?</div>\s*'
    r'<div style="font-family: Arial,[\s\S]*?>COLLECTIONS</div>\s*'
    r'<div style="width: 54px;[\s\S]*?</div>\s*'
    r'<div style="font-family: Arial,[\s\S]*?>ACESSORIOS FEMININOS</div>\s*'
    r"</td>",
    re.IGNORECASE,
)
_LEGACY_FOOTER_LOGO_RE = re.compile(
    r'\s*<div style="font-family: Georgia,[^"]*font-size: 28px; line-height: 30px;">Bia</div>\s*'
    r'<div style="font-family: Arial,[^"]*font-size: 10px; letter-spacing: 4px; margin-top: 4px;">'
    r"COLLECTIONS</div>",
    re.IGNORECASE,
)


ECOMMERCE_EMAIL_EVENTS = [
    "user_registered",
    "email_confirmation",
    "resend_email_confirmation",
    "password_reset",
    "password_changed",
    "email_changed",
    "login_new_device",
    "account_deleted",
    "order_created",
    "order_confirmed",
    "payment_approved",
    "payment_refused",
    "payment_pending",
    "payment_expired",
    "order_preparing",
    "order_invoiced",
    "order_shipped",
    "tracking_code_available",
    "order_out_for_delivery",
    "order_delivered",
    "order_cancelled",
    "cancellation_confirmed",
    "refund_requested",
    "refund_approved",
    "refund_completed",
    "abandoned_cart_1h",
    "abandoned_cart_24h",
    "abandoned_cart_3d",
    "cart_coupon_reminder",
    "cart_product_unavailable",
    "cart_product_price_drop",
    "product_back_in_stock",
    "product_out_of_stock",
    "product_on_sale",
    "new_product_launch",
    "wishlist_product_on_sale",
    "invoice_issued",
    "payment_receipt",
    "pix_generated",
    "pix_expiring",
    "boleto_generated",
    "boleto_expiring",
    "boleto_expired",
    "boleto_second_copy",
    "coupon_received",
    "coupon_expiring",
    "coupon_expired",
    "coupon_used",
    "cashback_available",
    "cashback_expiring",
    "review_request",
    "review_published",
    "review_replied",
    "support_ticket_created",
    "support_ticket_replied",
    "support_ticket_closed",
    "new_support_message",
    "newsletter",
    "store_news",
    "new_collection",
    "promotion_campaign",
    "exclusive_offer",
    "black_friday",
    "commemorative_date",
    "personalized_recommendations",
    "phone_changed",
    "address_changed",
    "card_changed",
    "suspicious_login",
    "access_attempt_blocked",
    "two_factor_code",
    "data_export_requested",
    "data_export_ready",
    "privacy_policy_updated",
    "terms_updated",
]


@dataclass(frozen=True)
class BrandEmailMessage:
    subject: str
    text: str
    html: str


def _clean(value: str | None) -> str:
    return (value or "").strip()


def _join_url(base_url: str, path: str) -> str:
    return f"{base_url.rstrip('/')}/{path.lstrip('/')}"


def brand_email_logo_url() -> str:
    from app.core.config import settings

    configured_url = _clean(settings.EMAIL_LOGO_URL)
    if configured_url:
        return configured_url

    for base_url in (settings.MP_NOTIFICATION_URL, settings.STORE_URL, settings.FRONTEND_URL):
        base_url = _clean(base_url)
        if base_url:
            return _join_url(base_url, BRAND_EMAIL_LOGO_PATH)
    return BRAND_EMAIL_LOGO_PATH


def brand_email_logo_img(*, width: int = 260) -> str:
    src = html_lib.escape(brand_email_logo_url(), quote=True)
    return (
        f'<img data-bia-email-logo="true" src="{src}" width="{width}" '
        'alt="Bia Collections" '
        f'style="display: block; width: {width}px; max-width: 100%; height: auto; '
        'margin: 0 auto; border: 0; outline: none; text-decoration: none;">'
    )


def brand_email_logo_cell() -> str:
    return (
        '<td align="center" style="padding: 34px 28px 22px; border-bottom: 1px solid #eee8df;">'
        f"{brand_email_logo_img(width=230)}"
        "</td>"
    )


def brand_email_logo_block() -> str:
    return (
        '<table role="presentation" width="100%" cellspacing="0" cellpadding="0" border="0">'
        '<tr><td align="center" style="padding: 24px 0 20px;">'
        f"{brand_email_logo_img(width=230)}"
        "</td></tr></table>"
    )


def ensure_brand_logo_html(value: str | None) -> str | None:
    if not value:
        return value
    if 'data-bia-email-logo="true"' in value or BRAND_EMAIL_LOGO_FILENAME in value:
        return value

    updated = _LEGACY_HEADER_LOGO_RE.sub(brand_email_logo_cell(), value, count=1)
    updated = _LEGACY_FOOTER_LOGO_RE.sub("", updated)
    if 'data-bia-email-logo="true"' in updated or BRAND_EMAIL_LOGO_FILENAME in updated:
        return updated

    logo_block = brand_email_logo_block()
    if re.search(r"<body\b[^>]*>", updated, flags=re.IGNORECASE):
        return re.sub(
            r"(<body\b[^>]*>)",
            rf"\1{logo_block}",
            updated,
            count=1,
            flags=re.IGNORECASE,
        )
    return f"{logo_block}{updated}"


def brand_email_html(
    *,
    title: str,
    preheader: str,
    intro: str,
    body_html: str = "",
    code: str | None = None,
    cta_label: str | None = None,
    cta_url: str | None = None,
    footer_note: str | None = None,
    footer_cta_label: str | None = None,
    footer_cta_url: str | None = None,
) -> str:
    code_block = ""
    if code:
        code_block = f"""
          <tr>
            <td align="center" style="padding: 10px 0 28px;">
              <div style="display: inline-block; border: 1px solid {BRAND_COLORS['gold']}; background: {BRAND_COLORS['off_white']}; padding: 18px 28px;">
                <span style="font-family: Georgia, 'Times New Roman', serif; font-size: 34px; line-height: 42px; letter-spacing: 10px; color: {BRAND_COLORS['black']};">{code}</span>
              </div>
            </td>
          </tr>
        """

    cta_block = ""
    if cta_label and cta_url:
        cta_block = f"""
          <tr>
            <td align="center" style="padding: 8px 0 30px;">
              <a href="{cta_url}" style="display: inline-block; background: {BRAND_COLORS['black']}; color: {BRAND_COLORS['white']}; font-family: Arial, Helvetica, sans-serif; font-size: 12px; letter-spacing: 2px; text-transform: uppercase; text-decoration: none; padding: 14px 26px;">{cta_label}</a>
            </td>
          </tr>
        """

    footer = footer_note or "Se você não solicitou esta mensagem, ignore este e-mail."
    footer_cta_block = ""
    if footer_cta_label and footer_cta_url:
        footer_cta_block = f"""
                <div style="margin-top: 16px;">
                  <a href="{footer_cta_url}" style="display: inline-block; border: 1px solid {BRAND_COLORS['gold']}; color: {BRAND_COLORS['white']}; font-family: Arial, Helvetica, sans-serif; font-size: 11px; letter-spacing: 2px; text-transform: uppercase; text-decoration: none; padding: 12px 22px;">{footer_cta_label}</a>
                </div>
        """

    return f"""<!doctype html>
<html lang="pt-BR">
  <head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>{title}</title>
  </head>
  <body style="margin: 0; padding: 0; background: {BRAND_COLORS['off_white']}; color: {BRAND_COLORS['black']};">
    <span style="display: none; visibility: hidden; opacity: 0; color: transparent; height: 0; width: 0; overflow: hidden;">{preheader}</span>
    <table role="presentation" width="100%" cellspacing="0" cellpadding="0" border="0" style="background: {BRAND_COLORS['off_white']}; padding: 32px 12px;">
      <tr>
        <td align="center">
          <table role="presentation" width="100%" cellspacing="0" cellpadding="0" border="0" style="max-width: 620px; background: {BRAND_COLORS['white']}; border: 1px solid #e8e1d8;">
            <tr>
              {brand_email_logo_cell()}
            </tr>
            <tr>
              <td style="padding: 34px 36px 8px;">
                <h1 style="margin: 0; font-family: Georgia, 'Times New Roman', serif; font-size: 32px; line-height: 38px; font-weight: normal; text-align: center; color: {BRAND_COLORS['black']};">{title}</h1>
                <p style="margin: 18px 0 24px; font-family: Arial, Helvetica, sans-serif; font-size: 15px; line-height: 24px; text-align: center; color: #4e4a45;">{intro}</p>
              </td>
            </tr>
            {code_block}
            <tr>
              <td style="padding: 0 38px 16px; font-family: Arial, Helvetica, sans-serif; font-size: 14px; line-height: 23px; color: #4e4a45;">
                {body_html}
              </td>
            </tr>
            {cta_block}
            <tr>
              <td style="padding: 24px 36px 36px; background: {BRAND_COLORS['black']}; color: {BRAND_COLORS['white']}; text-align: center;">
                <p style="margin: 0; font-family: Arial, Helvetica, sans-serif; font-size: 12px; line-height: 20px; color: #d9d2ca;">{footer}</p>
                {footer_cta_block}
              </td>
            </tr>
          </table>
        </td>
      </tr>
    </table>
  </body>
</html>"""


def two_factor_code_email(codigo: str) -> BrandEmailMessage:
    return BrandEmailMessage(
        subject="Seu código de acesso - Bia Collections",
        text=(
            f"Seu código de acesso é: {codigo}\n\n"
            "Ele expira em 10 minutos. Por segurança, não compartilhe este código com ninguém.\n\n"
            "Confira nossos cupons no Instagram da loja: "
            f"{BRAND_INSTAGRAM_URL}"
        ),
        html=brand_email_html(
            title="Seu código de acesso",
            preheader="Use este código para concluir seu acesso à Bia Collections.",
            intro="Use o código abaixo para concluir seu acesso com segurança.",
            code=codigo,
            body_html=(
                "<p style=\"margin: 0 0 12px; text-align: center;\">"
                "Este código expira em <strong>10 minutos</strong>.</p>"
                "<p style=\"margin: 0 0 18px; text-align: center;\">"
                "Por segurança, não compartilhe este código com ninguém.</p>"
                "<p style=\"margin: 0; text-align: center;\">"
                "Confira nossos cupons no Instagram da loja.</p>"
            ),
            cta_label="Ver Instagram",
            cta_url=BRAND_INSTAGRAM_URL,
        ),
    )


def password_reset_code_email(codigo: str) -> BrandEmailMessage:
    return BrandEmailMessage(
        subject="Redefinicao de senha - Bia Collections",
        text=(
            f"Use o codigo {codigo} para redefinir sua senha.\n"
            "Ele expira em 15 minutos.\n\n"
            "Se voce nao solicitou isso, ignore este e-mail."
        ),
        html=brand_email_html(
            title="Redefinicao de senha",
            preheader="Use este codigo para criar uma nova senha.",
            intro="Recebemos uma solicitacao para redefinir sua senha.",
            code=codigo,
            body_html=(
                "<p style=\"margin: 0 0 12px; text-align: center;\">"
                "Digite o codigo acima na tela de recuperacao de senha.</p>"
                "<p style=\"margin: 0; text-align: center;\">"
                "Ele expira em <strong>15 minutos</strong>.</p>"
            ),
        ),
    )

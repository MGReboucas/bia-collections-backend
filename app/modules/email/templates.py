from __future__ import annotations

from dataclasses import dataclass


BRAND_COLORS = {
    "black": "#111111",
    "white": "#FFFFFF",
    "off_white": "#F5F5F5",
    "nude": "#E7D2BB",
    "gold": "#C8A96B",
}


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

    footer = footer_note or "Se voce nao solicitou esta mensagem, ignore este e-mail com seguranca."

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
              <td align="center" style="padding: 38px 28px 18px; border-bottom: 1px solid #eee8df;">
                <div style="font-family: Georgia, 'Times New Roman', serif; font-size: 58px; line-height: 58px; color: {BRAND_COLORS['black']}; letter-spacing: 0;">Bia</div>
                <div style="font-family: Arial, Helvetica, sans-serif; font-size: 12px; letter-spacing: 5px; color: {BRAND_COLORS['black']}; margin-top: 6px;">COLLECTIONS</div>
                <div style="width: 54px; height: 1px; background: {BRAND_COLORS['gold']}; margin: 18px auto 12px;"></div>
                <div style="font-family: Arial, Helvetica, sans-serif; font-size: 10px; letter-spacing: 4px; color: #6f6a64;">ACESSORIOS FEMININOS</div>
              </td>
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
                <div style="font-family: Georgia, 'Times New Roman', serif; font-size: 28px; line-height: 30px;">Bia</div>
                <div style="font-family: Arial, Helvetica, sans-serif; font-size: 10px; letter-spacing: 4px; margin-top: 4px;">COLLECTIONS</div>
                <p style="margin: 18px 0 0; font-family: Arial, Helvetica, sans-serif; font-size: 12px; line-height: 20px; color: #d9d2ca;">{footer}</p>
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
        subject="Seu codigo de acesso - Bia Collections",
        text=(
            f"Seu codigo de acesso e: {codigo}\n\n"
            "Ele expira em 10 minutos. Se voce nao tentou entrar, ignore este e-mail."
        ),
        html=brand_email_html(
            title="Seu codigo de acesso",
            preheader="Use este codigo para concluir seu acesso a Bia Collections.",
            intro="Use o codigo abaixo para concluir seu acesso com seguranca.",
            code=codigo,
            body_html=(
                "<p style=\"margin: 0 0 12px; text-align: center;\">"
                "Este codigo expira em <strong>10 minutos</strong>.</p>"
                "<p style=\"margin: 0; text-align: center;\">"
                "Por seguranca, nao compartilhe este codigo com ninguem.</p>"
            ),
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

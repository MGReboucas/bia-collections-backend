from __future__ import annotations

import json
import re
from typing import Any

from sqlalchemy.orm import Session

from app.core.database import SessionLocal
from app.modules.email.models import EmailAutomation, EmailTemplate
from app.modules.email.templates import BRAND_INSTAGRAM_URL, brand_email_html


def _schema(*variables: str) -> str:
    return json.dumps({"variables": list(variables)}, ensure_ascii=False)


PREMIUM_TEMPLATE_MARKER = 'data-bia-template-style="premium-v2"'
ORDER_SUMMARY_TEMPLATE_MARKER = 'data-bia-order-summary="true"'

ORDER_SUMMARY_CATEGORIES = {"pedidos", "pagamentos", "financeiro", "avaliacoes"}
ORDER_SUMMARY_ADMIN_EVENTS = {
    "pedido_criado",
    "pagamento_aprovado",
    "pagamento_recusado",
    "pagamento_pendente",
    "pagamento_expirado",
    "pedido_preparando",
    "pedido_enviado",
    "pedido_entregue",
    "pedido_cancelado",
    "reembolso_aprovado",
    "reembolso_processado",
    "nota_fiscal_recibo",
    "troca_devolucao_recebida",
    "troca_devolucao_aprovada",
    "troca_devolucao_recusada",
    "avaliacao_pedido",
}


def _order_summary_block(*, admin: bool) -> str:
    items_variable = "pedido_itens_html" if admin else "order_items_html"
    total_variable = "pedido_total" if admin else "order_total"
    return (
        f'<div {ORDER_SUMMARY_TEMPLATE_MARKER}>'
        f"{{{{{items_variable}}}}}"
        '<table role="presentation" width="100%" cellspacing="0" cellpadding="0" border="0" '
        'style="border-collapse: collapse; margin: 0 0 22px;">'
        "<tr>"
        '<td style="padding: 12px 0; border-top: 1px solid #eee8df; font-family: Arial, Helvetica, sans-serif; '
        'font-size: 13px; line-height: 20px; color: #6f675f;">Total do pedido</td>'
        '<td align="right" style="padding: 12px 0; border-top: 1px solid #eee8df; '
        'font-family: Arial, Helvetica, sans-serif; font-size: 15px; line-height: 20px; '
        f'color: #111111;"><strong>{{{{{total_variable}}}}}</strong></td>'
        "</tr>"
        "</table>"
        "</div>"
    )


def _with_order_summary(
    body_html: str,
    text_template: str,
    variables: tuple[str, ...],
    *,
    admin: bool,
) -> tuple[str, str, tuple[str, ...]]:
    items_variable = "pedido_itens_html" if admin else "order_items_html"
    items_text_variable = "pedido_itens_text" if admin else "order_items_text"
    total_variable = "pedido_total" if admin else "order_total"

    if f"{{{{{items_variable}}}}}" not in body_html:
        body_html = f"{body_html}{_order_summary_block(admin=admin)}"
    if f"{{{{{items_text_variable}}}}}" not in text_template:
        text_template = (
            f"{text_template.rstrip()} Itens: {{{{{items_text_variable}}}}}. "
            f"Total do pedido: {{{{{total_variable}}}}}."
        )

    required = (items_variable, items_text_variable, total_variable)
    variables = variables + tuple(variable for variable in required if variable not in variables)
    return body_html, text_template, variables


_PORTUGUESE_COPY_REPLACEMENTS = {
    "Confirmacao": "Confirmação",
    "confirmacao": "confirmação",
    "Preparacao": "Preparação",
    "preparacao": "preparação",
    "Solicitacao": "Solicitação",
    "solicitacao": "solicitação",
    "Atualizacao": "Atualização",
    "atualizacao": "atualização",
    "Informacao": "Informação",
    "informacao": "informação",
    "informacoes": "informações",
    "Alteracao": "Alteração",
    "alteracao": "alteração",
    "Atencao": "Atenção",
    "atencao": "atenção",
    "Avaliacao": "Avaliação",
    "avaliacao": "avaliação",
    "Experiencia": "Experiência",
    "experiencia": "experiência",
    "Opiniao": "Opinião",
    "opiniao": "opinião",
    "Confianca": "Confiança",
    "confianca": "confiança",
    "Codigo": "Código",
    "codigo": "código",
    "Seguranca": "Segurança",
    "seguranca": "segurança",
    "Recuperacao": "Recuperação",
    "recuperacao": "recuperação",
    "Redefinicao": "Redefinição",
    "redefinicao": "redefinição",
    "Visualizacao": "Visualização",
    "visualizacao": "visualização",
    "Instituicao": "Instituição",
    "instituicao": "instituição",
    "Endereco": "Endereço",
    "endereco": "endereço",
    "Enderecos": "Endereços",
    "enderecos": "endereços",
    "Numero": "Número",
    "numero": "número",
    "Analise": "Análise",
    "analise": "análise",
    "Beneficio": "Benefício",
    "beneficio": "benefício",
    "Botao": "Botão",
    "botao": "botão",
    "Devolucao": "Devolução",
    "devolucao": "devolução",
    "Diferenca": "Diferença",
    "diferenca": "diferença",
    "Minimo": "Mínimo",
    "minimo": "mínimo",
    "Verificacao": "Verificação",
    "verificacao": "verificação",
    "Protocolo": "Protocolo",
    "proximos": "próximos",
    "proximo": "próximo",
    "orientacoes": "orientações",
    "necessaria": "necessária",
    "possivel": "possível",
    "sensivel": "sensível",
    "disponivel": "disponível",
    "duvida": "dúvida",
    "duvidas": "dúvidas",
    "acao": "ação",
    "acoes": "ações",
    "Ola": "Olá",
    "Voce": "Você",
    "voce": "você",
    "Voces": "Vocês",
    "voces": "vocês",
    "Nao": "Não",
    "nao": "não",
    "Esta": "Está",
    "esta": "está",
    "Ja": "Já",
    "ja": "já",
    "So": "Só",
    "so": "só",
    "Ate": "Até",
    "ate": "até",
    "Apos": "Após",
    "apos": "após",
    "Sera": "Será",
    "sera": "será",
    "Faca": "Faça",
    "faca": "faça",
    "Atraves": "Através",
    "atraves": "através",
    "recebera": "receberá",
    "acompanhara": "acompanhará",
    "seguira": "seguirá",
    "Email": "E-mail",
    "email": "e-mail",
}


def _review_portuguese_copy(value: str) -> str:
    placeholders: list[str] = []

    def protect_placeholder(match: re.Match[str]) -> str:
        placeholders.append(match.group(0))
        return f"__BIA_TEMPLATE_VARIABLE_{len(placeholders) - 1}__"

    reviewed = re.sub(r"{{[^{}]+}}", protect_placeholder, value)
    reviewed = reviewed.replace("data-bia-email-logo", "__BIA_EMAIL_LOGO_ATTRIBUTE__")
    reviewed = reviewed.replace("/uploads/email/", "/uploads/__BIA_EMAIL_PATH__/")
    reviewed = reviewed.replace("Bem-vinda a Loja", "Bem-vinda à Bia Collections")
    reviewed = reviewed.replace("Bem-vinda a Bia", "Bem-vinda à Bia")
    reviewed = reviewed.replace("Bem-vinda a __BIA_TEMPLATE_VARIABLE_", "Bem-vinda à __BIA_TEMPLATE_VARIABLE_")
    reviewed = reviewed.replace("pos-venda", "pós-venda")
    for source, target in _PORTUGUESE_COPY_REPLACEMENTS.items():
        if source in {"Esta", "esta"}:
            continue
        reviewed = re.sub(rf"\b{re.escape(source)}\b", target, reviewed)
    for source, target in (
        ("esta pronta", "está pronta"),
        ("esta pronto", "está pronto"),
        ("esta salvo", "está salvo"),
        ("esta salva", "está salva"),
        ("esta liberado", "está liberado"),
        ("esta liberada", "está liberada"),
        ("esta disponível", "está disponível"),
        ("esta sendo", "está sendo"),
        ("esta em preparo", "está em preparo"),
        ("esta em preparação", "está em preparação"),
        ("esta expirando", "está expirando"),
        ("esta chegando", "está chegando"),
        ("esta com estoque", "está com estoque"),
        ("ainda esta", "ainda está"),
        ("já esta", "já está"),
        ("Já esta", "Já está"),
        ("nenhuma ação e necessária", "nenhuma ação é necessária"),
        ("O valor aprovado e ", "O valor aprovado é "),
        ("Seu código de acesso e:", "Seu código de acesso é:"),
        ("seu código de acesso e:", "seu código de acesso é:"),
        ("Qualquer dúvida, fale", "Em caso de dúvida, fale"),
        ("vai analisar as informações e retornar", "analisará as informações e retornará"),
    ):
        reviewed = reviewed.replace(source, target)
    reviewed = reviewed.replace("Código copia e cola", "Código Pix Copia e Cola")
    reviewed = reviewed.replace("__BIA_EMAIL_LOGO_ATTRIBUTE__", "data-bia-email-logo")
    reviewed = reviewed.replace("/uploads/__BIA_EMAIL_PATH__/", "/uploads/email/")
    reviewed = re.sub(
        r"(__BIA_TEMPLATE_VARIABLE_\d+__)\s+([.,;:!?])",
        r"\1\2",
        reviewed,
    )
    for index, placeholder in enumerate(placeholders):
        reviewed = reviewed.replace(f"__BIA_TEMPLATE_VARIABLE_{index}__", placeholder)
    return reviewed


def _premium_body(body_html: str, *, internal: bool = False) -> str:
    alignment = "left" if internal else "center"
    return (
        f'<div {PREMIUM_TEMPLATE_MARKER} '
        f'style="text-align: {alignment}; color: #4e4a45;">'
        f"{body_html}"
        "</div>"
    )


def _default_customer_cta(
    variables: tuple[str, ...],
    *,
    admin: bool,
) -> tuple[str | None, str | None]:
    candidates = (
        (
            ("link_meus_pedidos", "Ver meus pedidos", "{{link_meus_pedidos}}"),
            ("loja_home_url", "Visitar a loja", "{{loja_home_url}}"),
            ("loja_url", "Visitar a loja", "{{loja_url}}"),
        )
        if admin
        else (
            ("orders_url", "Ver meus pedidos", "{{orders_url}}"),
            ("store_home_url", "Visitar a loja", "{{store_home_url}}"),
            ("store_url", "Visitar a loja", "{{store_url}}"),
        )
    )
    for variable, label, url in candidates:
        if variable in variables:
            return label, url
    return None, None


def _premium_text(text_template: str, *, internal: bool) -> str:
    if internal or BRAND_INSTAGRAM_URL in text_template:
        return text_template
    return f"{text_template.rstrip()} Confira novidades no Instagram: {BRAND_INSTAGRAM_URL}"


def _template(
    *,
    name: str,
    slug: str,
    category: str,
    subject: str,
    preheader: str,
    title: str,
    intro: str,
    body_html: str,
    text_template: str,
    variables: tuple[str, ...],
    cta_label: str | None = None,
    cta_url: str | None = None,
    footer_cta_label: str | None = None,
    footer_cta_url: str | None = None,
) -> dict[str, Any]:
    if category in ORDER_SUMMARY_CATEGORIES and "order_number" in variables:
        body_html, text_template, variables = _with_order_summary(
            body_html,
            text_template,
            variables,
            admin=False,
        )
    name = _review_portuguese_copy(name)
    subject = _review_portuguese_copy(subject)
    preheader = _review_portuguese_copy(preheader)
    title = _review_portuguese_copy(title)
    intro = _review_portuguese_copy(intro)
    body_html = _review_portuguese_copy(body_html)
    text_template = _review_portuguese_copy(text_template)
    cta_label = _review_portuguese_copy(cta_label) if cta_label else None
    footer_cta_label = _review_portuguese_copy(footer_cta_label) if footer_cta_label else None
    if not cta_label or not cta_url:
        default_label, default_url = _default_customer_cta(variables, admin=False)
        cta_label = cta_label or default_label
        cta_url = cta_url or default_url
    footer_cta_label = footer_cta_label or "Ver Instagram"
    footer_cta_url = footer_cta_url or BRAND_INSTAGRAM_URL
    return {
        "name": name,
        "slug": slug,
        "category": category,
        "subject": subject,
        "preheader": preheader,
        "html_template": brand_email_html(
            title=title,
            preheader=preheader,
            intro=intro,
            body_html=_premium_body(body_html),
            cta_label=cta_label,
            cta_url=cta_url,
            footer_cta_label=footer_cta_label,
            footer_cta_url=footer_cta_url,
        ),
        "text_template": _premium_text(text_template, internal=False),
        "variables_schema": _schema(*variables),
        "is_active": True,
    }


def _admin_template(
    *,
    nome: str,
    slug: str,
    evento: str,
    assunto: str,
    title: str,
    preheader: str,
    intro: str,
    body_html: str,
    text_template: str,
    variables: tuple[str, ...],
    status: str = "ativo",
    cta_label: str | None = None,
    cta_url: str | None = None,
    footer_cta_label: str | None = None,
    footer_cta_url: str | None = None,
) -> dict[str, Any]:
    if evento in ORDER_SUMMARY_ADMIN_EVENTS:
        body_html, text_template, variables = _with_order_summary(
            body_html,
            text_template,
            variables,
            admin=True,
        )
    nome = _review_portuguese_copy(nome)
    assunto = _review_portuguese_copy(assunto)
    preheader = _review_portuguese_copy(preheader)
    title = _review_portuguese_copy(title)
    intro = _review_portuguese_copy(intro)
    body_html = _review_portuguese_copy(body_html)
    text_template = _review_portuguese_copy(text_template)
    cta_label = _review_portuguese_copy(cta_label) if cta_label else None
    footer_cta_label = _review_portuguese_copy(footer_cta_label) if footer_cta_label else None
    internal = evento.startswith("interno_")
    if not internal and (not cta_label or not cta_url):
        default_label, default_url = _default_customer_cta(variables, admin=True)
        cta_label = cta_label or default_label
        cta_url = cta_url or default_url
    if not internal:
        footer_cta_label = footer_cta_label or "Ver Instagram"
        footer_cta_url = footer_cta_url or BRAND_INSTAGRAM_URL
    html = brand_email_html(
        title=title,
        preheader=preheader,
        intro=intro,
        body_html=_premium_body(body_html, internal=internal),
        cta_label=cta_label,
        cta_url=cta_url,
        footer_cta_label=footer_cta_label,
        footer_cta_url=footer_cta_url,
    )
    return {
        "nome": nome,
        "name": nome,
        "slug": slug,
        "category": evento,
        "subject": assunto,
        "preheader": preheader,
        "evento": evento,
        "status": status,
        "html": html,
        "html_template": html,
        "text_template": _premium_text(text_template, internal=internal),
        "variables_schema": _schema(*variables),
        "is_active": status == "ativo",
    }


def _fill_missing_admin_template_fields(template: EmailTemplate, data: dict[str, Any]) -> None:
    for key, value in data.items():
        current = getattr(template, key, None)
        if current is None or current == "":
            setattr(template, key, value)


ACCESS_CODE_TEMPLATE_REFRESH_SLUGS = {"two-factor-code", "admin-default-codigo-acesso"}
ACCESS_CODE_TEMPLATE_REFRESH_MARKERS = (
    "Seu codigo de acesso",
    "Seu codigo de acesso e",
    "Use este codigo",
    "Use o codigo abaixo",
    "Este codigo expira",
    "Por seguranca",
    "width: 260px",
    'width="260"',
)
ORDER_CREATED_TEMPLATE_REFRESH_SLUGS = {"order-created", "admin-default-pedido-criado"}
ORDER_CREATED_TEMPLATE_REFRESH_MARKERS = (
    "Total do pedido: <strong>{{order_total}}</strong>",
    "Total do pedido: <strong>{{pedido_total}}</strong>",
    "Assim que o pagamento for confirmado, vamos preparar tudo com cuidado.",
)
ORDER_CREATED_TEMPLATE_CURRENT_MARKERS = (
    "order_items_html",
    "pedido_itens_html",
    "link_meus_pedidos",
    "orders_url",
)
ORDER_CREATED_TEMPLATE_PREVIEW_INCOMPATIBLE_MARKERS = (
    "|safe",
    "|default('', true)",
)
PAYMENT_APPROVED_TEMPLATE_REFRESH_SLUGS = {"payment-approved", "admin-default-pagamento-aprovado"}
PAYMENT_APPROVED_TEMPLATE_REFRESH_MARKERS = (
    "Total confirmado: <strong>{{order_total}}</strong>",
    "Total confirmado: <strong>{{pedido_total}}</strong>",
    "Agora vamos separar seus produtos",
    "link_meus_pedidos",
    "orders_url",
    "Ir para a home da Bia Collections",
    "Ver Instagram",
)
PAYMENT_APPROVED_TEMPLATE_CURRENT_MARKERS = (
    "order_items_html",
    "pedido_itens_html",
)
PAYMENT_REFUSED_TEMPLATE_REFRESH_SLUGS = {"payment-refused", "admin-default-pagamento-recusado"}
PAYMENT_REFUSED_TEMPLATE_REFRESH_MARKERS = (
    "Voce pode tentar novamente pelo painel de pedidos",
    "Tente novamente pelo painel de pedidos",
    "Se o valor tiver sido reservado pelo banco",
)
PAYMENT_REFUSED_TEMPLATE_CURRENT_MARKERS = (
    "order_items_html",
    "pedido_itens_html",
    "Ainda dá tempo",
    "Ainda da tempo",
)
PAYMENT_PENDING_TEMPLATE_REFRESH_SLUGS = {"payment-pending", "admin-default-pagamento-pendente"}
PAYMENT_PENDING_TEMPLATE_REFRESH_MARKERS = (
    "Assim que o pagamento for confirmado",
    "Ainda estamos aguardando a confirmacao do pagamento",
    "Se voce ja pagou",
    "Total do pedido: <strong>{{pedido_total}}</strong>",
)
PAYMENT_PENDING_TEMPLATE_CURRENT_MARKERS = (
    "order_items_html",
    "pedido_itens_html",
    "Finalizar pagamento",
)
PAYMENT_EXPIRED_TEMPLATE_REFRESH_SLUGS = {"payment-expired", "admin-default-pagamento-expirado"}
PAYMENT_EXPIRED_TEMPLATE_REFRESH_MARKERS = (
    "Se ainda quiser os produtos, faca uma nova compra",
    "Se ainda quiser os produtos, faça uma nova compra",
    "O pedido nao seguira para preparo",
    "O pedido não seguirá para preparo",
)
PAYMENT_EXPIRED_TEMPLATE_CURRENT_MARKERS = (
    "order_items_html",
    "pedido_itens_html",
    "Uma nova chance para escolher seus favoritos",
    "Comprar novamente",
)


def _refresh_access_code_template_if_old(template: EmailTemplate, data: dict[str, Any]) -> None:
    if data["slug"] not in ACCESS_CODE_TEMPLATE_REFRESH_SLUGS:
        return

    content = " ".join(
        str(getattr(template, key, "") or "")
        for key in (
            "nome",
            "name",
            "subject",
            "preheader",
            "html",
            "html_template",
            "text_template",
        )
    )
    if not any(marker in content for marker in ACCESS_CODE_TEMPLATE_REFRESH_MARKERS):
        return

    for key, value in data.items():
        if key in {"status", "is_active"}:
            continue
        setattr(template, key, value)


def _refresh_order_created_template_if_old(template: EmailTemplate, data: dict[str, Any]) -> None:
    if data["slug"] not in ORDER_CREATED_TEMPLATE_REFRESH_SLUGS:
        return

    content = " ".join(
        str(getattr(template, key, "") or "")
        for key in (
            "nome",
            "name",
            "subject",
            "preheader",
            "html",
            "html_template",
            "text_template",
            "variables_schema",
        )
    )
    if any(marker in content for marker in ORDER_CREATED_TEMPLATE_CURRENT_MARKERS) and not any(
        marker in content for marker in ORDER_CREATED_TEMPLATE_PREVIEW_INCOMPATIBLE_MARKERS
    ):
        return
    if not any(marker in content for marker in ORDER_CREATED_TEMPLATE_REFRESH_MARKERS):
        return

    for key, value in data.items():
        if key in {"status", "is_active"}:
            continue
        setattr(template, key, value)


def _refresh_payment_approved_template_if_old(template: EmailTemplate, data: dict[str, Any]) -> None:
    if data["slug"] not in PAYMENT_APPROVED_TEMPLATE_REFRESH_SLUGS:
        return

    content = " ".join(
        str(getattr(template, key, "") or "")
        for key in (
            "nome",
            "name",
            "subject",
            "preheader",
            "html",
            "html_template",
            "text_template",
            "variables_schema",
        )
    )
    if any(marker in content for marker in PAYMENT_APPROVED_TEMPLATE_CURRENT_MARKERS):
        return
    if not any(marker in content for marker in PAYMENT_APPROVED_TEMPLATE_REFRESH_MARKERS):
        return

    for key, value in data.items():
        if key in {"status", "is_active"}:
            continue
        setattr(template, key, value)


def _refresh_payment_refused_template_if_old(template: EmailTemplate, data: dict[str, Any]) -> None:
    if data["slug"] not in PAYMENT_REFUSED_TEMPLATE_REFRESH_SLUGS:
        return

    content = " ".join(
        str(getattr(template, key, "") or "")
        for key in (
            "nome",
            "name",
            "subject",
            "preheader",
            "html",
            "html_template",
            "text_template",
            "variables_schema",
        )
    )
    if any(marker in content for marker in PAYMENT_REFUSED_TEMPLATE_CURRENT_MARKERS):
        return
    if not any(marker in content for marker in PAYMENT_REFUSED_TEMPLATE_REFRESH_MARKERS):
        return

    for key, value in data.items():
        if key in {"status", "is_active"}:
            continue
        setattr(template, key, value)


def _refresh_payment_pending_template_if_old(template: EmailTemplate, data: dict[str, Any]) -> None:
    if data["slug"] not in PAYMENT_PENDING_TEMPLATE_REFRESH_SLUGS:
        return

    content = " ".join(
        str(getattr(template, key, "") or "")
        for key in (
            "nome",
            "name",
            "subject",
            "preheader",
            "html",
            "html_template",
            "text_template",
            "variables_schema",
        )
    )
    if any(marker in content for marker in PAYMENT_PENDING_TEMPLATE_CURRENT_MARKERS):
        return
    if not any(marker in content for marker in PAYMENT_PENDING_TEMPLATE_REFRESH_MARKERS):
        return

    for key, value in data.items():
        if key in {"status", "is_active"}:
            continue
        setattr(template, key, value)


def _refresh_payment_expired_template_if_old(template: EmailTemplate, data: dict[str, Any]) -> None:
    if data["slug"] not in PAYMENT_EXPIRED_TEMPLATE_REFRESH_SLUGS:
        return

    content = " ".join(
        str(getattr(template, key, "") or "")
        for key in (
            "nome",
            "name",
            "subject",
            "preheader",
            "html",
            "html_template",
            "text_template",
            "variables_schema",
        )
    )
    if any(marker in content for marker in PAYMENT_EXPIRED_TEMPLATE_CURRENT_MARKERS):
        return
    if not any(marker in content for marker in PAYMENT_EXPIRED_TEMPLATE_REFRESH_MARKERS):
        return

    for key, value in data.items():
        if key in {"status", "is_active"}:
            continue
        setattr(template, key, value)


def _refresh_premium_template_if_seeded(template: EmailTemplate, data: dict[str, Any]) -> None:
    content = " ".join(
        str(getattr(template, key, "") or "")
        for key in ("html", "html_template")
    )
    if PREMIUM_TEMPLATE_MARKER in content:
        return

    created_at = getattr(template, "created_at", None)
    updated_at = getattr(template, "updated_at", None)
    if created_at and updated_at and updated_at != created_at:
        # Templates edited through the admin keep their custom content.
        return

    for key, value in data.items():
        if key in {"status", "is_active"}:
            continue
        setattr(template, key, value)


def _refresh_order_summary_template_if_missing(template: EmailTemplate, data: dict[str, Any]) -> None:
    seeded_html = str(data.get("html") or data.get("html_template") or "")
    if (
        ORDER_SUMMARY_TEMPLATE_MARKER not in seeded_html
        and "order_items_html" not in seeded_html
        and "pedido_itens_html" not in seeded_html
    ):
        return

    current_html = " ".join(
        str(getattr(template, key, "") or "")
        for key in ("html", "html_template")
    )
    if "order_items_html" in current_html or "pedido_itens_html" in current_html:
        return

    created_at = getattr(template, "created_at", None)
    updated_at = getattr(template, "updated_at", None)
    if created_at and updated_at and updated_at != created_at:
        # Never replace content explicitly customized through the admin.
        return

    for key, value in data.items():
        if key in {"status", "is_active"}:
            continue
        setattr(template, key, value)


def _review_existing_template_copy(template: EmailTemplate) -> None:
    for key in (
        "nome",
        "name",
        "subject",
        "preheader",
        "html",
        "html_template",
        "text_template",
    ):
        current = getattr(template, key, None)
        if isinstance(current, str) and current:
            setattr(template, key, _review_portuguese_copy(current))


EMAIL_TEMPLATE_SEEDS: list[dict[str, Any]] = [
    _template(
        name="Boas-vindas",
        slug="user-registered",
        category="conta",
        subject="Bem-vinda a Bia Collections",
        preheader="Sua conta foi criada com sucesso.",
        title="Bem-vinda a Loja",
        intro="Ola {{customer_name}}, sua conta já esta pronta.",
        body_html=(
            "<p style=\"margin: 0 0 16px; text-align: center;\">"
            "Que bom ter voce por aqui. Agora voce pode acompanhar pedidos, salvar enderecos e receber novidades escolhidas com cuidado.</p>"
            "<p style=\"margin: 0; text-align: center;\">"
            "<a href=\"{{store_home_url}}\" style=\"color: #111111; font-weight: bold; text-decoration: underline;\">"
            "Ir para a home da Bia Collections</a></p>"
        ),
        text_template="Ola {{customer_name}}, sua conta na Bia Collections foi criada com sucesso.",
        variables=("customer_name", "store_url"),
        cta_label="Ver Instagram",
        cta_url=BRAND_INSTAGRAM_URL,
    ),
    _template(
        name="Confirmacao de e-mail",
        slug="email-confirmation",
        category="conta",
        subject="Confirme seu e-mail - Bia Collections",
        preheader="Finalize a confirmacao da sua conta.",
        title="Confirme seu e-mail",
        intro="Ola {{customer_name}}, falta so confirmar seu endereco de e-mail.",
        body_html="<p>Clique no botao abaixo para confirmar sua conta e manter seus dados seguros.</p>",
        text_template="Confirme seu e-mail acessando: {{confirmation_url}}",
        variables=("customer_name", "confirmation_url"),
        cta_label="Confirmar e-mail",
        cta_url="{{confirmation_url}}",
    ),
    _template(
        name="Recuperacao de senha",
        slug="password-reset",
        category="seguranca",
        subject="Redefinicao de senha - Bia Collections",
        preheader="Use o codigo enviado para criar uma nova senha.",
        title="Redefinicao de senha",
        intro="Recebemos uma solicitacao para redefinir sua senha.",
        body_html="<p>Use o codigo <strong>{{reset_code}}</strong> para criar uma nova senha. Ele expira em {{expires_in_minutes}} minutos.</p>",
        text_template="Use o codigo {{reset_code}} para redefinir sua senha. Ele expira em {{expires_in_minutes}} minutos.",
        variables=("reset_code", "expires_in_minutes"),
    ),
    _template(
        name="Código de acesso",
        slug="two-factor-code",
        category="seguranca",
        subject="Seu código de acesso - Bia Collections",
        preheader="Use este código para concluir seu acesso.",
        title="Seu código de acesso",
        intro="Use o código abaixo para concluir seu acesso com segurança.",
        body_html=(
            "<p style=\"text-align:center; font-size:26px; letter-spacing:8px;\"><strong>{{code}}</strong></p>"
            "<p style=\"text-align:center;\">Este código expira em {{expires_in_minutes}} minutos.</p>"
            "<p style=\"text-align:center;\">Por segurança, não compartilhe este código com ninguém.</p>"
            "<p style=\"text-align:center;\">Confira nossos cupons no Instagram da loja.</p>"
        ),
        text_template=(
            "Seu código de acesso é: {{code}}. Ele expira em {{expires_in_minutes}} minutos. "
            "Confira nossos cupons no Instagram da loja: "
            f"{BRAND_INSTAGRAM_URL}"
        ),
        variables=("code", "expires_in_minutes"),
        cta_label="Ver Instagram",
        cta_url=BRAND_INSTAGRAM_URL,
    ),
    _template(
        name="Senha alterada",
        slug="password-changed",
        category="seguranca",
        subject="Sua senha foi alterada - Bia Collections",
        preheader="Confirmacao de alteracao de senha.",
        title="Senha alterada",
        intro="Ola {{customer_name}}, sua senha foi alterada com sucesso.",
        body_html="<p>Se foi voce, nenhuma acao e necessaria. Se nao reconhece esta alteracao, fale com nosso atendimento imediatamente.</p>",
        text_template="Sua senha da Bia Collections foi alterada. Se nao reconhece esta alteracao, fale com nosso atendimento.",
        variables=("customer_name", "store_url"),
    ),
    _template(
        name="Pedido criado",
        slug="order-created",
        category="pedidos",
        subject="Recebemos seu pedido {{order_number}}",
        preheader="Seu pedido foi criado e está aguardando pagamento.",
        title="Pedido recebido",
        intro="Olá {{customer_name}}, recebemos seu pedido {{order_number}} e já separamos os detalhes para você.",
        body_html=(
            "<p style=\"margin: 0 0 16px; text-align: center;\">"
            "Obrigada pela compra. Assim que o pagamento for confirmado, vamos preparar tudo com cuidado.</p>"
            "{{order_items_html}}"
            "<table role=\"presentation\" width=\"100%\" cellspacing=\"0\" cellpadding=\"0\" border=\"0\" "
            "style=\"border-collapse: collapse; margin: 0 0 22px;\">"
            "<tr>"
            "<td style=\"padding: 12px 0; border-top: 1px solid #eee8df; font-family: Arial, Helvetica, sans-serif; "
            "font-size: 13px; line-height: 20px; color: #6f675f;\">Total do pedido</td>"
            "<td align=\"right\" style=\"padding: 12px 0; border-top: 1px solid #eee8df; font-family: Arial, Helvetica, sans-serif; "
            "font-size: 15px; line-height: 20px; color: #111111;\"><strong>{{order_total}}</strong></td>"
            "</tr>"
            "</table>"
            "<p style=\"margin: 0 0 18px; text-align: center;\">"
            "Você pode acompanhar cada atualização em Meus pedidos ou voltar para a loja para conferir as novidades.</p>"
            "<p style=\"margin: 0; text-align: center;\">"
            "<a href=\"{{store_home_url}}\" style=\"color: #111111; font-weight: bold; text-decoration: underline;\">"
            "Ir para a home da Bia Collections</a></p>"
        ),
        text_template=(
            "Olá {{customer_name}}, recebemos seu pedido {{order_number}}. "
            "Itens: {{order_items_text}}. Total do pedido: {{order_total}}. "
            "Acompanhe em {{orders_url}}. Confira novidades no Instagram: "
            f"{BRAND_INSTAGRAM_URL}"
        ),
        variables=(
            "customer_name",
            "order_number",
            "order_total",
            "order_items_html",
            "order_items_text",
            "orders_url",
            "store_home_url",
            "store_url",
            "instagram_url",
        ),
        cta_label="Ver meus pedidos",
        cta_url="{{orders_url}}",
        footer_cta_label="Ver Instagram",
        footer_cta_url=BRAND_INSTAGRAM_URL,
    ),
    _template(
        name="Pagamento aprovado",
        slug="payment-approved",
        category="pagamentos",
        subject="Pagamento aprovado - Pedido {{order_number}}",
        preheader="Seu pagamento foi confirmado.",
        title="Pagamento aprovado",
        intro="Olá {{customer_name}}, o pagamento do pedido {{order_number}} foi aprovado com sucesso.",
        body_html=(
            "<p style=\"margin: 0 0 16px; text-align: center;\">"
            "Tudo certo com o pagamento. Agora vamos separar seus produtos com cuidado e avisar quando o pedido for enviado.</p>"
            "{{order_items_html}}"
            "<table role=\"presentation\" width=\"100%\" cellspacing=\"0\" cellpadding=\"0\" border=\"0\" "
            "style=\"border-collapse: collapse; margin: 0 0 22px;\">"
            "<tr>"
            "<td style=\"padding: 12px 0; border-top: 1px solid #eee8df; font-family: Arial, Helvetica, sans-serif; "
            "font-size: 13px; line-height: 20px; color: #6f675f;\">Total confirmado</td>"
            "<td align=\"right\" style=\"padding: 12px 0; border-top: 1px solid #eee8df; font-family: Arial, Helvetica, sans-serif; "
            "font-size: 15px; line-height: 20px; color: #111111;\"><strong>{{order_total}}</strong></td>"
            "</tr>"
            "</table>"
            "<p style=\"margin: 0 0 18px; text-align: center;\">"
            "Você pode acompanhar cada atualização em Meus pedidos ou voltar para a loja para conferir as novidades.</p>"
            "<p style=\"margin: 0; text-align: center;\">"
            "<a href=\"{{store_home_url}}\" style=\"color: #111111; font-weight: bold; text-decoration: underline;\">"
            "Ir para a home da Bia Collections</a></p>"
        ),
        text_template=(
            "Olá {{customer_name}}, o pagamento do pedido {{order_number}} foi aprovado. "
            "Itens: {{order_items_text}}. Total confirmado: {{order_total}}. Acompanhe em {{orders_url}}. "
            "Confira novidades no Instagram: "
            f"{BRAND_INSTAGRAM_URL}"
        ),
        variables=(
            "customer_name",
            "order_number",
            "order_total",
            "order_items_html",
            "order_items_text",
            "orders_url",
            "store_home_url",
            "store_url",
            "instagram_url",
        ),
        cta_label="Ver meus pedidos",
        cta_url="{{orders_url}}",
        footer_cta_label="Ver Instagram",
        footer_cta_url=BRAND_INSTAGRAM_URL,
    ),
    _template(
        name="Pagamento recusado",
        slug="payment-refused",
        category="pagamentos",
        subject="Pagamento não aprovado - Pedido {{order_number}}",
        preheader="Ainda dá tempo de concluir sua compra.",
        title="Pagamento não aprovado",
        intro="Olá {{customer_name}}, não conseguimos aprovar o pagamento do pedido {{order_number}}.",
        body_html=(
            "<p style=\"margin: 0 0 16px; text-align: center;\">"
            "<strong>Ainda dá tempo de concluir sua compra.</strong></p>"
            "<p style=\"margin: 0 0 16px; text-align: center;\">"
            "Seu pedido ainda pode ser concluído. Isso pode acontecer por limite, dados do pagamento, validação do banco "
            "ou uma instabilidade momentânea.</p>"
            "{{order_items_html}}"
            "<table role=\"presentation\" width=\"100%\" cellspacing=\"0\" cellpadding=\"0\" border=\"0\" "
            "style=\"border-collapse: collapse; margin: 0 0 22px;\">"
            "<tr>"
            "<td style=\"padding: 12px 0; border-top: 1px solid #eee8df; font-family: Arial, Helvetica, sans-serif; "
            "font-size: 13px; line-height: 20px; color: #6f675f;\">Total do pedido</td>"
            "<td align=\"right\" style=\"padding: 12px 0; border-top: 1px solid #eee8df; font-family: Arial, Helvetica, sans-serif; "
            "font-size: 15px; line-height: 20px; color: #111111;\"><strong>{{order_total}}</strong></td>"
            "</tr>"
            "</table>"
            "<p style=\"margin: 0 0 18px; text-align: center;\">"
            "Para garantir seus produtos, acesse Meus pedidos, revise o pagamento e tente novamente ou escolha outra forma de pagamento.</p>"
            "<p style=\"margin: 0; text-align: center;\">"
            "<a href=\"{{store_home_url}}\" style=\"color: #111111; font-weight: bold; text-decoration: underline;\">"
            "Ir para a home da Bia Collections</a></p>"
        ),
        text_template=(
            "Olá {{customer_name}}, não conseguimos aprovar o pagamento do pedido {{order_number}}. "
            "Itens: {{order_items_text}}. Total do pedido: {{order_total}}. "
            "Ainda dá tempo de concluir sua compra. Tente novamente ou escolha outra forma de pagamento em {{orders_url}}. "
            "Confira novidades no Instagram: "
            f"{BRAND_INSTAGRAM_URL}"
        ),
        variables=(
            "customer_name",
            "order_number",
            "order_total",
            "order_items_html",
            "order_items_text",
            "orders_url",
            "store_home_url",
            "store_url",
            "instagram_url",
        ),
        cta_label="Tentar novamente",
        cta_url="{{orders_url}}",
        footer_cta_label="Ver Instagram",
        footer_cta_url=BRAND_INSTAGRAM_URL,
    ),
    _template(
        name="Pagamento pendente",
        slug="payment-pending",
        category="pagamentos",
        subject="Pagamento pendente - Pedido {{order_number}}",
        preheader="Finalize o pagamento para garantir seus produtos.",
        title="Pagamento pendente",
        intro="Olá {{customer_name}}, o pedido {{order_number}} ainda está aguardando pagamento.",
        body_html=(
            "<p style=\"margin: 0 0 16px; text-align: center;\">"
            "<strong>Finalize o pagamento para garantir seus produtos.</strong></p>"
            "<p style=\"margin: 0 0 16px; text-align: center;\">"
            "Enquanto o pagamento não é confirmado, seu pedido ainda não segue para preparo. "
            "Acesse Meus pedidos para concluir agora ou escolher outra forma de pagamento.</p>"
            "{{order_items_html}}"
            "<table role=\"presentation\" width=\"100%\" cellspacing=\"0\" cellpadding=\"0\" border=\"0\" "
            "style=\"border-collapse: collapse; margin: 0 0 22px;\">"
            "<tr>"
            "<td style=\"padding: 12px 0; border-top: 1px solid #eee8df; font-family: Arial, Helvetica, sans-serif; "
            "font-size: 13px; line-height: 20px; color: #6f675f;\">Total do pedido</td>"
            "<td align=\"right\" style=\"padding: 12px 0; border-top: 1px solid #eee8df; font-family: Arial, Helvetica, sans-serif; "
            "font-size: 15px; line-height: 20px; color: #111111;\"><strong>{{order_total}}</strong></td>"
            "</tr>"
            "</table>"
            "<p style=\"margin: 0 0 18px; text-align: center;\">"
            "Se você já concluiu o pagamento, pode ficar tranquila: avisaremos assim que a confirmação chegar.</p>"
            "<p style=\"margin: 0; text-align: center;\">"
            "<a href=\"{{store_home_url}}\" style=\"color: #111111; font-weight: bold; text-decoration: underline;\">"
            "Ir para a home da Bia Collections</a></p>"
        ),
        text_template=(
            "Olá {{customer_name}}, o pedido {{order_number}} ainda está aguardando pagamento. "
            "Itens: {{order_items_text}}. Total do pedido: {{order_total}}. "
            "Finalize o pagamento para garantir seus produtos em {{orders_url}}. "
            "Se você já pagou, avisaremos assim que a confirmação chegar. Confira novidades no Instagram: "
            f"{BRAND_INSTAGRAM_URL}"
        ),
        variables=(
            "customer_name",
            "order_number",
            "order_total",
            "order_items_html",
            "order_items_text",
            "orders_url",
            "store_home_url",
            "store_url",
            "instagram_url",
        ),
        cta_label="Finalizar pagamento",
        cta_url="{{orders_url}}",
        footer_cta_label="Ver Instagram",
        footer_cta_url=BRAND_INSTAGRAM_URL,
    ),
    _template(
        name="Pagamento expirado",
        slug="payment-expired",
        category="pagamentos",
        subject="Seu pedido {{order_number}} expirou — seus favoritos ainda esperam por você",
        preheader="O prazo terminou, mas você pode escolher seus favoritos novamente.",
        title="Pagamento expirado",
        intro="Olá {{customer_name}}, o prazo para pagar o pedido {{order_number}} terminou.",
        body_html=(
            "<p style=\"margin: 0 0 16px; text-align: center;\">"
            "<strong>Uma nova chance para escolher seus favoritos.</strong></p>"
            "<p style=\"margin: 0 0 16px; text-align: center;\">"
            "Como o pagamento não foi concluído a tempo, o pedido foi encerrado e não seguirá para preparo.</p>"
            "{{order_items_html}}"
            "<table role=\"presentation\" width=\"100%\" cellspacing=\"0\" cellpadding=\"0\" border=\"0\" "
            "style=\"border-collapse: collapse; margin: 0 0 22px;\">"
            "<tr>"
            "<td style=\"padding: 12px 0; border-top: 1px solid #eee8df; font-family: Arial, Helvetica, sans-serif; "
            "font-size: 13px; line-height: 20px; color: #6f675f;\">Valor do pedido expirado</td>"
            "<td align=\"right\" style=\"padding: 12px 0; border-top: 1px solid #eee8df; font-family: Arial, Helvetica, sans-serif; "
            "font-size: 15px; line-height: 20px; color: #111111;\"><strong>{{order_total}}</strong></td>"
            "</tr>"
            "</table>"
            "<p style=\"margin: 0 0 18px; text-align: center;\">"
            "Se você ainda amou essas peças, volte à loja e monte seu pedido novamente. "
            "A disponibilidade pode mudar, então aproveite para garantir seus favoritos.</p>"
            "<p style=\"margin: 0; text-align: center;\">"
            "<a href=\"{{orders_url}}\" style=\"color: #111111; font-weight: bold; text-decoration: underline;\">"
            "Consultar meus pedidos</a></p>"
        ),
        text_template=(
            "Olá {{customer_name}}, o prazo para pagar o pedido {{order_number}} terminou. "
            "Itens: {{order_items_text}}. Valor do pedido expirado: {{order_total}}. "
            "Você pode montar uma nova compra em {{store_home_url}}, conforme a disponibilidade dos produtos. "
            "Consulte seus pedidos em {{orders_url}}. Confira novidades no Instagram: "
            f"{BRAND_INSTAGRAM_URL}"
        ),
        variables=(
            "customer_name",
            "order_number",
            "order_total",
            "order_items_html",
            "order_items_text",
            "orders_url",
            "store_home_url",
            "store_url",
            "instagram_url",
        ),
        cta_label="Comprar novamente",
        cta_url="{{store_home_url}}",
        footer_cta_label="Ver Instagram",
        footer_cta_url=BRAND_INSTAGRAM_URL,
    ),
    _template(
        name="PIX gerado",
        slug="pix-generated",
        category="financeiro",
        subject="PIX gerado - Pedido {{order_number}}",
        preheader="Use o codigo PIX para pagar seu pedido.",
        title="PIX gerado",
        intro="Seu PIX para o pedido {{order_number}} ja esta disponivel.",
        body_html="<p>Codigo copia e cola:</p><p style=\"word-break: break-all;\"><strong>{{pix_code}}</strong></p>",
        text_template="PIX do pedido {{order_number}}: {{pix_code}}",
        variables=("order_number", "pix_code"),
    ),
    _template(
        name="Pedido em preparo",
        slug="order-preparing",
        category="pedidos",
        subject="Seu pedido {{order_number}} esta em preparo",
        preheader="Estamos separando seus produtos.",
        title="Pedido em preparo",
        intro="Ola {{customer_name}}, seu pedido esta sendo preparado.",
        body_html="<p>Vamos avisar novamente quando ele sair para entrega.</p>",
        text_template="Seu pedido {{order_number}} esta em preparo.",
        variables=("customer_name", "order_number"),
    ),
    _template(
        name="Pedido enviado",
        slug="order-shipped",
        category="pedidos",
        subject="Seu pedido {{order_number}} foi enviado",
        preheader="Seu pedido saiu para transporte.",
        title="Pedido enviado",
        intro="Ola {{customer_name}}, seu pedido {{order_number}} foi enviado.",
        body_html="<p>Codigo de rastreio: <strong>{{tracking_code}}</strong></p>",
        text_template="Seu pedido {{order_number}} foi enviado. Rastreio: {{tracking_code}}.",
        variables=("customer_name", "order_number", "tracking_code", "tracking_url"),
        cta_label="Acompanhar entrega",
        cta_url="{{tracking_url}}",
    ),
    _template(
        name="Codigo de rastreio",
        slug="tracking-code-available",
        category="pedidos",
        subject="Codigo de rastreio do pedido {{order_number}}",
        preheader="Seu rastreio ja esta disponivel.",
        title="Rastreio disponivel",
        intro="Ola {{customer_name}}, seu codigo de rastreio ja esta disponivel.",
        body_html="<p>Codigo: <strong>{{tracking_code}}</strong></p>",
        text_template="Codigo de rastreio do pedido {{order_number}}: {{tracking_code}}.",
        variables=("customer_name", "order_number", "tracking_code", "tracking_url"),
    ),
    _template(
        name="Pedido entregue",
        slug="order-delivered",
        category="pedidos",
        subject="Pedido {{order_number}} entregue",
        preheader="Esperamos que voce ame seus produtos.",
        title="Pedido entregue",
        intro="Ola {{customer_name}}, seu pedido foi entregue.",
        body_html="<p>Esperamos que cada detalhe tenha chegado perfeito. Obrigada por escolher a Bia Collections.</p>",
        text_template="Pedido {{order_number}} entregue. Obrigada por comprar na Bia Collections.",
        variables=("customer_name", "order_number"),
    ),
    _template(
        name="Pedido cancelado",
        slug="order-cancelled",
        category="pedidos",
        subject="Pedido {{order_number}} cancelado",
        preheader="Seu pedido foi cancelado.",
        title="Pedido cancelado",
        intro="O pedido {{order_number}} foi cancelado.",
        body_html="<p>Se voce tiver qualquer duvida, fale com nosso atendimento.</p>",
        text_template="Pedido {{order_number}} cancelado.",
        variables=("order_number",),
    ),
    _template(
        name="Carrinho abandonado 1h",
        slug="abandoned-cart-1h",
        category="carrinho",
        subject="Voce deixou alguns favoritos na Bia",
        preheader="Seu carrinho ainda esta esperando por voce.",
        title="Seu carrinho esta salvo",
        intro="Ola {{customer_name}}, seus itens continuam no carrinho.",
        body_html="<p>Finalize sua compra antes que algum produto acabe.</p>",
        text_template="Seu carrinho na Bia Collections ainda esta salvo.",
        variables=("customer_name", "store_url"),
        cta_label="Voltar ao carrinho",
        cta_url="{{store_url}}/checkout",
    ),
    _template(
        name="Produto voltou ao estoque",
        slug="product-back-in-stock",
        category="produtos",
        subject="{{product_name}} voltou ao estoque",
        preheader="O produto que voce queria esta disponivel novamente.",
        title="Voltou ao estoque",
        intro="{{product_name}} esta disponivel novamente.",
        body_html="<p>Corra para garantir o seu antes que acabe de novo.</p>",
        text_template="{{product_name}} voltou ao estoque na Bia Collections.",
        variables=("product_name", "store_url"),
        cta_label="Ver produto",
        cta_url="{{product_url}}",
    ),
    _template(
        name="Cupom expirando",
        slug="coupon-expiring",
        category="cupons",
        subject="Seu cupom {{coupon_code}} esta expirando",
        preheader="Aproveite seu beneficio antes do prazo terminar.",
        title="Cupom expirando",
        intro="Seu cupom {{coupon_code}} esta chegando ao fim.",
        body_html="<p>Use antes de {{coupon_expires_at}} para aproveitar o beneficio.</p>",
        text_template="Seu cupom {{coupon_code}} expira em {{coupon_expires_at}}.",
        variables=("coupon_code", "coupon_expires_at", "store_url"),
        cta_label="Usar cupom",
        cta_url="{{store_url}}",
    ),
    _template(
        name="Pedido aguardando avaliacao",
        slug="review-request",
        category="avaliacoes",
        subject="Conte como foi sua experiencia",
        preheader="Sua opiniao ajuda outras clientes.",
        title="Como foi sua experiencia?",
        intro="Ola {{customer_name}}, queremos saber o que voce achou do pedido {{order_number}}.",
        body_html="<p>Sua avaliacao ajuda outras clientes a escolherem com confianca.</p>",
        text_template="Avalie sua experiencia com o pedido {{order_number}}.",
        variables=("customer_name", "order_number", "review_url"),
        cta_label="Avaliar pedido",
        cta_url="{{review_url}}",
    ),
    _template(
        name="Atendimento respondido",
        slug="support-ticket-replied",
        category="atendimento",
        subject="Respondemos seu atendimento {{support_ticket_id}}",
        preheader="Nossa equipe respondeu sua mensagem.",
        title="Atendimento respondido",
        intro="Ola {{customer_name}}, sua solicitacao recebeu uma resposta.",
        body_html="<p>Confira a resposta do nosso atendimento no painel da loja.</p>",
        text_template="Respondemos seu atendimento {{support_ticket_id}}.",
        variables=("customer_name", "support_ticket_id", "store_url"),
        cta_label="Ver atendimento",
        cta_url="{{store_url}}",
    ),
]


ADMIN_EMAIL_TEMPLATE_SEEDS: list[dict[str, Any]] = [
    _admin_template(
        nome="Boas-vindas",
        slug="admin-default-boas-vindas",
        evento="boas_vindas",
        assunto="Bem-vinda a {{loja_nome}}",
        title="Bem-vinda a Bia",
        preheader="Sua conta foi criada com sucesso.",
        intro="Ola {{cliente_nome}}, sua conta na {{loja_nome}} esta pronta.",
        body_html=(
            "<p style=\"margin: 0 0 14px;\">Que bom ter voce por aqui. "
            "Agora voce pode acompanhar pedidos, salvar enderecos e receber novidades escolhidas com cuidado.</p>"
            "<p style=\"margin: 0;\">Esperamos que cada detalhe da sua experiencia combine com voce.</p>"
        ),
        text_template=(
            "Ola {{cliente_nome}}, sua conta na {{loja_nome}} esta pronta. "
            "Voce ja pode acompanhar pedidos, salvar enderecos e receber novidades."
        ),
        variables=("cliente_nome", "loja_nome", "loja_url"),
        cta_label="Ver loja",
        cta_url="{{loja_url}}",
    ),
    _admin_template(
        nome="Confirmacao de pedido",
        slug="admin-default-pedido-criado",
        evento="pedido_criado",
        assunto="Recebemos seu pedido {{pedido_numero}}",
        title="Pedido recebido",
        preheader="Seu pedido foi criado na Bia Collections.",
        intro="Olá {{cliente_nome}}, recebemos seu pedido {{pedido_numero}} e já separamos os detalhes para você.",
        body_html=(
            "<p style=\"margin: 0 0 16px; text-align: center;\">"
            "Obrigada pela compra. Assim que o pagamento for confirmado, vamos preparar tudo com cuidado.</p>"
            "{{pedido_itens_html}}"
            "<table role=\"presentation\" width=\"100%\" cellspacing=\"0\" cellpadding=\"0\" border=\"0\" "
            "style=\"border-collapse: collapse; margin: 0 0 22px;\">"
            "<tr>"
            "<td style=\"padding: 12px 0; border-top: 1px solid #eee8df; font-family: Arial, Helvetica, sans-serif; "
            "font-size: 13px; line-height: 20px; color: #6f675f;\">Total do pedido</td>"
            "<td align=\"right\" style=\"padding: 12px 0; border-top: 1px solid #eee8df; font-family: Arial, Helvetica, sans-serif; "
            "font-size: 15px; line-height: 20px; color: #111111;\"><strong>{{pedido_total}}</strong></td>"
            "</tr>"
            "</table>"
            "<p style=\"margin: 0 0 18px; text-align: center;\">"
            "Você pode acompanhar cada atualização em Meus pedidos ou voltar para a loja para conferir as novidades.</p>"
            "<p style=\"margin: 0; text-align: center;\">"
            "<a href=\"{{loja_home_url}}\" style=\"color: #111111; font-weight: bold; text-decoration: underline;\">"
            "Ir para a home da Bia Collections</a></p>"
        ),
        text_template=(
            "Olá {{cliente_nome}}, recebemos seu pedido {{pedido_numero}}. "
            "Itens: {{pedido_itens_text}}. Total do pedido: {{pedido_total}}. "
            "Acompanhe em {{link_meus_pedidos}}. Confira novidades no Instagram: "
            f"{BRAND_INSTAGRAM_URL}"
        ),
        variables=(
            "cliente_nome",
            "pedido_numero",
            "pedido_total",
            "pedido_itens_html",
            "pedido_itens_text",
            "link_meus_pedidos",
            "loja_home_url",
            "loja_nome",
            "loja_url",
            "instagram_url",
        ),
        cta_label="Ver meus pedidos",
        cta_url="{{link_meus_pedidos}}",
        footer_cta_label="Ver Instagram",
        footer_cta_url=BRAND_INSTAGRAM_URL,
    ),
    _admin_template(
        nome="Pagamento aprovado",
        slug="admin-default-pagamento-aprovado",
        evento="pagamento_aprovado",
        assunto="Pagamento aprovado - Pedido {{pedido_numero}}",
        title="Pagamento aprovado",
        preheader="Seu pagamento foi confirmado.",
        intro="Olá {{cliente_nome}}, o pagamento do pedido {{pedido_numero}} foi aprovado com sucesso.",
        body_html=(
            "<p style=\"margin: 0 0 16px; text-align: center;\">"
            "Tudo certo com o pagamento. Agora vamos separar seus produtos com cuidado e avisar quando o pedido for enviado.</p>"
            "{{pedido_itens_html}}"
            "<table role=\"presentation\" width=\"100%\" cellspacing=\"0\" cellpadding=\"0\" border=\"0\" "
            "style=\"border-collapse: collapse; margin: 0 0 22px;\">"
            "<tr>"
            "<td style=\"padding: 12px 0; border-top: 1px solid #eee8df; font-family: Arial, Helvetica, sans-serif; "
            "font-size: 13px; line-height: 20px; color: #6f675f;\">Total confirmado</td>"
            "<td align=\"right\" style=\"padding: 12px 0; border-top: 1px solid #eee8df; font-family: Arial, Helvetica, sans-serif; "
            "font-size: 15px; line-height: 20px; color: #111111;\"><strong>{{pedido_total}}</strong></td>"
            "</tr>"
            "</table>"
            "<p style=\"margin: 0 0 18px; text-align: center;\">"
            "Você pode acompanhar cada atualização em Meus pedidos ou voltar para a loja para conferir as novidades.</p>"
            "<p style=\"margin: 0; text-align: center;\">"
            "<a href=\"{{loja_home_url}}\" style=\"color: #111111; font-weight: bold; text-decoration: underline;\">"
            "Ir para a home da Bia Collections</a></p>"
        ),
        text_template=(
            "Olá {{cliente_nome}}, o pagamento do pedido {{pedido_numero}} foi aprovado. "
            "Itens: {{pedido_itens_text}}. Total confirmado: {{pedido_total}}. Acompanhe em {{link_meus_pedidos}}. "
            "Confira novidades no Instagram: "
            f"{BRAND_INSTAGRAM_URL}"
        ),
        variables=(
            "cliente_nome",
            "pedido_numero",
            "pedido_total",
            "pedido_itens_html",
            "pedido_itens_text",
            "link_meus_pedidos",
            "loja_home_url",
            "loja_nome",
            "loja_url",
            "instagram_url",
        ),
        cta_label="Ver meus pedidos",
        cta_url="{{link_meus_pedidos}}",
        footer_cta_label="Ver Instagram",
        footer_cta_url=BRAND_INSTAGRAM_URL,
    ),
    _admin_template(
        nome="Pagamento recusado",
        slug="admin-default-pagamento-recusado",
        evento="pagamento_recusado",
        assunto="Pagamento não aprovado - Pedido {{pedido_numero}}",
        title="Pagamento não aprovado",
        preheader="Ainda dá tempo de concluir sua compra.",
        intro="Olá {{cliente_nome}}, não conseguimos aprovar o pagamento do pedido {{pedido_numero}}.",
        body_html=(
            "<p style=\"margin: 0 0 16px; text-align: center;\">"
            "<strong>Ainda dá tempo de concluir sua compra.</strong></p>"
            "<p style=\"margin: 0 0 16px; text-align: center;\">"
            "Seu pedido ainda pode ser concluído. Isso pode acontecer por limite, dados do pagamento, validação do banco "
            "ou uma instabilidade momentânea.</p>"
            "{{pedido_itens_html}}"
            "<table role=\"presentation\" width=\"100%\" cellspacing=\"0\" cellpadding=\"0\" border=\"0\" "
            "style=\"border-collapse: collapse; margin: 0 0 22px;\">"
            "<tr>"
            "<td style=\"padding: 12px 0; border-top: 1px solid #eee8df; font-family: Arial, Helvetica, sans-serif; "
            "font-size: 13px; line-height: 20px; color: #6f675f;\">Total do pedido</td>"
            "<td align=\"right\" style=\"padding: 12px 0; border-top: 1px solid #eee8df; font-family: Arial, Helvetica, sans-serif; "
            "font-size: 15px; line-height: 20px; color: #111111;\"><strong>{{pedido_total}}</strong></td>"
            "</tr>"
            "</table>"
            "<p style=\"margin: 0 0 18px; text-align: center;\">"
            "Para garantir seus produtos, acesse Meus pedidos, revise o pagamento e tente novamente ou escolha outra forma de pagamento.</p>"
            "<p style=\"margin: 0; text-align: center;\">"
            "<a href=\"{{loja_home_url}}\" style=\"color: #111111; font-weight: bold; text-decoration: underline;\">"
            "Ir para a home da Bia Collections</a></p>"
        ),
        text_template=(
            "Olá {{cliente_nome}}, não conseguimos aprovar o pagamento do pedido {{pedido_numero}}. "
            "Itens: {{pedido_itens_text}}. Total do pedido: {{pedido_total}}. "
            "Ainda dá tempo de concluir sua compra. Tente novamente ou escolha outra forma de pagamento em {{link_meus_pedidos}}. "
            "Confira novidades no Instagram: "
            f"{BRAND_INSTAGRAM_URL}"
        ),
        variables=(
            "cliente_nome",
            "pedido_numero",
            "pedido_total",
            "pedido_itens_html",
            "pedido_itens_text",
            "link_meus_pedidos",
            "loja_home_url",
            "loja_nome",
            "loja_url",
            "instagram_url",
        ),
        cta_label="Tentar novamente",
        cta_url="{{link_meus_pedidos}}",
        footer_cta_label="Ver Instagram",
        footer_cta_url=BRAND_INSTAGRAM_URL,
    ),
    _admin_template(
        nome="Pagamento pendente",
        slug="admin-default-pagamento-pendente",
        evento="pagamento_pendente",
        assunto="Pagamento pendente - Pedido {{pedido_numero}}",
        title="Pagamento pendente",
        preheader="Finalize o pagamento para garantir seus produtos.",
        intro="Olá {{cliente_nome}}, o pedido {{pedido_numero}} ainda está aguardando pagamento.",
        body_html=(
            "<p style=\"margin: 0 0 16px; text-align: center;\">"
            "<strong>Finalize o pagamento para garantir seus produtos.</strong></p>"
            "<p style=\"margin: 0 0 16px; text-align: center;\">"
            "Enquanto o pagamento não é confirmado, seu pedido ainda não segue para preparo. "
            "Acesse Meus pedidos para concluir agora ou escolher outra forma de pagamento.</p>"
            "{{pedido_itens_html}}"
            "<table role=\"presentation\" width=\"100%\" cellspacing=\"0\" cellpadding=\"0\" border=\"0\" "
            "style=\"border-collapse: collapse; margin: 0 0 22px;\">"
            "<tr>"
            "<td style=\"padding: 12px 0; border-top: 1px solid #eee8df; font-family: Arial, Helvetica, sans-serif; "
            "font-size: 13px; line-height: 20px; color: #6f675f;\">Total do pedido</td>"
            "<td align=\"right\" style=\"padding: 12px 0; border-top: 1px solid #eee8df; font-family: Arial, Helvetica, sans-serif; "
            "font-size: 15px; line-height: 20px; color: #111111;\"><strong>{{pedido_total}}</strong></td>"
            "</tr>"
            "</table>"
            "<p style=\"margin: 0 0 18px; text-align: center;\">"
            "Se você já concluiu o pagamento, pode ficar tranquila: avisaremos assim que a confirmação chegar.</p>"
            "<p style=\"margin: 0; text-align: center;\">"
            "<a href=\"{{loja_home_url}}\" style=\"color: #111111; font-weight: bold; text-decoration: underline;\">"
            "Ir para a home da Bia Collections</a></p>"
        ),
        text_template=(
            "Olá {{cliente_nome}}, o pedido {{pedido_numero}} ainda está aguardando pagamento. "
            "Itens: {{pedido_itens_text}}. Total do pedido: {{pedido_total}}. "
            "Finalize o pagamento para garantir seus produtos em {{link_meus_pedidos}}. "
            "Se você já pagou, avisaremos assim que a confirmação chegar. Confira novidades no Instagram: "
            f"{BRAND_INSTAGRAM_URL}"
        ),
        variables=(
            "cliente_nome",
            "pedido_numero",
            "pedido_total",
            "pedido_itens_html",
            "pedido_itens_text",
            "link_meus_pedidos",
            "loja_home_url",
            "loja_nome",
            "loja_url",
            "instagram_url",
        ),
        cta_label="Finalizar pagamento",
        cta_url="{{link_meus_pedidos}}",
        footer_cta_label="Ver Instagram",
        footer_cta_url=BRAND_INSTAGRAM_URL,
    ),
    _admin_template(
        nome="Pagamento expirado",
        slug="admin-default-pagamento-expirado",
        evento="pagamento_expirado",
        assunto="Seu pedido {{pedido_numero}} expirou — seus favoritos ainda esperam por você",
        title="Pagamento expirado",
        preheader="O prazo terminou, mas você pode escolher seus favoritos novamente.",
        intro="Olá {{cliente_nome}}, o prazo para pagar o pedido {{pedido_numero}} terminou.",
        body_html=(
            "<p style=\"margin: 0 0 16px; text-align: center;\">"
            "<strong>Uma nova chance para escolher seus favoritos.</strong></p>"
            "<p style=\"margin: 0 0 16px; text-align: center;\">"
            "Como o pagamento não foi concluído a tempo, o pedido foi encerrado e não seguirá para preparo.</p>"
            "{{pedido_itens_html}}"
            "<table role=\"presentation\" width=\"100%\" cellspacing=\"0\" cellpadding=\"0\" border=\"0\" "
            "style=\"border-collapse: collapse; margin: 0 0 22px;\">"
            "<tr>"
            "<td style=\"padding: 12px 0; border-top: 1px solid #eee8df; font-family: Arial, Helvetica, sans-serif; "
            "font-size: 13px; line-height: 20px; color: #6f675f;\">Valor do pedido expirado</td>"
            "<td align=\"right\" style=\"padding: 12px 0; border-top: 1px solid #eee8df; font-family: Arial, Helvetica, sans-serif; "
            "font-size: 15px; line-height: 20px; color: #111111;\"><strong>{{pedido_total}}</strong></td>"
            "</tr>"
            "</table>"
            "<p style=\"margin: 0 0 18px; text-align: center;\">"
            "Se você ainda amou essas peças, volte à loja e monte seu pedido novamente. "
            "A disponibilidade pode mudar, então aproveite para garantir seus favoritos.</p>"
            "<p style=\"margin: 0; text-align: center;\">"
            "<a href=\"{{link_meus_pedidos}}\" style=\"color: #111111; font-weight: bold; text-decoration: underline;\">"
            "Consultar meus pedidos</a></p>"
        ),
        text_template=(
            "Olá {{cliente_nome}}, o prazo para pagar o pedido {{pedido_numero}} terminou. "
            "Itens: {{pedido_itens_text}}. Valor do pedido expirado: {{pedido_total}}. "
            "Você pode montar uma nova compra em {{loja_home_url}}, conforme a disponibilidade dos produtos. "
            "Consulte seus pedidos em {{link_meus_pedidos}}. Confira novidades no Instagram: "
            f"{BRAND_INSTAGRAM_URL}"
        ),
        variables=(
            "cliente_nome",
            "pedido_numero",
            "pedido_total",
            "pedido_itens_html",
            "pedido_itens_text",
            "link_meus_pedidos",
            "loja_home_url",
            "loja_nome",
            "loja_url",
            "instagram_url",
        ),
        cta_label="Comprar novamente",
        cta_url="{{loja_home_url}}",
        footer_cta_label="Ver Instagram",
        footer_cta_url=BRAND_INSTAGRAM_URL,
    ),
    _admin_template(
        nome="Pedido em preparacao",
        slug="admin-default-pedido-preparando",
        evento="pedido_preparando",
        assunto="Seu pedido {{pedido_numero}} esta em preparacao",
        title="Pedido em preparacao",
        preheader="Estamos separando seus produtos.",
        intro="Ola {{cliente_nome}}, seu pedido {{pedido_numero}} entrou em preparacao.",
        body_html=(
            "<p style=\"margin: 0 0 14px;\">A equipe da Bia Collections ja esta cuidando dos detalhes.</p>"
            "<p style=\"margin: 0;\">Voce recebera um novo aviso quando o pedido for enviado.</p>"
        ),
        text_template=(
            "Ola {{cliente_nome}}, seu pedido {{pedido_numero}} entrou em preparacao. "
            "Avisaremos quando ele for enviado."
        ),
        variables=("cliente_nome", "pedido_numero", "pedido_total", "loja_nome", "loja_url"),
    ),
    _admin_template(
        nome="Pedido enviado",
        slug="admin-default-pedido-enviado",
        evento="pedido_enviado",
        assunto="Seu pedido {{pedido_numero}} foi enviado",
        title="Pedido enviado",
        preheader="Seu pedido saiu para transporte.",
        intro="Ola {{cliente_nome}}, seu pedido {{pedido_numero}} saiu para entrega.",
        body_html=(
            "<p style=\"margin: 0 0 14px;\">Codigo de rastreio: <strong>{{codigo_rastreio}}</strong></p>"
            "<p style=\"margin: 0;\">Obrigada por comprar com a {{loja_nome}}.</p>"
        ),
        text_template=(
            "Ola {{cliente_nome}}, seu pedido {{pedido_numero}} saiu para entrega. "
            "Codigo de rastreio: {{codigo_rastreio}}. Obrigada por comprar com a {{loja_nome}}."
        ),
        variables=("cliente_nome", "pedido_numero", "codigo_rastreio", "loja_nome", "loja_url"),
    ),
    _admin_template(
        nome="Pedido entregue",
        slug="admin-default-pedido-entregue",
        evento="pedido_entregue",
        assunto="Pedido {{pedido_numero}} entregue",
        title="Pedido entregue",
        preheader="Esperamos que voce ame seus produtos.",
        intro="Ola {{cliente_nome}}, seu pedido {{pedido_numero}} foi entregue.",
        body_html=(
            "<p style=\"margin: 0 0 14px;\">Esperamos que cada detalhe tenha chegado perfeito.</p>"
            "<p style=\"margin: 0;\">Obrigada por escolher a Bia Collections.</p>"
        ),
        text_template=(
            "Ola {{cliente_nome}}, seu pedido {{pedido_numero}} foi entregue. "
            "Obrigada por escolher a {{loja_nome}}."
        ),
        variables=("cliente_nome", "pedido_numero", "loja_nome", "loja_url"),
    ),
    _admin_template(
        nome="Pedido cancelado",
        slug="admin-default-pedido-cancelado",
        evento="pedido_cancelado",
        assunto="Pedido {{pedido_numero}} cancelado",
        title="Pedido cancelado",
        preheader="Seu pedido foi cancelado.",
        intro="Ola {{cliente_nome}}, o pedido {{pedido_numero}} foi cancelado.",
        body_html=(
            "<p style=\"margin: 0 0 14px;\">Se o pagamento ja tiver sido feito, nossa equipe acompanhara o proximo passo.</p>"
            "<p style=\"margin: 0;\">Qualquer duvida, fale com nosso atendimento.</p>"
        ),
        text_template=(
            "Ola {{cliente_nome}}, o pedido {{pedido_numero}} foi cancelado. "
            "Se o pagamento ja tiver sido feito, nossa equipe acompanhara o proximo passo."
        ),
        variables=("cliente_nome", "pedido_numero", "pedido_total", "loja_nome", "loja_url"),
    ),
    _admin_template(
        nome="Reembolso aprovado",
        slug="admin-default-reembolso-aprovado",
        evento="reembolso_aprovado",
        assunto="Reembolso aprovado - Pedido {{pedido_numero}}",
        title="Reembolso aprovado",
        preheader="Sua solicitacao de reembolso foi aprovada.",
        intro="Ola {{cliente_nome}}, aprovamos o reembolso do pedido {{pedido_numero}}.",
        body_html=(
            "<p style=\"margin: 0 0 14px;\">O valor aprovado e <strong>{{valor_reembolso}}</strong>.</p>"
            "<p style=\"margin: 0;\">O prazo de processamento pode variar conforme a forma de pagamento.</p>"
        ),
        text_template=(
            "Ola {{cliente_nome}}, aprovamos o reembolso do pedido {{pedido_numero}}. "
            "Valor aprovado: {{valor_reembolso}}."
        ),
        variables=("cliente_nome", "pedido_numero", "valor_reembolso", "prazo_reembolso", "loja_nome", "loja_url"),
    ),
    _admin_template(
        nome="Reembolso processado",
        slug="admin-default-reembolso-processado",
        evento="reembolso_processado",
        assunto="Reembolso processado - Pedido {{pedido_numero}}",
        title="Reembolso processado",
        preheader="Seu reembolso foi processado.",
        intro="Ola {{cliente_nome}}, o reembolso do pedido {{pedido_numero}} foi processado.",
        body_html=(
            "<p style=\"margin: 0 0 14px;\">Valor processado: <strong>{{valor_reembolso}}</strong>.</p>"
            "<p style=\"margin: 0;\">A visualizacao na fatura ou conta segue o prazo da instituicao financeira.</p>"
        ),
        text_template=(
            "Ola {{cliente_nome}}, o reembolso do pedido {{pedido_numero}} foi processado. "
            "Valor: {{valor_reembolso}}."
        ),
        variables=("cliente_nome", "pedido_numero", "valor_reembolso", "prazo_reembolso", "loja_nome", "loja_url"),
    ),
    _admin_template(
        nome="Nota fiscal e recibo",
        slug="admin-default-nota-fiscal-recibo",
        evento="nota_fiscal_recibo",
        assunto="Nota fiscal do pedido {{pedido_numero}}",
        title="Documento do pedido",
        preheader="Sua nota fiscal ou recibo ja esta disponivel.",
        intro="Ola {{cliente_nome}}, o documento do pedido {{pedido_numero}} ja esta disponivel.",
        body_html=(
            "<p style=\"margin: 0 0 14px;\">Voce pode acessar a nota fiscal ou recibo pelos links do pedido.</p>"
            "<p style=\"margin: 0;\">Guarde este email para consultar os dados da compra quando precisar.</p>"
        ),
        text_template=(
            "Ola {{cliente_nome}}, a nota fiscal ou recibo do pedido {{pedido_numero}} esta disponivel. "
            "Nota fiscal: {{link_nota_fiscal}} Recibo: {{link_recibo}}."
        ),
        variables=("cliente_nome", "pedido_numero", "link_nota_fiscal", "link_recibo", "loja_nome", "loja_url"),
        cta_label="Ver pedido",
        cta_url="{{loja_url}}/conta/pedidos",
    ),
    _admin_template(
        nome="Troca ou devolucao recebida",
        slug="admin-default-troca-devolucao-recebida",
        evento="troca_devolucao_recebida",
        assunto="Recebemos sua solicitacao - Pedido {{pedido_numero}}",
        title="Solicitacao recebida",
        preheader="Sua troca ou devolucao entrou em analise.",
        intro="Ola {{cliente_nome}}, recebemos sua solicitacao referente ao pedido {{pedido_numero}}.",
        body_html=(
            "<p style=\"margin: 0 0 14px;\">Protocolo: <strong>{{protocolo_troca}}</strong>.</p>"
            "<p style=\"margin: 0;\">Nossa equipe vai analisar as informacoes e retornar com os proximos passos.</p>"
        ),
        text_template=(
            "Ola {{cliente_nome}}, recebemos sua solicitacao referente ao pedido {{pedido_numero}}. "
            "Protocolo: {{protocolo_troca}}."
        ),
        variables=("cliente_nome", "pedido_numero", "protocolo_troca", "loja_nome", "loja_url"),
    ),
    _admin_template(
        nome="Troca ou devolucao aprovada",
        slug="admin-default-troca-devolucao-aprovada",
        evento="troca_devolucao_aprovada",
        assunto="Solicitacao aprovada - Pedido {{pedido_numero}}",
        title="Solicitacao aprovada",
        preheader="Sua troca ou devolucao foi aprovada.",
        intro="Ola {{cliente_nome}}, aprovamos sua solicitacao referente ao pedido {{pedido_numero}}.",
        body_html=(
            "<p style=\"margin: 0 0 14px;\">Protocolo: <strong>{{protocolo_troca}}</strong>.</p>"
            "<p style=\"margin: 0;\">Siga as orientacoes enviadas pela nossa equipe para concluir o processo.</p>"
        ),
        text_template=(
            "Ola {{cliente_nome}}, aprovamos sua solicitacao referente ao pedido {{pedido_numero}}. "
            "Protocolo: {{protocolo_troca}}."
        ),
        variables=("cliente_nome", "pedido_numero", "protocolo_troca", "loja_nome", "loja_url"),
    ),
    _admin_template(
        nome="Troca ou devolucao recusada",
        slug="admin-default-troca-devolucao-recusada",
        evento="troca_devolucao_recusada",
        assunto="Atualizacao da solicitacao - Pedido {{pedido_numero}}",
        title="Solicitacao analisada",
        preheader="Temos uma atualizacao sobre sua troca ou devolucao.",
        intro="Ola {{cliente_nome}}, analisamos sua solicitacao referente ao pedido {{pedido_numero}}.",
        body_html=(
            "<p style=\"margin: 0 0 14px;\">No momento, nao foi possivel aprovar a solicitacao.</p>"
            "<p style=\"margin: 0;\">Motivo: <strong>{{motivo_recusa}}</strong>.</p>"
        ),
        text_template=(
            "Ola {{cliente_nome}}, analisamos sua solicitacao referente ao pedido {{pedido_numero}}. "
            "No momento, nao foi possivel aprovar. Motivo: {{motivo_recusa}}."
        ),
        variables=("cliente_nome", "pedido_numero", "protocolo_troca", "motivo_recusa", "loja_nome", "loja_url"),
    ),
    _admin_template(
        nome="Recuperacao de senha",
        slug="admin-default-recuperacao-senha",
        evento="recuperacao_senha",
        assunto="Redefinicao de senha - {{loja_nome}}",
        title="Redefinicao de senha",
        preheader="Use o codigo enviado para criar uma nova senha.",
        intro="Ola {{cliente_nome}}, recebemos uma solicitacao para redefinir sua senha.",
        body_html=(
            "<p style=\"margin: 0 0 14px; text-align: center;\">Use o codigo abaixo para continuar:</p>"
            "<p style=\"margin: 0 0 16px; text-align: center; font-size: 24px; letter-spacing: 6px; color: #111111;\">"
            "<strong>{{codigo}}</strong></p>"
            "<p style=\"margin: 0; text-align: center;\">Este codigo expira em {{minutos_expiracao}} minutos.</p>"
        ),
        text_template=(
            "Ola {{cliente_nome}}, recebemos uma solicitacao para redefinir sua senha. "
            "Use o codigo {{codigo}}. Este codigo expira em {{minutos_expiracao}} minutos."
        ),
        variables=("cliente_nome", "codigo", "minutos_expiracao", "loja_nome", "loja_url", "link_recuperacao"),
    ),
    _admin_template(
        nome="Código de acesso",
        slug="admin-default-codigo-acesso",
        evento="codigo_acesso",
        assunto="Seu código de acesso - {{loja_nome}}",
        title="Seu código de acesso",
        preheader="Use este código para concluir seu acesso.",
        intro="Use o código abaixo para concluir seu acesso com segurança.",
        body_html=(
            "<p style=\"margin: 0 0 16px; text-align: center; font-size: 24px; letter-spacing: 6px; color: #111111;\">"
            "<strong>{{codigo}}</strong></p>"
            "<p style=\"margin: 0 0 12px; text-align: center;\">Este código expira em {{minutos_expiracao}} minutos.</p>"
            "<p style=\"margin: 0 0 18px; text-align: center;\">Por segurança, não compartilhe este código com ninguém.</p>"
            "<p style=\"margin: 0; text-align: center;\">Confira nossos cupons no Instagram da loja.</p>"
        ),
        text_template=(
            "Seu código de acesso é: {{codigo}}. Este código expira em {{minutos_expiracao}} minutos. "
            "Confira nossos cupons no Instagram da loja: "
            f"{BRAND_INSTAGRAM_URL}"
        ),
        variables=("codigo", "minutos_expiracao", "loja_nome", "loja_url"),
        cta_label="Ver Instagram",
        cta_url=BRAND_INSTAGRAM_URL,
    ),
    _admin_template(
        nome="Senha alterada",
        slug="admin-default-senha-alterada",
        evento="senha_alterada",
        assunto="Senha alterada - {{loja_nome}}",
        title="Senha alterada",
        preheader="Confirmacao de alteracao de senha.",
        intro="Ola {{cliente_nome}}, sua senha foi alterada com sucesso.",
        body_html=(
            "<p style=\"margin: 0 0 14px;\">Se foi voce, nenhuma acao e necessaria.</p>"
            "<p style=\"margin: 0;\">Se nao reconhece esta alteracao, fale com nosso atendimento imediatamente.</p>"
        ),
        text_template=(
            "Ola {{cliente_nome}}, sua senha foi alterada com sucesso. "
            "Se nao reconhece esta alteracao, fale com nosso atendimento imediatamente."
        ),
        variables=("cliente_nome", "loja_nome", "loja_url"),
    ),
    _admin_template(
        nome="Dados sensiveis alterados",
        slug="admin-default-dados-sensiveis-alterados",
        evento="dados_sensiveis_alterados",
        assunto="Dados da sua conta foram atualizados - {{loja_nome}}",
        title="Dados atualizados",
        preheader="Uma informacao sensivel da sua conta foi alterada.",
        intro="Ola {{cliente_nome}}, identificamos uma alteracao em dados importantes da sua conta.",
        body_html=(
            "<p style=\"margin: 0 0 14px;\">Tipo de alteracao: <strong>{{tipo_alteracao}}</strong>.</p>"
            "<p style=\"margin: 0;\">Se voce nao fez essa alteracao, fale com nosso atendimento agora.</p>"
        ),
        text_template=(
            "Ola {{cliente_nome}}, uma informacao sensivel da sua conta foi alterada. "
            "Tipo de alteracao: {{tipo_alteracao}}. Se nao foi voce, fale com nosso atendimento."
        ),
        variables=("cliente_nome", "tipo_alteracao", "loja_nome", "loja_url"),
    ),
    _admin_template(
        nome="Produto voltou ao estoque",
        slug="admin-default-produto-voltou-estoque",
        evento="produto_voltou_estoque",
        assunto="{{produto_nome}} voltou ao estoque",
        title="Voltou ao estoque",
        preheader="O produto que voce queria esta disponivel novamente.",
        intro="Ola {{cliente_nome}}, {{produto_nome}} voltou para a Bia Collections.",
        body_html=(
            "<p style=\"margin: 0 0 14px;\">Ele ja esta disponivel na loja, mas pode acabar novamente.</p>"
            "<p style=\"margin: 0;\">Passe para garantir o seu enquanto ainda tem estoque.</p>"
        ),
        text_template=(
            "Ola {{cliente_nome}}, {{produto_nome}} voltou ao estoque na {{loja_nome}}. "
            "Acesse: {{produto_url}}."
        ),
        variables=("cliente_nome", "produto_nome", "produto_url", "loja_nome", "loja_url"),
        cta_label="Ver produto",
        cta_url="{{produto_url}}",
    ),
    _admin_template(
        nome="Carrinho abandonado",
        slug="admin-default-carrinho-abandonado",
        evento="carrinho_abandonado",
        assunto="Seu carrinho ainda esta esperando por voce",
        title="Seu carrinho esta salvo",
        preheader="Alguns favoritos ficaram no carrinho.",
        intro="Ola {{cliente_nome}}, seus itens continuam reservados no carrinho.",
        body_html=(
            "<p style=\"margin: 0 0 14px;\">Finalize sua compra antes que algum produto acabe.</p>"
            "<p style=\"margin: 0;\">Se tiver um cupom, use no checkout: <strong>{{cupom_codigo}}</strong>.</p>"
        ),
        text_template=(
            "Ola {{cliente_nome}}, seus itens continuam no carrinho da {{loja_nome}}. "
            "Finalize sua compra: {{carrinho_url}}."
        ),
        variables=("cliente_nome", "carrinho_url", "cupom_codigo", "loja_nome", "loja_url"),
        cta_label="Voltar ao carrinho",
        cta_url="{{carrinho_url}}",
    ),
    _admin_template(
        nome="Cupom disponivel",
        slug="admin-default-cupom-disponivel",
        evento="cupom_disponivel",
        assunto="Seu cupom {{cupom_codigo}} esta disponivel",
        title="Cupom disponivel",
        preheader="Seu cupom ja esta liberado.",
        intro="Ola {{cliente_nome}}, voce tem um cupom para usar na {{loja_nome}}.",
        body_html=(
            "<p style=\"margin: 0 0 14px; text-align: center;\">Codigo do cupom: "
            "<strong>{{cupom_codigo}}</strong></p>"
            "<p style=\"margin: 0; text-align: center;\">Aproveite enquanto ele estiver disponivel.</p>"
        ),
        text_template=(
            "Ola {{cliente_nome}}, voce tem um cupom para usar na {{loja_nome}}. "
            "Codigo do cupom: {{cupom_codigo}}. Aproveite enquanto ele estiver disponivel."
        ),
        variables=("cliente_nome", "cupom_codigo", "cupom_descricao", "cupom_valor", "cupom_validade", "loja_nome", "loja_url"),
    ),
    _admin_template(
        nome="Pedido aguardando avaliacao",
        slug="admin-default-avaliacao-pedido",
        evento="avaliacao_pedido",
        assunto="Conte como foi sua experiencia",
        title="Como foi sua experiencia?",
        preheader="Sua opiniao ajuda outras clientes.",
        intro="Ola {{cliente_nome}}, queremos saber o que voce achou do pedido {{pedido_numero}}.",
        body_html=(
            "<p style=\"margin: 0 0 14px;\">Sua avaliacao ajuda outras clientes a escolherem com mais confianca.</p>"
            "<p style=\"margin: 0;\">Leva menos de um minuto e faz diferenca para a Bia Collections.</p>"
        ),
        text_template=(
            "Ola {{cliente_nome}}, queremos saber o que voce achou do pedido {{pedido_numero}}. "
            "Avalie aqui: {{link_avaliacao}}."
        ),
        variables=("cliente_nome", "pedido_numero", "link_avaliacao", "loja_nome", "loja_url"),
        cta_label="Avaliar pedido",
        cta_url="{{link_avaliacao}}",
    ),
    _admin_template(
        nome="Interno - novo pedido",
        slug="admin-default-interno-novo-pedido",
        evento="interno_novo_pedido",
        assunto="Novo pedido recebido - {{pedido_numero}}",
        title="Novo pedido recebido",
        preheader="Um novo pedido entrou na loja.",
        intro="Pedido {{pedido_numero}} recebido no painel da {{loja_nome}}.",
        body_html=(
            "<p style=\"margin: 0 0 14px;\">Cliente: <strong>{{cliente_nome}}</strong> ({{cliente_email}}).</p>"
            "<p style=\"margin: 0;\">Total: <strong>{{pedido_total}}</strong>.</p>"
        ),
        text_template=(
            "Novo pedido recebido: {{pedido_numero}}. Cliente: {{cliente_nome}} ({{cliente_email}}). "
            "Total: {{pedido_total}}. Abrir: {{link_pedido_admin}}."
        ),
        variables=("pedido_numero", "pedido_total", "cliente_nome", "cliente_email", "link_pedido_admin", "loja_nome"),
        cta_label="Abrir pedido",
        cta_url="{{link_pedido_admin}}",
    ),
    _admin_template(
        nome="Interno - pagamento confirmado",
        slug="admin-default-interno-pagamento-confirmado",
        evento="interno_pagamento_confirmado",
        assunto="Pagamento confirmado - {{pedido_numero}}",
        title="Pagamento confirmado",
        preheader="Um pedido pago precisa de preparacao.",
        intro="O pagamento do pedido {{pedido_numero}} foi confirmado.",
        body_html=(
            "<p style=\"margin: 0 0 14px;\">Cliente: <strong>{{cliente_nome}}</strong> ({{cliente_email}}).</p>"
            "<p style=\"margin: 0;\">Forma de pagamento: <strong>{{forma_pagamento}}</strong>. Total: <strong>{{pedido_total}}</strong>.</p>"
        ),
        text_template=(
            "Pagamento confirmado para o pedido {{pedido_numero}}. Cliente: {{cliente_nome}} ({{cliente_email}}). "
            "Forma: {{forma_pagamento}}. Total: {{pedido_total}}."
        ),
        variables=("pedido_numero", "pedido_total", "cliente_nome", "cliente_email", "forma_pagamento", "link_pedido_admin", "loja_nome"),
        cta_label="Preparar pedido",
        cta_url="{{link_pedido_admin}}",
    ),
    _admin_template(
        nome="Interno - estoque baixo",
        slug="admin-default-interno-estoque-baixo",
        evento="interno_estoque_baixo",
        assunto="Estoque baixo - {{produto_nome}}",
        title="Estoque baixo",
        preheader="Um produto precisa de atencao no estoque.",
        intro="{{produto_nome}} esta com estoque baixo.",
        body_html=(
            "<p style=\"margin: 0 0 14px;\">Quantidade atual: <strong>{{estoque_atual}}</strong>.</p>"
            "<p style=\"margin: 0;\">Estoque minimo configurado: <strong>{{estoque_minimo}}</strong>.</p>"
        ),
        text_template=(
            "Estoque baixo para {{produto_nome}}. Quantidade atual: {{estoque_atual}}. "
            "Estoque minimo: {{estoque_minimo}}."
        ),
        variables=("produto_nome", "produto_id", "estoque_atual", "estoque_minimo", "link_produto_admin", "loja_nome"),
        cta_label="Ver produto",
        cta_url="{{link_produto_admin}}",
    ),
    _admin_template(
        nome="Interno - troca ou devolucao",
        slug="admin-default-interno-troca-devolucao",
        evento="interno_troca_devolucao",
        assunto="Nova solicitacao de troca/devolucao - {{pedido_numero}}",
        title="Nova solicitacao",
        preheader="Uma cliente abriu uma solicitacao de pos-venda.",
        intro="A solicitacao {{protocolo_troca}} precisa de analise.",
        body_html=(
            "<p style=\"margin: 0 0 14px;\">Pedido: <strong>{{pedido_numero}}</strong>.</p>"
            "<p style=\"margin: 0;\">Cliente: <strong>{{cliente_nome}}</strong> ({{cliente_email}}).</p>"
        ),
        text_template=(
            "Nova solicitacao de troca/devolucao {{protocolo_troca}} para o pedido {{pedido_numero}}. "
            "Cliente: {{cliente_nome}} ({{cliente_email}})."
        ),
        variables=("protocolo_troca", "pedido_numero", "cliente_nome", "cliente_email", "link_solicitacao_admin", "loja_nome"),
        cta_label="Analisar",
        cta_url="{{link_solicitacao_admin}}",
    ),
    _admin_template(
        nome="Interno - falha operacional",
        slug="admin-default-interno-falha-operacional",
        evento="interno_falha_operacional",
        assunto="Falha em pagamento ou envio - {{pedido_numero}}",
        title="Falha operacional",
        preheader="Um fluxo da loja precisa de verificacao.",
        intro="Identificamos uma falha no pedido {{pedido_numero}}.",
        body_html=(
            "<p style=\"margin: 0 0 14px;\">Tipo de falha: <strong>{{tipo_falha}}</strong>.</p>"
            "<p style=\"margin: 0;\">Detalhes: {{detalhes_falha}}</p>"
        ),
        text_template=(
            "Falha operacional no pedido {{pedido_numero}}. Tipo: {{tipo_falha}}. "
            "Detalhes: {{detalhes_falha}}."
        ),
        variables=("pedido_numero", "tipo_falha", "detalhes_falha", "link_pedido_admin", "loja_nome"),
        cta_label="Verificar pedido",
        cta_url="{{link_pedido_admin}}",
    ),
    _admin_template(
        nome="Email manual",
        slug="admin-default-manual",
        evento="manual",
        assunto="Mensagem da {{loja_nome}}",
        status="rascunho",
        title="Ola {{cliente_nome}}",
        preheader="Uma mensagem especial da Bia Collections.",
        intro="Preparamos uma mensagem especial para voce.",
        body_html=(
            "<p style=\"margin: 0 0 14px;\">Escreva aqui a mensagem que deseja enviar manualmente.</p>"
            "<p style=\"margin: 0;\">{{loja_nome}}</p>"
        ),
        text_template="Ola {{cliente_nome}}. Escreva aqui a mensagem que deseja enviar manualmente. {{loja_nome}}",
        variables=("cliente_nome", "loja_nome", "loja_url"),
    ),
]


AUTOMATION_SEEDS = [
    ("user_registered", "user-registered", 0),
    ("email_confirmation", "email-confirmation", 0),
    ("resend_email_confirmation", "email-confirmation", 0),
    ("password_reset", "password-reset", 0),
    ("password_changed", "password-changed", 0),
    ("two_factor_code", "two-factor-code", 0),
    ("order_created", "order-created", 0),
    ("payment_approved", "payment-approved", 0),
    ("payment_refused", "payment-refused", 0),
    ("payment_pending", "payment-pending", 0),
    ("payment_expired", "payment-expired", 0),
    ("pix_generated", "pix-generated", 0),
    ("order_preparing", "order-preparing", 0),
    ("order_shipped", "order-shipped", 0),
    ("tracking_code_available", "tracking-code-available", 0),
    ("order_delivered", "order-delivered", 0),
    ("order_cancelled", "order-cancelled", 0),
    ("abandoned_cart_1h", "abandoned-cart-1h", 60),
    ("abandoned_cart_24h", "abandoned-cart-1h", 1440),
    ("abandoned_cart_3d", "abandoned-cart-1h", 4320),
    ("product_back_in_stock", "product-back-in-stock", 0),
    ("coupon_expiring", "coupon-expiring", 0),
    ("review_request", "review-request", 0),
    ("support_ticket_replied", "support-ticket-replied", 0),
]


def seed_email_automation(db: Session | None = None) -> None:
    owns_session = db is None
    session = db or SessionLocal()
    try:
        templates_by_slug: dict[str, EmailTemplate] = {}
        for data in EMAIL_TEMPLATE_SEEDS:
            template = session.query(EmailTemplate).filter(EmailTemplate.slug == data["slug"]).first()
            if not template:
                template = EmailTemplate(**data)
                session.add(template)
                session.flush()
            else:
                _refresh_access_code_template_if_old(template, data)
                _refresh_order_created_template_if_old(template, data)
                _refresh_payment_approved_template_if_old(template, data)
                _refresh_payment_refused_template_if_old(template, data)
                _refresh_payment_pending_template_if_old(template, data)
                _refresh_payment_expired_template_if_old(template, data)
                _refresh_order_summary_template_if_missing(template, data)
                _refresh_premium_template_if_seeded(template, data)
                _review_existing_template_copy(template)
            templates_by_slug[data["slug"]] = template

        for data in ADMIN_EMAIL_TEMPLATE_SEEDS:
            template = session.query(EmailTemplate).filter(EmailTemplate.slug == data["slug"]).first()
            if template:
                _refresh_access_code_template_if_old(template, data)
                _refresh_order_created_template_if_old(template, data)
                _refresh_payment_approved_template_if_old(template, data)
                _refresh_payment_refused_template_if_old(template, data)
                _refresh_payment_pending_template_if_old(template, data)
                _refresh_payment_expired_template_if_old(template, data)
                _refresh_order_summary_template_if_missing(template, data)
                _refresh_premium_template_if_seeded(template, data)
                _fill_missing_admin_template_fields(template, data)
                _review_existing_template_copy(template)
                continue

            exists_for_event = (
                session.query(EmailTemplate)
                .filter(EmailTemplate.evento == data["evento"])
                .first()
            )
            if not exists_for_event:
                session.add(EmailTemplate(**data))

        for event_key, template_slug, delay_minutes in AUTOMATION_SEEDS:
            template = templates_by_slug.get(template_slug)
            if not template:
                continue
            exists = (
                session.query(EmailAutomation)
                .filter(
                    EmailAutomation.event_key == event_key,
                    EmailAutomation.email_template_id == template.id,
                    EmailAutomation.channel == "email",
                )
                .first()
            )
            if not exists:
                session.add(
                    EmailAutomation(
                        event_key=event_key,
                        email_template_id=template.id,
                        channel="email",
                        delay_minutes=delay_minutes,
                        is_active=True,
                    )
                )
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        if owns_session:
            session.close()

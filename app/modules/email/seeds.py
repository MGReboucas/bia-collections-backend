from __future__ import annotations

import json
from typing import Any

from sqlalchemy.orm import Session

from app.core.database import SessionLocal
from app.modules.email.models import EmailAutomation, EmailTemplate
from app.modules.email.templates import brand_email_html


def _schema(*variables: str) -> str:
    return json.dumps({"variables": list(variables)}, ensure_ascii=False)


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
) -> dict[str, Any]:
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
            body_html=body_html,
            cta_label=cta_label,
            cta_url=cta_url,
        ),
        "text_template": text_template,
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
) -> dict[str, Any]:
    html = brand_email_html(
        title=title,
        preheader=preheader,
        intro=intro,
        body_html=body_html,
        cta_label=cta_label,
        cta_url=cta_url,
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
        "text_template": text_template,
        "variables_schema": _schema(*variables),
        "is_active": status == "ativo",
    }


def _fill_missing_admin_template_fields(template: EmailTemplate, data: dict[str, Any]) -> None:
    for key, value in data.items():
        current = getattr(template, key, None)
        if current is None or current == "":
            setattr(template, key, value)


EMAIL_TEMPLATE_SEEDS: list[dict[str, Any]] = [
    _template(
        name="Boas-vindas",
        slug="user-registered",
        category="conta",
        subject="Bem-vinda a Bia Collections",
        preheader="Sua conta foi criada com sucesso.",
        title="Bem-vinda a Bia",
        intro="Ola {{customer_name}}, sua conta ja esta pronta.",
        body_html="<p>Que bom ter voce por aqui. A partir de agora, voce pode acompanhar pedidos, salvar enderecos e receber novidades da Bia Collections.</p>",
        text_template="Ola {{customer_name}}, sua conta na Bia Collections foi criada com sucesso.",
        variables=("customer_name", "store_url"),
        cta_label="Ver loja",
        cta_url="{{store_url}}",
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
        name="Codigo de acesso",
        slug="two-factor-code",
        category="seguranca",
        subject="Seu codigo de acesso - Bia Collections",
        preheader="Use este codigo para concluir seu acesso.",
        title="Seu codigo de acesso",
        intro="Use o codigo abaixo para concluir seu acesso com seguranca.",
        body_html="<p style=\"text-align:center; font-size:26px; letter-spacing:8px;\"><strong>{{code}}</strong></p><p style=\"text-align:center;\">Este codigo expira em {{expires_in_minutes}} minutos.</p>",
        text_template="Seu codigo de acesso e: {{code}}. Ele expira em {{expires_in_minutes}} minutos.",
        variables=("code", "expires_in_minutes"),
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
        preheader="Seu pedido foi criado e esta aguardando pagamento.",
        title="Pedido recebido",
        intro="Ola {{customer_name}}, recebemos seu pedido {{order_number}}.",
        body_html="<p>Total do pedido: <strong>{{order_total}}</strong>.</p><p>Assim que o pagamento for confirmado, vamos preparar tudo com cuidado.</p>",
        text_template="Pedido {{order_number}} recebido. Total: {{order_total}}.",
        variables=("customer_name", "order_number", "order_total", "store_url"),
        cta_label="Acompanhar pedido",
        cta_url="{{store_url}}/meus-pedidos",
    ),
    _template(
        name="Pagamento aprovado",
        slug="payment-approved",
        category="pagamentos",
        subject="Pagamento aprovado - Pedido {{order_number}}",
        preheader="Seu pagamento foi confirmado.",
        title="Pagamento aprovado",
        intro="Ola {{customer_name}}, o pagamento do pedido {{order_number}} foi aprovado.",
        body_html="<p>Agora vamos separar seus produtos e avisar quando o pedido avancar.</p>",
        text_template="Pagamento aprovado para o pedido {{order_number}}.",
        variables=("customer_name", "order_number", "store_url"),
        cta_label="Ver pedido",
        cta_url="{{store_url}}/meus-pedidos",
    ),
    _template(
        name="Pagamento recusado",
        slug="payment-refused",
        category="pagamentos",
        subject="Pagamento nao aprovado - Pedido {{order_number}}",
        preheader="Nao conseguimos confirmar seu pagamento.",
        title="Pagamento nao aprovado",
        intro="Ola {{customer_name}}, nao conseguimos confirmar o pagamento do pedido {{order_number}}.",
        body_html="<p>Voce pode tentar novamente pelo painel de pedidos ou escolher outra forma de pagamento.</p>",
        text_template="Pagamento nao aprovado para o pedido {{order_number}}.",
        variables=("customer_name", "order_number", "store_url"),
        cta_label="Tentar novamente",
        cta_url="{{store_url}}/meus-pedidos",
    ),
    _template(
        name="Pagamento pendente",
        slug="payment-pending",
        category="pagamentos",
        subject="Pagamento pendente - Pedido {{order_number}}",
        preheader="Seu pagamento ainda esta em analise.",
        title="Pagamento pendente",
        intro="Ola {{customer_name}}, seu pedido {{order_number}} ainda esta aguardando confirmacao.",
        body_html="<p>Assim que o pagamento for confirmado, voce recebera um novo aviso.</p>",
        text_template="Pagamento pendente para o pedido {{order_number}}.",
        variables=("customer_name", "order_number"),
    ),
    _template(
        name="Pagamento expirado",
        slug="payment-expired",
        category="pagamentos",
        subject="Pagamento expirado - Pedido {{order_number}}",
        preheader="O prazo de pagamento terminou.",
        title="Pagamento expirado",
        intro="O prazo de pagamento do pedido {{order_number}} terminou.",
        body_html="<p>Se ainda quiser os produtos, faca uma nova compra na loja.</p>",
        text_template="O pagamento do pedido {{order_number}} expirou.",
        variables=("order_number", "store_url"),
        cta_label="Voltar para loja",
        cta_url="{{store_url}}",
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
        nome="Confirmacao de pedido",
        slug="admin-default-pedido-criado",
        evento="pedido_criado",
        assunto="Recebemos seu pedido {{pedido_numero}}",
        title="Pedido recebido",
        preheader="Seu pedido foi criado na Bia Collections.",
        intro="Ola {{cliente_nome}}, recebemos seu pedido {{pedido_numero}}.",
        body_html=(
            "<p style=\"margin: 0 0 14px;\">Total do pedido: <strong>{{pedido_total}}</strong>.</p>"
            "<p style=\"margin: 0;\">Assim que o pagamento for confirmado, vamos preparar tudo com cuidado.</p>"
        ),
        text_template=(
            "Ola {{cliente_nome}}, recebemos seu pedido {{pedido_numero}}. "
            "Total do pedido: {{pedido_total}}. Assim que o pagamento for confirmado, vamos preparar tudo com cuidado."
        ),
        variables=("cliente_nome", "pedido_numero", "pedido_total", "loja_nome", "loja_url"),
    ),
    _admin_template(
        nome="Pagamento aprovado",
        slug="admin-default-pagamento-aprovado",
        evento="pagamento_aprovado",
        assunto="Pagamento aprovado - Pedido {{pedido_numero}}",
        title="Pagamento aprovado",
        preheader="Seu pagamento foi confirmado.",
        intro="Ola {{cliente_nome}}, o pagamento do pedido {{pedido_numero}} foi aprovado.",
        body_html=(
            "<p style=\"margin: 0 0 14px;\">Total confirmado: <strong>{{pedido_total}}</strong>.</p>"
            "<p style=\"margin: 0;\">Agora vamos separar seus produtos e avisar quando o pedido for enviado.</p>"
        ),
        text_template=(
            "Ola {{cliente_nome}}, o pagamento do pedido {{pedido_numero}} foi aprovado. "
            "Total confirmado: {{pedido_total}}. Agora vamos separar seus produtos."
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
        nome="Codigo de acesso",
        slug="admin-default-codigo-acesso",
        evento="codigo_acesso",
        assunto="Seu codigo de acesso - {{loja_nome}}",
        title="Seu codigo de acesso",
        preheader="Use este codigo para concluir seu acesso.",
        intro="Use o codigo abaixo para concluir seu acesso com seguranca.",
        body_html=(
            "<p style=\"margin: 0 0 16px; text-align: center; font-size: 24px; letter-spacing: 6px; color: #111111;\">"
            "<strong>{{codigo}}</strong></p>"
            "<p style=\"margin: 0; text-align: center;\">Este codigo expira em {{minutos_expiracao}} minutos.</p>"
        ),
        text_template=(
            "Seu codigo de acesso e {{codigo}}. Este codigo expira em {{minutos_expiracao}} minutos."
        ),
        variables=("codigo", "minutos_expiracao", "loja_nome", "loja_url"),
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
            templates_by_slug[data["slug"]] = template

        for data in ADMIN_EMAIL_TEMPLATE_SEEDS:
            template = session.query(EmailTemplate).filter(EmailTemplate.slug == data["slug"]).first()
            if template:
                _fill_missing_admin_template_fields(template, data)
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

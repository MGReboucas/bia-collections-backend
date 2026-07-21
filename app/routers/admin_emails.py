from __future__ import annotations

import re
from uuid import uuid4
from datetime import datetime, timezone

from fastapi import APIRouter, Body, Depends, HTTPException, Response, status
from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.database import get_db
from app.dependencies import get_current_master_admin_user
from app.models.usuario import Usuario
from app.modules.email.models import EmailTemplate
from app.modules.email.provider import EmailProvider
from app.modules.email.service import EmailAutomationService
from app.schemas.admin_emails import (
    AdminEmailEnviarManualPayload,
    AdminEmailManualLogOut,
    AdminEmailManualSendResponse,
    AdminEmailTemplateOut,
    AdminEmailTemplatePayload,
    AdminEmailTestePayload,
)

router = APIRouter(
    prefix="/admin/emails",
    tags=["admin-emails"],
    dependencies=[Depends(get_current_master_admin_user)],
)

VAR_PATTERN = re.compile(r"{{\s*([a-zA-Z0-9_]+)\s*}}")
EVENTO_TO_SLUG_PREFIX = {
    "pedido_criado": "pedido-criado",
    "pagamento_aprovado": "pagamento-aprovado",
    "pedido_enviado": "pedido-enviado",
    "recuperacao_senha": "recuperacao-senha",
    "codigo_acesso": "codigo-acesso",
    "cupom_disponivel": "cupom-disponivel",
    "manual": "manual",
}


def _error(status_code: int, message: str) -> HTTPException:
    return HTTPException(status_code=status_code, detail={"message": message})


def _validation_message(exc: ValidationError) -> str:
    errors = exc.errors()
    if not errors:
        return "Dados invalidos."
    first = errors[0]
    loc = [str(part) for part in first.get("loc", []) if part != "body"]
    field = loc[-1] if loc else "campo"
    if first.get("type") == "missing":
        return f"Campo obrigatorio: {field}."
    return f"{field}: {first.get('msg', 'valor invalido')}."


def _parse_template_payload(body: dict) -> AdminEmailTemplatePayload:
    try:
        return AdminEmailTemplatePayload.model_validate(body)
    except ValidationError as exc:
        raise _error(422, _validation_message(exc)) from exc


def _parse_teste_payload(body: dict) -> AdminEmailTestePayload:
    try:
        return AdminEmailTestePayload.model_validate(body)
    except ValidationError as exc:
        raise _error(422, _validation_message(exc)) from exc


def _parse_enviar_manual_payload(body: dict) -> AdminEmailEnviarManualPayload:
    try:
        return AdminEmailEnviarManualPayload.model_validate(body)
    except ValidationError as exc:
        raise _error(422, _validation_message(exc)) from exc


def _template_out(template: EmailTemplate) -> AdminEmailTemplateOut:
    return AdminEmailTemplateOut(
        id=template.id,
        nome=template.nome or template.name,
        assunto=template.subject,
        evento=template.evento,
        status=template.status or ("ativo" if template.is_active else "rascunho"),
        html=template.html or template.html_template,
        atualizado_em=template.updated_at,
    )


def _render_template(value: str, variaveis: dict[str, str]) -> str:
    def replace(match: re.Match[str]) -> str:
        return str(variaveis.get(match.group(1), ""))

    return VAR_PATTERN.sub(replace, value)


def _html_to_text(value: str) -> str:
    return " ".join(re.sub(r"<[^>]+>", " ", value).split())


def _ensure_single_active(
    db: Session,
    *,
    evento: str,
    template_id: int | None = None,
) -> None:
    if evento == "manual":
        return
    query = db.query(EmailTemplate).filter(
        EmailTemplate.evento == evento,
        EmailTemplate.status == "ativo",
    )
    if template_id is not None:
        query = query.filter(EmailTemplate.id != template_id)
    if query.first():
        raise _error(409, "Ja existe um template ativo para este evento.")


def _slug_for(template: EmailTemplate | None, evento: str, nome: str) -> str:
    if template and template.slug:
        return template.slug
    prefix = EVENTO_TO_SLUG_PREFIX.get(evento, evento.replace("_", "-"))
    cleaned_name = re.sub(r"[^a-zA-Z0-9]+", "-", nome.strip().lower()).strip("-")
    suffix = cleaned_name or str(int(datetime.now(timezone.utc).timestamp()))
    return f"admin-{prefix}-{suffix}-{uuid4().hex[:8]}"


def _apply_payload(template: EmailTemplate, data: AdminEmailTemplatePayload) -> None:
    template.nome = data.nome
    template.subject = data.assunto
    template.evento = data.evento
    template.status = data.status
    template.html = data.html
    template.name = data.nome
    template.category = data.evento
    template.html_template = data.html
    template.text_template = _html_to_text(data.html)
    template.variables_schema = "{}"
    template.is_active = data.status == "ativo"
    template.slug = _slug_for(template, data.evento, data.nome)


def _user_variables(user: Usuario) -> dict[str, str]:
    customer_name = user.nome_completo or user.username
    store_url = settings.STORE_URL or settings.FRONTEND_URL
    return {
        "cliente_nome": customer_name,
        "customer_name": customer_name,
        "email": user.email,
        "loja_nome": settings.STORE_NAME,
        "store_name": settings.STORE_NAME,
        "loja_url": store_url,
        "store_url": store_url,
    }


def _base_manual_variables() -> dict[str, str]:
    store_url = settings.STORE_URL or settings.FRONTEND_URL
    return {
        "loja_nome": settings.STORE_NAME,
        "store_name": settings.STORE_NAME,
        "loja_url": store_url,
        "store_url": store_url,
    }


@router.get("", response_model=list[AdminEmailTemplateOut])
def listar_templates_email(
    db: Session = Depends(get_db),
    _: Usuario = Depends(get_current_master_admin_user),
):
    templates = (
        db.query(EmailTemplate)
        .filter(EmailTemplate.evento.isnot(None))
        .order_by(EmailTemplate.updated_at.desc(), EmailTemplate.id.desc())
        .all()
    )
    return [_template_out(template) for template in templates]


@router.post("", response_model=AdminEmailTemplateOut, status_code=status.HTTP_201_CREATED)
def criar_template_email(
    body: dict = Body(default_factory=dict),
    db: Session = Depends(get_db),
    _: Usuario = Depends(get_current_master_admin_user),
):
    data = _parse_template_payload(body)
    if data.status == "ativo":
        _ensure_single_active(db, evento=data.evento)

    template = EmailTemplate(
        name=data.nome,
        slug=_slug_for(None, data.evento, data.nome),
        category=data.evento,
        subject=data.assunto,
        html_template=data.html,
        text_template=_html_to_text(data.html),
        variables_schema="{}",
        is_active=data.status == "ativo",
    )
    _apply_payload(template, data)
    db.add(template)
    db.commit()
    db.refresh(template)
    return _template_out(template)


@router.post("/{template_id}/enviar", response_model=AdminEmailManualSendResponse)
def enviar_template_manual(
    template_id: int,
    body: dict = Body(default_factory=dict),
    db: Session = Depends(get_db),
    _: Usuario = Depends(get_current_master_admin_user),
):
    data = _parse_enviar_manual_payload(body)
    template = db.query(EmailTemplate).filter(EmailTemplate.id == template_id).first()
    if not template or template.evento != "manual":
        raise _error(404, "Template manual nao encontrado.")
    if template.status != "ativo" or not template.is_active:
        raise _error(409, "Template manual precisa estar ativo para envio.")

    recipients: list[dict[str, object]] = []
    if data.usuario_ids:
        users = db.query(Usuario).filter(Usuario.id.in_(data.usuario_ids)).all()
        users_by_id = {user.id: user for user in users}
        missing_ids = [user_id for user_id in data.usuario_ids if user_id not in users_by_id]
        if missing_ids:
            raise _error(404, "Um ou mais destinatarios nao foram encontrados.")
        for user_id in data.usuario_ids:
            user = users_by_id[user_id]
            recipients.append(
                {
                    "email": user.email.strip().lower(),
                    "user_id": user.id,
                    "variaveis": _user_variables(user),
                }
            )

    for recipient in data.destinatarios:
        recipients.append(
            {
                "email": recipient.email,
                "user_id": recipient.user_id,
                "variaveis": recipient.variaveis,
            }
        )

    service = EmailAutomationService(db, provider=EmailProvider())
    logs = []
    for recipient in recipients:
        variaveis = {
            **_base_manual_variables(),
            **data.variaveis,
            **dict(recipient["variaveis"]),
        }
        email = str(recipient["email"])
        payload = {
            **variaveis,
            "variaveis": variaveis,
            "to": email,
            "email": email,
            "user_id": recipient["user_id"],
            "dedupe_key": f"manual:{template.id}:{email}:{uuid4().hex}",
        }
        logs.append(
            service.send_template_now(
                template,
                payload,
                event_key="manual",
                raise_on_failure=False,
            )
        )

    enviados = sum(1 for log in logs if log.status == "sent")
    falhas = len(logs) - enviados
    return AdminEmailManualSendResponse(
        message="Campanha manual processada.",
        total=len(logs),
        enviados=enviados,
        falhas=falhas,
        logs=[
            AdminEmailManualLogOut(id=log.id, email=log.email, status=log.status)
            for log in logs
        ],
    )


@router.put("/{template_id}", response_model=AdminEmailTemplateOut)
def atualizar_template_email(
    template_id: int,
    body: dict = Body(default_factory=dict),
    db: Session = Depends(get_db),
    _: Usuario = Depends(get_current_master_admin_user),
):
    data = _parse_template_payload(body)
    template = db.query(EmailTemplate).filter(EmailTemplate.id == template_id).first()
    if not template or template.evento is None:
        raise _error(404, "Template nao encontrado.")
    if data.status == "ativo":
        _ensure_single_active(db, evento=data.evento, template_id=template_id)

    _apply_payload(template, data)
    db.commit()
    db.refresh(template)
    return _template_out(template)


@router.delete("/{template_id}", status_code=status.HTTP_204_NO_CONTENT)
def deletar_template_email(
    template_id: int,
    db: Session = Depends(get_db),
    _: Usuario = Depends(get_current_master_admin_user),
):
    template = db.query(EmailTemplate).filter(EmailTemplate.id == template_id).first()
    if not template or template.evento is None:
        raise _error(404, "Template nao encontrado.")

    db.delete(template)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/{template_id}/teste")
def enviar_teste_template_email(
    template_id: int,
    body: dict = Body(default_factory=dict),
    db: Session = Depends(get_db),
    _: Usuario = Depends(get_current_master_admin_user),
):
    data = _parse_teste_payload(body)
    template = db.query(EmailTemplate).filter(EmailTemplate.id == template_id).first()
    if not template or template.evento is None:
        raise _error(404, "Template nao encontrado.")

    subject = _render_template(template.subject, data.variaveis)
    html = _render_template(template.html or template.html_template, data.variaveis)
    try:
        EmailProvider().send(
            to=data.email_destino,
            subject=subject,
            html=html,
            text=re.sub(r"<[^>]+>", " ", html),
        )
    except Exception as exc:
        raise _error(502, f"Falha ao enviar email de teste: {exc}") from exc

    return {"message": "Email de teste enviado."}

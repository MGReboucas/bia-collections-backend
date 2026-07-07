from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session, joinedload

from app.database import get_db
from app.dependencies import get_current_master_admin_user
from app.models.usuario import Usuario
from app.modules.email.models import EmailAutomation, EmailLog, EmailTemplate
from app.modules.email.schemas import (
    EmailAutomationCreate,
    EmailAutomationOut,
    EmailAutomationStatusUpdate,
    EmailAutomationUpdate,
    EmailLogOut,
    EmailTemplateCreate,
    EmailTemplateOut,
    EmailTemplateStatusUpdate,
    EmailTemplateUpdate,
    RetryEmailResponse,
)
from app.modules.email.service import EmailAutomationService

router = APIRouter(
    prefix="/admin/email",
    tags=["admin-email"],
    dependencies=[Depends(get_current_master_admin_user)],
)


def _automation_out(automation: EmailAutomation) -> EmailAutomationOut:
    return EmailAutomationOut(
        id=automation.id,
        event_key=automation.event_key,
        email_template_id=automation.email_template_id,
        channel=automation.channel,
        delay_minutes=automation.delay_minutes,
        is_active=automation.is_active,
        created_at=automation.created_at,
        updated_at=automation.updated_at,
        template_slug=automation.template.slug if automation.template else None,
        template_name=automation.template.name if automation.template else None,
    )


@router.get("/templates", response_model=list[EmailTemplateOut])
def listar_templates(
    category: str | None = Query(None),
    active: bool | None = Query(None),
    db: Session = Depends(get_db),
    _: Usuario = Depends(get_current_master_admin_user),
):
    query = db.query(EmailTemplate).order_by(EmailTemplate.category.asc(), EmailTemplate.name.asc())
    if category:
        query = query.filter(EmailTemplate.category == category)
    if active is not None:
        query = query.filter(EmailTemplate.is_active.is_(active))
    return query.all()


@router.post("/templates", response_model=EmailTemplateOut, status_code=status.HTTP_201_CREATED)
def criar_template(
    data: EmailTemplateCreate,
    db: Session = Depends(get_db),
    _: Usuario = Depends(get_current_master_admin_user),
):
    exists = db.query(EmailTemplate).filter(EmailTemplate.slug == data.slug).first()
    if exists:
        raise HTTPException(status_code=409, detail="Template ja cadastrado.")
    template = EmailTemplate(**data.model_dump())
    db.add(template)
    db.commit()
    db.refresh(template)
    return template


@router.put("/templates/{template_id}", response_model=EmailTemplateOut)
def editar_template(
    template_id: int,
    data: EmailTemplateUpdate,
    db: Session = Depends(get_db),
    _: Usuario = Depends(get_current_master_admin_user),
):
    template = db.query(EmailTemplate).filter(EmailTemplate.id == template_id).first()
    if not template:
        raise HTTPException(status_code=404, detail="Template nao encontrado.")

    updates = data.model_dump(exclude_unset=True)
    if "slug" in updates:
        updates["slug"] = updates["slug"].strip().lower().replace(" ", "-")
        duplicate = (
            db.query(EmailTemplate)
            .filter(EmailTemplate.slug == updates["slug"], EmailTemplate.id != template_id)
            .first()
        )
        if duplicate:
            raise HTTPException(status_code=409, detail="Slug ja cadastrado.")

    for key, value in updates.items():
        setattr(template, key, value)
    db.commit()
    db.refresh(template)
    return template


@router.patch("/templates/{template_id}/status", response_model=EmailTemplateOut)
def alterar_status_template(
    template_id: int,
    data: EmailTemplateStatusUpdate,
    db: Session = Depends(get_db),
    _: Usuario = Depends(get_current_master_admin_user),
):
    template = db.query(EmailTemplate).filter(EmailTemplate.id == template_id).first()
    if not template:
        raise HTTPException(status_code=404, detail="Template nao encontrado.")
    template.is_active = data.is_active
    db.commit()
    db.refresh(template)
    return template


@router.get("/automations", response_model=list[EmailAutomationOut])
def listar_automacoes(
    event_key: str | None = Query(None),
    active: bool | None = Query(None),
    db: Session = Depends(get_db),
    _: Usuario = Depends(get_current_master_admin_user),
):
    query = db.query(EmailAutomation).options(joinedload(EmailAutomation.template)).order_by(EmailAutomation.event_key.asc())
    if event_key:
        query = query.filter(EmailAutomation.event_key == event_key)
    if active is not None:
        query = query.filter(EmailAutomation.is_active.is_(active))
    return [_automation_out(item) for item in query.all()]


@router.post("/automations", response_model=EmailAutomationOut, status_code=status.HTTP_201_CREATED)
def criar_automacao(
    data: EmailAutomationCreate,
    db: Session = Depends(get_db),
    _: Usuario = Depends(get_current_master_admin_user),
):
    template = db.query(EmailTemplate).filter(EmailTemplate.id == data.email_template_id).first()
    if not template:
        raise HTTPException(status_code=404, detail="Template nao encontrado.")
    automation = EmailAutomation(**data.model_dump())
    db.add(automation)
    db.commit()
    db.refresh(automation)
    automation = (
        db.query(EmailAutomation)
        .options(joinedload(EmailAutomation.template))
        .filter(EmailAutomation.id == automation.id)
        .one()
    )
    return _automation_out(automation)


@router.put("/automations/{automation_id}", response_model=EmailAutomationOut)
def editar_automacao(
    automation_id: int,
    data: EmailAutomationUpdate,
    db: Session = Depends(get_db),
    _: Usuario = Depends(get_current_master_admin_user),
):
    automation = db.query(EmailAutomation).filter(EmailAutomation.id == automation_id).first()
    if not automation:
        raise HTTPException(status_code=404, detail="Automacao nao encontrada.")

    updates = data.model_dump(exclude_unset=True)
    if "email_template_id" in updates:
        template = db.query(EmailTemplate).filter(EmailTemplate.id == updates["email_template_id"]).first()
        if not template:
            raise HTTPException(status_code=404, detail="Template nao encontrado.")
    for key, value in updates.items():
        setattr(automation, key, value)
    db.commit()
    automation = (
        db.query(EmailAutomation)
        .options(joinedload(EmailAutomation.template))
        .filter(EmailAutomation.id == automation.id)
        .one()
    )
    return _automation_out(automation)


@router.patch("/automations/{automation_id}/status", response_model=EmailAutomationOut)
def alterar_status_automacao(
    automation_id: int,
    data: EmailAutomationStatusUpdate,
    db: Session = Depends(get_db),
    _: Usuario = Depends(get_current_master_admin_user),
):
    automation = (
        db.query(EmailAutomation)
        .options(joinedload(EmailAutomation.template))
        .filter(EmailAutomation.id == automation_id)
        .first()
    )
    if not automation:
        raise HTTPException(status_code=404, detail="Automacao nao encontrada.")
    automation.is_active = data.is_active
    db.commit()
    db.refresh(automation)
    return _automation_out(automation)


@router.get("/logs", response_model=list[EmailLogOut])
def listar_logs(
    status_filter: str | None = Query(None, alias="status"),
    event_key: str | None = Query(None),
    email: str | None = Query(None),
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
    _: Usuario = Depends(get_current_master_admin_user),
):
    query = db.query(EmailLog).order_by(EmailLog.created_at.desc())
    if status_filter:
        query = query.filter(EmailLog.status == status_filter)
    if event_key:
        query = query.filter(EmailLog.event_key == event_key)
    if email:
        query = query.filter(EmailLog.email == email.strip().lower())
    return query.offset((page - 1) * limit).limit(limit).all()


@router.post("/logs/{log_id}/retry", response_model=RetryEmailResponse)
def reenviar_email_com_falha(
    log_id: int,
    db: Session = Depends(get_db),
    _: Usuario = Depends(get_current_master_admin_user),
):
    try:
        log = EmailAutomationService(db).retry_failed_email(log_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return RetryEmailResponse(
        id=log.id,
        status=log.status,
        message="Email reenfileirado para envio.",
    )

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.orm import Session, joinedload

from app.database import get_db
from app.dependencies import get_current_master_admin_user, get_current_user
from app.models.produto import Produto
from app.models.usuario import Usuario
from app.modules.email.marketing import (
    TRACKING_PIXEL,
    campaign_metrics,
    dispatch_campaign,
    record_tracking_event,
    set_marketing_consent,
    unsubscribe_token,
    verify_tracking_token,
)
from app.modules.email.models import (
    EmailCampaign,
    EmailTemplate,
    MarketingPreference,
    ProductStockInterest,
)

router = APIRouter(prefix="/marketing", tags=["marketing"])
admin_router = APIRouter(
    prefix="/admin/marketing",
    tags=["admin-marketing"],
    dependencies=[Depends(get_current_master_admin_user)],
)

CAMPAIGN_STATUSES = {"rascunho", "aguardando_aprovacao", "aprovada", "agendada", "enviando", "concluida", "cancelada"}
SEGMENTS = {"todos", "com_pedidos", "sem_pedidos", "clientes_vip", "inativos_90d"}


class ConsentPayload(BaseModel):
    aceito: bool


class CampaignPayload(BaseModel):
    nome: str
    template_a_id: int
    template_b_id: int | None = None
    segmento: str = "todos"
    percentual_variante_b: int = Field(50, ge=0, le=100)
    limite_frequencia_dias: int = Field(7, ge=1, le=90)

    @field_validator("nome")
    @classmethod
    def nome_valido(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Nome obrigatorio.")
        return value

    @field_validator("segmento")
    @classmethod
    def segmento_valido(cls, value: str) -> str:
        if value not in SEGMENTS:
            raise ValueError("Segmento invalido.")
        return value


class SchedulePayload(BaseModel):
    agendada_para: datetime


def _campaign_out(campaign: EmailCampaign) -> dict:
    return {
        "id": campaign.id,
        "nome": campaign.name,
        "status": campaign.status,
        "segmento": campaign.segment,
        "template_a_id": campaign.template_a_id,
        "template_b_id": campaign.template_b_id,
        "percentual_variante_b": campaign.ab_percentage,
        "limite_frequencia_dias": campaign.frequency_cap_days,
        "agendada_para": campaign.scheduled_at,
        "aprovada_em": campaign.approved_at,
        "criada_em": campaign.created_at,
        "concluida_em": campaign.completed_at,
    }


@router.get("/preferencias")
def get_preferences(
    db: Session = Depends(get_db),
    user: Usuario = Depends(get_current_user),
):
    preference = db.query(MarketingPreference).filter(MarketingPreference.user_id == user.id).first()
    return {
        "email_marketing": bool(preference and preference.email_consent),
        "descadastro_url": f"/api/v1/marketing/unsubscribe/{unsubscribe_token(user)}",
    }


@router.patch("/preferencias")
def update_preferences(
    data: ConsentPayload,
    db: Session = Depends(get_db),
    user: Usuario = Depends(get_current_user),
):
    preference = set_marketing_consent(db, user, data.aceito, source="preferencias_conta")
    return {"email_marketing": preference.email_consent}


@router.get("/unsubscribe/{token}")
def unsubscribe(token: str, db: Session = Depends(get_db)):
    payload = verify_tracking_token(token)
    if not payload or payload.get("kind") != "unsubscribe":
        raise HTTPException(status_code=400, detail="Link de descadastro invalido ou expirado.")
    user = db.query(Usuario).filter(
        Usuario.id == int(payload["uid"]),
        Usuario.email == payload["email"],
    ).first()
    if not user:
        raise HTTPException(status_code=404, detail="Conta nao encontrada.")
    set_marketing_consent(db, user, False, source="link_descadastro")
    return {"message": "Descadastro confirmado. Voce nao recebera novas campanhas de marketing."}


@router.get("/open/{token}.gif")
def track_open(token: str, request: Request, db: Session = Depends(get_db)):
    payload = verify_tracking_token(token)
    if payload and payload.get("kind") == "open":
        record_tracking_event(
            db,
            payload,
            "open",
            ip=request.client.host if request.client else "",
            user_agent=request.headers.get("user-agent", ""),
        )
    return Response(
        content=TRACKING_PIXEL,
        media_type="image/gif",
        headers={"Cache-Control": "no-store, no-cache, must-revalidate"},
    )


@router.get("/click/{token}")
def track_click(token: str, request: Request, db: Session = Depends(get_db)):
    payload = verify_tracking_token(token)
    if not payload or payload.get("kind") != "click":
        raise HTTPException(status_code=400, detail="Link invalido ou expirado.")
    target = str(payload.get("url") or "")
    if not target.startswith(("http://", "https://")):
        raise HTTPException(status_code=400, detail="Destino invalido.")
    record_tracking_event(
        db,
        payload,
        "click",
        target_url=target,
        ip=request.client.host if request.client else "",
        user_agent=request.headers.get("user-agent", ""),
    )
    return RedirectResponse(target, status_code=302)


@router.post("/estoque/{produto_id}", status_code=status.HTTP_201_CREATED)
def subscribe_stock(
    produto_id: int,
    db: Session = Depends(get_db),
    user: Usuario = Depends(get_current_user),
):
    produto = db.query(Produto).filter(Produto.id == produto_id, Produto.ativo.is_(True)).first()
    if not produto:
        raise HTTPException(status_code=404, detail="Produto nao encontrado.")
    interest = db.query(ProductStockInterest).filter(
        ProductStockInterest.user_id == user.id,
        ProductStockInterest.product_id == produto_id,
    ).first()
    if not interest:
        interest = ProductStockInterest(user_id=user.id, product_id=produto_id)
        db.add(interest)
    interest.is_active = True
    interest.notified_at = None
    db.commit()
    return {"message": "Avisaremos quando o produto voltar ao estoque."}


@router.delete("/estoque/{produto_id}", status_code=status.HTTP_204_NO_CONTENT)
def unsubscribe_stock(
    produto_id: int,
    db: Session = Depends(get_db),
    user: Usuario = Depends(get_current_user),
):
    interest = db.query(ProductStockInterest).filter(
        ProductStockInterest.user_id == user.id,
        ProductStockInterest.product_id == produto_id,
    ).first()
    if interest:
        interest.is_active = False
        db.commit()
    return Response(status_code=204)


def _templates_or_404(db: Session, data: CampaignPayload) -> None:
    ids = [data.template_a_id] + ([data.template_b_id] if data.template_b_id else [])
    found = db.query(EmailTemplate).filter(EmailTemplate.id.in_(ids), EmailTemplate.is_active.is_(True)).count()
    if found != len(ids):
        raise HTTPException(status_code=404, detail="Template ativo nao encontrado.")


@admin_router.get("/campanhas")
def list_campaigns(
    db: Session = Depends(get_db),
    _: Usuario = Depends(get_current_master_admin_user),
):
    return [_campaign_out(item) for item in db.query(EmailCampaign).order_by(EmailCampaign.created_at.desc()).all()]


@admin_router.post("/campanhas", status_code=status.HTTP_201_CREATED)
def create_campaign(
    data: CampaignPayload,
    db: Session = Depends(get_db),
    admin: Usuario = Depends(get_current_master_admin_user),
):
    _templates_or_404(db, data)
    campaign = EmailCampaign(
        name=data.nome,
        template_a_id=data.template_a_id,
        template_b_id=data.template_b_id,
        segment=data.segmento,
        ab_percentage=data.percentual_variante_b,
        frequency_cap_days=data.limite_frequencia_dias,
        status="rascunho",
        created_by_id=admin.id,
    )
    db.add(campaign)
    db.commit()
    db.refresh(campaign)
    return _campaign_out(campaign)


@admin_router.put("/campanhas/{campaign_id}")
def update_campaign(
    campaign_id: int,
    data: CampaignPayload,
    db: Session = Depends(get_db),
    _: Usuario = Depends(get_current_master_admin_user),
):
    campaign = db.query(EmailCampaign).filter(EmailCampaign.id == campaign_id).first()
    if not campaign:
        raise HTTPException(status_code=404, detail="Campanha nao encontrada.")
    if campaign.status not in {"rascunho", "aguardando_aprovacao"}:
        raise HTTPException(status_code=409, detail="Campanha em andamento nao pode ser editada.")
    _templates_or_404(db, data)
    campaign.name = data.nome
    campaign.template_a_id = data.template_a_id
    campaign.template_b_id = data.template_b_id
    campaign.segment = data.segmento
    campaign.ab_percentage = data.percentual_variante_b
    campaign.frequency_cap_days = data.limite_frequencia_dias
    campaign.status = "rascunho"
    db.commit()
    return _campaign_out(campaign)


@admin_router.post("/campanhas/{campaign_id}/solicitar-aprovacao")
def request_approval(
    campaign_id: int,
    db: Session = Depends(get_db),
    _: Usuario = Depends(get_current_master_admin_user),
):
    campaign = db.query(EmailCampaign).filter(EmailCampaign.id == campaign_id).first()
    if not campaign or campaign.status != "rascunho":
        raise HTTPException(status_code=409, detail="Apenas rascunhos podem ser enviados para aprovacao.")
    campaign.status = "aguardando_aprovacao"
    db.commit()
    return _campaign_out(campaign)


@admin_router.post("/campanhas/{campaign_id}/aprovar")
def approve_campaign(
    campaign_id: int,
    db: Session = Depends(get_db),
    admin: Usuario = Depends(get_current_master_admin_user),
):
    campaign = db.query(EmailCampaign).filter(EmailCampaign.id == campaign_id).first()
    if not campaign or campaign.status != "aguardando_aprovacao":
        raise HTTPException(status_code=409, detail="Campanha nao esta aguardando aprovacao.")
    campaign.status = "aprovada"
    campaign.approved_at = datetime.now(timezone.utc)
    campaign.approved_by_id = admin.id
    db.commit()
    return _campaign_out(campaign)


@admin_router.post("/campanhas/{campaign_id}/agendar")
def schedule_campaign(
    campaign_id: int,
    data: SchedulePayload,
    db: Session = Depends(get_db),
    _: Usuario = Depends(get_current_master_admin_user),
):
    campaign = db.query(EmailCampaign).filter(EmailCampaign.id == campaign_id).first()
    if not campaign or campaign.status != "aprovada":
        raise HTTPException(status_code=409, detail="Campanha precisa estar aprovada.")
    scheduled = data.agendada_para
    if scheduled.tzinfo is None:
        scheduled = scheduled.replace(tzinfo=timezone.utc)
    if scheduled <= datetime.now(timezone.utc):
        raise HTTPException(status_code=422, detail="Agendamento precisa estar no futuro.")
    campaign.status = "agendada"
    campaign.scheduled_at = scheduled
    db.commit()
    return _campaign_out(campaign)


@admin_router.post("/campanhas/{campaign_id}/enviar")
def send_campaign(
    campaign_id: int,
    db: Session = Depends(get_db),
    _: Usuario = Depends(get_current_master_admin_user),
):
    campaign = (
        db.query(EmailCampaign)
        .options(joinedload(EmailCampaign.template_a), joinedload(EmailCampaign.template_b))
        .filter(EmailCampaign.id == campaign_id)
        .first()
    )
    if not campaign or campaign.status != "aprovada":
        raise HTTPException(status_code=409, detail="Campanha precisa estar aprovada.")
    return {"enfileirados": dispatch_campaign(db, campaign), "campanha": _campaign_out(campaign)}


@admin_router.post("/campanhas/{campaign_id}/cancelar")
def cancel_campaign(
    campaign_id: int,
    db: Session = Depends(get_db),
    _: Usuario = Depends(get_current_master_admin_user),
):
    campaign = db.query(EmailCampaign).filter(EmailCampaign.id == campaign_id).first()
    if not campaign or campaign.status in {"enviando", "concluida"}:
        raise HTTPException(status_code=409, detail="Campanha nao pode ser cancelada.")
    campaign.status = "cancelada"
    db.commit()
    return _campaign_out(campaign)


@admin_router.get("/campanhas/{campaign_id}/metricas")
def metrics(
    campaign_id: int,
    db: Session = Depends(get_db),
    _: Usuario = Depends(get_current_master_admin_user),
):
    if not db.query(EmailCampaign.id).filter(EmailCampaign.id == campaign_id).first():
        raise HTTPException(status_code=404, detail="Campanha nao encontrada.")
    return campaign_metrics(db, campaign_id)

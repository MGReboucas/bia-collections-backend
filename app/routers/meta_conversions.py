from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from jose import JWTError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.security import decode_token
from app.database import get_db
from app.models.usuario import Usuario
from app.schemas.meta_conversions import MetaEventRequest, MetaEventResponse
from app.services.meta_conversions import (
    client_ip_from_request,
    meta_credentials_configured,
    send_meta_web_event,
)

router = APIRouter(prefix="/meta", tags=["meta"])


def _optional_current_user(request: Request, db: Session) -> Usuario | None:
    authorization = request.headers.get("authorization", "")
    token = None
    if authorization.lower().startswith("bearer "):
        token = authorization.split(" ", 1)[1].strip()
    if not token:
        token = request.cookies.get(settings.SESSION_COOKIE_NAME)
    if not token:
        return None

    try:
        payload = decode_token(token)
    except JWTError:
        return None
    username = payload.get("sub")
    if not username:
        return None
    return db.query(Usuario).filter(Usuario.username == username).first()


@router.post("/events", response_model=MetaEventResponse)
def registrar_evento_meta(
    data: MetaEventRequest,
    request: Request,
    db: Session = Depends(get_db),
):
    current_user = _optional_current_user(request, db)
    client_user_agent = data.client_user_agent or request.headers.get("user-agent")
    client_ip_address = client_ip_from_request(request)
    fbp = data.fbp or request.cookies.get("_fbp")
    fbc = data.fbc or request.cookies.get("_fbc")

    user_data = data.user_data.model_dump(exclude_none=True) if data.user_data else None
    custom_data = data.custom_data.model_dump(exclude_none=True) if data.custom_data else None
    sent = send_meta_web_event(
        event_name=data.event_name,
        event_id=data.event_id,
        event_time=data.event_time,
        event_source_url=data.event_source_url,
        client_user_agent=client_user_agent,
        client_ip_address=client_ip_address,
        fbp=fbp,
        fbc=fbc,
        user_data=user_data,
        custom_data=custom_data,
        current_user=current_user,
    )
    return MetaEventResponse(
        event_name=data.event_name,
        event_id=data.event_id,
        sent_to_meta=sent,
        configured=meta_credentials_configured(),
    )

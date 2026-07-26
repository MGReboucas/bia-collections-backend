from datetime import datetime
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.core.config import settings
from app.dependencies import get_current_user, is_master_admin_email
from app.models.usuario import Usuario
from app.schemas.usuario import (
    AtualizarPerfil,
    ConfirmarAlteracaoEmail,
    SolicitarAlteracaoEmail,
    UsuarioPerfil,
)
from app.modules.email.service import EmailAutomationService
from app.services.two_factor_service import (
    TwoFactorError,
    create_two_factor_challenge,
    get_open_challenge,
    verify_two_factor_code,
)
from app.services.upload_service import upload_image, delete_old_image

router = APIRouter(prefix="/usuario", tags=["usuario"])


def _data_hora_local() -> str:
    return datetime.now(ZoneInfo("America/Sao_Paulo")).strftime("%d/%m/%Y às %H:%M")


def _security_url() -> str:
    return f"{(settings.FRONTEND_URL or settings.STORE_URL).rstrip('/')}/recuperar-senha"


def _trigger_sensitive_change(
    db: Session,
    user: Usuario,
    *,
    recipient: str,
    change_type: str,
    dedupe_suffix: str,
) -> None:
    data_hora = _data_hora_local()
    EmailAutomationService(db).trigger_event(
        "sensitive_data_changed",
        {
            "to": recipient,
            "email": recipient,
            "customer_name": user.nome_completo or user.username,
            "cliente_nome": user.nome_completo or user.username,
            "user_id": user.id,
            "change_type": change_type,
            "tipo_alteracao": change_type,
            "date_time": data_hora,
            "data_hora": data_hora,
            "security_url": _security_url(),
            "link_seguranca": _security_url(),
            "store_name": settings.STORE_NAME,
            "loja_nome": settings.STORE_NAME,
            "store_url": settings.STORE_URL or settings.FRONTEND_URL,
            "loja_url": settings.STORE_URL or settings.FRONTEND_URL,
            "dedupe_key": f"sensitive_data_changed:{user.id}:{dedupe_suffix}",
        },
    )


def _usuario_perfil_response(user: Usuario) -> UsuarioPerfil:
    perfil = UsuarioPerfil.model_validate(user)
    perfil.is_admin = is_master_admin_email(user.email)
    return perfil


@router.get("/perfil", response_model=UsuarioPerfil)
def obter_perfil(current_user: Usuario = Depends(get_current_user)):
    return _usuario_perfil_response(current_user)


@router.put("/perfil", response_model=UsuarioPerfil)
def atualizar_perfil(
    data: AtualizarPerfil,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
):
    if data.email is not None and data.email != current_user.email:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Para alterar o e-mail, solicite e confirme o código de segurança.",
        )

    telefone_anterior = current_user.telefone
    if data.nome_completo is not None:
        current_user.nome_completo = data.nome_completo
    if data.telefone is not None:
        current_user.telefone = data.telefone

    db.commit()
    db.refresh(current_user)
    if data.telefone is not None and data.telefone != telefone_anterior:
        _trigger_sensitive_change(
            db,
            current_user,
            recipient=current_user.email,
            change_type="telefone",
            dedupe_suffix=f"telefone:{datetime.now().timestamp()}",
        )
    return _usuario_perfil_response(current_user)


@router.post("/perfil/email/solicitar")
def solicitar_alteracao_email(
    data: SolicitarAlteracaoEmail,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
):
    if data.novo_email == current_user.email.strip().lower():
        raise HTTPException(status_code=409, detail="Este já é o e-mail atual da conta.")
    if db.query(Usuario.id).filter(Usuario.email == data.novo_email).first():
        raise HTTPException(status_code=409, detail="E-mail já está em uso.")

    challenge = create_two_factor_challenge(
        db,
        current_user,
        finalidade="alteracao_email",
        valor_pendente=data.novo_email,
    )
    EmailAutomationService(db).send_event_now(
        "email_change_confirmation",
        {
            "to": current_user.email,
            "email": current_user.email,
            "customer_name": current_user.nome_completo or current_user.username,
            "cliente_nome": current_user.nome_completo or current_user.username,
            "code": challenge.codigo,
            "codigo": challenge.codigo,
            "expires_in_minutes": str(challenge.expires_in // 60),
            "minutos_expiracao": str(challenge.expires_in // 60),
            "new_email": data.novo_email,
            "novo_email": data.novo_email,
            "user_id": current_user.id,
            "store_name": settings.STORE_NAME,
            "loja_nome": settings.STORE_NAME,
            "store_url": settings.STORE_URL or settings.FRONTEND_URL,
            "loja_url": settings.STORE_URL or settings.FRONTEND_URL,
            "dedupe_key": f"email_change_confirmation:{challenge.challenge.id}",
        },
        raise_on_failure=False,
    )
    return {
        "token": challenge.token,
        "email_destino": current_user.email,
        "novo_email": data.novo_email,
        "expires_in": challenge.expires_in,
    }


@router.post("/perfil/email/confirmar", response_model=UsuarioPerfil)
def confirmar_alteracao_email(
    data: ConfirmarAlteracaoEmail,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
):
    challenge = get_open_challenge(db, data.token)
    if not challenge or challenge.usuario_id != current_user.id:
        raise HTTPException(status_code=400, detail="Código inválido ou expirado.")
    novo_email = (challenge.valor_pendente or "").strip().lower()
    if not novo_email:
        raise HTTPException(status_code=400, detail="Código inválido ou expirado.")
    try:
        verify_two_factor_code(
            db,
            data.token,
            data.codigo,
            finalidade="alteracao_email",
        )
    except TwoFactorError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
    if db.query(Usuario.id).filter(Usuario.email == novo_email, Usuario.id != current_user.id).first():
        raise HTTPException(status_code=409, detail="E-mail já está em uso.")

    email_anterior = current_user.email
    current_user.email = novo_email
    db.commit()
    db.refresh(current_user)
    suffix = f"email:{challenge.id}"
    _trigger_sensitive_change(
        db,
        current_user,
        recipient=email_anterior,
        change_type="e-mail",
        dedupe_suffix=f"{suffix}:anterior",
    )
    _trigger_sensitive_change(
        db,
        current_user,
        recipient=novo_email,
        change_type="e-mail",
        dedupe_suffix=f"{suffix}:novo",
    )
    return _usuario_perfil_response(current_user)


@router.post("/perfil/foto", response_model=UsuarioPerfil)
async def upload_foto(
    foto: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
):
    # Remove foto anterior se for local (Cloudinary ignora)
    delete_old_image(current_user.foto_url)

    url = await upload_image(foto, folder="bia-collections/avatars")
    current_user.foto_url = url
    db.commit()
    db.refresh(current_user)
    return _usuario_perfil_response(current_user)


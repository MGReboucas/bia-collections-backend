import logging
import secrets
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from slowapi import Limiter
from slowapi.util import get_remote_address
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import is_master_admin_email
from app.models.usuario import Usuario
from app.models.reset_senha import ResetSenha
from app.core.config import settings
from app.core.security import verify_password, get_password_hash, create_access_token
from app.core.email import enviar_email_codigo_acesso, enviar_email_reset
from app.modules.email.models import EmailTemplate
from app.modules.email.service import EmailAutomationService
from app.services.two_factor_service import (
    CreatedTwoFactorChallenge,
    TwoFactorError,
    create_resend_challenge,
    create_two_factor_challenge,
    verify_two_factor_code,
)
from app.schemas.auth import (
    LoginRequest,
    CadastroRequest,
    RecuperarSenhaRequest,
    SolicitarRedefinicaoRequest,
    VerificarCodigoRequest,
    RedefinirSenhaRequest,
    ResendTwoFactorRequest,
    ResendTwoFactorResponse,
    TokenResponse,
    TwoFactorChallengeResponse,
    UsuarioBasico,
    VerifyTwoFactorRequest,
)

router = APIRouter(prefix="/auth", tags=["auth"])
limiter = Limiter(key_func=get_remote_address)
logger = logging.getLogger(__name__)


def _normalizar_email(email: str | None) -> str:
    return (email or "").strip().lower()


def _email_mascarado(email: str) -> str:
    local, sep, dominio = email.partition("@")
    if not sep:
        return "***"
    return f"{local[:2]}***@{dominio}"


def _frontend_url(path: str = "") -> str:
    base_url = (settings.FRONTEND_URL or settings.STORE_URL or "").rstrip("/")
    return f"{base_url}{path}" if base_url else path


def _usuario_por_email(db: Session, email: str) -> Usuario | None:
    return (
        db.query(Usuario)
        .filter(func.lower(func.trim(Usuario.email)) == email)
        .first()
    )


def _usuario_basico_response(user: Usuario) -> UsuarioBasico:
    usuario = UsuarioBasico.model_validate(user)
    usuario.is_admin = is_master_admin_email(user.email)
    return usuario


def _token_response(user: Usuario) -> TokenResponse:
    return TokenResponse(
        access_token=create_access_token({"sub": user.username}),
        usuario=_usuario_basico_response(user),
    )


_COOKIE_NAME = "cb_token"
_COOKIE_MAX_AGE = 86400  # 1 day in seconds


def _set_auth_cookie(response: Response, user: Usuario) -> None:
    token = create_access_token({"sub": user.username})
    response.set_cookie(
        key=_COOKIE_NAME,
        value=token,
        httponly=True,
        samesite="lax",
        path="/",
        max_age=_COOKIE_MAX_AGE,
        secure=False,  # set to True behind HTTPS in production
    )


def _has_admin_template_configured(db: Session, evento: str) -> bool:
    return db.query(EmailTemplate.id).filter(EmailTemplate.evento == evento).first() is not None


def _send_two_factor_email(db: Session, challenge: CreatedTwoFactorChallenge, email: str) -> None:
    has_admin_template = _has_admin_template_configured(db, "codigo_acesso")
    try:
        log = EmailAutomationService(db).send_event_now(
            "two_factor_code",
            {
                "to": email,
                "email": email,
                "code": challenge.codigo,
                "codigo": challenge.codigo,
                "expires_in_minutes": str(challenge.expires_in // 60),
                "minutos_expiracao": str(challenge.expires_in // 60),
                "dedupe_key": f"two_factor_code:{challenge.challenge.id}",
                "store_name": settings.STORE_NAME,
                "loja_nome": settings.STORE_NAME,
                "store_url": settings.STORE_URL or settings.FRONTEND_URL,
                "loja_url": settings.STORE_URL or settings.FRONTEND_URL,
            },
            raise_on_failure=False,
        )
        if log:
            return
        if not has_admin_template:
            enviar_email_codigo_acesso(email, challenge.codigo)
    except Exception:
        logger.exception(
            "Falha ao enviar codigo de acesso para %s",
            _email_mascarado(email),
        )


def _challenge_response(
    challenge: CreatedTwoFactorChallenge,
    user: Usuario,
    message: str,
) -> TwoFactorChallengeResponse:
    return TwoFactorChallengeResponse(
        two_factor_token=challenge.token,
        email=user.email,
        expires_in=challenge.expires_in,
        message=message,
    )


def _raise_two_factor_error(error: TwoFactorError) -> None:
    raise HTTPException(status_code=error.status_code, detail=error.detail)


@router.post("/login", response_model=TwoFactorChallengeResponse)
@limiter.limit("10/minute")
def login(request: Request, data: LoginRequest, db: Session = Depends(get_db)):
    user = (
        db.query(Usuario)
        .filter((Usuario.username == data.login) | (Usuario.email == data.login))
        .first()
    )
    if not user or not verify_password(data.senha, user.senha_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Usuário ou senha inválidos.",
        )
    challenge = create_two_factor_challenge(db, user)
    _send_two_factor_email(db, challenge, user.email)
    return _challenge_response(challenge, user, "Codigo enviado por e-mail.")


@router.post("/cadastro", response_model=TwoFactorChallengeResponse, status_code=status.HTTP_201_CREATED)
@limiter.limit("5/minute")
def cadastro(request: Request, data: CadastroRequest, db: Session = Depends(get_db)):
    if data.senha != data.confirma_senha:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="As senhas não coincidem.",
        )
    existing = (
        db.query(Usuario)
        .filter((Usuario.email == data.email) | (Usuario.username == data.username))
        .first()
    )
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Email ou usuário já cadastrado.",
        )
    user = Usuario(
        username=data.username,
        email=data.email,
        senha_hash=get_password_hash(data.senha),
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    challenge = create_two_factor_challenge(db, user)
    _send_two_factor_email(db, challenge, user.email)
    return _challenge_response(challenge, user, "Conta criada. Codigo enviado por e-mail.")


@router.post("/login/verificar-2fa", response_model=TokenResponse)
def verificar_2fa(data: VerifyTwoFactorRequest, response: Response, db: Session = Depends(get_db)):
    try:
        user = verify_two_factor_code(db, data.two_factor_token, data.codigo)
    except TwoFactorError as error:
        _raise_two_factor_error(error)

    _set_auth_cookie(response, user)
    return _token_response(user)


@router.post("/login/reenviar-2fa", response_model=ResendTwoFactorResponse)
def reenviar_2fa(data: ResendTwoFactorRequest, db: Session = Depends(get_db)):
    try:
        challenge = create_resend_challenge(db, data.two_factor_token)
    except TwoFactorError as error:
        _raise_two_factor_error(error)

    user = challenge.challenge.usuario
    _send_two_factor_email(db, challenge, user.email)
    return ResendTwoFactorResponse(
        two_factor_token=challenge.token,
        email=user.email,
        expires_in=challenge.expires_in,
        message="Novo codigo enviado.",
    )


@router.post("/recuperar-senha")
@limiter.limit("5/minute")
def recuperar_senha(request: Request, data: RecuperarSenhaRequest, db: Session = Depends(get_db)):  # noqa: ARG001
    return {"mensagem": "Se o e-mail existir, você receberá as instruções."}


# ── Redefinição de senha em 3 etapas ──────────────────────────────────────────────

@router.post("/solicitar-redefinicao")
@limiter.limit("3/minute")
def solicitar_redefinicao(request: Request, data: SolicitarRedefinicaoRequest, db: Session = Depends(get_db)):
    """Etapa 1 — gera código de 6 dígitos, armazena hash e envia por e-mail."""
    email = _normalizar_email(data.email)
    user = _usuario_por_email(db, email)
    # Resposta genérica para não revelar se o e-mail existe
    if not user:
        logger.info("Reset de senha solicitado para email nao cadastrado: %s", _email_mascarado(email))
        return {"mensagem": "Se o e-mail existir, você receberá o código."}

    # Invalida códigos anteriores do mesmo e-mail
    db.query(ResetSenha).filter(
        ResetSenha.email == email,
        ResetSenha.usado == False,  # noqa: E712
    ).update({"usado": True})

    codigo = str(secrets.randbelow(900000) + 100000)  # 100000–999999
    expira_em = datetime.now(timezone.utc) + timedelta(minutes=15)

    reset = ResetSenha(
        email=email,
        codigo_hash=get_password_hash(codigo),
        expira_em=expira_em,
    )
    db.add(reset)
    db.commit()

    has_admin_template = _has_admin_template_configured(db, "recuperacao_senha")
    try:
        log = EmailAutomationService(db).send_event_now(
            "password_reset",
            {
                "to": email,
                "email": email,
                "reset_code": codigo,
                "codigo": codigo,
                "expires_in_minutes": "15",
                "minutos_expiracao": "15",
                "customer_name": user.nome_completo or user.username,
                "cliente_nome": user.nome_completo or user.username,
                "user_id": user.id,
                "store_name": settings.STORE_NAME,
                "loja_nome": settings.STORE_NAME,
                "store_url": settings.STORE_URL or settings.FRONTEND_URL,
                "loja_url": settings.STORE_URL or settings.FRONTEND_URL,
                "link_recuperacao": _frontend_url("/recuperar-senha"),
                "dedupe_key": f"password_reset:{reset.id}",
            },
            raise_on_failure=False,
        )
        if not log and not has_admin_template:
            enviar_email_reset(email, codigo)
    except Exception:
        logger.exception("Falha ao enviar email de reset para %s", _email_mascarado(email))

    logger.info("Solicitacao de reset processada para %s", _email_mascarado(email))
    return {"mensagem": "Se o e-mail existir, você receberá o código."}


@router.post("/verificar-codigo")
def verificar_codigo(data: VerificarCodigoRequest, db: Session = Depends(get_db)):
    """Etapa 2 — verifica se o código é válido sem consumi-lo."""
    email = _normalizar_email(data.email)
    agora = datetime.now(timezone.utc)
    registros = (
        db.query(ResetSenha)
        .filter(
            ResetSenha.email == email,
            ResetSenha.usado == False,  # noqa: E712
            ResetSenha.expira_em > agora,
        )
        .all()
    )

    for r in registros:
        if verify_password(data.codigo, r.codigo_hash):
            return {"valido": True}

    raise HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail="Código inválido ou expirado.",
    )


@router.post("/redefinir-senha")
def redefinir_senha(data: RedefinirSenhaRequest, db: Session = Depends(get_db)):
    """Etapa 3 — valida código, redefine senha e invalida o registro."""
    if data.nova_senha != data.confirma_senha:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="As senhas não coincidem.",
        )

    email = _normalizar_email(data.email)
    agora = datetime.now(timezone.utc)
    registros = (
        db.query(ResetSenha)
        .filter(
            ResetSenha.email == email,
            ResetSenha.usado == False,  # noqa: E712
            ResetSenha.expira_em > agora,
        )
        .all()
    )

    registro_valido = None
    for r in registros:
        if verify_password(data.codigo, r.codigo_hash):
            registro_valido = r
            break

    if not registro_valido:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Código inválido ou expirado.",
        )

    user = _usuario_por_email(db, email)
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Usuário não encontrado.")

    user.senha_hash = get_password_hash(data.nova_senha)
    registro_valido.usado = True
    db.commit()
    try:
        EmailAutomationService(db).trigger_event(
            "password_changed",
            {
                "to": user.email,
                "email": user.email,
                "customer_name": user.nome_completo or user.username,
                "user_id": user.id,
                "store_name": settings.STORE_NAME,
                "store_url": settings.STORE_URL or settings.FRONTEND_URL,
                "dedupe_key": f"password_changed:{user.id}:{registro_valido.id}",
            },
        )
    except Exception:
        logger.exception("Falha ao disparar email de senha alterada para %s", _email_mascarado(email))

    return {"mensagem": "Senha redefinida com sucesso."}


@router.post("/logout")
def logout(response: Response):
    response.delete_cookie(key=_COOKIE_NAME, path="/", httponly=True, samesite="lax")
    return {"mensagem": "Logout realizado com sucesso."}


import secrets
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, status
from slowapi import Limiter
from slowapi.util import get_remote_address
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.usuario import Usuario
from app.models.reset_senha import ResetSenha
from app.core.security import verify_password, get_password_hash, create_access_token
from app.core.email import enviar_email_reset
from app.schemas.auth import (
    LoginRequest,
    CadastroRequest,
    RecuperarSenhaRequest,
    SolicitarRedefinicaoRequest,
    VerificarCodigoRequest,
    RedefinirSenhaRequest,
    TokenResponse,
    UsuarioBasico,
)

router = APIRouter(prefix="/auth", tags=["auth"])
limiter = Limiter(key_func=get_remote_address)


@router.post("/login", response_model=TokenResponse)
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
    token = create_access_token({"sub": user.username})
    return TokenResponse(
        access_token=token,
        usuario=UsuarioBasico.model_validate(user),
    )


@router.post("/cadastro", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
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
    token = create_access_token({"sub": user.username})
    return TokenResponse(
        access_token=token,
        usuario=UsuarioBasico.model_validate(user),
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
    user = db.query(Usuario).filter(Usuario.email == data.email).first()
    # Resposta genérica para não revelar se o e-mail existe
    if not user:
        return {"mensagem": "Se o e-mail existir, você receberá o código."}

    # Invalida códigos anteriores do mesmo e-mail
    db.query(ResetSenha).filter(
        ResetSenha.email == data.email,
        ResetSenha.usado == False,  # noqa: E712
    ).update({"usado": True})

    codigo = str(secrets.randbelow(900000) + 100000)  # 100000–999999
    expira_em = datetime.now(timezone.utc) + timedelta(minutes=15)

    reset = ResetSenha(
        email=data.email,
        codigo_hash=get_password_hash(codigo),
        expira_em=expira_em,
    )
    db.add(reset)
    db.commit()

    try:
        enviar_email_reset(data.email, codigo)
    except Exception:
        # Não expõe o erro de SMTP ao cliente
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Não foi possível enviar o e-mail. Tente novamente.",
        )

    return {"mensagem": "Se o e-mail existir, você receberá o código."}


@router.post("/verificar-codigo")
def verificar_codigo(data: VerificarCodigoRequest, db: Session = Depends(get_db)):
    """Etapa 2 — verifica se o código é válido sem consumi-lo."""
    agora = datetime.now(timezone.utc)
    registros = (
        db.query(ResetSenha)
        .filter(
            ResetSenha.email == data.email,
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

    agora = datetime.now(timezone.utc)
    registros = (
        db.query(ResetSenha)
        .filter(
            ResetSenha.email == data.email,
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

    user = db.query(Usuario).filter(Usuario.email == data.email).first()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Usuário não encontrado.")

    user.senha_hash = get_password_hash(data.nova_senha)
    registro_valido.usado = True
    db.commit()

    return {"mensagem": "Senha redefinida com sucesso."}

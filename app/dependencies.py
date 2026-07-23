import logging
from typing import Any, Optional

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session
from jose import JWTError

from app.database import get_db
from app.core.config import settings
from app.core.security import decode_token

# auto_error=False so we can fall back to the httpOnly cookie
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login", auto_error=False)
logger = logging.getLogger("app.security")


def normalize_email(email: str | None) -> str:
    return (email or "").strip().lower()


MASTER_ADMIN_EMAIL = normalize_email(settings.MASTER_ADMIN_EMAIL)


def is_master_admin_email(email: str | None) -> bool:
    return normalize_email(email) == MASTER_ADMIN_EMAIL


def is_master_admin_user(user: Any) -> bool:
    return is_master_admin_email(getattr(user, "email", None))


def is_user_active(user: Any) -> bool:
    for attr in ("ativo", "is_active", "active"):
        if hasattr(user, attr) and getattr(user, attr) is False:
            return False

    if hasattr(user, "status"):
        value = getattr(user, "status")
        if isinstance(value, str):
            return value.strip().lower() in {"ativo", "active", "enabled", "habilitado"}
        return bool(value)

    return True


def log_admin_access_denied(user: Any, route: str, reason: str) -> None:
    logger.warning(
        "Tentativa negada de acesso admin: user_id=%s email=%s rota=%s motivo=%s",
        getattr(user, "id", None),
        getattr(user, "email", None),
        route,
        reason,
    )


def get_current_user(
    request: Request,
    token: Optional[str] = Depends(oauth2_scheme),
    db: Session = Depends(get_db),
):
    from app.models.usuario import Usuario

    # Prefer Authorization header; fall back to the httpOnly session cookie.
    actual_token = token or request.cookies.get(settings.SESSION_COOKIE_NAME)

    exc = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Credenciais inválidas.",
        headers={"WWW-Authenticate": "Bearer"},
    )
    if not actual_token:
        raise exc
    try:
        payload = decode_token(actual_token)
        username: str = payload.get("sub")
        if username is None:
            raise exc
    except JWTError:
        raise exc

    user = db.query(Usuario).filter(Usuario.username == username).first()
    if user is None:
        raise exc
    return user


def get_current_master_admin_user(
    request: Request,
    current_user=Depends(get_current_user),
):
    route = request.url.path

    if not is_user_active(current_user):
        log_admin_access_denied(current_user, route, "usuario_inativo")
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Acesso restrito ao administrador mestre.",
        )

    if not is_master_admin_user(current_user):
        log_admin_access_denied(current_user, route, "email_nao_autorizado")
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Acesso restrito ao administrador mestre.",
        )

    if request.method.upper() in {"POST", "PUT", "PATCH", "DELETE"}:
        logger.info(
            "Acao admin autorizada: user_id=%s email=%s metodo=%s rota=%s",
            getattr(current_user, "id", None),
            getattr(current_user, "email", None),
            request.method.upper(),
            route,
        )

    return current_user

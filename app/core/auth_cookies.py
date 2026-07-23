import secrets

from fastapi import Response

from app.core.config import settings
from app.core.security import create_access_token
from app.models.usuario import Usuario


def _cookie_max_age() -> int:
    return settings.ACCESS_TOKEN_EXPIRE_DAYS * 24 * 60 * 60


def _cookie_options(*, httponly: bool) -> dict:
    options = {
        "httponly": httponly,
        "secure": settings.cookie_secure,
        "samesite": settings.cookie_samesite,
        "path": "/",
        "max_age": _cookie_max_age(),
    }
    if settings.cookie_domain:
        options["domain"] = settings.cookie_domain
    return options


def new_csrf_token() -> str:
    return secrets.token_urlsafe(32)


def set_csrf_cookie(response: Response, csrf_token: str | None = None) -> str:
    token = csrf_token or new_csrf_token()
    response.set_cookie(
        key=settings.CSRF_COOKIE_NAME,
        value=token,
        **_cookie_options(httponly=False),
    )
    return token


def issue_auth_cookies(response: Response, user: Usuario) -> tuple[str, str]:
    access_token = create_access_token({"sub": user.username})
    response.set_cookie(
        key=settings.SESSION_COOKIE_NAME,
        value=access_token,
        **_cookie_options(httponly=True),
    )
    csrf_token = set_csrf_cookie(response)
    return access_token, csrf_token


def clear_auth_cookies(response: Response) -> None:
    delete_options = {
        "path": "/",
        "secure": settings.cookie_secure,
        "samesite": settings.cookie_samesite,
        "httponly": True,
    }
    csrf_delete_options = {**delete_options, "httponly": False}
    if settings.cookie_domain:
        delete_options["domain"] = settings.cookie_domain
        csrf_delete_options["domain"] = settings.cookie_domain

    response.delete_cookie(key=settings.SESSION_COOKIE_NAME, **delete_options)
    response.delete_cookie(key=settings.CSRF_COOKIE_NAME, **csrf_delete_options)

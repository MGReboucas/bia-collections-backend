import hmac

from fastapi import Request

from app.core.config import settings


MUTATING_METHODS = {"POST", "PUT", "PATCH", "DELETE"}
CSRF_EXEMPT_PATHS = {
    "/api/v1/auth/login",
    "/api/v1/auth/cadastro",
    "/api/v1/auth/login/verificar-2fa",
    "/api/v1/auth/login/reenviar-2fa",
    "/api/v1/auth/recuperar-senha",
    "/api/v1/auth/solicitar-redefinicao",
    "/api/v1/auth/verificar-codigo",
    "/api/v1/auth/redefinir-senha",
    "/api/v1/pagamentos/webhook",
}


def _has_bearer_token(request: Request) -> bool:
    return request.headers.get("authorization", "").lower().startswith("bearer ")


def should_enforce_csrf(request: Request) -> bool:
    if request.method.upper() not in MUTATING_METHODS:
        return False
    if request.url.path in CSRF_EXEMPT_PATHS:
        return False
    if _has_bearer_token(request):
        return False
    return bool(request.cookies.get(settings.SESSION_COOKIE_NAME))


def csrf_is_valid(request: Request) -> bool:
    cookie_token = request.cookies.get(settings.CSRF_COOKIE_NAME)
    header_token = (
        request.headers.get("x-csrf-token")
        or request.headers.get("x-xsrf-token")
    )
    if not cookie_token or not header_token:
        return False
    return hmac.compare_digest(cookie_token, header_token)

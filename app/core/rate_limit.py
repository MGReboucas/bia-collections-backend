from collections import defaultdict, deque
from time import monotonic
from typing import Deque

from fastapi import Request
from fastapi.responses import JSONResponse

from app.core.config import settings


RateLimitRule = tuple[int, int]
_hits: dict[str, Deque[float]] = defaultdict(deque)


def clear_rate_limit_state() -> None:
    _hits.clear()


def _client_ip(request: Request) -> str:
    forwarded_for = request.headers.get("x-forwarded-for", "")
    if forwarded_for:
        return forwarded_for.split(",", 1)[0].strip()
    return request.client.host if request.client else "unknown"


def _rule_for(request: Request) -> RateLimitRule | None:
    path = request.url.path
    method = request.method.upper()

    if method == "POST" and path == "/api/v1/auth/login":
        return 10, 60
    if method == "POST" and path == "/api/v1/auth/cadastro":
        return 5, 60
    if method == "POST" and path == "/api/v1/auth/login/verificar-2fa":
        return 10, 60
    if method == "POST" and path == "/api/v1/auth/login/reenviar-2fa":
        return 5, 60
    if method == "POST" and path in {
        "/api/v1/auth/recuperar-senha",
        "/api/v1/auth/solicitar-redefinicao",
    }:
        return 3, 60
    if method == "POST" and path in {
        "/api/v1/auth/verificar-codigo",
        "/api/v1/auth/redefinir-senha",
    }:
        return 8, 60
    if method == "POST" and path.startswith("/api/v1/pagamentos/") and path != "/api/v1/pagamentos/webhook":
        return 20, 60
    if method in {"POST", "PUT", "PATCH", "DELETE"} and path.startswith("/api/v1/admin"):
        return 60, 60
    return None


def rate_limit_response_if_needed(request: Request) -> JSONResponse | None:
    if not settings.rate_limit_enabled:
        return None

    rule = _rule_for(request)
    if not rule:
        return None

    limit, window_seconds = rule
    now = monotonic()
    key = f"{_client_ip(request)}:{request.method}:{request.url.path}"
    bucket = _hits[key]

    while bucket and now - bucket[0] >= window_seconds:
        bucket.popleft()

    if len(bucket) >= limit:
        retry_after = max(1, int(window_seconds - (now - bucket[0])))
        return JSONResponse(
            status_code=429,
            content={
                "detail": "Muitas tentativas. Tente novamente em alguns segundos.",
                "retry_after_seconds": retry_after,
            },
            headers={"Retry-After": str(retry_after)},
        )

    bucket.append(now)
    return None

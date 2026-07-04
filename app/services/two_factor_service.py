import hashlib
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.security import get_password_hash, verify_password
from app.models.two_factor import TwoFactorChallenge
from app.models.usuario import Usuario


@dataclass
class CreatedTwoFactorChallenge:
    token: str
    codigo: str
    challenge: TwoFactorChallenge

    @property
    def expires_in(self) -> int:
        return settings.TWO_FACTOR_CODE_EXPIRE_SECONDS


class TwoFactorError(Exception):
    status_code = 400
    detail = "Codigo invalido ou expirado."


class TwoFactorExpiredError(TwoFactorError):
    detail = "Codigo invalido ou expirado."


class TwoFactorAttemptsExceededError(TwoFactorError):
    status_code = 429
    detail = "Limite de tentativas excedido."


class TwoFactorResendTooSoonError(TwoFactorError):
    status_code = 429
    detail = "Aguarde antes de solicitar um novo codigo."


class TwoFactorResendLimitError(TwoFactorError):
    status_code = 429
    detail = "Limite de reenvios excedido. Tente novamente mais tarde."


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def as_aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def hash_two_factor_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def generate_two_factor_code() -> str:
    return str(secrets.randbelow(900000) + 100000)


def generate_two_factor_token() -> str:
    return secrets.token_urlsafe(48)


def invalidate_user_challenges(db: Session, usuario_id: int) -> None:
    db.query(TwoFactorChallenge).filter(
        TwoFactorChallenge.usuario_id == usuario_id,
        TwoFactorChallenge.usado.is_(False),
    ).update({"usado": True}, synchronize_session=False)


def invalidate_challenge(db: Session, challenge: TwoFactorChallenge) -> None:
    challenge.usado = True
    db.commit()


def create_two_factor_challenge(
    db: Session,
    user: Usuario,
    *,
    resend_window_start: datetime | None = None,
    resend_count: int = 0,
) -> CreatedTwoFactorChallenge:
    now = utc_now()
    codigo = generate_two_factor_code()
    token = generate_two_factor_token()

    invalidate_user_challenges(db, user.id)
    challenge = TwoFactorChallenge(
        usuario_id=user.id,
        token_hash=hash_two_factor_token(token),
        codigo_hash=get_password_hash(codigo),
        expira_em=now + timedelta(seconds=settings.TWO_FACTOR_CODE_EXPIRE_SECONDS),
        usado=False,
        tentativas=0,
        ultimo_envio_em=now,
        reenvio_janela_inicio=resend_window_start or now,
        reenvios_na_janela=resend_count,
    )
    db.add(challenge)
    db.commit()
    db.refresh(challenge)

    return CreatedTwoFactorChallenge(token=token, codigo=codigo, challenge=challenge)


def get_open_challenge(db: Session, token: str) -> TwoFactorChallenge | None:
    return (
        db.query(TwoFactorChallenge)
        .filter(
            TwoFactorChallenge.token_hash == hash_two_factor_token(token),
            TwoFactorChallenge.usado.is_(False),
        )
        .first()
    )


def ensure_challenge_can_be_used(db: Session, challenge: TwoFactorChallenge | None) -> TwoFactorChallenge:
    if not challenge:
        raise TwoFactorExpiredError()

    if as_aware_utc(challenge.expira_em) <= utc_now():
        invalidate_challenge(db, challenge)
        raise TwoFactorExpiredError()

    if challenge.tentativas >= settings.TWO_FACTOR_MAX_ATTEMPTS:
        invalidate_challenge(db, challenge)
        raise TwoFactorAttemptsExceededError()

    return challenge


def verify_two_factor_code(db: Session, token: str, codigo: str) -> Usuario:
    challenge = ensure_challenge_can_be_used(db, get_open_challenge(db, token))
    user = db.query(Usuario).filter(Usuario.id == challenge.usuario_id).first()
    if not user:
        invalidate_challenge(db, challenge)
        raise TwoFactorExpiredError()

    if not verify_password(codigo, challenge.codigo_hash):
        challenge.tentativas += 1
        if challenge.tentativas >= settings.TWO_FACTOR_MAX_ATTEMPTS:
            challenge.usado = True
        db.commit()
        raise TwoFactorExpiredError()

    challenge.usado = True
    db.commit()
    db.refresh(user)
    return user


def create_resend_challenge(db: Session, token: str) -> CreatedTwoFactorChallenge:
    challenge = ensure_challenge_can_be_used(db, get_open_challenge(db, token))
    now = utc_now()
    last_sent = as_aware_utc(challenge.ultimo_envio_em)
    if now - last_sent < timedelta(seconds=settings.TWO_FACTOR_RESEND_COOLDOWN_SECONDS):
        raise TwoFactorResendTooSoonError()

    window_start = as_aware_utc(challenge.reenvio_janela_inicio)
    resend_count = challenge.reenvios_na_janela
    if now - window_start >= timedelta(hours=1):
        window_start = now
        resend_count = 0

    if resend_count >= settings.TWO_FACTOR_RESEND_HOURLY_LIMIT:
        raise TwoFactorResendLimitError()

    user = db.query(Usuario).filter(Usuario.id == challenge.usuario_id).first()
    if not user:
        invalidate_challenge(db, challenge)
        raise TwoFactorExpiredError()

    return create_two_factor_challenge(
        db,
        user,
        resend_window_start=window_start,
        resend_count=resend_count + 1,
    )

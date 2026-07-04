import importlib
import os
from pathlib import Path
from datetime import datetime, timedelta, timezone

TEST_DB_PATH = Path(__file__).resolve().parents[1] / "test_admin_security.db"
if TEST_DB_PATH.exists():
    TEST_DB_PATH.unlink()

os.environ["DATABASE_URL"] = f"sqlite:///{TEST_DB_PATH.as_posix()}"
os.environ["SECRET_KEY"] = "test-secret-key-for-admin-security-1234567890"
os.environ["MASTER_ADMIN_EMAIL"] = "reboucas444@gmail.com"

from fastapi.testclient import TestClient
import pytest

from app.core.security import create_access_token, get_password_hash, verify_password
from app.database import Base, SessionLocal, engine
from app.dependencies import MASTER_ADMIN_EMAIL
from app.models.reset_senha import ResetSenha
from app.models.two_factor import TwoFactorChallenge
from app.models.usuario import Usuario
from app.services.two_factor_service import hash_two_factor_token
from main import app

PASSWORD = "senha-segura-123"
auth_router_module = importlib.import_module("app.routers.auth")


@pytest.fixture(scope="session", autouse=True)
def cleanup_test_database_file():
    yield
    engine.dispose()
    if TEST_DB_PATH.exists():
        TEST_DB_PATH.unlink()


@pytest.fixture(autouse=True)
def reset_database():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def sent_2fa_codes(monkeypatch):
    sent: list[dict[str, str]] = []

    def fake_send(destinatario: str, codigo: str) -> None:
        sent.append({"email": destinatario, "codigo": codigo})

    auth_module = importlib.import_module("app.routers.auth")
    monkeypatch.setattr(auth_module, "enviar_email_codigo_acesso", fake_send)
    return sent


def create_user(username: str, email: str, is_admin: bool = False) -> int:
    db = SessionLocal()
    try:
        user = Usuario(
            username=username,
            email=email,
            senha_hash=get_password_hash(PASSWORD),
            is_admin=is_admin,
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        return user.id
    finally:
        db.close()


def auth_headers(username: str, extra_payload: dict | None = None) -> dict[str, str]:
    payload = {"sub": username}
    if extra_payload:
        payload.update(extra_payload)
    token = create_access_token(payload)
    return {"Authorization": f"Bearer {token}"}


def get_challenge_by_token(token: str) -> TwoFactorChallenge:
    db = SessionLocal()
    try:
        challenge = (
            db.query(TwoFactorChallenge)
            .filter(TwoFactorChallenge.token_hash == hash_two_factor_token(token))
            .first()
        )
        assert challenge is not None
        return challenge
    finally:
        db.close()


def update_challenge_by_token(token: str, **values) -> None:
    db = SessionLocal()
    try:
        db.query(TwoFactorChallenge).filter(
            TwoFactorChallenge.token_hash == hash_two_factor_token(token)
        ).update(values)
        db.commit()
    finally:
        db.close()


def test_admin_usuarios_sem_token_recebe_401(client):
    response = client.get("/api/v1/admin/usuarios")

    assert response.status_code == 401


def test_usuario_comum_recebe_403_em_admin_usuarios(client):
    create_user("cliente", "cliente@example.com")

    response = client.get("/api/v1/admin/usuarios", headers=auth_headers("cliente"))

    assert response.status_code == 403


def test_usuario_is_admin_com_email_diferente_recebe_403(client):
    create_user("admin-flag", "admin-flag@example.com", is_admin=True)

    response = client.get("/api/v1/admin/usuarios", headers=auth_headers("admin-flag"))

    assert response.status_code == 403


def test_login_com_senha_correta_envia_codigo_e_nao_retorna_token(client, sent_2fa_codes):
    create_user("cliente-2fa", "cliente-2fa@example.com")

    response = client.post(
        "/api/v1/auth/login",
        json={"login": "cliente-2fa", "senha": PASSWORD},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["requires_2fa"] is True
    assert body["email"] == "cliente-2fa@example.com"
    assert body["expires_in"] == 600
    assert "access_token" not in body
    assert sent_2fa_codes[-1]["email"] == "cliente-2fa@example.com"

    challenge = get_challenge_by_token(body["two_factor_token"])
    assert challenge.codigo_hash != sent_2fa_codes[-1]["codigo"]
    assert verify_password(sent_2fa_codes[-1]["codigo"], challenge.codigo_hash)


def test_codigo_correto_retorna_token_final(client, sent_2fa_codes):
    create_user("cliente-token", "cliente-token@example.com")
    login = client.post(
        "/api/v1/auth/login",
        json={"login": "cliente-token", "senha": PASSWORD},
    )

    response = client.post(
        "/api/v1/auth/login/verificar-2fa",
        json={
            "two_factor_token": login.json()["two_factor_token"],
            "codigo": sent_2fa_codes[-1]["codigo"],
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["access_token"]
    assert body["token_type"] == "bearer"
    assert body["usuario"]["email"] == "cliente-token@example.com"
    assert body["usuario"]["foto_url"] is None


def test_codigo_errado_nao_loga(client, sent_2fa_codes):
    create_user("cliente-errado", "cliente-errado@example.com")
    login = client.post(
        "/api/v1/auth/login",
        json={"login": "cliente-errado", "senha": PASSWORD},
    )

    response = client.post(
        "/api/v1/auth/login/verificar-2fa",
        json={"two_factor_token": login.json()["two_factor_token"], "codigo": "000000"},
    )

    assert response.status_code == 400
    assert "access_token" not in response.json()


def test_limite_de_tentativas_invalida_desafio(client, sent_2fa_codes):
    create_user("cliente-tentativas", "cliente-tentativas@example.com")
    login = client.post(
        "/api/v1/auth/login",
        json={"login": "cliente-tentativas", "senha": PASSWORD},
    )
    token = login.json()["two_factor_token"]
    correct_code = sent_2fa_codes[-1]["codigo"]

    for _ in range(5):
        response = client.post(
            "/api/v1/auth/login/verificar-2fa",
            json={"two_factor_token": token, "codigo": "000000"},
        )
        assert response.status_code == 400

    blocked = client.post(
        "/api/v1/auth/login/verificar-2fa",
        json={"two_factor_token": token, "codigo": correct_code},
    )
    assert blocked.status_code == 400
    assert "access_token" not in blocked.json()


def test_codigo_expirado_nao_loga(client, sent_2fa_codes):
    create_user("cliente-expirado", "cliente-expirado@example.com")
    login = client.post(
        "/api/v1/auth/login",
        json={"login": "cliente-expirado", "senha": PASSWORD},
    )
    update_challenge_by_token(
        login.json()["two_factor_token"],
        expira_em=datetime.now(timezone.utc) - timedelta(seconds=1),
    )

    response = client.post(
        "/api/v1/auth/login/verificar-2fa",
        json={
            "two_factor_token": login.json()["two_factor_token"],
            "codigo": sent_2fa_codes[-1]["codigo"],
        },
    )

    assert response.status_code == 400
    assert "access_token" not in response.json()


def test_reenviar_invalida_codigo_antigo(client, sent_2fa_codes):
    create_user("cliente-reenvio", "cliente-reenvio@example.com")
    login = client.post(
        "/api/v1/auth/login",
        json={"login": "cliente-reenvio", "senha": PASSWORD},
    )
    old_token = login.json()["two_factor_token"]
    old_code = sent_2fa_codes[-1]["codigo"]
    update_challenge_by_token(
        old_token,
        ultimo_envio_em=datetime.now(timezone.utc) - timedelta(seconds=61),
    )

    resend = client.post(
        "/api/v1/auth/login/reenviar-2fa",
        json={"two_factor_token": old_token},
    )

    assert resend.status_code == 200
    new_token = resend.json()["two_factor_token"]
    new_code = sent_2fa_codes[-1]["codigo"]
    assert new_token != old_token

    old_verify = client.post(
        "/api/v1/auth/login/verificar-2fa",
        json={"two_factor_token": old_token, "codigo": old_code},
    )
    assert old_verify.status_code == 400

    new_verify = client.post(
        "/api/v1/auth/login/verificar-2fa",
        json={"two_factor_token": new_token, "codigo": new_code},
    )
    assert new_verify.status_code == 200
    assert new_verify.json()["access_token"]


def test_reenviar_tem_cooldown(client, sent_2fa_codes):
    create_user("cliente-cooldown", "cliente-cooldown@example.com")
    login = client.post(
        "/api/v1/auth/login",
        json={"login": "cliente-cooldown", "senha": PASSWORD},
    )

    response = client.post(
        "/api/v1/auth/login/reenviar-2fa",
        json={"two_factor_token": login.json()["two_factor_token"]},
    )

    assert response.status_code == 429


def test_reenviar_tem_limite_por_hora(client, sent_2fa_codes):
    create_user("cliente-hourly", "cliente-hourly@example.com")
    login = client.post(
        "/api/v1/auth/login",
        json={"login": "cliente-hourly", "senha": PASSWORD},
    )
    token = login.json()["two_factor_token"]

    for _ in range(5):
        update_challenge_by_token(
            token,
            ultimo_envio_em=datetime.now(timezone.utc) - timedelta(seconds=61),
        )
        response = client.post(
            "/api/v1/auth/login/reenviar-2fa",
            json={"two_factor_token": token},
        )
        assert response.status_code == 200
        token = response.json()["two_factor_token"]

    update_challenge_by_token(
        token,
        ultimo_envio_em=datetime.now(timezone.utc) - timedelta(seconds=61),
    )
    blocked = client.post(
        "/api/v1/auth/login/reenviar-2fa",
        json={"two_factor_token": token},
    )

    assert blocked.status_code == 429


def test_cadastro_novo_exige_codigo_antes_de_entrar(client, sent_2fa_codes):
    response = client.post(
        "/api/v1/auth/cadastro",
        json={
            "username": "novo-2fa",
            "email": "novo-2fa@example.com",
            "senha": PASSWORD,
            "confirma_senha": PASSWORD,
        },
    )

    assert response.status_code == 201
    body = response.json()
    assert body["requires_2fa"] is True
    assert "access_token" not in body
    assert sent_2fa_codes[-1]["email"] == "novo-2fa@example.com"

    verified = client.post(
        "/api/v1/auth/login/verificar-2fa",
        json={
            "two_factor_token": body["two_factor_token"],
            "codigo": sent_2fa_codes[-1]["codigo"],
        },
    )

    assert verified.status_code == 200
    assert verified.json()["access_token"]
    assert verified.json()["usuario"]["email"] == "novo-2fa@example.com"


def test_master_admin_recebe_200_e_is_admin_no_login_e_perfil(client, sent_2fa_codes):
    create_user("master", MASTER_ADMIN_EMAIL)

    login = client.post(
        "/api/v1/auth/login",
        json={"login": "master", "senha": PASSWORD},
    )
    assert login.status_code == 200
    assert login.json()["requires_2fa"] is True
    assert "access_token" not in login.json()
    assert sent_2fa_codes[-1]["email"] == MASTER_ADMIN_EMAIL

    verified = client.post(
        "/api/v1/auth/login/verificar-2fa",
        json={
            "two_factor_token": login.json()["two_factor_token"],
            "codigo": sent_2fa_codes[-1]["codigo"],
        },
    )
    assert verified.status_code == 200
    assert verified.json()["usuario"]["is_admin"] is True

    token = verified.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}
    perfil = client.get("/api/v1/usuario/perfil", headers=headers)
    assert perfil.status_code == 200
    assert perfil.json()["is_admin"] is True

    usuarios = client.get("/api/v1/admin/usuarios", headers=headers)
    assert usuarios.status_code == 200


def test_solicitar_redefinicao_normaliza_email_e_envia_codigo(client, monkeypatch):
    create_user("cliente-reset", "cliente@example.com")
    enviados = []

    def fake_enviar_email(destinatario: str, codigo: str) -> None:
        enviados.append({"destinatario": destinatario, "codigo": codigo})

    monkeypatch.setattr(auth_router_module, "enviar_email_reset", fake_enviar_email)

    response = client.post(
        "/api/v1/auth/solicitar-redefinicao",
        json={"email": " Cliente@Example.com "},
    )

    assert response.status_code == 200
    assert len(enviados) == 1
    assert enviados[0]["destinatario"] == "cliente@example.com"
    assert enviados[0]["codigo"].isdigit()
    assert len(enviados[0]["codigo"]) == 6

    db = SessionLocal()
    try:
        reset = (
            db.query(ResetSenha)
            .filter(ResetSenha.email == "cliente@example.com", ResetSenha.usado.is_(False))
            .one()
        )
        assert verify_password(enviados[0]["codigo"], reset.codigo_hash)
    finally:
        db.close()


def test_solicitar_redefinicao_email_inexistente_nao_chama_smtp(client, monkeypatch):
    def fake_enviar_email(destinatario: str, codigo: str) -> None:
        raise AssertionError("SMTP nao deve ser chamado para email inexistente")

    monkeypatch.setattr(auth_router_module, "enviar_email_reset", fake_enviar_email)

    response = client.post(
        "/api/v1/auth/solicitar-redefinicao",
        json={"email": "ninguem@example.com"},
    )

    assert response.status_code == 200
    db = SessionLocal()
    try:
        assert db.query(ResetSenha).count() == 0
    finally:
        db.close()


def test_master_admin_nao_consegue_excluir_a_si_mesmo(client):
    master_id = create_user("master", MASTER_ADMIN_EMAIL, is_admin=True)

    response = client.delete(
        f"/api/v1/admin/usuarios/{master_id}",
        headers=auth_headers("master"),
    )

    assert response.status_code == 403


def test_master_admin_nao_consegue_remover_proprio_privilegio(client):
    master_id = create_user("master", MASTER_ADMIN_EMAIL, is_admin=True)

    response = client.put(
        f"/api/v1/admin/usuarios/{master_id}/admin",
        json={"is_admin": False},
        headers=auth_headers("master"),
    )

    assert response.status_code == 403


def test_master_admin_pode_alterar_e_deletar_usuario_comum(client):
    create_user("master", MASTER_ADMIN_EMAIL, is_admin=True)
    alvo_id = create_user("alvo", "alvo@example.com")
    headers = auth_headers("master")

    update = client.put(
        f"/api/v1/admin/usuarios/{alvo_id}/admin",
        json={"is_admin": True},
        headers=headers,
    )
    assert update.status_code == 200
    assert update.json()["is_admin"] is True

    delete = client.delete(f"/api/v1/admin/usuarios/{alvo_id}", headers=headers)
    assert delete.status_code == 204


def test_payload_token_e_cookie_manipulados_nao_liberam_admin(client):
    create_user("cliente", "cliente@example.com")
    headers = auth_headers(
        "cliente",
        {"email": MASTER_ADMIN_EMAIL, "is_admin": True, "role": "admin"},
    )
    client.cookies.set("cb_is_admin", "true")

    response = client.get(
        "/api/v1/admin/usuarios",
        headers=headers,
    )

    assert response.status_code == 403

import importlib
import hashlib
import hmac
import json
import os
import re
import re
from pathlib import Path
from datetime import date, datetime, timedelta, timezone

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
from app.models.avaliacao import Avaliacao
from app.models.reset_senha import ResetSenha
from app.models.banner import Banner
from app.models.cupom import Cupom, CupomResgatado, CupomUsado
from app.models.pagamento import Pagamento
from app.models.pedido import ItemPedido, Pedido
from app.models.produto import Categoria, Produto, ProdutoImagem
from app.models.two_factor import TwoFactorChallenge
from app.models.usuario import Usuario
from app.modules.email.models import (
    EmailCampaign,
    EmailCampaignRecipient,
    EmailLog,
    EmailTemplate,
    EmailTrackingEvent,
    MarketingPreference,
    ProductStockInterest,
)
from app.modules.email.seeds import (
    ADMIN_EMAIL_TEMPLATE_SEEDS,
    EMAIL_TEMPLATE_SEEDS,
    _review_portuguese_copy,
    seed_email_automation,
)
from app.modules.email.templates import password_reset_code_email
from app.modules.email.service import trigger_welcome_email_event
from app.modules.email.marketing import (
    attribute_order_conversion,
    notify_product_back_in_stock,
    set_marketing_consent,
)
from app.services.two_factor_service import hash_two_factor_token
from main import app

PASSWORD = "senha-segura-123"
PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32
JPG_BYTES = b"\xff\xd8\xff\xe0" + b"\x00" * 32
WEBP_BYTES = b"RIFF" + b"\x20\x00\x00\x00" + b"WEBP" + b"\x00" * 32
auth_router_module = importlib.import_module("app.routers.auth")
admin_module = importlib.import_module("app.routers.admin")
email_module = importlib.import_module("app.core.email")
pagamentos_module = importlib.import_module("app.routers.pagamentos")
rate_limit_module = importlib.import_module("app.core.rate_limit")


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


def create_product_review(
    *,
    produto_nome: str,
    username: str,
    email: str,
    status: str,
    mostrar_home: bool = False,
) -> tuple[int, int]:
    user_id = create_user(username, email)
    db = SessionLocal()
    try:
        produto = Produto(nome=produto_nome, descricao="Produto teste", preco=99.9)
        db.add(produto)
        db.flush()
        avaliacao = Avaliacao(
            produto_id=produto.id,
            usuario_id=user_id,
            nota=5,
            comentario=f"Avaliacao {produto_nome}",
            status=status,
            mostrar_home=mostrar_home,
        )
        db.add(avaliacao)
        db.commit()
        return produto.id, avaliacao.id
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
    assert body["resend_cooldown_seconds"] == 60
    assert "access_token" not in body
    assert sent_2fa_codes[-1]["email"] == "cliente-2fa@example.com"

    challenge = get_challenge_by_token(body["two_factor_token"])
    assert challenge.finalidade == "login"
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
    assert body["csrf_token"]
    assert body["usuario"]["email"] == "cliente-token@example.com"
    assert body["usuario"]["foto_url"] is None
    set_cookie = response.headers.get("set-cookie", "")
    assert "cb_token=" in set_cookie
    assert "HttpOnly" in set_cookie
    assert "SameSite=lax" in set_cookie
    assert "cb_csrf=" in set_cookie


def test_cookie_auth_exige_csrf_em_metodo_mutavel(client, sent_2fa_codes):
    create_user("cliente-csrf", "cliente-csrf@example.com")
    login = client.post(
        "/api/v1/auth/login",
        json={"login": "cliente-csrf", "senha": PASSWORD},
    )
    verified = client.post(
        "/api/v1/auth/login/verificar-2fa",
        json={
            "two_factor_token": login.json()["two_factor_token"],
            "codigo": sent_2fa_codes[-1]["codigo"],
        },
    )
    assert verified.status_code == 200

    blocked = client.put(
        "/api/v1/usuario/perfil",
        json={"nome_completo": "Cliente Sem CSRF"},
    )
    assert blocked.status_code == 403

    csrf_token = client.cookies.get("cb_csrf")
    allowed = client.put(
        "/api/v1/usuario/perfil",
        json={"nome_completo": "Cliente Com CSRF"},
        headers={"X-CSRF-Token": csrf_token},
    )
    assert allowed.status_code == 200
    assert allowed.json()["nome_completo"] == "Cliente Com CSRF"


def test_logout_limpa_cookies_de_auth(client, sent_2fa_codes):
    create_user("cliente-logout", "cliente-logout@example.com")
    login = client.post(
        "/api/v1/auth/login",
        json={"login": "cliente-logout", "senha": PASSWORD},
    )
    verified = client.post(
        "/api/v1/auth/login/verificar-2fa",
        json={
            "two_factor_token": login.json()["two_factor_token"],
            "codigo": sent_2fa_codes[-1]["codigo"],
        },
    )
    assert verified.status_code == 200
    assert client.cookies.get("cb_token")

    response = client.post(
        "/api/v1/auth/logout",
        headers={"X-CSRF-Token": client.cookies.get("cb_csrf")},
    )
    assert response.status_code == 200
    assert client.cookies.get("cb_token") is None
    assert client.cookies.get("cb_csrf") is None


def test_respostas_incluem_headers_de_seguranca(client):
    response = client.get("/")

    assert response.status_code == 200
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["x-frame-options"] == "DENY"
    assert "frame-ancestors 'none'" in response.headers["content-security-policy"]


def test_cors_rejeita_origem_nao_autorizada(client):
    response = client.options(
        "/api/v1/auth/login",
        headers={
            "Origin": "https://evil.example",
            "Access-Control-Request-Method": "POST",
        },
    )

    assert response.headers.get("access-control-allow-origin") is None


def test_rate_limit_retorna_429_com_retry_after(client, monkeypatch):
    rate_limit_module.clear_rate_limit_state()
    monkeypatch.setattr(rate_limit_module.settings, "RATE_LIMIT_ENABLED", True)

    for _ in range(3):
        ok = client.post(
            "/api/v1/auth/recuperar-senha",
            json={"email": "cliente-rate@example.com"},
        )
        assert ok.status_code == 200

    blocked = client.post(
        "/api/v1/auth/recuperar-senha",
        json={"email": "cliente-rate@example.com"},
    )

    assert blocked.status_code == 429
    assert blocked.headers["retry-after"]
    assert blocked.json()["retry_after_seconds"] >= 1
    rate_limit_module.clear_rate_limit_state()


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
    assert resend.json()["expires_in"] == 600
    assert resend.json()["resend_cooldown_seconds"] == 60
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
    body = response.json()
    assert body["detail"] == "Aguarde antes de solicitar um novo codigo."
    assert 1 <= body["retry_after_seconds"] <= 60
    assert response.headers["retry-after"] == str(body["retry_after_seconds"])


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


def test_envio_por_resend_usa_api_http_quando_api_key_configurada(monkeypatch):
    captured = {}

    class FakeResponse:
        status_code = 200

    class FakeClient:
        def __init__(self, timeout):
            captured["timeout"] = timeout

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return None

        def post(self, url, headers=None, json=None):
            captured["url"] = url
            captured["headers"] = headers
            captured["json"] = json
            return FakeResponse()

    monkeypatch.setattr(email_module.settings, "EMAIL_PROVIDER", "auto")
    monkeypatch.setattr(email_module.settings, "RESEND_API_KEY", "resend-key")
    monkeypatch.setattr(email_module.settings, "RESEND_API_URL", "https://api.resend.test/emails")
    monkeypatch.setattr(email_module.settings, "BREVO_API_KEY", "")
    monkeypatch.setattr(email_module.settings, "SMTP_FROM", "")
    monkeypatch.setattr(email_module.settings, "SMTP_USER", "")
    monkeypatch.setattr(email_module.settings, "EMAIL_FROM", "sender@example.com")
    monkeypatch.setattr(email_module.settings, "EMAIL_FROM_NAME", "Bia Collections")
    monkeypatch.setattr(email_module.httpx, "Client", FakeClient)

    email_module.enviar_email_codigo_acesso("cliente@example.com", "123456")

    assert captured["url"] == "https://api.resend.test/emails"
    assert captured["headers"] == {"Authorization": "Bearer resend-key"}
    assert captured["json"]["from"] == "Bia Collections <sender@example.com>"
    assert captured["json"]["to"] == ["cliente@example.com"]
    assert captured["json"]["subject"] == "Seu código de acesso - Bia Collections"
    assert 'data-bia-email-logo="true"' in captured["json"]["html"]
    assert "bia-collections-logooficial.png" in captured["json"]["html"]
    assert 'width="230"' in captured["json"]["html"]
    assert "Se você não tentou acessar ou criar uma conta" in captured["json"]["html"]
    assert "Instagram" not in captured["json"]["html"]
    assert "123456" in captured["json"]["text"]


def test_envio_por_brevo_usa_api_http_quando_configurado(monkeypatch):
    captured = {}

    class FakeResponse:
        status_code = 201

    class FakeClient:
        def __init__(self, timeout):
            captured["timeout"] = timeout

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return None

        def post(self, url, headers=None, json=None):
            captured["url"] = url
            captured["headers"] = headers
            captured["json"] = json
            return FakeResponse()

    monkeypatch.setattr(email_module.settings, "EMAIL_PROVIDER", "brevo")
    monkeypatch.setattr(email_module.settings, "BREVO_API_KEY", "brevo-key")
    monkeypatch.setattr(email_module.settings, "BREVO_API_URL", "https://api.brevo.test/v3/smtp/email")
    monkeypatch.setattr(email_module.settings, "SMTP_FROM", "")
    monkeypatch.setattr(email_module.settings, "SMTP_USER", "")
    monkeypatch.setattr(email_module.settings, "EMAIL_FROM", "sender@example.com")
    monkeypatch.setattr(email_module.settings, "EMAIL_FROM_NAME", "Bia Collections")
    monkeypatch.setattr(email_module.httpx, "Client", FakeClient)

    email_module.enviar_email_codigo_acesso("cliente@example.com", "123456")

    assert captured["url"] == "https://api.brevo.test/v3/smtp/email"
    assert captured["headers"] == {"api-key": "brevo-key"}
    assert captured["json"]["sender"] == {"name": "Bia Collections", "email": "sender@example.com"}
    assert captured["json"]["to"] == [{"email": "cliente@example.com"}]
    assert captured["json"]["subject"] == "Seu código de acesso - Bia Collections"
    assert 'data-bia-email-logo="true"' in captured["json"]["htmlContent"]
    assert "bia-collections-logooficial.png" in captured["json"]["htmlContent"]
    assert 'width="230"' in captured["json"]["htmlContent"]
    assert "Se você não tentou acessar ou criar uma conta" in captured["json"]["htmlContent"]
    assert "Instagram" not in captured["json"]["htmlContent"]
    assert "123456" in captured["json"]["textContent"]


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


def test_master_admin_cria_categoria_com_json_sem_imagem(client):
    create_user("master", MASTER_ADMIN_EMAIL, is_admin=True)

    response = client.post(
        "/api/v1/admin/categorias",
        json={"nome": "Acessorios"},
        headers=auth_headers("master"),
    )

    assert response.status_code == 201
    assert response.json() == {
        "id": response.json()["id"],
        "nome": "Acessorios",
        "imagem_url": None,
    }


def test_master_admin_cria_categoria_com_upload_de_imagem(client, monkeypatch):
    create_user("master", MASTER_ADMIN_EMAIL, is_admin=True)

    async def fake_upload_image(file, folder):
        assert file.filename == "bolsas.webp"
        assert folder == "bia-collections/categorias"
        return "https://cdn.example.test/bolsas.webp"

    monkeypatch.setattr(admin_module, "upload_image", fake_upload_image)

    response = client.post(
        "/api/v1/admin/categorias",
        data={"nome": "Bolsas"},
        files={"imagem": ("bolsas.webp", WEBP_BYTES, "image/webp")},
        headers=auth_headers("master"),
    )

    assert response.status_code == 201
    assert response.json()["nome"] == "Bolsas"
    assert response.json()["imagem_url"] == "https://cdn.example.test/bolsas.webp"

    categorias = client.get("/api/v1/categorias")
    assert categorias.status_code == 200
    assert categorias.json() == [
        {
            "id": response.json()["id"],
            "nome": "Bolsas",
            "imagem_url": "https://cdn.example.test/bolsas.webp",
        }
    ]


def test_master_admin_atualiza_categoria_sem_imagem_mantem_imagem(client, monkeypatch):
    create_user("master", MASTER_ADMIN_EMAIL, is_admin=True)
    db = SessionLocal()
    try:
        categoria = Categoria(nome="Bolsas", imagem_url="/uploads/categorias/bolsas.webp")
        db.add(categoria)
        db.commit()
        categoria_id = categoria.id
    finally:
        db.close()

    async def fail_upload_image(file, folder):
        raise AssertionError("Upload nao deve ser chamado sem nova imagem")

    def fail_delete_old_image(url):
        raise AssertionError("Imagem antiga nao deve ser removida sem substituicao")

    monkeypatch.setattr(admin_module, "upload_image", fail_upload_image)
    monkeypatch.setattr(admin_module, "delete_old_image", fail_delete_old_image)

    response = client.put(
        f"/api/v1/admin/categorias/{categoria_id}",
        data={"nome": "Bolsas Premium"},
        headers=auth_headers("master"),
    )

    assert response.status_code == 200
    assert response.json() == {
        "id": categoria_id,
        "nome": "Bolsas Premium",
        "imagem_url": "/uploads/categorias/bolsas.webp",
    }

    categorias = client.get("/api/v1/categorias")
    assert categorias.status_code == 200
    assert categorias.json() == [
        {
            "id": categoria_id,
            "nome": "Bolsas Premium",
            "imagem_url": "/uploads/categorias/bolsas.webp",
        }
    ]


def test_master_admin_atualiza_categoria_com_upload_remove_imagem_antiga(client, monkeypatch):
    create_user("master", MASTER_ADMIN_EMAIL, is_admin=True)
    db = SessionLocal()
    try:
        categoria = Categoria(nome="Vestidos", imagem_url="/uploads/categorias/antiga.webp")
        db.add(categoria)
        db.commit()
        categoria_id = categoria.id
    finally:
        db.close()

    async def fake_upload_image(file, folder):
        assert file.filename == "vestidos.png"
        assert folder == "bia-collections/categorias"
        return "/uploads/categorias/nova.png"

    removed = []

    def fake_delete_old_image(url):
        removed.append(url)

    monkeypatch.setattr(admin_module, "upload_image", fake_upload_image)
    monkeypatch.setattr(admin_module, "delete_old_image", fake_delete_old_image)

    response = client.put(
        f"/api/v1/admin/categorias/{categoria_id}",
        data={"nome": "Vestidos Festa"},
        files={"imagem": ("vestidos.png", PNG_BYTES, "image/png")},
        headers=auth_headers("master"),
    )

    assert response.status_code == 200
    assert response.json() == {
        "id": categoria_id,
        "nome": "Vestidos Festa",
        "imagem_url": "/uploads/categorias/nova.png",
    }
    assert removed == ["/uploads/categorias/antiga.webp"]


def test_master_admin_atualiza_categoria_valida_duplicidade_e_existencia(client):
    create_user("master", MASTER_ADMIN_EMAIL, is_admin=True)
    db = SessionLocal()
    try:
        bolsas = Categoria(nome="Bolsas")
        vestidos = Categoria(nome="Vestidos")
        db.add_all([bolsas, vestidos])
        db.commit()
        bolsas_id = bolsas.id
        vestidos_id = vestidos.id
    finally:
        db.close()

    headers = auth_headers("master")
    duplicate = client.put(
        f"/api/v1/admin/categorias/{bolsas_id}",
        data={"nome": "vestidos"},
        headers=headers,
    )
    missing = client.put(
        "/api/v1/admin/categorias/999999",
        data={"nome": "Nova"},
        headers=headers,
    )
    same_name = client.put(
        f"/api/v1/admin/categorias/{vestidos_id}",
        data={"nome": "Vestidos"},
        headers=headers,
    )

    assert duplicate.status_code == 409
    assert missing.status_code == 404
    assert same_name.status_code == 200
    assert same_name.json()["nome"] == "Vestidos"


def test_master_admin_cria_produto_com_galeria_de_imagens(client, monkeypatch):
    create_user("master", MASTER_ADMIN_EMAIL, is_admin=True)

    async def fake_upload_image(file, folder):
        assert folder == "bia-collections/produtos"
        return f"/uploads/produtos/{file.filename}"

    monkeypatch.setattr(admin_module, "upload_image", fake_upload_image)

    response = client.post(
        "/api/v1/admin/produtos",
        data={
            "nome": "Vestido galeria",
            "descricao": "Produto com varias imagens",
            "preco": "129.9",
            "estoque": "7",
            "tamanhos": "P,M",
            "cores": "Preto,Branco",
            "modelos_nomes": '["Preto","Branco","Caramelo"]',
            "modelo_cores": "Preto, Branco, Caramelo",
            "cores_nomes": "Preto,Branco,Caramelo",
            "ativo": "true",
        },
        files=[
            ("imagem", ("legado.webp", WEBP_BYTES, "image/webp")),
            ("imagens", ("capa.webp", WEBP_BYTES, "image/webp")),
            ("imagens", ("detalhe.png", PNG_BYTES, "image/png")),
            ("imagens", ("look.jpg", JPG_BYTES, "image/jpeg")),
        ],
        headers=auth_headers("master"),
    )

    assert response.status_code == 201
    body = response.json()
    assert body["ativo"] is True
    assert body["imagem_url"] == "/uploads/produtos/capa.webp"
    assert [imagem["imagem_url"] for imagem in body["imagens"]] == [
        "/uploads/produtos/capa.webp",
        "/uploads/produtos/detalhe.png",
        "/uploads/produtos/look.jpg",
    ]
    assert [imagem["ordem"] for imagem in body["imagens"]] == [0, 1, 2]
    assert [imagem["principal"] for imagem in body["imagens"]] == [True, False, False]
    assert [imagem["modelo_nome"] for imagem in body["imagens"]] == ["Preto", "Branco", "Caramelo"]
    assert [imagem["modelo_cor"] for imagem in body["imagens"]] == ["Preto", "Branco", "Caramelo"]
    assert [imagem["cor_nome"] for imagem in body["imagens"]] == ["Preto", "Branco", "Caramelo"]
    assert [imagem["modelo"] for imagem in body["imagens"]] == ["Preto", "Branco", "Caramelo"]
    assert [imagem["cor"] for imagem in body["imagens"]] == ["Preto", "Branco", "Caramelo"]

    produtos_admin = client.get("/api/v1/admin/produtos", headers=auth_headers("master"))
    assert produtos_admin.status_code == 200
    assert produtos_admin.json()["itens"][0]["ativo"] is True
    assert produtos_admin.json()["itens"][0]["imagens"] == body["imagens"]

    produtos_publicos = client.get("/api/v1/produtos")
    assert produtos_publicos.status_code == 200
    item = produtos_publicos.json()["itens"][0]
    assert item["ativo"] is True
    assert item["imagem_url"] == "/uploads/produtos/capa.webp"
    assert item["imagens"] == body["imagens"]

    detalhe = client.get(f"/api/v1/produtos/{body['id']}")
    assert detalhe.status_code == 200
    assert detalhe.json()["ativo"] is True
    assert detalhe.json()["imagens"] == body["imagens"]


def test_admin_produtos_retorna_estado_real_de_visibilidade(client):
    create_user("master", MASTER_ADMIN_EMAIL, is_admin=True)
    db = SessionLocal()
    try:
        produto = Produto(nome="Produto oculto", preco=19.9, ativo=False)
        db.add(produto)
        db.commit()
        produto_id = produto.id
    finally:
        db.close()

    produtos_admin = client.get("/api/v1/admin/produtos", headers=auth_headers("master"))
    assert produtos_admin.status_code == 200
    item = produtos_admin.json()["itens"][0]
    assert item["id"] == produto_id
    assert item["ativo"] is False

    produtos_publicos = client.get("/api/v1/produtos")
    assert produtos_publicos.status_code == 200
    assert produtos_publicos.json()["total"] == 0
    assert produtos_publicos.json()["itens"] == []


def test_master_admin_atualiza_produto_substitui_galeria_e_remove_antigas(client, monkeypatch):
    create_user("master", MASTER_ADMIN_EMAIL, is_admin=True)
    db = SessionLocal()
    try:
        produto = Produto(
            nome="Bolsa antiga",
            preco=199.9,
            imagem_url="/uploads/produtos/antiga-capa.webp",
            ativo=True,
            imagens=[
                ProdutoImagem(
                    imagem_url="/uploads/produtos/antiga-capa.webp",
                    ordem=0,
                    principal=True,
                ),
                ProdutoImagem(
                    imagem_url="/uploads/produtos/antigo-detalhe.webp",
                    ordem=1,
                    principal=False,
                ),
            ],
        )
        db.add(produto)
        db.commit()
        produto_id = produto.id
    finally:
        db.close()

    async def fake_upload_image(file, folder):
        assert folder == "bia-collections/produtos"
        return f"/uploads/produtos/nova-{file.filename}"

    removed = []

    def fake_delete_old_image(url):
        removed.append(url)

    monkeypatch.setattr(admin_module, "upload_image", fake_upload_image)
    monkeypatch.setattr(admin_module, "delete_old_image", fake_delete_old_image)

    response = client.put(
        f"/api/v1/admin/produtos/{produto_id}",
        data={
            "nome": "Bolsa nova",
            "descricao": "Galeria nova",
            "preco": "219.9",
            "modelos": "Preto,Caramelo",
            "modelo_cores": '["Preto","Caramelo"]',
            "cores_nomes": '["Preto","Caramelo"]',
            "ativo": "true",
        },
        files=[
            ("imagens", ("capa.webp", WEBP_BYTES, "image/webp")),
            ("imagens", ("detalhe.png", PNG_BYTES, "image/png")),
        ],
        headers=auth_headers("master"),
    )

    assert response.status_code == 200
    body = response.json()
    assert body["imagem_url"] == "/uploads/produtos/nova-capa.webp"
    assert [imagem["imagem_url"] for imagem in body["imagens"]] == [
        "/uploads/produtos/nova-capa.webp",
        "/uploads/produtos/nova-detalhe.png",
    ]
    assert [imagem["modelo_nome"] for imagem in body["imagens"]] == ["Preto", "Caramelo"]
    assert [imagem["modelo_cor"] for imagem in body["imagens"]] == ["Preto", "Caramelo"]
    assert [imagem["cor_nome"] for imagem in body["imagens"]] == ["Preto", "Caramelo"]
    assert set(removed) == {
        "/uploads/produtos/antiga-capa.webp",
        "/uploads/produtos/antigo-detalhe.webp",
    }

    db = SessionLocal()
    try:
        produto = db.query(Produto).filter(Produto.id == produto_id).one()
        assert produto.imagem_url == "/uploads/produtos/nova-capa.webp"
        assert [imagem.imagem_url for imagem in produto.imagens] == [
            "/uploads/produtos/nova-capa.webp",
            "/uploads/produtos/nova-detalhe.png",
        ]
        assert [imagem.modelo_nome for imagem in produto.imagens] == ["Preto", "Caramelo"]
        assert [imagem.modelo_cor for imagem in produto.imagens] == ["Preto", "Caramelo"]
        assert [imagem.cor_nome for imagem in produto.imagens] == ["Preto", "Caramelo"]
    finally:
        db.close()


def test_master_admin_atualiza_produto_sem_imagens_mantem_galeria(client, monkeypatch):
    create_user("master", MASTER_ADMIN_EMAIL, is_admin=True)
    db = SessionLocal()
    try:
        produto = Produto(
            nome="Produto sem troca",
            preco=89.9,
            imagem_url="/uploads/produtos/capa.webp",
            ativo=True,
            imagens=[
                ProdutoImagem(
                    imagem_url="/uploads/produtos/capa.webp",
                    ordem=0,
                    principal=True,
                )
            ],
        )
        db.add(produto)
        db.commit()
        produto_id = produto.id
    finally:
        db.close()

    async def fail_upload_image(file, folder):
        raise AssertionError("Upload nao deve ser chamado sem novas imagens")

    def fail_delete_old_image(url):
        raise AssertionError("Imagem antiga nao deve ser removida sem substituicao")

    monkeypatch.setattr(admin_module, "upload_image", fail_upload_image)
    monkeypatch.setattr(admin_module, "delete_old_image", fail_delete_old_image)

    response = client.put(
        f"/api/v1/admin/produtos/{produto_id}",
        data={
            "nome": "Produto renomeado",
            "descricao": "Sem trocar imagem",
            "preco": "99.9",
            "ativo": "true",
        },
        headers=auth_headers("master"),
    )

    assert response.status_code == 200
    body = response.json()
    assert body["nome"] == "Produto renomeado"
    assert body["imagem_url"] == "/uploads/produtos/capa.webp"
    assert [imagem["imagem_url"] for imagem in body["imagens"]] == [
        "/uploads/produtos/capa.webp"
    ]
    assert body["imagens"][0]["modelo_nome"] is None
    assert body["imagens"][0]["modelo_cor"] is None
    assert body["imagens"][0]["cor_nome"] is None
    assert body["imagens"][0]["modelo"] is None
    assert body["imagens"][0]["cor"] is None


def test_master_admin_atualiza_produto_preserva_descricao_e_salva_metadata_por_url(client, monkeypatch):
    create_user("master", MASTER_ADMIN_EMAIL, is_admin=True)
    db = SessionLocal()
    try:
        categoria = Categoria(nome="Acessorios")
        db.add(categoria)
        db.flush()
        produto = Produto(
            nome="Relogio modelos",
            descricao="Descricao publica preenchida",
            preco=189.9,
            preco_promocional=169.9,
            estoque=5,
            categoria_id=categoria.id,
            tamanhos=json.dumps(["Unico"]),
            cores=json.dumps(["Branco", "Cinza", "Dourado", "Marrom", "Preto"]),
            imagem_url="/uploads/produtos/relogio-branco.webp",
            ativo=True,
            imagens=[
                ProdutoImagem(
                    imagem_url="/uploads/produtos/relogio-branco.webp",
                    ordem=0,
                    principal=True,
                    modelo_nome="Branco",
                    cor_nome="Branco",
                ),
                ProdutoImagem(
                    imagem_url="/uploads/produtos/relogio-dourado.webp",
                    ordem=1,
                    principal=False,
                    modelo_nome="Cinza",
                    cor_nome="Cinza",
                ),
            ],
        )
        db.add(produto)
        db.commit()
        produto_id = produto.id
        categoria_id = categoria.id
    finally:
        db.close()

    def fail_delete_old_image(url):
        raise AssertionError("Imagem mantida nao deve ser removida")

    monkeypatch.setattr(admin_module, "delete_old_image", fail_delete_old_image)

    response = client.put(
        f"/api/v1/admin/produtos/{produto_id}",
        data={
            "nome": "Relogio modelos editado",
            "descricao": "",
            "preco": "199.9",
            "preco_promocional": "159.9",
            "estoque": "12",
            "categoria_id": str(categoria_id),
            "tamanhos": "Unico,Ajustavel",
            "cores": "Branco,Cinza,Dourado,Marrom,Preto",
            "ativo": "true",
            "imagens_manter": json.dumps(
                [
                    "https://loja.example.test/uploads/produtos/relogio-branco.webp",
                    "/uploads/produtos/relogio-dourado.webp",
                ]
            ),
            "capa_url": "https://loja.example.test/uploads/produtos/relogio-dourado.webp",
            "imagens_metadata": json.dumps(
                [
                    {
                        "url": "https://loja.example.test/uploads/produtos/relogio-branco.webp",
                        "ordem": 0,
                        "principal": False,
                        "modelo": "Branco",
                        "cor": "Branco",
                    },
                    {
                        "url": "https://loja.example.test/uploads/produtos/relogio-dourado.webp",
                        "ordem": 1,
                        "principal": True,
                        "modelo": "Dourado",
                        "cor": "Dourado",
                    },
                ]
            ),
        },
        headers=auth_headers("master"),
    )

    assert response.status_code == 200
    body = response.json()
    assert body["descricao"] == "Descricao publica preenchida"
    assert body["preco_promocional"] == 159.9
    assert body["estoque"] == 12
    assert body["categoria"] == "Acessorios"
    assert body["tamanhos"] == ["Unico", "Ajustavel"]
    assert body["cores"] == ["Branco", "Cinza", "Dourado", "Marrom", "Preto"]
    assert body["imagem_url"] == "/uploads/produtos/relogio-dourado.webp"
    assert [imagem["imagem_url"] for imagem in body["imagens"]] == [
        "/uploads/produtos/relogio-branco.webp",
        "/uploads/produtos/relogio-dourado.webp",
    ]
    assert [imagem["ordem"] for imagem in body["imagens"]] == [0, 1]
    assert [imagem["principal"] for imagem in body["imagens"]] == [False, True]
    assert body["imagens"][1]["modelo"] == "Dourado"
    assert body["imagens"][1]["cor"] == "Dourado"

    detalhe = client.get(f"/api/v1/produtos/{produto_id}")
    assert detalhe.status_code == 200
    detalhe_body = detalhe.json()
    assert detalhe_body["descricao"] == "Descricao publica preenchida"
    assert detalhe_body["imagens"] == body["imagens"]

    db = SessionLocal()
    try:
        produto = db.query(Produto).filter(Produto.id == produto_id).one()
        assert produto.descricao == "Descricao publica preenchida"
        assert produto.preco_promocional == 159.9
        assert produto.estoque == 12
        assert json.loads(produto.tamanhos) == ["Unico", "Ajustavel"]
        assert json.loads(produto.cores) == ["Branco", "Cinza", "Dourado", "Marrom", "Preto"]
        imagens = sorted(produto.imagens, key=lambda imagem: imagem.ordem)
        assert imagens[1].imagem_url == "/uploads/produtos/relogio-dourado.webp"
        assert imagens[1].modelo_nome == "Dourado"
        assert imagens[1].cor_nome == "Dourado"
        assert imagens[1].principal is True
    finally:
        db.close()


def test_master_admin_valida_limite_tipo_e_tamanho_das_imagens(client, monkeypatch):
    create_user("master", MASTER_ADMIN_EMAIL, is_admin=True)

    async def fail_upload_image(file, folder):
        raise AssertionError("Upload nao deve ocorrer quando a validacao falha")

    monkeypatch.setattr(admin_module, "upload_image", fail_upload_image)
    headers = auth_headers("master")
    data = {"nome": "Produto invalido", "preco": "10", "ativo": "true"}

    too_many = client.post(
        "/api/v1/admin/produtos",
        data=data,
        files=[
            ("imagens", (f"imagem-{index}.webp", WEBP_BYTES, "image/webp"))
            for index in range(11)
        ],
        headers=headers,
    )
    assert too_many.status_code == 422
    assert "maximo 10 imagens" in too_many.json()["detail"]

    invalid_type = client.post(
        "/api/v1/admin/produtos",
        data=data,
        files={"imagens": ("arquivo.txt", b"text", "text/plain")},
        headers=headers,
    )
    assert invalid_type.status_code == 422
    assert "formato invalido" in invalid_type.json()["detail"]

    invalid_content = client.post(
        "/api/v1/admin/produtos",
        data=data,
        files={"imagens": ("fake.png", b"not a real image", "image/png")},
        headers=headers,
    )
    assert invalid_content.status_code == 422
    assert "imagem" in invalid_content.json()["detail"].lower()

    oversized = client.post(
        "/api/v1/admin/produtos",
        data=data,
        files={
            "imagens": (
                "grande.webp",
                b"x" * (admin_module.MAX_SIZE + 1),
                "image/webp",
            )
        },
        headers=headers,
    )
    assert oversized.status_code == 422
    assert "5 MB" in oversized.json()["detail"]


def test_master_admin_atualiza_produto_valida_limite_total_da_galeria(client, monkeypatch):
    create_user("master", MASTER_ADMIN_EMAIL, is_admin=True)
    image_urls = [f"/uploads/produtos/existente-{index}.webp" for index in range(9)]
    db = SessionLocal()
    try:
        produto = Produto(
            nome="Produto galeria limite",
            preco=59.9,
            imagem_url=image_urls[0],
            ativo=True,
            imagens=[
                ProdutoImagem(
                    imagem_url=image_url,
                    ordem=index,
                    principal=index == 0,
                )
                for index, image_url in enumerate(image_urls)
            ],
        )
        db.add(produto)
        db.commit()
        produto_id = produto.id
    finally:
        db.close()

    async def fail_upload_image(file, folder):
        raise AssertionError("Upload nao deve ocorrer quando a validacao falha")

    monkeypatch.setattr(admin_module, "upload_image", fail_upload_image)

    response = client.put(
        f"/api/v1/admin/produtos/{produto_id}",
        data={
            "nome": "Produto galeria limite",
            "preco": "59.9",
            "ativo": "true",
            "imagens_manter": json.dumps(image_urls),
        },
        files=[
            ("imagens", ("nova-1.webp", WEBP_BYTES, "image/webp")),
            ("imagens", ("nova-2.webp", WEBP_BYTES, "image/webp")),
        ],
        headers=auth_headers("master"),
    )

    assert response.status_code == 422
    assert "maximo 10 imagens" in response.json()["detail"]


def test_listar_produtos_filtra_categoria_por_slug_normalizado(client):
    db = SessionLocal()
    try:
        categoria = Categoria(nome="\u00d3culos")
        outra_categoria = Categoria(nome="Bolsas")
        db.add_all([categoria, outra_categoria])
        db.flush()
        db.add_all([
            Produto(
                nome="Oculos teste",
                preco=89.9,
                categoria_id=categoria.id,
                ativo=True,
            ),
            Produto(
                nome="Bolsa teste",
                preco=129.9,
                categoria_id=outra_categoria.id,
                ativo=True,
            ),
        ])
        db.commit()
    finally:
        db.close()

    response = client.get("/api/v1/produtos?categoria=oculos")

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert body["itens"][0]["nome"] == "Oculos teste"
    assert body["itens"][0]["categoria"] == "\u00d3culos"


def test_master_admin_nao_exclui_categoria_com_produto_ativo(client):
    create_user("master", MASTER_ADMIN_EMAIL, is_admin=True)
    db = SessionLocal()
    try:
        categoria = Categoria(nome="Bolsas")
        db.add(categoria)
        db.flush()
        db.add(
            Produto(
                nome="Bolsa teste",
                preco=99.9,
                categoria_id=categoria.id,
                ativo=True,
            )
        )
        db.commit()
        categoria_id = categoria.id
    finally:
        db.close()

    response = client.delete(
        f"/api/v1/admin/categorias/{categoria_id}",
        headers=auth_headers("master"),
    )

    assert response.status_code == 409


def test_master_admin_exclui_categoria_depois_de_soft_delete_dos_produtos(client):
    create_user("master", MASTER_ADMIN_EMAIL, is_admin=True)
    db = SessionLocal()
    try:
        categoria = Categoria(nome="Vestidos")
        db.add(categoria)
        db.flush()
        produto = Produto(
            nome="Vestido teste",
            preco=129.9,
            categoria_id=categoria.id,
            ativo=True,
        )
        db.add(produto)
        db.commit()
        categoria_id = categoria.id
        produto_id = produto.id
    finally:
        db.close()

    headers = auth_headers("master")
    delete_produto = client.delete(
        f"/api/v1/admin/produtos/{produto_id}",
        headers=headers,
    )
    delete_categoria = client.delete(
        f"/api/v1/admin/categorias/{categoria_id}",
        headers=headers,
    )

    assert delete_produto.status_code == 204
    assert delete_categoria.status_code == 204

    db = SessionLocal()
    try:
        produto = db.query(Produto).filter(Produto.id == produto_id).one()
        assert produto.ativo is False
        assert produto.categoria_id is None
        assert db.query(Categoria).filter(Categoria.id == categoria_id).first() is None
    finally:
        db.close()


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


def test_criar_pedido_inclui_frete_e_cupom_frete(client):
    create_user("cliente-pedido", "cliente-pedido@example.com")
    db = SessionLocal()
    try:
        produto = Produto(nome="Bolsa checkout", preco=100.0, ativo=True)
        cupom = Cupom(
            codigo="FRETE",
            descricao="Frete gratis",
            tipo="frete",
            valor=0.0,
            validade=datetime.now(timezone.utc).date() + timedelta(days=1),
            ativo=True,
        )
        db.add_all([produto, cupom])
        db.commit()
        produto_id = produto.id
    finally:
        db.close()

    response = client.post(
        "/api/v1/pedidos",
        json={
            "itens": [{"produto_id": produto_id, "quantidade": 1}],
            "endereco": {
                "cep": "01001-000",
                "rua": "Rua Teste",
                "numero": "10",
                "bairro": "Centro",
                "cidade": "Sao Paulo",
                "estado": "SP",
            },
            "forma_pagamento": "pix",
            "frete": {"nome": "PAC", "prazo": "7 a 10 dias", "valor": 12.9},
            "cupom_codigo": "FRETE",
        },
        headers=auth_headers("cliente-pedido"),
    )

    assert response.status_code == 201
    body = response.json()
    assert body["subtotal"] == 100.0
    assert body["valor_frete"] == 0.0
    assert body["desconto_aplicado"] == 12.9
    assert body["total"] == 100.0

    db = SessionLocal()
    try:
        pedido = db.query(Pedido).filter(Pedido.numero == body["numero_pedido"]).one()
        assert pedido.subtotal == 100.0
        assert pedido.valor_frete == 0.0
        assert pedido.tipo_frete == "PAC"
        assert pedido.prazo_frete == "7 a 10 dias"
        assert db.query(CupomUsado).count() == 0
        assert db.query(Cupom).filter(Cupom.codigo == "FRETE").one().total_usos == 0
    finally:
        db.close()


def test_criar_pedido_persiste_campos_meta_opcionais_sem_expor_na_resposta(client):
    create_user("cliente-meta-pedido", "cliente-meta-pedido@example.com")
    db = SessionLocal()
    try:
        produto = Produto(nome="Bolsa Meta", preco=89.9, ativo=True)
        db.add(produto)
        db.commit()
        produto_id = produto.id
    finally:
        db.close()

    response = client.post(
        "/api/v1/pedidos",
        json={
            "itens": [{"produto_id": produto_id, "quantidade": 1}],
            "endereco": {
                "cep": "01001-000",
                "rua": "Rua Teste",
                "numero": "10",
                "bairro": "Centro",
                "cidade": "Sao Paulo",
                "estado": "SP",
            },
            "forma_pagamento": "pix",
            "frete": {"nome": "PAC", "prazo": "7 a 10 dias", "valor": 0.0},
            "cupom_codigo": None,
            "meta_event_id": "evt-pedido-123",
            "meta_source_url": "https://www.biacollections.com/checkout",
            "client_user_agent": "Mozilla/5.0 Test",
        },
        headers={
            **auth_headers("cliente-meta-pedido"),
            "x-forwarded-for": "198.51.100.10",
        },
    )

    assert response.status_code == 201
    body = response.json()
    assert "meta_event_id" not in body
    assert "meta_fbp" not in body
    assert "meta_fbc" not in body

    db = SessionLocal()
    try:
        pedido = db.query(Pedido).filter(Pedido.numero == body["numero_pedido"]).one()
        assert pedido.meta_event_id == "evt-pedido-123"
        assert pedido.meta_fbp is None
        assert pedido.meta_fbc is None
        assert pedido.meta_source_url == "https://www.biacollections.com/checkout"
        assert pedido.client_user_agent == "Mozilla/5.0 Test"
        assert pedido.client_ip_address == "198.51.100.10"
        assert pedido.meta_purchase_enviado_em is None
    finally:
        db.close()


def test_cliente_valida_cupom_por_codigo_e_adicionar_fica_compatibilidade(client):
    create_user("cliente-cupom", "cliente-cupom@example.com")
    create_user("outra-cliente-cupom", "outra-cliente-cupom@example.com")
    db = SessionLocal()
    try:
        db.add(
            Cupom(
                codigo="SOCIAL15",
                descricao="Cupom divulgado nas redes sociais",
                tipo="porcentagem",
                valor=15.0,
                validade=datetime.now(timezone.utc).date() + timedelta(days=5),
                ativo=True,
                valor_minimo_pedido=50.0,
            )
        )
        db.commit()
    finally:
        db.close()

    headers = auth_headers("cliente-cupom")
    sem_resgate = client.get("/api/v1/cupons", headers=headers)
    assert sem_resgate.status_code == 200
    assert sem_resgate.json() == {"ativos": [], "usados": []}

    validacao_antes = client.post(
        "/api/v1/cupons/validar",
        json={"codigo": "SOCIAL15", "total": 100.0},
        headers=headers,
    )
    assert validacao_antes.status_code == 200
    assert validacao_antes.json()["valido"] is True
    assert validacao_antes.json()["valor_desconto"] == 15.0
    assert validacao_antes.json()["total_com_desconto"] == 85.0

    sem_login = client.post("/api/v1/cupons/adicionar", json={"codigo": "SOCIAL15"})
    assert sem_login.status_code == 401

    adicionado = client.post(
        "/api/v1/cupons/adicionar",
        json={"codigo": "  social15  "},
        headers=headers,
    )
    assert adicionado.status_code == 200
    assert adicionado.json()["ja_adicionado"] is False
    assert adicionado.json()["cupom"]["codigo"] == "SOCIAL15"
    assert adicionado.json()["cupom"]["valor_minimo_pedido"] == 50.0

    repetido = client.post(
        "/api/v1/cupons/adicionar",
        json={"codigo": "SOCIAL15"},
        headers=headers,
    )
    assert repetido.status_code == 200
    assert repetido.json()["ja_adicionado"] is True

    carteira = client.get("/api/v1/cupons", headers=headers)
    assert carteira.status_code == 200
    assert [cupom["codigo"] for cupom in carteira.json()["ativos"]] == ["SOCIAL15"]

    outra_carteira = client.get(
        "/api/v1/cupons",
        headers=auth_headers("outra-cliente-cupom"),
    )
    assert outra_carteira.status_code == 200
    assert outra_carteira.json()["ativos"] == []

    outra_validacao = client.post(
        "/api/v1/cupons/validar",
        json={"codigo": "SOCIAL15", "total": 100.0},
        headers=auth_headers("outra-cliente-cupom"),
    )
    assert outra_validacao.status_code == 200
    assert outra_validacao.json()["valido"] is True
    assert outra_validacao.json()["valor_desconto"] == 15.0

    validacao_depois = client.post(
        "/api/v1/cupons/validar",
        json={"codigo": "SOCIAL15", "total": 100.0},
        headers=headers,
    )
    assert validacao_depois.status_code == 200
    assert validacao_depois.json()["valido"] is True
    assert validacao_depois.json()["valor_desconto"] == 15.0


def test_criar_pedido_revalida_cupom_codigo_antes_de_aplicar(client):
    create_user("cliente-cupom-revalidacao", "cliente-cupom-revalidacao@example.com")
    db = SessionLocal()
    try:
        produto = Produto(nome="Bolsa revalidacao", preco=100.0, ativo=True)
        cupom = Cupom(
            codigo="MUDOU10",
            descricao="Cupom alterado depois da validacao",
            tipo="valor",
            valor=10.0,
            validade=datetime.now(timezone.utc).date() + timedelta(days=1),
            ativo=True,
        )
        db.add_all([produto, cupom])
        db.commit()
        produto_id = produto.id
    finally:
        db.close()

    headers = auth_headers("cliente-cupom-revalidacao")
    validacao = client.post(
        "/api/v1/cupons/validar",
        json={"codigo": "MUDOU10", "total": 100.0},
        headers=headers,
    )
    assert validacao.status_code == 200
    assert validacao.json()["valido"] is True

    db = SessionLocal()
    try:
        db.query(Cupom).filter(Cupom.codigo == "MUDOU10").update({"ativo": False})
        db.commit()
    finally:
        db.close()

    response = client.post(
        "/api/v1/pedidos",
        json={
            "itens": [{"produto_id": produto_id, "quantidade": 1}],
            "endereco": {
                "cep": "01001-000",
                "rua": "Rua Teste",
                "numero": "10",
                "bairro": "Centro",
                "cidade": "Sao Paulo",
                "estado": "SP",
            },
            "forma_pagamento": "pix",
            "frete": {"nome": "PAC", "prazo": "7 a 10 dias", "valor": 0.0},
            "cupom_codigo": "MUDOU10",
        },
        headers=headers,
    )

    assert response.status_code == 422
    assert "inativo" in response.json()["detail"].lower()
    db = SessionLocal()
    try:
        assert db.query(Pedido).count() == 0
    finally:
        db.close()


@pytest.mark.parametrize(
    ("codigo", "ativo", "dias_validade"),
    [
        ("INATIVO", False, 5),
        ("EXPIRADO", True, -1),
    ],
)
def test_cliente_nao_adiciona_cupom_indisponivel(client, codigo, ativo, dias_validade):
    username = f"cliente-{codigo.lower()}"
    create_user(username, f"{codigo.lower()}@example.com")
    db = SessionLocal()
    try:
        db.add(
            Cupom(
                codigo=codigo,
                descricao="Cupom indisponivel",
                tipo="valor",
                valor=10.0,
                validade=datetime.now(timezone.utc).date() + timedelta(days=dias_validade),
                ativo=ativo,
            )
        )
        db.commit()
    finally:
        db.close()

    response = client.post(
        "/api/v1/cupons/adicionar",
        json={"codigo": codigo},
        headers=auth_headers(username),
    )

    assert response.status_code == 422
    assert "inativo, expirado ou esgotado" in response.json()["detail"]


def test_criar_pedido_usa_preco_promocional_quando_existir(client):
    create_user("cliente-promo", "cliente-promo@example.com")
    db = SessionLocal()
    try:
        produto = Produto(
            nome="Bolsa promo",
            preco=149.9,
            preco_promocional=1.5,
            ativo=True,
        )
        db.add(produto)
        db.commit()
        produto_id = produto.id
    finally:
        db.close()

    response = client.post(
        "/api/v1/pedidos",
        json={
            "itens": [{"produto_id": produto_id, "quantidade": 2}],
            "endereco": {
                "cep": "01001-000",
                "rua": "Rua Teste",
                "numero": "10",
                "bairro": "Centro",
                "cidade": "Sao Paulo",
                "estado": "SP",
            },
            "forma_pagamento": "pix",
            "frete": {"nome": "PAC", "prazo": "7 a 10 dias", "valor": 26.9},
        },
        headers=auth_headers("cliente-promo"),
    )

    assert response.status_code == 201
    body = response.json()
    assert body["subtotal"] == 3.0
    assert body["valor_frete"] == 26.9
    assert body["total"] == pytest.approx(29.9)

    db = SessionLocal()
    try:
        pedido = db.query(Pedido).filter(Pedido.numero == body["numero_pedido"]).one()
        assert pedido.subtotal == 3.0
        assert pedido.total == pytest.approx(29.9)
        assert pedido.itens[0].preco_unitario == 1.5
    finally:
        db.close()


def test_admin_pedidos_oculta_pagamentos_pendentes_por_padrao(client):
    create_user("master", MASTER_ADMIN_EMAIL, is_admin=True)
    cliente_id = create_user("cliente-admin-pedidos", "cliente-admin-pedidos@example.com")
    db = SessionLocal()
    try:
        db.add_all(
            [
                Pedido(
                    numero="0000100",
                    usuario_id=cliente_id,
                    status="Aguardando pagamento",
                    forma_pagamento="pix",
                    subtotal=50.0,
                    valor_frete=0.0,
                    total=50.0,
                ),
                Pedido(
                    numero="0000101",
                    usuario_id=cliente_id,
                    status="Pagamento aprovado",
                    forma_pagamento="pix",
                    subtotal=75.0,
                    valor_frete=0.0,
                    total=75.0,
                ),
            ]
        )
        db.add(
            Pagamento(
                pedido_numero="0000101",
                tipo="pix",
                valor=75.0,
                status="aprovado",
                mp_status="approved",
                mp_payment_id="pay_admin_1",
            )
        )
        db.commit()
    finally:
        db.close()

    headers = auth_headers("master")
    padrao = client.get("/api/v1/admin/pedidos", headers=headers)
    com_pendentes = client.get("/api/v1/admin/pedidos?incluir_pendentes=true", headers=headers)

    assert padrao.status_code == 200
    assert [pedido["numero"] for pedido in padrao.json()] == ["0000101"]
    assert padrao.json()[0]["pagamento"]["status"] == "aprovado"
    assert com_pendentes.status_code == 200
    assert {pedido["numero"] for pedido in com_pendentes.json()} == {"0000100", "0000101"}


def test_pagamento_pix_reutiliza_qr_code_pendente(client, monkeypatch):
    create_user("cliente-pix", "cliente-pix@example.com")
    db = SessionLocal()
    try:
        user = db.query(Usuario).filter(Usuario.username == "cliente-pix").one()
        pedido = Pedido(
            numero="0000001",
            usuario_id=user.id,
            status="Aguardando pagamento",
            forma_pagamento="pix",
            subtotal=50.0,
            valor_frete=10.0,
            total=60.0,
        )
        db.add(pedido)
        db.commit()
    finally:
        db.close()

    pagamentos_module = importlib.import_module("app.routers.pagamentos")
    creates = []

    def fake_criar_order_pix_mp(payload, idempotency_key):
        creates.append(payload)
        return 201, {
            "id": "ord_pix_1",
            "status": "action_required",
            "transactions": {
                "payments": [
                    {
                        "id": "pay_pix_1",
                        "status": "action_required",
                        "payment_method": {
                            "id": "pix",
                            "type": "bank_transfer",
                            "qr_code": "pix-copia-e-cola",
                            "qr_code_base64": "base64",
                        },
                    }
                ]
            },
        }

    monkeypatch.setattr(pagamentos_module.settings, "MP_ACCESS_TOKEN", "token")
    monkeypatch.setattr(pagamentos_module.settings, "MP_NOTIFICATION_URL", "https://api.example.test")
    monkeypatch.setattr(pagamentos_module, "_criar_order_pix_mp", fake_criar_order_pix_mp)
    email_events = []
    monkeypatch.setattr(
        pagamentos_module,
        "trigger_order_email_event",
        lambda *args, **kwargs: email_events.append((args, kwargs)),
    )

    headers = auth_headers("cliente-pix")
    first = client.post("/api/v1/pagamentos/pix/0000001", headers=headers)
    second = client.post("/api/v1/pagamentos/pix/0000001", headers=headers)

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["payment_id"] == "pay_pix_1"
    assert second.json()["payment_id"] == "pay_pix_1"
    assert len(creates) == 1
    assert creates[0]["total_amount"] == "60.00"
    assert creates[0]["external_reference"] == "0000001"
    assert creates[0]["payer"] == {"email": "cliente-pix@example.com"}
    assert "notification_url" not in creates[0]
    assert "metadata" not in creates[0]
    payment = creates[0]["transactions"]["payments"][0]
    assert payment["amount"] == "60.00"
    assert payment["payment_method"] == {"id": "pix", "type": "bank_transfer"}
    assert len(email_events) == 1
    assert email_events[0][0][1] == "payment_pending"
    assert email_events[0][0][2].numero == "0000001"

    db = SessionLocal()
    try:
        pagamento = db.query(Pagamento).filter(Pagamento.pedido_numero == "0000001").one()
        assert pagamento.mp_order_id == "ord_pix_1"
        assert pagamento.mp_payment_id == "pay_pix_1"
    finally:
        db.close()


def test_pagamento_pix_traduz_erro_credenciais_live():
    pagamentos_module = importlib.import_module("app.routers.pagamentos")

    message = pagamentos_module._mensagem_erro_mp({
        "message": "Unauthorized use of live credentials",
    }, fluxo="pix")

    assert "credenciais de producao" in message
    assert "comprador real diferente" in message
    assert "Unauthorized use of live credentials" in message


def test_pagamento_cartao_traduz_erro_credenciais_live_sem_mencionar_pix():
    pagamentos_module = importlib.import_module("app.routers.pagamentos")

    message = pagamentos_module._mensagem_erro_mp({
        "message": "Unauthorized use of live credentials",
    }, fluxo="cartao")

    assert "order de cartao" in message
    assert "Checkout Transparente via Orders" in message
    assert "gerar PIX" not in message
    assert "Unauthorized use of live credentials" in message


def test_pagamento_cartao_aprovado_cria_payload_e_atualiza_pedido(client, monkeypatch):
    create_user("cliente-cartao", "cliente-cartao@example.com")
    db = SessionLocal()
    try:
        user = db.query(Usuario).filter(Usuario.username == "cliente-cartao").one()
        pedido = Pedido(
            numero="0000003",
            usuario_id=user.id,
            status="Aguardando pagamento",
            forma_pagamento="cartao",
            subtotal=100.0,
            valor_frete=12.5,
            total=112.5,
        )
        db.add(pedido)
        db.commit()
    finally:
        db.close()

    pagamentos_module = importlib.import_module("app.routers.pagamentos")
    creates = []

    def fake_criar_order_cartao_mp(payload, idempotency_key):
        creates.append({"payload": payload, "idempotency_key": idempotency_key})
        return 201, {
            "id": "ord_card_approved",
            "status": "processed",
            "status_detail": "accredited",
            "external_reference": "0000003",
            "total_amount": "112.50",
            "transactions": {
                "payments": [
                    {
                        "id": "pay_card_approved",
                        "amount": "112.50",
                        "status": "processed",
                        "status_detail": "accredited",
                        "payment_method": {
                            "id": "visa",
                            "type": "credit_card",
                            "installments": 2,
                        },
                    }
                ]
            },
        }

    email_events = []
    monkeypatch.setattr(pagamentos_module.settings, "MP_ACCESS_TOKEN", "token")
    monkeypatch.setattr(pagamentos_module.settings, "MP_NOTIFICATION_URL", "https://api.example.test")
    monkeypatch.setattr(pagamentos_module, "_criar_order_cartao_mp", fake_criar_order_cartao_mp)
    monkeypatch.setattr(
        pagamentos_module,
        "trigger_order_email_event",
        lambda db, event_key, pedido: email_events.append((event_key, pedido.numero)),
    )

    payload = {
        "token": "card-token",
        "payment_method_id": "visa",
        "issuer_id": "25",
        "installments": 2,
        "transaction_amount": 112.5,
        "payer": {
            "email": "pagador@example.com",
            "identification": {"type": "CPF", "number": "12345678909"},
        },
    }
    response = client.post(
        "/api/v1/pagamentos/cartao/0000003",
        json=payload,
        headers=auth_headers("cliente-cartao"),
    )

    assert response.status_code == 200
    body = response.json()
    assert body == {
        "payment_id": "pay_card_approved",
        "status": "aprovado",
        "mp_status": "processed",
        "status_detail": "accredited",
        "status_pedido": "Pagamento aprovado",
        "payment_method_id": "visa",
    }
    assert len(creates) == 1
    mp_payload = creates[0]["payload"]
    assert mp_payload["type"] == "online"
    assert mp_payload["processing_mode"] == "automatic"
    assert mp_payload["capture_mode"] == "automatic"
    assert mp_payload["total_amount"] == "112.50"
    assert mp_payload["description"] == "Bia Collections - Pedido 0000003"
    assert mp_payload["payer"] == payload["payer"]
    assert mp_payload["external_reference"] == "0000003"
    assert "notification_url" not in mp_payload
    payment_method = mp_payload["transactions"]["payments"][0]["payment_method"]
    assert mp_payload["transactions"]["payments"][0]["amount"] == "112.50"
    assert payment_method == {
        "id": "visa",
        "type": "credit_card",
        "token": "card-token",
        "installments": 2,
    }

    db = SessionLocal()
    try:
        pedido = db.query(Pedido).filter(Pedido.numero == "0000003").one()
        pagamento = db.query(Pagamento).filter(Pagamento.pedido_numero == "0000003").one()
        assert pedido.status == "Pagamento aprovado"
        assert pagamento.tipo == "cartao"
        assert pagamento.valor == 112.5
        assert pagamento.status == "aprovado"
        assert pagamento.mp_status == "processed"
        assert pagamento.mp_payment_id == "pay_card_approved"
        assert pagamento.mp_order_id == "ord_card_approved"
        assert pagamento.idempotency_key.startswith("bia-cartao-0000003-")
    finally:
        db.close()
    assert email_events == [("payment_approved", "0000003")]


def test_meta_purchase_enviado_apos_cartao_aprovado_com_payload_e_idempotencia(client, monkeypatch):
    create_user("cliente-meta-cartao", "cliente-meta-cartao@example.com")
    db = SessionLocal()
    try:
        user = db.query(Usuario).filter(Usuario.username == "cliente-meta-cartao").one()
        user.nome_completo = "Cliente Meta"
        user.telefone = "+55 (11) 99999-0000"
        produto = Produto(nome="Produto Meta", preco=50.0, ativo=True)
        db.add(produto)
        db.flush()
        user_id = user.id
        pedido = Pedido(
            numero="0000016",
            usuario_id=user.id,
            status="Aguardando pagamento",
            forma_pagamento="cartao",
            subtotal=100.0,
            valor_frete=10.0,
            total=110.0,
            endereco_cep="01001-000",
            endereco_cidade="Sao Paulo",
            endereco_estado="SP",
            meta_event_id="evt-meta-123",
            meta_fbp="fb.1.123.abc",
            meta_fbc="fb.1.123.click",
            meta_source_url="https://www.biacollections.com/checkout",
            client_user_agent="Mozilla/5.0 Test",
            client_ip_address="203.0.113.20",
        )
        db.add(pedido)
        db.flush()
        db.add(
            ItemPedido(
                pedido_id=pedido.id,
                produto_id=produto.id,
                nome_produto=produto.nome,
                preco_unitario=50.0,
                quantidade=2,
            )
        )
        produto_id = produto.id
        db.commit()
    finally:
        db.close()

    pagamentos_module = importlib.import_module("app.routers.pagamentos")
    meta_module = importlib.import_module("app.services.meta_conversions")
    sent_meta_payloads = []

    def fake_criar_order_cartao_mp(payload, idempotency_key):
        return 201, {
            "id": "ord_meta_card",
            "status": "processed",
            "status_detail": "accredited",
            "external_reference": "0000016",
            "total_amount": "110.00",
            "transactions": {
                "payments": [
                    {
                        "id": "pay_meta_card",
                        "amount": "110.00",
                        "status": "processed",
                        "status_detail": "accredited",
                        "payment_method": {"id": "visa", "type": "credit_card"},
                    }
                ]
            },
        }

    def fake_post_meta_events(pixel_id, access_token, payload):
        sent_meta_payloads.append(
            {
                "pixel_id": pixel_id,
                "access_token": access_token,
                "payload": payload,
            }
        )
        return True

    monkeypatch.setattr(pagamentos_module.settings, "MP_ACCESS_TOKEN", "token")
    monkeypatch.setattr(pagamentos_module, "_criar_order_cartao_mp", fake_criar_order_cartao_mp)
    monkeypatch.setattr(pagamentos_module, "trigger_order_email_event", lambda *args, **kwargs: None)
    monkeypatch.setattr(pagamentos_module, "trigger_admin_order_paid_email", lambda *args, **kwargs: None)
    monkeypatch.setattr(pagamentos_module, "attribute_order_conversion", lambda *args, **kwargs: None)
    monkeypatch.setattr(meta_module.settings, "META_PIXEL_ID", "pixel-123")
    monkeypatch.setattr(meta_module.settings, "META_ACCESS_TOKEN", "meta-token")
    monkeypatch.setattr(meta_module.settings, "META_TEST_EVENT_CODE", "TEST123")
    monkeypatch.setattr(meta_module, "_post_meta_events", fake_post_meta_events)

    response = client.post(
        "/api/v1/pagamentos/cartao/0000016",
        json={
            "token": "card-token",
            "payment_method_id": "visa",
            "installments": 1,
            "transaction_amount": 110.0,
            "payer": {
                "email": "pagador@example.com",
                "identification": {"type": "CPF", "number": "12345678909"},
            },
        },
        headers=auth_headers("cliente-meta-cartao"),
    )

    assert response.status_code == 200
    assert len(sent_meta_payloads) == 1
    assert sent_meta_payloads[0]["pixel_id"] == "pixel-123"
    assert sent_meta_payloads[0]["access_token"] == "meta-token"
    assert sent_meta_payloads[0]["payload"]["test_event_code"] == "TEST123"
    event = sent_meta_payloads[0]["payload"]["data"][0]
    assert event["event_name"] == "Purchase"
    assert event["event_id"] == "evt-meta-123"
    assert event["action_source"] == "website"
    assert event["event_source_url"] == "https://www.biacollections.com/checkout"
    assert event["user_data"]["fbp"] == "fb.1.123.abc"
    assert event["user_data"]["fbc"] == "fb.1.123.click"
    assert event["user_data"]["client_user_agent"] == "Mozilla/5.0 Test"
    assert event["user_data"]["client_ip_address"] == "203.0.113.20"
    assert event["user_data"]["em"] == hashlib.sha256("cliente-meta-cartao@example.com".encode()).hexdigest()
    assert event["user_data"]["ph"] == hashlib.sha256("5511999990000".encode()).hexdigest()
    assert event["user_data"]["fn"] == hashlib.sha256("cliente".encode()).hexdigest()
    assert event["user_data"]["ln"] == hashlib.sha256("meta".encode()).hexdigest()
    assert event["user_data"]["ct"] == hashlib.sha256("sao paulo".encode()).hexdigest()
    assert event["user_data"]["st"] == hashlib.sha256("sp".encode()).hexdigest()
    assert event["user_data"]["zp"] == hashlib.sha256("01001-000".encode()).hexdigest()
    assert event["user_data"]["country"] == hashlib.sha256("br".encode()).hexdigest()
    assert event["user_data"]["external_id"] == hashlib.sha256(str(user_id).encode()).hexdigest()
    assert event["custom_data"]["currency"] == "BRL"
    assert event["custom_data"]["value"] == 110.0
    assert event["custom_data"]["content_type"] == "product"
    assert event["custom_data"]["content_ids"] == [str(produto_id)]
    assert event["custom_data"]["contents"] == [
        {"id": str(produto_id), "quantity": 2, "item_price": 50.0, "title": "Produto Meta"}
    ]
    assert event["custom_data"]["num_items"] == 2
    assert event["custom_data"]["order_id"] == "0000016"

    db = SessionLocal()
    try:
        pedido = db.query(Pedido).filter(Pedido.numero == "0000016").one()
        pagamento = db.query(Pagamento).filter(Pagamento.pedido_numero == "0000016").one()
        assert pedido.meta_purchase_enviado_em is not None
        assert pedido.meta_purchase_payment_id == "pay_meta_card"

        assert meta_module.send_meta_purchase_for_paid_order(db, pedido, pagamento) is False
        assert len(sent_meta_payloads) == 1
    finally:
        db.close()


def test_meta_web_event_endpoint_envia_pageview_com_request_data(client, monkeypatch):
    meta_module = importlib.import_module("app.services.meta_conversions")
    sent_meta_payloads = []

    def fake_post_meta_events(pixel_id, access_token, payload):
        sent_meta_payloads.append(
            {
                "pixel_id": pixel_id,
                "access_token": access_token,
                "payload": payload,
            }
        )
        return True

    monkeypatch.setattr(meta_module.settings, "META_PIXEL_ID", "pixel-123")
    monkeypatch.setattr(meta_module.settings, "META_ACCESS_TOKEN", "meta-token")
    monkeypatch.setattr(meta_module.settings, "META_TEST_EVENT_CODE", "TEST456")
    monkeypatch.setattr(meta_module, "_post_meta_events", fake_post_meta_events)

    response = client.post(
        "/api/v1/meta/events",
        json={
            "event_name": "PageView",
            "event_id": "evt-page-123",
            "event_source_url": "https://www.biacollections.com/produtos",
            "fbp": "fb.1.456.browser",
            "fbc": "fb.1.456.click",
        },
        headers={
            "user-agent": "Mozilla/5.0 PageView",
            "x-forwarded-for": "198.51.100.77",
        },
    )

    assert response.status_code == 200
    assert response.json() == {
        "event_name": "PageView",
        "event_id": "evt-page-123",
        "sent_to_meta": True,
        "configured": True,
    }
    assert len(sent_meta_payloads) == 1
    assert sent_meta_payloads[0]["pixel_id"] == "pixel-123"
    assert sent_meta_payloads[0]["access_token"] == "meta-token"
    assert sent_meta_payloads[0]["payload"]["test_event_code"] == "TEST456"
    event = sent_meta_payloads[0]["payload"]["data"][0]
    assert event["event_name"] == "PageView"
    assert event["event_id"] == "evt-page-123"
    assert event["action_source"] == "website"
    assert event["event_source_url"] == "https://www.biacollections.com/produtos"
    assert event["user_data"] == {
        "fbp": "fb.1.456.browser",
        "fbc": "fb.1.456.click",
        "client_user_agent": "Mozilla/5.0 PageView",
        "client_ip_address": "198.51.100.77",
    }
    assert "custom_data" not in event


def test_meta_web_event_endpoint_envia_viewcontent_com_user_data_e_custom_data(client, monkeypatch):
    user_id = create_user("cliente-meta-view", "cliente-meta-view@example.com")
    db = SessionLocal()
    try:
        user = db.query(Usuario).filter(Usuario.id == user_id).one()
        user.nome_completo = "Maria Teste"
        user.telefone = "+55 11 98888-7777"
        db.commit()
    finally:
        db.close()

    meta_module = importlib.import_module("app.services.meta_conversions")
    sent_meta_payloads = []

    def fake_post_meta_events(pixel_id, access_token, payload):
        sent_meta_payloads.append(payload)
        return True

    monkeypatch.setattr(meta_module.settings, "META_PIXEL_ID", "pixel-123")
    monkeypatch.setattr(meta_module.settings, "META_ACCESS_TOKEN", "meta-token")
    monkeypatch.setattr(meta_module.settings, "META_TEST_EVENT_CODE", "")
    monkeypatch.setattr(meta_module, "_post_meta_events", fake_post_meta_events)

    response = client.post(
        "/api/v1/meta/events",
        json={
            "event_name": "ViewContent",
            "event_id": "evt-view-123",
            "event_source_url": "https://www.biacollections.com/produtos/10",
            "user_data": {
                "city": "Sao Paulo",
                "state": "SP",
                "zip_code": "01001-000",
            },
            "custom_data": {
                "value": 89.9,
                "contents": [
                    {
                        "id": "10",
                        "quantity": 1,
                        "item_price": 89.9,
                        "title": "Bolsa Teste",
                    }
                ],
                "content_name": "Bolsa Teste",
            },
        },
        headers={
            **auth_headers("cliente-meta-view"),
            "user-agent": "Mozilla/5.0 ViewContent",
            "x-forwarded-for": "203.0.113.55",
        },
    )

    assert response.status_code == 200
    event = sent_meta_payloads[0]["data"][0]
    assert event["event_name"] == "ViewContent"
    assert event["event_id"] == "evt-view-123"
    assert event["user_data"]["client_ip_address"] == "203.0.113.55"
    assert event["user_data"]["client_user_agent"] == "Mozilla/5.0 ViewContent"
    assert event["user_data"]["em"] == hashlib.sha256("cliente-meta-view@example.com".encode()).hexdigest()
    assert event["user_data"]["ph"] == hashlib.sha256("5511988887777".encode()).hexdigest()
    assert event["user_data"]["fn"] == hashlib.sha256("maria".encode()).hexdigest()
    assert event["user_data"]["ln"] == hashlib.sha256("teste".encode()).hexdigest()
    assert event["user_data"]["ct"] == hashlib.sha256("sao paulo".encode()).hexdigest()
    assert event["user_data"]["st"] == hashlib.sha256("sp".encode()).hexdigest()
    assert event["user_data"]["zp"] == hashlib.sha256("01001-000".encode()).hexdigest()
    assert event["custom_data"]["currency"] == "BRL"
    assert event["custom_data"]["content_type"] == "product"
    assert event["custom_data"]["content_ids"] == ["10"]
    assert event["custom_data"]["contents"] == [
        {"id": "10", "quantity": 1, "item_price": 89.9, "title": "Bolsa Teste"}
    ]
    assert event["custom_data"]["num_items"] == 1


def test_meta_web_event_endpoint_nao_aceita_purchase_publico(client):
    response = client.post(
        "/api/v1/meta/events",
        json={
            "event_name": "Purchase",
            "event_id": "evt-purchase-forjado",
            "event_source_url": "https://www.biacollections.com/checkout",
        },
    )

    assert response.status_code == 422


def test_pagamento_cartao_sem_issuer_nao_bloqueia_checkout(client, monkeypatch):
    create_user("cliente-cartao-sem-issuer", "cliente-cartao-sem-issuer@example.com")
    db = SessionLocal()
    try:
        user = db.query(Usuario).filter(Usuario.username == "cliente-cartao-sem-issuer").one()
        db.add(
            Pedido(
                numero="0000007",
                usuario_id=user.id,
                status="Aguardando pagamento",
                forma_pagamento="cartao",
                subtotal=100.0,
                valor_frete=0.0,
                total=100.0,
            )
        )
        db.commit()
    finally:
        db.close()

    pagamentos_module = importlib.import_module("app.routers.pagamentos")
    creates = []

    def fake_criar_order_cartao_mp(payload, idempotency_key):
        creates.append(payload)
        return 201, {
            "id": "ord_card_no_issuer",
            "status": "processed",
            "status_detail": "accredited",
            "external_reference": "0000007",
            "total_amount": "100.00",
            "transactions": {
                "payments": [
                    {
                        "id": "pay_card_no_issuer",
                        "amount": "100.00",
                        "status": "processed",
                        "status_detail": "accredited",
                        "payment_method": {"id": "visa", "type": "credit_card"},
                    }
                ]
            },
        }

    monkeypatch.setattr(pagamentos_module.settings, "MP_ACCESS_TOKEN", "token")
    monkeypatch.setattr(pagamentos_module, "_criar_order_cartao_mp", fake_criar_order_cartao_mp)
    monkeypatch.setattr(
        pagamentos_module,
        "trigger_order_email_event",
        lambda *args, **kwargs: None,
    )

    response = client.post(
        "/api/v1/pagamentos/cartao/0000007",
        json={
            "token": "card-token",
            "payment_method_id": "visa",
            "issuer_id": "",
            "installments": 1,
            "transaction_amount": 100.0,
            "payer": {
                "email": "pagador@example.com",
                "identification": {"type": "CPF", "number": "12345678909"},
            },
        },
        headers=auth_headers("cliente-cartao-sem-issuer"),
    )

    assert response.status_code == 200
    assert response.json()["status"] == "aprovado"
    assert len(creates) == 1
    assert "issuer_id" not in creates[0]
    assert creates[0]["transactions"]["payments"][0]["payment_method"]["id"] == "visa"


def test_pagamento_cartao_erro_credenciais_live_retorna_mensagem_de_cartao(client, monkeypatch):
    create_user("cliente-cartao-credencial-live", "cliente-cartao-credencial-live@example.com")
    db = SessionLocal()
    try:
        user = db.query(Usuario).filter(Usuario.username == "cliente-cartao-credencial-live").one()
        db.add(
            Pedido(
                numero="0000008",
                usuario_id=user.id,
                status="Aguardando pagamento",
                forma_pagamento="cartao",
                subtotal=100.0,
                valor_frete=0.0,
                total=100.0,
            )
        )
        db.commit()
    finally:
        db.close()

    pagamentos_module = importlib.import_module("app.routers.pagamentos")

    def fake_criar_order_cartao_mp(payload, idempotency_key):
        return 401, {
            "message": "Unauthorized use of live credentials",
            "error": "unauthorized",
            "status": 401,
        }

    monkeypatch.setattr(pagamentos_module.settings, "MP_ACCESS_TOKEN", "token")
    monkeypatch.setattr(pagamentos_module, "_criar_order_cartao_mp", fake_criar_order_cartao_mp)

    response = client.post(
        "/api/v1/pagamentos/cartao/0000008",
        json={
            "token": "card-token",
            "payment_method_id": "visa",
            "installments": 1,
            "transaction_amount": 100.0,
            "payer": {
                "email": "pagador@example.com",
                "identification": {"type": "CPF", "number": "12345678909"},
            },
        },
        headers=auth_headers("cliente-cartao-credencial-live"),
    )

    assert response.status_code == 502
    detail = response.json()["detail"]
    assert "order de cartao" in detail
    assert "Checkout Transparente via Orders" in detail
    assert "gerar PIX" not in detail


def test_pagamento_cartao_valor_divergente_retorna_422(client, monkeypatch):
    create_user("cliente-cartao-divergente", "cliente-cartao-divergente@example.com")
    db = SessionLocal()
    try:
        user = db.query(Usuario).filter(Usuario.username == "cliente-cartao-divergente").one()
        db.add(
            Pedido(
                numero="0000004",
                usuario_id=user.id,
                status="Aguardando pagamento",
                forma_pagamento="cartao",
                subtotal=80.0,
                valor_frete=10.0,
                total=90.0,
            )
        )
        db.commit()
    finally:
        db.close()

    pagamentos_module = importlib.import_module("app.routers.pagamentos")
    monkeypatch.setattr(pagamentos_module.settings, "MP_ACCESS_TOKEN", "token")

    response = client.post(
        "/api/v1/pagamentos/cartao/0000004",
        json={
            "token": "card-token",
            "payment_method_id": "visa",
            "issuer_id": "25",
            "installments": 1,
            "transaction_amount": 85.0,
            "payer": {
                "email": "pagador@example.com",
                "identification": {"type": "CPF", "number": "12345678909"},
            },
        },
        headers=auth_headers("cliente-cartao-divergente"),
    )

    assert response.status_code == 422
    assert "valor divergente" in response.json()["detail"]


def test_pagamento_cartao_recusado_permite_nova_tentativa(client, monkeypatch):
    create_user("cliente-cartao-recusado", "cliente-cartao-recusado@example.com")
    db = SessionLocal()
    try:
        user = db.query(Usuario).filter(Usuario.username == "cliente-cartao-recusado").one()
        db.add(
            Pedido(
                numero="0000005",
                usuario_id=user.id,
                status="Aguardando pagamento",
                forma_pagamento="cartao",
                subtotal=70.0,
                valor_frete=0.0,
                total=70.0,
            )
        )
        db.commit()
    finally:
        db.close()

    pagamentos_module = importlib.import_module("app.routers.pagamentos")
    create_count = 0

    def fake_criar_order_cartao_mp(payload, idempotency_key):
        nonlocal create_count
        create_count += 1
        return 402, {
            "id": f"ord_card_rejected_{create_count}",
            "status": "failed",
            "status_detail": "cc_rejected_other_reason",
            "external_reference": "0000005",
            "total_amount": "70.00",
            "transactions": {
                "payments": [
                    {
                        "id": f"pay_card_rejected_{create_count}",
                        "amount": "70.00",
                        "status": "failed",
                        "status_detail": "cc_rejected_other_reason",
                        "payment_method": {"id": "master", "type": "credit_card"},
                    }
                ]
            },
        }

    email_events = []
    monkeypatch.setattr(pagamentos_module.settings, "MP_ACCESS_TOKEN", "token")
    monkeypatch.setattr(pagamentos_module, "_criar_order_cartao_mp", fake_criar_order_cartao_mp)
    monkeypatch.setattr(
        pagamentos_module,
        "trigger_order_email_event",
        lambda db, event_key, pedido: email_events.append((event_key, pedido.numero)),
    )

    payload = {
        "token": "card-token",
        "payment_method_id": "master",
        "issuer_id": "30",
        "installments": 1,
        "transaction_amount": 70.0,
        "payer": {
            "email": "pagador@example.com",
            "identification": {"type": "CPF", "number": "12345678909"},
        },
    }
    headers = auth_headers("cliente-cartao-recusado")
    first = client.post("/api/v1/pagamentos/cartao/0000005", json=payload, headers=headers)
    second = client.post("/api/v1/pagamentos/cartao/0000005", json=payload, headers=headers)

    assert first.status_code == 200
    assert first.json()["status"] == "recusado"
    assert first.json()["status_pedido"] == "Pagamento recusado"
    assert second.status_code == 200
    assert second.json()["status"] == "recusado"
    assert create_count == 2

    db = SessionLocal()
    try:
        pedido = db.query(Pedido).filter(Pedido.numero == "0000005").one()
        pagamentos = db.query(Pagamento).filter(Pagamento.pedido_numero == "0000005").all()
        assert pedido.status == "Pagamento recusado"
        assert len(pagamentos) == 2
        assert all(pagamento.tipo == "cartao" for pagamento in pagamentos)
    finally:
        db.close()
    assert email_events == [
        ("payment_refused", "0000005"),
        ("payment_refused", "0000005"),
    ]


def test_webhook_aprovado_atualiza_pedido_e_pagamento(client, monkeypatch):
    create_user("cliente-webhook", "cliente-webhook@example.com")
    db = SessionLocal()
    try:
        user = db.query(Usuario).filter(Usuario.username == "cliente-webhook").one()
        cupom = Cupom(
            codigo="WEBHOOK10",
            descricao="Cupom webhook",
            tipo="valor",
            valor=10.0,
            validade=datetime.now(timezone.utc).date() + timedelta(days=1),
            ativo=True,
        )
        db.add(cupom)
        db.flush()
        pedido = Pedido(
            numero="0000002",
            usuario_id=user.id,
            status="Aguardando pagamento",
            forma_pagamento="cartao",
            subtotal=80.0,
            valor_frete=15.0,
            total=95.0,
            cupom_codigo=cupom.codigo,
            desconto_aplicado=10.0,
        )
        db.add(pedido)
        db.flush()
        db.add(
            Pagamento(
                pedido_numero=pedido.numero,
                tipo="checkout_pro",
                valor=95.0,
                mp_preference_id="pref_1",
                status="pendente",
            )
        )
        db.commit()
    finally:
        db.close()

    pagamentos_module = importlib.import_module("app.routers.pagamentos")

    class FakePaymentResource:
        def get(self, payment_id):
            assert payment_id == "pay_card_1"
            return {
                "status": 200,
                "response": {
                    "id": payment_id,
                    "status": "approved",
                    "preference_id": "pref_1",
                    "payment_method_id": "visa",
                    "transaction_amount": 95.0,
                },
            }

    class FakeSDK:
        def __init__(self, token):
            self.token = token

        def payment(self):
            return FakePaymentResource()

    monkeypatch.setattr(pagamentos_module.settings, "MP_ACCESS_TOKEN", "token")
    monkeypatch.setattr(pagamentos_module.settings, "MP_WEBHOOK_SECRET", "")
    monkeypatch.setattr(pagamentos_module.mercadopago, "SDK", FakeSDK)
    monkeypatch.setattr(pagamentos_module, "trigger_order_email_event", lambda *args, **kwargs: None)

    response = client.post(
        "/api/v1/pagamentos/webhook",
        json={"type": "payment", "data": {"id": "pay_card_1"}},
    )

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}

    db = SessionLocal()
    try:
        pedido = db.query(Pedido).filter(Pedido.numero == "0000002").one()
        pagamento = db.query(Pagamento).filter(Pagamento.pedido_numero == "0000002").one()
        assert pedido.status == "Pagamento aprovado"
        assert pagamento.status == "aprovado"
        assert pagamento.mp_status == "approved"
        assert pagamento.mp_payment_id == "pay_card_1"
        assert db.query(CupomUsado).filter(CupomUsado.pedido_id == pedido.id).count() == 1
        assert db.query(Cupom).filter(Cupom.codigo == "WEBHOOK10").one().total_usos == 1
    finally:
        db.close()


def test_webhook_cartao_metadata_atualiza_pagamento_e_pedido(client, monkeypatch):
    create_user("cliente-webhook-cartao", "cliente-webhook-cartao@example.com")
    db = SessionLocal()
    try:
        user = db.query(Usuario).filter(Usuario.username == "cliente-webhook-cartao").one()
        pedido = Pedido(
            numero="0000006",
            usuario_id=user.id,
            status="Aguardando pagamento",
            forma_pagamento="cartao",
            subtotal=120.0,
            valor_frete=0.0,
            total=120.0,
        )
        db.add(pedido)
        db.flush()
        db.add(
            Pagamento(
                pedido_numero=pedido.numero,
                tipo="cartao",
                valor=120.0,
                status="pendente",
            )
        )
        db.commit()
    finally:
        db.close()

    pagamentos_module = importlib.import_module("app.routers.pagamentos")

    class FakePaymentResource:
        def get(self, payment_id):
            assert payment_id == "pay_card_webhook"
            return {
                "status": 200,
                "response": {
                    "id": payment_id,
                    "status": "approved",
                    "status_detail": "accredited",
                    "payment_method_id": "visa",
                    "transaction_amount": 120.0,
                    "external_reference": "0000006",
                    "metadata": {
                        "pedido_numero": "0000006",
                        "payment_flow": "cartao",
                    },
                },
            }

    class FakeSDK:
        def __init__(self, token):
            self.token = token

        def payment(self):
            return FakePaymentResource()

    email_events = []
    monkeypatch.setattr(pagamentos_module.settings, "MP_ACCESS_TOKEN", "token")
    monkeypatch.setattr(pagamentos_module.settings, "MP_WEBHOOK_SECRET", "")
    monkeypatch.setattr(pagamentos_module.mercadopago, "SDK", FakeSDK)
    monkeypatch.setattr(
        pagamentos_module,
        "trigger_order_email_event",
        lambda db, event_key, pedido: email_events.append((event_key, pedido.numero)),
    )

    response = client.post(
        "/api/v1/pagamentos/webhook",
        json={"type": "payment", "data": {"id": "pay_card_webhook"}},
    )

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}

    db = SessionLocal()
    try:
        pedido = db.query(Pedido).filter(Pedido.numero == "0000006").one()
        pagamento = db.query(Pagamento).filter(Pagamento.pedido_numero == "0000006").one()
        assert pedido.status == "Pagamento aprovado"
        assert pagamento.tipo == "cartao"
        assert pagamento.status == "aprovado"
        assert pagamento.mp_status == "approved"
        assert pagamento.mp_payment_id == "pay_card_webhook"
        assert pagamento.valor == 120.0
    finally:
        db.close()
    assert email_events == [("payment_approved", "0000006")]


def test_webhook_pix_order_processed_atualiza_pedido_e_pagamento(client, monkeypatch):
    create_user("cliente-webhook-pix", "cliente-webhook-pix@example.com")
    db = SessionLocal()
    try:
        user = db.query(Usuario).filter(Usuario.username == "cliente-webhook-pix").one()
        pedido = Pedido(
            numero="0000007",
            usuario_id=user.id,
            status="Aguardando pagamento",
            forma_pagamento="pix",
            subtotal=70.0,
            valor_frete=5.0,
            total=75.0,
        )
        db.add(pedido)
        db.flush()
        db.add(
            Pagamento(
                pedido_numero=pedido.numero,
                tipo="pix",
                valor=75.0,
                status="pendente",
                mp_payment_id="pay_pix_order",
                mp_order_id="ord_pix_paid",
            )
        )
        db.commit()
    finally:
        db.close()

    pagamentos_module = importlib.import_module("app.routers.pagamentos")

    def fake_consultar_order_mp(order_id):
        assert order_id == "ord_pix_paid"
        return 200, {
            "id": "ord_pix_paid",
            "status": "processed",
            "status_detail": "accredited",
            "external_reference": "0000007",
            "total_amount": "75.00",
            "transactions": {
                "payments": [
                    {
                        "id": "pay_pix_order",
                        "status": "processed",
                        "status_detail": "accredited",
                        "payment_method": {"id": "pix", "type": "bank_transfer"},
                    }
                ]
            },
        }

    email_events = []
    monkeypatch.setattr(pagamentos_module.settings, "MP_ACCESS_TOKEN", "token")
    monkeypatch.setattr(pagamentos_module.settings, "MP_WEBHOOK_SECRET", "")
    monkeypatch.setattr(pagamentos_module, "_consultar_order_mp", fake_consultar_order_mp)
    monkeypatch.setattr(
        pagamentos_module,
        "trigger_order_email_event",
        lambda db, event_key, pedido: email_events.append((event_key, pedido.numero)),
    )

    response = client.post(
        "/api/v1/pagamentos/webhook?type=order&data.id=ord_pix_paid",
        json={},
    )

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}

    db = SessionLocal()
    try:
        pedido = db.query(Pedido).filter(Pedido.numero == "0000007").one()
        pagamento = db.query(Pagamento).filter(Pagamento.pedido_numero == "0000007").one()
        assert pedido.status == "Pagamento aprovado"
        assert pagamento.tipo == "pix"
        assert pagamento.status == "aprovado"
        assert pagamento.mp_status == "processed"
        assert pagamento.mp_payment_id == "pay_pix_order"
        assert pagamento.mp_order_id == "ord_pix_paid"
    finally:
        db.close()
    assert email_events == [("payment_approved", "0000007")]


def test_webhook_em_producao_exige_secret_configurado(client, monkeypatch):
    monkeypatch.setattr(pagamentos_module.settings, "MP_WEBHOOK_SECRET", "")
    monkeypatch.setattr(pagamentos_module.settings, "REQUIRE_MP_WEBHOOK_SECRET", True)

    response = client.post(
        "/api/v1/pagamentos/webhook",
        json={"type": "payment", "data": {"id": "pay_without_secret"}},
    )

    assert response.status_code == 503
    assert response.json()["detail"] == "Webhook secret nao configurado."


def test_status_pix_pendente_busca_order_por_referencia_sem_order_id(client, monkeypatch):
    create_user("cliente-status-pix", "cliente-status-pix@example.com")
    db = SessionLocal()
    try:
        user = db.query(Usuario).filter(Usuario.username == "cliente-status-pix").one()
        pedido = Pedido(
            numero="0000008",
            usuario_id=user.id,
            status="Aguardando pagamento",
            forma_pagamento="pix",
            subtotal=45.0,
            valor_frete=5.0,
            total=50.0,
        )
        db.add(pedido)
        db.flush()
        db.add(
            Pagamento(
                pedido_numero=pedido.numero,
                tipo="pix",
                valor=50.0,
                status="pendente",
                mp_payment_id="pay_pix_old",
            )
        )
        db.commit()
    finally:
        db.close()

    pagamentos_module = importlib.import_module("app.routers.pagamentos")

    def fake_buscar_order_mp_por_referencia(external_reference, criado_em):
        assert external_reference == "0000008"
        assert criado_em is not None
        return {
            "id": "ord_pix_found",
            "status": "processed",
            "status_detail": "accredited",
            "external_reference": "0000008",
            "total_amount": "50.00",
            "transactions": {
                "payments": [
                    {
                        "id": "pay_pix_found",
                        "status": "processed",
                        "status_detail": "accredited",
                        "payment_method": {"id": "pix", "type": "bank_transfer"},
                    }
                ]
            },
        }

    monkeypatch.setattr(pagamentos_module.settings, "MP_ACCESS_TOKEN", "token")
    monkeypatch.setattr(
        pagamentos_module,
        "_buscar_order_mp_por_referencia",
        fake_buscar_order_mp_por_referencia,
    )

    response = client.get(
        "/api/v1/pagamentos/status/0000008",
        headers=auth_headers("cliente-status-pix"),
    )

    assert response.status_code == 200
    body = response.json()
    assert body["pago"] is True
    assert body["status_pedido"] == "Pagamento aprovado"
    assert body["pagamento"]["status"] == "aprovado"
    assert body["pagamento"]["mp_status"] == "processed"
    assert body["pagamento"]["payment_id"] == "pay_pix_found"
    assert body["pagamento"]["order_id"] == "ord_pix_found"

    db = SessionLocal()
    try:
        pedido = db.query(Pedido).filter(Pedido.numero == "0000008").one()
        pagamento = db.query(Pagamento).filter(Pagamento.pedido_numero == "0000008").one()
        assert pedido.status == "Pagamento aprovado"
        assert pagamento.mp_order_id == "ord_pix_found"
    finally:
        db.close()


def test_assinatura_webhook_fallback_valida_hmac():
    pagamentos_module = importlib.import_module("app.routers.pagamentos")
    secret = "segredo"
    data_id = "123456"
    request_id = "abc"
    ts = "1704908010"
    manifest = f"id:{data_id};request-id:{request_id};ts:{ts};"
    signature = hmac.new(
        secret.encode("utf-8"),
        manifest.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()

    assert pagamentos_module._validar_assinatura_fallback(
        f"ts={ts},v1={signature}",
        request_id,
        data_id,
        secret,
    )
    assert not pagamentos_module._validar_assinatura_fallback(
        f"ts={ts},v1=invalida",
        request_id,
        data_id,
        secret,
    )


def test_admin_marca_avaliacao_aprovada_para_home(client):
    create_user("master-home", MASTER_ADMIN_EMAIL, is_admin=True)
    _, avaliacao_id = create_product_review(
        produto_nome="Vestido Home",
        username="cliente-review-home",
        email="cliente-review-home@example.com",
        status="aprovada",
    )

    response = client.put(
        f"/api/v1/admin/avaliacoes/{avaliacao_id}/home",
        json={"mostrar_home": True},
        headers=auth_headers("master-home"),
    )

    assert response.status_code == 200
    body = response.json()
    assert body["id"] == avaliacao_id
    assert body["status"] == "aprovada"
    assert body["mostrar_home"] is True


def test_admin_status_reprovado_remove_avaliacao_da_home(client):
    create_user("master-home-status", MASTER_ADMIN_EMAIL, is_admin=True)
    _, avaliacao_id = create_product_review(
        produto_nome="Vestido Status Home",
        username="cliente-review-status-home",
        email="cliente-review-status-home@example.com",
        status="aprovada",
        mostrar_home=True,
    )

    response = client.put(
        f"/api/v1/admin/avaliacoes/{avaliacao_id}/status",
        json={"status": "reprovada"},
        headers=auth_headers("master-home-status"),
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "reprovada"
    assert body["mostrar_home"] is False


def test_admin_nao_destaca_avaliacao_pendente_ou_reprovada(client):
    create_user("master-home-bloqueio", MASTER_ADMIN_EMAIL, is_admin=True)
    _, pendente_id = create_product_review(
        produto_nome="Blusa Pendente",
        username="cliente-review-pendente",
        email="cliente-review-pendente@example.com",
        status="pendente",
    )
    _, reprovada_id = create_product_review(
        produto_nome="Blusa Reprovada",
        username="cliente-review-reprovada",
        email="cliente-review-reprovada@example.com",
        status="reprovada",
    )
    headers = auth_headers("master-home-bloqueio")

    pendente = client.put(
        f"/api/v1/admin/avaliacoes/{pendente_id}/home",
        json={"mostrar_home": True},
        headers=headers,
    )
    reprovada = client.put(
        f"/api/v1/admin/avaliacoes/{reprovada_id}/home",
        json={"mostrar_home": True},
        headers=headers,
    )

    assert pendente.status_code == 400
    assert reprovada.status_code == 400
    assert "aprovadas" in pendente.json()["detail"]
    assert "aprovadas" in reprovada.json()["detail"]


def test_public_home_retorna_apenas_avaliacoes_aprovadas_destacadas(client):
    _, featured_id = create_product_review(
        produto_nome="Saia Home Aprovada",
        username="cliente-home-aprovada",
        email="cliente-home-aprovada@example.com",
        status="aprovada",
        mostrar_home=True,
    )
    create_product_review(
        produto_nome="Saia Home Pendente",
        username="cliente-home-pendente",
        email="cliente-home-pendente@example.com",
        status="pendente",
        mostrar_home=True,
    )
    create_product_review(
        produto_nome="Saia Home Nao Destacada",
        username="cliente-home-nao-destacada",
        email="cliente-home-nao-destacada@example.com",
        status="aprovada",
        mostrar_home=False,
    )

    response = client.get("/api/v1/avaliacoes?mostrar_home=true")

    assert response.status_code == 200
    body = response.json()
    assert [item["id"] for item in body] == [featured_id]
    assert body[0]["mostrar_home"] is True
    assert body[0]["status"] == "aprovada"


def test_public_produto_retorna_avaliacoes_aprovadas_do_produto(client):
    produto_id, aprovada_id = create_product_review(
        produto_nome="Produto Avaliado",
        username="cliente-produto-aprovada",
        email="cliente-produto-aprovada@example.com",
        status="aprovada",
    )
    create_product_review(
        produto_nome="Produto Pendente",
        username="cliente-produto-pendente",
        email="cliente-produto-pendente@example.com",
        status="pendente",
    )
    _, outra_aprovada_id = create_product_review(
        produto_nome="Outro Produto Avaliado",
        username="cliente-produto-outra",
        email="cliente-produto-outra@example.com",
        status="aprovada",
    )

    response = client.get(f"/api/v1/avaliacoes?produto_id={produto_id}&status=aprovada")

    assert response.status_code == 200
    body = response.json()
    assert [item["id"] for item in body] == [aprovada_id]
    assert outra_aprovada_id not in [item["id"] for item in body]


def seed_admin_email_flow(monkeypatch):
    seed_email_automation()
    tasks_module = importlib.import_module("app.modules.email.tasks")
    monkeypatch.setattr(tasks_module, "enqueue_email_log", lambda *args, **kwargs: None)


def patch_service_email_provider(monkeypatch):
    sent: list[dict[str, str | None]] = []
    service_module = importlib.import_module("app.modules.email.service")

    class FakeResult:
        def __init__(self, index: int):
            self.provider = "fake"
            self.provider_message_id = f"fake-message-{index}"

    class FakeEmailProvider:
        def send(self, to: str, subject: str, html: str | None = None, text: str | None = None):
            sent.append({"to": to, "subject": subject, "html": html, "text": text})
            return FakeResult(len(sent))

    monkeypatch.setattr(service_module, "EmailProvider", FakeEmailProvider)
    return sent, FakeEmailProvider


def email_logs() -> list[EmailLog]:
    db = SessionLocal()
    try:
        return db.query(EmailLog).order_by(EmailLog.id.asc()).all()
    finally:
        db.close()


def create_basic_product(nome: str = "Vestido Email", preco: float = 50.0) -> int:
    db = SessionLocal()
    try:
        produto = Produto(
            nome=nome,
            descricao="Produto para email",
            preco=preco,
            imagem_url="/uploads/produtos/vestido-email.webp",
            ativo=True,
            imagens=[
                ProdutoImagem(
                    imagem_url="/uploads/produtos/vestido-email.webp",
                    ordem=0,
                    principal=True,
                    modelo_nome="Azul",
                    modelo_cor="Azul",
                    cor_nome="Azul",
                )
            ],
        )
        db.add(produto)
        db.commit()
        db.refresh(produto)
        return produto.id
    finally:
        db.close()


def create_order_record(
    *,
    username: str,
    email: str,
    numero: str,
    status_pedido: str = "Aguardando pagamento",
    forma_pagamento: str = "pix",
    total: float = 100.0,
    codigo_rastreio: str | None = None,
) -> tuple[int, int]:
    user_id = create_user(username, email)
    db = SessionLocal()
    try:
        product_subtotal = max(total - 10.0, 0.0)
        produto = Produto(
            nome=f"Produto {numero}",
            descricao="Produto para email de pagamento",
            preco=product_subtotal,
            imagem_url=f"/uploads/produtos/{numero.lower()}.webp",
            ativo=True,
            imagens=[
                ProdutoImagem(
                    imagem_url=f"/uploads/produtos/{numero.lower()}.webp",
                    ordem=0,
                    principal=True,
                    modelo_nome="Dourado",
                    modelo_cor="Dourado",
                    cor_nome="Dourado",
                )
            ],
        )
        db.add(produto)
        db.flush()
        pedido = Pedido(
            numero=numero,
            usuario_id=user_id,
            status=status_pedido,
            forma_pagamento=forma_pagamento,
            subtotal=product_subtotal,
            valor_frete=10.0,
            total=total,
            codigo_rastreio=codigo_rastreio,
        )
        db.add(pedido)
        db.flush()
        db.add(
            ItemPedido(
                pedido_id=pedido.id,
                produto_id=produto.id,
                nome_produto=produto.nome,
                preco_unitario=product_subtotal,
                tamanho="Unico",
                cor="Dourado",
                quantidade=1,
            )
        )
        db.commit()
        db.refresh(pedido)
        return pedido.id, user_id
    finally:
        db.close()


def assert_email_log_snapshot(
    log: EmailLog,
    *,
    event_key: str,
    recipient: str,
    status_log: str,
    subject_contains: str,
    html_contains: str,
    text_contains: str,
    payload_values: dict[str, str],
) -> dict:
    assert log.event_key == event_key
    assert log.email == recipient
    assert log.status == status_log
    assert log.subject is not None and subject_contains in log.subject
    assert log.html_snapshot is not None and html_contains in log.html_snapshot
    assert 'data-bia-email-logo="true"' in log.html_snapshot
    assert "bia-collections-logooficial.png" in log.html_snapshot
    assert log.text_snapshot is not None and text_contains in log.text_snapshot
    payload = json.loads(log.payload_json or "{}")
    for key, value in payload_values.items():
        assert payload[key] == value
    return payload


def test_pedido_criado_usa_template_admin_e_registra_log_renderizado(client, monkeypatch):
    seed_admin_email_flow(monkeypatch)
    create_user("cliente-email-pedido", "cliente-email-pedido@example.com")
    produto_id = create_basic_product()

    response = client.post(
        "/api/v1/pedidos",
        json={
            "itens": [{"produto_id": produto_id, "quantidade": 2, "tamanho": "M", "cor": "Azul"}],
            "endereco": {
                "cep": "01001000",
                "rua": "Rua Teste",
                "numero": "123",
                "bairro": "Centro",
                "cidade": "Sao Paulo",
                "estado": "SP",
            },
            "forma_pagamento": "pix",
            "frete": {"nome": "PAC", "prazo": "5 dias", "valor": 10.0},
        },
        headers=auth_headers("cliente-email-pedido"),
    )

    assert response.status_code == 201
    numero = response.json()["numero_pedido"]
    logs = email_logs()
    assert len(logs) == 1
    log = logs[0]
    assert log.template_slug == "admin-default-pedido-criado"
    payload = assert_email_log_snapshot(
        log,
        event_key="pedido_criado",
        recipient="cliente-email-pedido@example.com",
        status_log="pendente",
        subject_contains=f"Recebemos seu pedido {numero}",
        html_contains="Pedido recebido",
        text_contains=numero,
        payload_values={"pedido_numero": numero, "cliente_nome": "cliente-email-pedido"},
    )
    assert log.dedupe_key == f"pedido_criado:{numero}"
    assert payload["pedido_total"] == "R$ 110,00"
    assert payload["link_meus_pedidos"] == "http://localhost:3000/meus-pedidos"
    assert "pedido_itens_html|default" not in log.html_snapshot
    assert "Resumo do pedido" in log.html_snapshot
    assert "Vestido Email" in log.html_snapshot
    assert "Quantidade: <strong>2</strong>" in log.html_snapshot
    assert "Cor: <strong>Azul</strong>" in log.html_snapshot
    assert "Modelo/Tamanho: <strong>M</strong>" in log.html_snapshot
    assert "/uploads/produtos/vestido-email.webp" in log.html_snapshot
    assert "Ver meus pedidos" in log.html_snapshot
    assert "http://localhost:3000/meus-pedidos" in log.html_snapshot
    assert "Ir para a home da Bia Collections" in log.html_snapshot
    assert "Ver Instagram" in log.html_snapshot
    assert "https://www.instagram.com/biacollectionstore" in log.html_snapshot
    assert "Se você não solicitou esta mensagem" in log.html_snapshot


def test_todos_templates_de_pedido_e_pos_venda_incluem_resumo_do_pedido():
    seeds_module = importlib.import_module("app.modules.email.seeds")

    customer_templates = [
        template
        for template in seeds_module.EMAIL_TEMPLATE_SEEDS
        if template["category"] in seeds_module.ORDER_SUMMARY_CATEGORIES
        and "order_number" in template["variables_schema"]
    ]
    admin_templates = [
        template
        for template in seeds_module.ADMIN_EMAIL_TEMPLATE_SEEDS
        if template["evento"] in seeds_module.ORDER_SUMMARY_ADMIN_EVENTS
    ]

    assert customer_templates
    assert admin_templates
    for template in customer_templates:
        assert "{{order_items_html}}" in template["html_template"], template["slug"]
        assert "{{order_total}}" in template["html_template"], template["slug"]
    for template in admin_templates:
        assert "{{pedido_itens_html}}" in template["html_template"], template["slug"]
        assert "{{pedido_total}}" in template["html_template"], template["slug"]


def test_renderizacao_adiciona_resumo_quando_template_antigo_nao_possui_card():
    email_service_module = importlib.import_module("app.modules.email.service")
    template = EmailTemplate(
        nome="Pedido em preparação antigo",
        name="Pedido em preparação antigo",
        slug="pedido-preparando-antigo",
        category="pedido_preparando",
        evento="pedido_preparando",
        status="ativo",
        subject="Pedido {{pedido_numero}}",
        preheader="Seu pedido está em preparação.",
        html_template=(
            '<html><body><div data-bia-template-style="premium-v2">'
            "<p>Seu pedido está sendo preparado.</p></div></body></html>"
        ),
        text_template="Seu pedido está sendo preparado.",
        variables_schema="{}",
        is_active=True,
    )
    summary_html = (
        '<table><tr><td style="text-transform: uppercase;">Resumo do pedido</td></tr>'
        "<tr><td>Produto Teste</td></tr></table>"
    )

    db = SessionLocal()
    try:
        rendered = email_service_module.EmailAutomationService(db).render_template(
            template.slug,
            {
                "pedido_numero": "BC-1048",
                "pedido_itens_html": summary_html,
            },
            template=template,
        )
    finally:
        db.close()

    assert "Resumo do pedido" in rendered.html
    assert "Produto Teste" in rendered.html
    assert rendered.html.index("Produto Teste") < rendered.html.index("</div>")


def test_renderizacao_de_todo_fluxo_de_pedidos_mantem_um_unico_resumo_padronizado():
    seeds_module = importlib.import_module("app.modules.email.seeds")
    email_service_module = importlib.import_module("app.modules.email.service")
    summary_html = (
        '<table role="presentation" width="100%" style="margin:20px 0 24px;'
        'border:1px solid #e8e1d8;background:#fbfaf8;">'
        "<tr><td>Resumo do pedido</td></tr><tr><td>Produto Teste</td></tr></table>"
    )
    payload = {
        "cliente_nome": "Bianca",
        "pedido_numero": "BC-1048",
        "pedido_total": "R$ 249,90",
        "pedido_itens_html": summary_html,
        "pedido_itens_text": "Produto Teste",
        "loja_nome": "Bia Collections",
        "loja_url": "https://bia.example.test",
        "loja_home_url": "https://bia.example.test",
        "link_meus_pedidos": "https://bia.example.test/meus-pedidos",
    }

    db = SessionLocal()
    try:
        service = email_service_module.EmailAutomationService(db)
        for data in seeds_module.ADMIN_EMAIL_TEMPLATE_SEEDS:
            if data["evento"] not in seeds_module.ORDER_SUMMARY_ADMIN_EVENTS:
                continue
            template = EmailTemplate(**data)
            rendered = service.render_template(template.slug, payload, template=template)
            assert rendered.html.count("Resumo do pedido") == 1, template.slug
            assert rendered.html.count("Produto Teste") == 1, template.slug
            assert "{{pedido_itens_html}}" not in rendered.html, template.slug
            assert rendered.html.index("Produto Teste") < rendered.html.rindex("R$ 249,90"), template.slug
    finally:
        db.close()


def test_statuses_pendentes_de_pagamento_disparam_email_pendente():
    payment_status_module = importlib.import_module("app.services.payment_status")

    assert (
        payment_status_module.ORDER_STATUS_EMAIL_EVENTS[
            payment_status_module.ORDER_STATUS_AGUARDANDO
        ]
        == "payment_pending"
    )
    for status_mp in (
        "pending",
        "in_process",
        "processing",
        "in_review",
        "action_required",
    ):
        assert payment_status_module.PAYMENT_EMAIL_EVENTS[status_mp] == "payment_pending"


def test_fluxo_completo_troca_devolucao_dispara_emails_cliente(client, monkeypatch):
    seed_admin_email_flow(monkeypatch)
    create_user("master-pos-venda", MASTER_ADMIN_EMAIL, is_admin=True)
    order_id, _ = create_order_record(
        username="cliente-troca",
        email="cliente-troca@example.com",
        numero="TROCA1001",
        status_pedido="Entregue",
    )

    created = client.post(
        "/api/v1/pos-venda/trocas-devolucoes",
        json={
            "pedido_numero": "TROCA1001",
            "tipo": "troca",
            "motivo": "O tamanho recebido nao serviu como esperado.",
        },
        headers=auth_headers("cliente-troca"),
    )
    assert created.status_code == 201
    body = created.json()
    assert body["status"] == "recebida"
    assert body["protocolo"].startswith("TD-TROCA1001-")

    approved = client.patch(
        f"/api/v1/admin/pos-venda/trocas-devolucoes/{body['id']}",
        json={"status": "aprovada"},
        headers=auth_headers("master-pos-venda"),
    )
    assert approved.status_code == 200
    assert approved.json()["status"] == "aprovada"

    logs = [log for log in email_logs() if log.order_id == order_id]
    assert {log.event_key for log in logs} >= {
        "troca_devolucao_recebida",
        "troca_devolucao_aprovada",
    }
    customer_logs = [log for log in logs if log.email == "cliente-troca@example.com"]
    assert all("Resumo do pedido" in (log.html_snapshot or "") for log in customer_logs)


def test_documento_e_reembolso_aprovado_disparam_emails(client, monkeypatch):
    seed_admin_email_flow(monkeypatch)
    create_user("master-documento", MASTER_ADMIN_EMAIL, is_admin=True)
    order_id, _ = create_order_record(
        username="cliente-documento",
        email="cliente-documento@example.com",
        numero="DOC1001",
        status_pedido="Entregue",
        total=249.9,
    )

    document = client.post(
        "/api/v1/admin/pos-venda/pedidos/DOC1001/documentos",
        json={
            "tipo": "nota_fiscal",
            "numero": "NF-1001",
            "url": "https://documentos.example.test/nf-1001.pdf",
        },
        headers=auth_headers("master-documento"),
    )
    refund = client.post(
        "/api/v1/admin/pos-venda/pedidos/DOC1001/reembolsos/aprovar",
        json={"valor": 100.0, "prazo_dias_uteis": 7},
        headers=auth_headers("master-documento"),
    )

    assert document.status_code == 201
    assert document.json()["tipo"] == "nota_fiscal"
    assert refund.status_code == 201
    assert refund.json()["status"] == "aprovado"
    logs = [log for log in email_logs() if log.order_id == order_id]
    assert {log.event_key for log in logs} >= {
        "nota_fiscal_recibo",
        "reembolso_aprovado",
    }
    assert all("Resumo do pedido" in (log.html_snapshot or "") for log in logs)


def test_metricas_email_e_retry_usam_api_admin_consolidada(client, monkeypatch):
    seed_admin_email_flow(monkeypatch)
    create_user("master-metricas-email", MASTER_ADMIN_EMAIL, is_admin=True)
    db = SessionLocal()
    try:
        log = EmailLog(
            email="cliente-metricas@example.com",
            template_slug="teste",
            event_key="pedido_criado",
            status="enviado",
            attempts=1,
        )
        db.add(log)
        db.commit()
        db.refresh(log)
        log_id = log.id
    finally:
        db.close()

    headers = auth_headers("master-metricas-email")
    metrics = client.get("/api/v1/admin/emails/metricas", headers=headers)
    retry = client.post(f"/api/v1/admin/emails/logs/{log_id}/retry", headers=headers)

    assert metrics.status_code == 200
    assert metrics.json()["total"] == 1
    assert metrics.json()["taxa_sucesso"] == 100.0
    assert retry.status_code == 409


def test_pedido_entregue_agenda_avaliacao_para_tres_dias(client, monkeypatch):
    seed_admin_email_flow(monkeypatch)
    create_user("master-review-delay", MASTER_ADMIN_EMAIL, is_admin=True)
    order_id, _ = create_order_record(
        username="cliente-review-delay",
        email="cliente-review-delay@example.com",
        numero="REVIEW3001",
        status_pedido="Enviado",
    )

    response = client.put(
        "/api/v1/admin/pedidos/REVIEW3001/status",
        json={"status": "Entregue"},
        headers=auth_headers("master-review-delay"),
    )

    assert response.status_code == 200
    logs = [log for log in email_logs() if log.order_id == order_id]
    delivered = next(log for log in logs if log.event_key == "pedido_entregue")
    review = next(log for log in logs if log.event_key == "avaliacao_pedido")
    assert delivered.next_attempt_at is None
    assert review.next_attempt_at is not None
    delay = review.next_attempt_at.replace(tzinfo=timezone.utc) - datetime.now(timezone.utc)
    assert timedelta(days=2, hours=23) < delay <= timedelta(days=3, minutes=1)


def test_pagamento_aprovado_cartao_e_webhook_registram_logs_cliente_e_admin(client, monkeypatch):
    seed_admin_email_flow(monkeypatch)
    sent, _ = patch_service_email_provider(monkeypatch)
    card_order_id, _ = create_order_record(
        username="cliente-email-card",
        email="cliente-email-card@example.com",
        numero="EMAILPAY1",
        forma_pagamento="cartao",
        total=112.5,
    )
    webhook_order_id, _ = create_order_record(
        username="cliente-email-webhook",
        email="cliente-email-webhook@example.com",
        numero="EMAILPAY2",
        forma_pagamento="cartao",
        total=90.0,
    )

    pagamentos_module = importlib.import_module("app.routers.pagamentos")

    class FakeCardPayment:
        def create(self, payload, options=None):
            return {
                "status": 201,
                "response": {
                    "id": "pay_card_email",
                    "status": "approved",
                    "status_detail": "accredited",
                    "payment_method_id": "visa",
                },
            }

        def get(self, payment_id):
            assert payment_id == "pay_webhook_email"
            return {
                "status": 200,
                "response": {
                    "id": "pay_webhook_email",
                    "status": "approved",
                    "status_detail": "accredited",
                    "external_reference": "EMAILPAY2",
                    "transaction_amount": 90.0,
                    "payment_method_id": "visa",
                    "metadata": {"pedido_numero": "EMAILPAY2", "payment_flow": "cartao"},
                },
            }

    class FakeSDK:
        def __init__(self, access_token):
            assert access_token == "token"

        def payment(self):
            return FakeCardPayment()

    def fake_criar_order_cartao_mp(payload, idempotency_key):
        return 201, {
            "id": "ord_card_email",
            "status": "processed",
            "status_detail": "accredited",
            "external_reference": "EMAILPAY1",
            "total_amount": "112.50",
            "transactions": {
                "payments": [
                    {
                        "id": "pay_card_email",
                        "amount": "112.50",
                        "status": "processed",
                        "status_detail": "accredited",
                        "payment_method": {"id": "visa", "type": "credit_card"},
                    }
                ]
            },
        }

    monkeypatch.setattr(pagamentos_module.settings, "MP_ACCESS_TOKEN", "token")
    monkeypatch.setattr(pagamentos_module.settings, "MP_WEBHOOK_SECRET", "")
    monkeypatch.setattr(pagamentos_module.settings, "ADMIN_ORDER_NOTIFICATION_EMAIL", "dona@example.com")
    monkeypatch.setattr(pagamentos_module.settings, "FRONTEND_URL", "https://loja.example.test")
    monkeypatch.setattr(pagamentos_module.mercadopago, "SDK", FakeSDK)
    monkeypatch.setattr(pagamentos_module, "_criar_order_cartao_mp", fake_criar_order_cartao_mp)

    card_response = client.post(
        "/api/v1/pagamentos/cartao/EMAILPAY1",
        json={
            "token": "tok_card",
            "payment_method_id": "visa",
            "issuer_id": "123",
            "installments": 1,
            "transaction_amount": 112.5,
            "payer": {
                "email": "pagador@example.com",
                "identification": {"type": "CPF", "number": "12345678909"},
            },
        },
        headers=auth_headers("cliente-email-card"),
    )
    webhook_response = client.post(
        "/api/v1/pagamentos/webhook",
        json={"type": "payment", "data": {"id": "pay_webhook_email"}},
    )

    assert card_response.status_code == 200
    assert webhook_response.status_code == 200
    logs = email_logs()
    assert len(logs) == 4
    customer_logs = [log for log in logs if log.event_key == "pagamento_aprovado"]
    admin_logs = [log for log in logs if log.event_key == "admin_order_paid"]
    assert len(customer_logs) == 2
    assert len(admin_logs) == 2
    assert {log.order_id for log in customer_logs} == {card_order_id, webhook_order_id}
    for log, numero, recipient in [
        (customer_logs[0], "EMAILPAY1", "cliente-email-card@example.com"),
        (customer_logs[1], "EMAILPAY2", "cliente-email-webhook@example.com"),
    ]:
        assert log.template_slug == "admin-default-pagamento-aprovado"
        payload = assert_email_log_snapshot(
            log,
            event_key="pagamento_aprovado",
            recipient=recipient,
            status_log="pendente",
            subject_contains=f"Pagamento aprovado - Pedido {numero}",
            html_contains="Pagamento aprovado",
            text_contains=numero,
            payload_values={"pedido_numero": numero},
        )
        assert log.dedupe_key == f"pagamento_aprovado:{numero}"
        assert payload["link_meus_pedidos"] == "https://loja.example.test/meus-pedidos"
        assert payload["pedido_itens_text"].startswith(f"Produto {numero}")
        assert "Resumo do pedido" in log.html_snapshot
        assert f"Produto {numero}" in log.html_snapshot
        assert "Quantidade: <strong>1</strong>" in log.html_snapshot
        assert "Cor: <strong>Dourado</strong>" in log.html_snapshot
        assert "Modelo/Tamanho: <strong>Unico</strong>" in log.html_snapshot
        assert f"/uploads/produtos/{numero.lower()}.webp" in log.html_snapshot
        assert "Total confirmado" in log.html_snapshot
        assert "Ver meus pedidos" in log.html_snapshot
        assert "https://loja.example.test/meus-pedidos" in log.html_snapshot
        assert "Ir para a home da Bia Collections" in log.html_snapshot
        assert "https://loja.example.test" in log.html_snapshot
        assert "Ver Instagram" in log.html_snapshot
        assert "https://www.instagram.com/biacollectionstore" in log.html_snapshot
    for log, numero, customer_email in [
        (admin_logs[0], "EMAILPAY1", "cliente-email-card@example.com"),
        (admin_logs[1], "EMAILPAY2", "cliente-email-webhook@example.com"),
    ]:
        assert log.template_slug == "admin-order-paid"
        payload = assert_email_log_snapshot(
            log,
            event_key="admin_order_paid",
            recipient="dona@example.com",
            status_log="enviado",
            subject_contains=f"Novo pedido pago #{numero}",
            html_contains="Novo pedido pago",
            text_contains=numero,
            payload_values={"pedido_numero": numero, "customer_email": customer_email},
        )
        assert log.dedupe_key == f"admin_order_paid:{numero}"
        assert payload["link_pedido_admin"] == f"https://loja.example.test/admin/pedidos/{numero}"
    assert [item["to"] for item in sent] == ["dona@example.com", "dona@example.com"]


def test_pagamento_recusado_usa_template_admin_com_recuperacao_de_compra(client, monkeypatch):
    seed_admin_email_flow(monkeypatch)
    order_id, _ = create_order_record(
        username="cliente-email-refused",
        email="cliente-email-refused@example.com",
        numero="EMAILREF1",
        forma_pagamento="cartao",
        total=88.0,
    )
    email_service_module = importlib.import_module("app.modules.email.service")

    db = SessionLocal()
    try:
        pedido = db.query(Pedido).filter(Pedido.id == order_id).one()
        email_service_module.trigger_order_email_event(db, "payment_refused", pedido)
    finally:
        db.close()

    logs = email_logs()
    assert len(logs) == 1
    log = logs[0]
    assert log.template_slug == "admin-default-pagamento-recusado"
    payload = assert_email_log_snapshot(
        log,
        event_key="pagamento_recusado",
        recipient="cliente-email-refused@example.com",
        status_log="pendente",
        subject_contains="Pagamento não aprovado - Pedido EMAILREF1",
        html_contains="Pagamento não aprovado",
        text_contains="Tente novamente",
        payload_values={"pedido_numero": "EMAILREF1", "cliente_nome": "cliente-email-refused"},
    )
    assert log.dedupe_key == "pagamento_recusado:EMAILREF1"
    assert payload["link_meus_pedidos"] == "http://localhost:3000/meus-pedidos"
    assert "Seu pedido ainda pode ser concluído" in log.html_snapshot
    assert "Resumo do pedido" in log.html_snapshot
    assert "Produto EMAILREF1" in log.html_snapshot
    assert "Quantidade: <strong>1</strong>" in log.html_snapshot
    assert "Cor: <strong>Dourado</strong>" in log.html_snapshot
    assert "Modelo/Tamanho: <strong>Unico</strong>" in log.html_snapshot
    assert "/uploads/produtos/emailref1.webp" in log.html_snapshot
    assert "Total do pedido" in log.html_snapshot
    assert "Tentar novamente" in log.html_snapshot
    assert "http://localhost:3000/meus-pedidos" in log.html_snapshot
    assert "Ir para a home da Bia Collections" in log.html_snapshot
    assert "Ver Instagram" in log.html_snapshot


def test_pagamento_pendente_usa_template_admin_com_chamada_para_finalizar(client, monkeypatch):
    seed_admin_email_flow(monkeypatch)
    order_id, _ = create_order_record(
        username="cliente-email-pending",
        email="cliente-email-pending@example.com",
        numero="EMAILPEND1",
        forma_pagamento="pix",
        total=138.0,
    )
    email_service_module = importlib.import_module("app.modules.email.service")

    db = SessionLocal()
    try:
        pedido = db.query(Pedido).filter(Pedido.id == order_id).one()
        email_service_module.trigger_order_email_event(db, "payment_pending", pedido)
    finally:
        db.close()

    logs = email_logs()
    assert len(logs) == 1
    log = logs[0]
    assert log.template_slug == "admin-default-pagamento-pendente"
    payload = assert_email_log_snapshot(
        log,
        event_key="pagamento_pendente",
        recipient="cliente-email-pending@example.com",
        status_log="pendente",
        subject_contains="Pagamento pendente - Pedido EMAILPEND1",
        html_contains="Pagamento pendente",
        text_contains="Finalize o pagamento",
        payload_values={"pedido_numero": "EMAILPEND1", "cliente_nome": "cliente-email-pending"},
    )
    assert log.dedupe_key == "pagamento_pendente:EMAILPEND1"
    assert payload["link_meus_pedidos"] == "http://localhost:3000/meus-pedidos"
    assert "Finalize o pagamento para garantir seus produtos" in log.html_snapshot
    assert "Enquanto o pagamento não é confirmado" in log.html_snapshot
    assert "Resumo do pedido" in log.html_snapshot
    assert "Produto EMAILPEND1" in log.html_snapshot
    assert "Quantidade: <strong>1</strong>" in log.html_snapshot
    assert "Cor: <strong>Dourado</strong>" in log.html_snapshot
    assert "Modelo/Tamanho: <strong>Unico</strong>" in log.html_snapshot
    assert "/uploads/produtos/emailpend1.webp" in log.html_snapshot
    assert "Total do pedido" in log.html_snapshot
    assert "Finalizar pagamento" in log.html_snapshot
    assert "http://localhost:3000/meus-pedidos" in log.html_snapshot
    assert "Ir para a home da Bia Collections" in log.html_snapshot
    assert "Ver Instagram" in log.html_snapshot


def test_webhook_aprovado_repetido_nao_duplica_email_admin(client, monkeypatch):
    seed_admin_email_flow(monkeypatch)
    sent, _ = patch_service_email_provider(monkeypatch)
    create_order_record(
        username="cliente-email-webhook-dup",
        email="cliente-email-webhook-dup@example.com",
        numero="EMAILDUP1",
        forma_pagamento="cartao",
        total=75.0,
    )

    pagamentos_module = importlib.import_module("app.routers.pagamentos")

    class FakePaymentResource:
        def get(self, payment_id):
            assert payment_id == "pay_webhook_dup"
            return {
                "status": 200,
                "response": {
                    "id": "pay_webhook_dup",
                    "status": "approved",
                    "status_detail": "accredited",
                    "external_reference": "EMAILDUP1",
                    "transaction_amount": 75.0,
                    "payment_method_id": "visa",
                    "metadata": {"pedido_numero": "EMAILDUP1", "payment_flow": "cartao"},
                },
            }

    class FakeSDK:
        def __init__(self, access_token):
            assert access_token == "token"

        def payment(self):
            return FakePaymentResource()

    monkeypatch.setattr(pagamentos_module.settings, "MP_ACCESS_TOKEN", "token")
    monkeypatch.setattr(pagamentos_module.settings, "MP_WEBHOOK_SECRET", "")
    monkeypatch.setattr(pagamentos_module.settings, "ADMIN_ORDER_NOTIFICATION_EMAIL", "dona@example.com")
    monkeypatch.setattr(pagamentos_module.mercadopago, "SDK", FakeSDK)

    first = client.post(
        "/api/v1/pagamentos/webhook",
        json={"type": "payment", "data": {"id": "pay_webhook_dup"}},
    )
    second = client.post(
        "/api/v1/pagamentos/webhook",
        json={"type": "payment", "data": {"id": "pay_webhook_dup"}},
    )

    assert first.status_code == 200
    assert second.status_code == 200
    logs = email_logs()
    customer_logs = [log for log in logs if log.event_key == "pagamento_aprovado"]
    admin_logs = [log for log in logs if log.event_key == "admin_order_paid"]
    assert len(customer_logs) == 1
    assert len(admin_logs) == 1
    assert admin_logs[0].dedupe_key == "admin_order_paid:EMAILDUP1"
    assert sent[0]["to"] == "dona@example.com"
    assert len(sent) == 1


def test_pagamento_aprovado_sem_email_admin_configurado_usa_master_admin(client, monkeypatch):
    seed_admin_email_flow(monkeypatch)
    sent, _ = patch_service_email_provider(monkeypatch)
    create_order_record(
        username="cliente-email-admin-fallback",
        email="cliente-email-admin-fallback@example.com",
        numero="EMAILFALL1",
        forma_pagamento="cartao",
        total=88.0,
    )

    pagamentos_module = importlib.import_module("app.routers.pagamentos")

    def fake_criar_order_cartao_mp(payload, idempotency_key):
        return 201, {
            "id": "ord_card_fallback",
            "status": "processed",
            "status_detail": "accredited",
            "external_reference": "EMAILFALL1",
            "total_amount": "88.00",
            "transactions": {
                "payments": [
                    {
                        "id": "pay_card_fallback",
                        "amount": "88.00",
                        "status": "processed",
                        "status_detail": "accredited",
                        "payment_method": {"id": "visa", "type": "credit_card"},
                    }
                ]
            },
        }

    monkeypatch.setattr(pagamentos_module.settings, "MP_ACCESS_TOKEN", "token")
    monkeypatch.setattr(pagamentos_module.settings, "ADMIN_ORDER_NOTIFICATION_EMAIL", "")
    monkeypatch.setattr(pagamentos_module, "_criar_order_cartao_mp", fake_criar_order_cartao_mp)

    response = client.post(
        "/api/v1/pagamentos/cartao/EMAILFALL1",
        json={
            "token": "tok_card",
            "payment_method_id": "visa",
            "issuer_id": "123",
            "installments": 1,
            "transaction_amount": 88.0,
            "payer": {
                "email": "pagador@example.com",
                "identification": {"type": "CPF", "number": "12345678909"},
            },
        },
        headers=auth_headers("cliente-email-admin-fallback"),
    )

    assert response.status_code == 200
    admin_logs = [log for log in email_logs() if log.event_key == "admin_order_paid"]
    assert len(admin_logs) == 1
    assert admin_logs[0].email == MASTER_ADMIN_EMAIL
    assert admin_logs[0].status == "enviado"
    assert sent[0]["to"] == MASTER_ADMIN_EMAIL


def test_pedido_enviado_por_status_e_rastreio_sem_duplicar(client, monkeypatch):
    seed_admin_email_flow(monkeypatch)
    create_user("master-email-ship", MASTER_ADMIN_EMAIL, is_admin=True)
    headers = auth_headers("master-email-ship")
    status_order_id, _ = create_order_record(
        username="cliente-email-ship-status",
        email="cliente-email-ship-status@example.com",
        numero="EMAILSHIP1",
        status_pedido="Pagamento aprovado",
        codigo_rastreio="BRSTATUS123",
    )
    tracking_order_id, _ = create_order_record(
        username="cliente-email-ship-track",
        email="cliente-email-ship-track@example.com",
        numero="EMAILSHIP2",
        status_pedido="Pagamento aprovado",
    )
    duplicate_order_id, _ = create_order_record(
        username="cliente-email-ship-dup",
        email="cliente-email-ship-dup@example.com",
        numero="EMAILSHIP3",
        status_pedido="Pagamento aprovado",
        codigo_rastreio="BRDUP789",
    )

    status_response = client.put(
        "/api/v1/admin/pedidos/EMAILSHIP1/status",
        json={"status": "Enviado"},
        headers=headers,
    )
    tracking_response = client.put(
        "/api/v1/admin/pedidos/EMAILSHIP2/rastreio",
        json={"codigo_rastreio": "BRTRACK456"},
        headers=headers,
    )
    duplicate_status = client.put(
        "/api/v1/admin/pedidos/EMAILSHIP3/status",
        json={"status": "Enviado"},
        headers=headers,
    )
    duplicate_tracking = client.put(
        "/api/v1/admin/pedidos/EMAILSHIP3/rastreio",
        json={"codigo_rastreio": "BRDUP789"},
        headers=headers,
    )

    assert status_response.status_code == 200
    assert tracking_response.status_code == 200
    assert duplicate_status.status_code == 200
    assert duplicate_tracking.status_code == 200

    logs = email_logs()
    assert len([log for log in logs if log.order_id == duplicate_order_id]) == 1
    by_order = {log.order_id: log for log in logs}
    assert by_order[status_order_id].template_slug == "admin-default-pedido-enviado"
    assert_email_log_snapshot(
        by_order[status_order_id],
        event_key="pedido_enviado",
        recipient="cliente-email-ship-status@example.com",
        status_log="pendente",
        subject_contains="Seu pedido EMAILSHIP1 foi enviado",
        html_contains="BRSTATUS123",
        text_contains="BRSTATUS123",
        payload_values={"pedido_numero": "EMAILSHIP1", "codigo_rastreio": "BRSTATUS123"},
    )
    assert_email_log_snapshot(
        by_order[tracking_order_id],
        event_key="pedido_enviado",
        recipient="cliente-email-ship-track@example.com",
        status_log="pendente",
        subject_contains="Seu pedido EMAILSHIP2 foi enviado",
        html_contains="BRTRACK456",
        text_contains="BRTRACK456",
        payload_values={"pedido_numero": "EMAILSHIP2", "codigo_rastreio": "BRTRACK456"},
    )
    assert by_order[duplicate_order_id].dedupe_key == "pedido_enviado:EMAILSHIP3:BRDUP789"
    assert "BRDUP789" in (by_order[duplicate_order_id].html_snapshot or "")


def test_recuperacao_senha_usa_template_admin_e_log_sent(client, monkeypatch):
    seed_admin_email_flow(monkeypatch)
    sent, _ = patch_service_email_provider(monkeypatch)
    create_user("cliente-email-reset", "cliente-email-reset@example.com")

    response = client.post(
        "/api/v1/auth/solicitar-redefinicao",
        json={"email": " Cliente-Email-Reset@Example.com "},
    )

    assert response.status_code == 200
    logs = email_logs()
    assert len(logs) == 1
    log = logs[0]
    assert log.template_slug == "admin-default-recuperacao-senha"
    payload = assert_email_log_snapshot(
        log,
        event_key="recuperacao_senha",
        recipient="cliente-email-reset@example.com",
        status_log="enviado",
        subject_contains="Redefinição de senha - Bia Collections",
        html_contains="Redefinição de senha",
        text_contains="15",
        payload_values={"cliente_nome": "cliente-email-reset", "minutos_expiracao": "15"},
    )
    assert payload["codigo"].isdigit()
    assert payload["codigo"] in log.html_snapshot
    assert payload["codigo"] in log.text_snapshot
    assert sent[0]["to"] == "cliente-email-reset@example.com"


def test_codigo_acesso_login_cadastro_reenviar_usa_template_admin(client, monkeypatch):
    seed_admin_email_flow(monkeypatch)
    sent, _ = patch_service_email_provider(monkeypatch)
    create_user("cliente-email-2fa", "cliente-email-2fa@example.com")

    login = client.post(
        "/api/v1/auth/login",
        json={"login": "cliente-email-2fa", "senha": PASSWORD},
    )
    assert login.status_code == 200
    update_challenge_by_token(
        login.json()["two_factor_token"],
        ultimo_envio_em=datetime.now(timezone.utc) - timedelta(seconds=61),
    )
    resend = client.post(
        "/api/v1/auth/login/reenviar-2fa",
        json={"two_factor_token": login.json()["two_factor_token"]},
    )
    cadastro = client.post(
        "/api/v1/auth/cadastro",
        json={
            "username": "cliente-email-cadastro-2fa",
            "email": "cliente-email-cadastro-2fa@example.com",
            "senha": PASSWORD,
            "confirma_senha": PASSWORD,
        },
    )

    assert resend.status_code == 200
    assert cadastro.status_code == 201
    logs = email_logs()
    assert len(logs) == 3
    assert len(sent) == 3
    assert [log.event_key for log in logs] == ["codigo_acesso", "codigo_acesso", "codigo_acesso"]
    assert [log.status for log in logs] == ["enviado", "enviado", "enviado"]
    assert [log.template_slug for log in logs] == ["admin-default-codigo-acesso"] * 3
    assert [log.email for log in logs] == [
        "cliente-email-2fa@example.com",
        "cliente-email-2fa@example.com",
        "cliente-email-cadastro-2fa@example.com",
    ]
    for log in logs:
        payload = json.loads(log.payload_json or "{}")
        assert payload["codigo"].isdigit()
        assert payload["codigo"] in log.html_snapshot
        assert payload["codigo"] in log.text_snapshot
        assert log.subject == "Seu código de acesso - Bia Collections"
        assert "Se você não tentou acessar" in log.html_snapshot
        assert "Instagram" not in log.html_snapshot


def test_adicionar_cupom_na_conta_nao_dispara_email(client, monkeypatch):
    seed_admin_email_flow(monkeypatch)
    create_user("cliente-email-cupom", "cliente-email-cupom@example.com")
    db = SessionLocal()
    try:
        cupom = Cupom(
            codigo="EMAIL15",
            descricao="Cupom de email",
            tipo="porcentagem",
            valor=15,
            validade=date.today() + timedelta(days=30),
            ativo=True,
            valor_minimo_pedido=50.0,
        )
        db.add(cupom)
        db.commit()
    finally:
        db.close()

    response = client.post(
        "/api/v1/cupons/adicionar",
        json={"codigo": "email15"},
        headers=auth_headers("cliente-email-cupom"),
    )

    assert response.status_code == 200
    assert email_logs() == []


def test_admin_cupons_reutiliza_codigo_apos_soft_delete_com_vinculo(client):
    create_user("master-cupom-reuso", MASTER_ADMIN_EMAIL, is_admin=True)
    cliente_id = create_user("cliente-cupom-reuso", "cliente-cupom-reuso@example.com")
    headers = auth_headers("master-cupom-reuso")
    payload = {
        "codigo": "REUSO10",
        "descricao": "Cupom de reuso",
        "tipo": "valor",
        "valor": 10,
        "validade": (date.today() + timedelta(days=7)).isoformat(),
        "ativo": True,
        "valor_minimo_pedido": 0,
        "max_usos": 100,
    }

    criado = client.post("/api/v1/admin/cupons", json=payload, headers=headers)
    assert criado.status_code == 201
    cupom_antigo_id = criado.json()["id"]

    duplicado = client.post(
        "/api/v1/admin/cupons",
        json={**payload, "descricao": "Cupom duplicado ativo"},
        headers=headers,
    )
    assert duplicado.status_code == 409
    assert duplicado.json()["detail"] == "Cupom já cadastrado."

    db = SessionLocal()
    try:
        db.add(CupomResgatado(cupom_id=cupom_antigo_id, usuario_id=cliente_id))
        db.commit()
    finally:
        db.close()

    deletado = client.delete(f"/api/v1/admin/cupons/{cupom_antigo_id}", headers=headers)
    assert deletado.status_code == 204

    listagem_padrao = client.get("/api/v1/admin/cupons", headers=headers)
    assert listagem_padrao.status_code == 200
    assert cupom_antigo_id not in [cupom["id"] for cupom in listagem_padrao.json()]

    listagem_com_deletados = client.get(
        "/api/v1/admin/cupons?incluir_deletados=true",
        headers=headers,
    )
    assert listagem_com_deletados.status_code == 200
    assert cupom_antigo_id in [cupom["id"] for cupom in listagem_com_deletados.json()]

    recriado = client.post(
        "/api/v1/admin/cupons",
        json={**payload, "descricao": "Cupom recriado"},
        headers=headers,
    )
    assert recriado.status_code == 201
    assert recriado.json()["codigo"] == "REUSO10"
    assert recriado.json()["id"] != cupom_antigo_id

    db = SessionLocal()
    try:
        cupons = db.query(Cupom).filter(Cupom.codigo == "REUSO10").order_by(Cupom.id.asc()).all()
        assert len(cupons) == 2
        assert cupons[0].id == cupom_antigo_id
        assert cupons[0].ativo is False
        assert cupons[0].deletado_em is not None
        assert cupons[1].id == recriado.json()["id"]
        assert cupons[1].deletado_em is None
        assert (
            db.query(CupomResgatado)
            .filter(
                CupomResgatado.cupom_id == cupom_antigo_id,
                CupomResgatado.usuario_id == cliente_id,
            )
            .count()
            == 1
        )
    finally:
        db.close()


def test_admin_cupons_put_ignora_codigo_soft_deletado_ao_validar_conflito(client):
    create_user("master-cupom-put", MASTER_ADMIN_EMAIL, is_admin=True)
    headers = auth_headers("master-cupom-put")
    validade = date.today() + timedelta(days=7)
    db = SessionLocal()
    try:
        soft_deletado = Cupom(
            codigo="ANTIGO10",
            descricao="Cupom antigo",
            tipo="valor",
            valor=10,
            validade=validade,
            ativo=False,
            deletado_em=datetime.now(timezone.utc),
        )
        editavel = Cupom(
            codigo="EDITAR10",
            descricao="Cupom editavel",
            tipo="valor",
            valor=10,
            validade=validade,
            ativo=True,
        )
        ocupado = Cupom(
            codigo="OCUPADO10",
            descricao="Cupom ocupado",
            tipo="valor",
            valor=10,
            validade=validade,
            ativo=True,
        )
        db.add_all([soft_deletado, editavel, ocupado])
        db.commit()
        editavel_id = editavel.id
    finally:
        db.close()

    permitido = client.put(
        f"/api/v1/admin/cupons/{editavel_id}",
        json={
            "codigo": "ANTIGO10",
            "descricao": "Cupom agora reaproveitado",
            "tipo": "valor",
            "valor": 10,
            "validade": validade.isoformat(),
            "ativo": True,
            "valor_minimo_pedido": 0,
            "max_usos": 100,
        },
        headers=headers,
    )
    assert permitido.status_code == 200
    assert permitido.json()["codigo"] == "ANTIGO10"

    conflito = client.put(
        f"/api/v1/admin/cupons/{editavel_id}",
        json={
            "codigo": "OCUPADO10",
            "descricao": "Cupom em conflito",
            "tipo": "valor",
            "valor": 10,
            "validade": validade.isoformat(),
            "ativo": True,
            "valor_minimo_pedido": 0,
            "max_usos": 100,
        },
        headers=headers,
    )
    assert conflito.status_code == 409
    assert conflito.json()["detail"] == "Cupom já cadastrado."


def test_cupom_promocional_novo_dispara_campanha_no_checkout(client, monkeypatch):
    seed_admin_email_flow(monkeypatch)
    create_user("master-cupom-campanha", MASTER_ADMIN_EMAIL, is_admin=True)
    recipient_id = create_user("cliente-email-cupom", "cliente-email-cupom@example.com")
    db = SessionLocal()
    try:
        recipient = db.query(Usuario).filter(Usuario.id == recipient_id).one()
        set_marketing_consent(db, recipient, True, source="teste")
    finally:
        db.close()

    response = client.post(
        "/api/v1/admin/cupons",
        json={
            "codigo": "EMAIL15",
            "descricao": "Cupom momentâneo de e-mail",
            "tipo": "porcentagem",
            "valor": 15,
            "validade": (date.today() + timedelta(days=7)).isoformat(),
            "ativo": True,
            "valor_minimo_pedido": 50,
            "max_usos": 100,
        },
        headers=auth_headers("master-cupom-campanha"),
    )

    assert response.status_code == 201
    logs = email_logs()
    assert len(logs) == 1
    log = logs[0]
    assert log.template_slug == "admin-default-cupom-disponivel"
    assert_email_log_snapshot(
        log,
        event_key="marketing_campaign",
        recipient="cliente-email-cupom@example.com",
        status_log="pendente",
        subject_contains="Seu cupom EMAIL15 está disponível",
        html_contains="EMAIL15",
        text_contains="EMAIL15",
        payload_values={"cupom_codigo": "EMAIL15", "cliente_nome": "cliente-email-cupom"},
    )


def test_email_boas_vindas_inclui_cupom_para_checkout(client, monkeypatch):
    seed_admin_email_flow(monkeypatch)
    user_id = create_user("cliente-boas-vindas", "cliente-boas-vindas@example.com")
    db = SessionLocal()
    try:
        db.add(
            Cupom(
                codigo="BOAS-VINDAS10",
                descricao="10% na primeira compra",
                tipo="porcentagem",
                valor=10,
                validade=date.today() + timedelta(days=30),
                ativo=True,
            )
        )
        db.commit()
        usuario = db.query(Usuario).filter(Usuario.id == user_id).one()
        trigger_welcome_email_event(db, usuario)
    finally:
        db.close()

    logs = email_logs()
    assert len(logs) == 1
    assert logs[0].event_key == "boas_vindas"
    assert "BOAS-VINDAS10" in (logs[0].html_snapshot or "")
    assert "10%" in (logs[0].text_snapshot or "")


def test_boas_vindas_so_apos_confirmar_cadastro(client, monkeypatch):
    seed_admin_email_flow(monkeypatch)
    patch_service_email_provider(monkeypatch)
    create_user("cliente-login-sem-boas-vindas", "cliente-login-sem-boas-vindas@example.com")

    login = client.post(
        "/api/v1/auth/login",
        json={"login": "cliente-login-sem-boas-vindas", "senha": PASSWORD},
    )
    assert login.status_code == 200
    login_token = login.json()["two_factor_token"]
    login_challenge = get_challenge_by_token(login_token)
    assert login_challenge.finalidade == "login"
    login_code = json.loads(email_logs()[-1].payload_json or "{}")["codigo"]

    login_verify = client.post(
        "/api/v1/auth/login/verificar-2fa",
        json={"two_factor_token": login_token, "codigo": login_code},
    )
    assert login_verify.status_code == 200
    assert "boas_vindas" not in [log.event_key for log in email_logs()]

    cadastro = client.post(
        "/api/v1/auth/cadastro",
        json={
            "username": "cliente-cadastro-boas-vindas",
            "email": "cliente-cadastro-boas-vindas@example.com",
            "senha": PASSWORD,
            "confirma_senha": PASSWORD,
        },
    )
    assert cadastro.status_code == 201
    cadastro_token = cadastro.json()["two_factor_token"]
    cadastro_challenge = get_challenge_by_token(cadastro_token)
    assert cadastro_challenge.finalidade == "cadastro"
    assert "boas_vindas" not in [log.event_key for log in email_logs()]
    cadastro_code = json.loads(email_logs()[-1].payload_json or "{}")["codigo"]

    cadastro_verify = client.post(
        "/api/v1/auth/login/verificar-2fa",
        json={"two_factor_token": cadastro_token, "codigo": cadastro_code},
    )

    assert cadastro_verify.status_code == 200
    logs = email_logs()
    welcome_logs = [log for log in logs if log.event_key == "boas_vindas"]
    assert len(welcome_logs) == 1
    assert "novo_acesso" in [log.event_key for log in logs]
    assert "BOAS-VINDAS10" in (welcome_logs[0].html_snapshot or "")
    assert "10%" in (welcome_logs[0].text_snapshot or "")


def test_campanha_exige_consentimento_aprovacao_rastreia_e_respeita_frequencia(client, monkeypatch):
    seed_admin_email_flow(monkeypatch)
    create_user("master-marketing", MASTER_ADMIN_EMAIL, is_admin=True)
    opted_id = create_user("marketing-optin", "marketing-optin@example.com")
    create_user("marketing-sem-optin", "marketing-sem-optin@example.com")
    db = SessionLocal()
    try:
        opted = db.query(Usuario).filter(Usuario.id == opted_id).one()
        set_marketing_consent(db, opted, True, source="teste")
        template = db.query(EmailTemplate).filter(EmailTemplate.evento == "cupom_disponivel").one()
        template_id = template.id
    finally:
        db.close()

    headers = auth_headers("master-marketing")
    created = client.post(
        "/api/v1/admin/marketing/campanhas",
        json={
            "nome": "Campanha teste",
            "template_a_id": template_id,
            "segmento": "todos",
            "limite_frequencia_dias": 7,
        },
        headers=headers,
    )
    assert created.status_code == 201
    campaign_id = created.json()["id"]
    assert client.post(
        f"/api/v1/admin/marketing/campanhas/{campaign_id}/enviar", headers=headers
    ).status_code == 409
    assert client.post(
        f"/api/v1/admin/marketing/campanhas/{campaign_id}/solicitar-aprovacao", headers=headers
    ).status_code == 200
    assert client.post(
        f"/api/v1/admin/marketing/campanhas/{campaign_id}/aprovar", headers=headers
    ).status_code == 200
    sent = client.post(
        f"/api/v1/admin/marketing/campanhas/{campaign_id}/enviar", headers=headers
    )
    assert sent.status_code == 200
    assert sent.json()["enfileirados"] == 1

    logs = email_logs()
    assert len(logs) == 1
    assert logs[0].email == "marketing-optin@example.com"
    html = logs[0].html_snapshot or ""
    assert "/api/v1/marketing/open/" in html
    assert "/api/v1/marketing/click/" in html
    assert "/api/v1/marketing/unsubscribe/" in html

    open_token = re.search(r'/marketing/open/([^"/]+)\.gif', html).group(1)
    assert client.get(f"/api/v1/marketing/open/{open_token}.gif").status_code == 200
    click_token = re.search(r"/marketing/click/([^\"/]+)", html).group(1)
    click = client.get(f"/api/v1/marketing/click/{click_token}", follow_redirects=False)
    assert click.status_code == 302
    db = SessionLocal()
    try:
        pedido = Pedido(
            numero="MKT-CONV-1",
            usuario_id=opted_id,
            status="Pagamento aprovado",
            forma_pagamento="pix",
            total=199.9,
            valor_frete=0,
        )
        db.add(pedido)
        db.commit()
        db.refresh(pedido)
        assert attribute_order_conversion(db, pedido) is True
    finally:
        db.close()

    metrics = client.get(
        f"/api/v1/admin/marketing/campanhas/{campaign_id}/metricas", headers=headers
    )
    assert metrics.status_code == 200
    assert metrics.json()["destinatarios"] == 1
    assert metrics.json()["aberturas"] == 1
    assert metrics.json()["cliques"] == 1
    assert metrics.json()["conversoes"] == 1


def test_descadastro_bloqueia_novas_campanhas(client):
    user_id = create_user("marketing-descadastro", "marketing-descadastro@example.com")
    db = SessionLocal()
    try:
        user = db.query(Usuario).filter(Usuario.id == user_id).one()
        set_marketing_consent(db, user, True, source="teste")
    finally:
        db.close()

    preferences = client.get(
        "/api/v1/marketing/preferencias",
        headers=auth_headers("marketing-descadastro"),
    )
    assert preferences.status_code == 200
    unsubscribe_url = preferences.json()["descadastro_url"]
    response = client.get(unsubscribe_url)
    assert response.status_code == 200
    db = SessionLocal()
    try:
        preference = db.query(MarketingPreference).filter(
            MarketingPreference.user_id == user_id
        ).one()
        assert preference.email_consent is False
        assert preference.unsubscribed_at is not None
    finally:
        db.close()


def test_interesse_real_em_estoque_dispara_uma_unica_notificacao(client, monkeypatch):
    seed_admin_email_flow(monkeypatch)
    user_id = create_user("cliente-reposicao", "cliente-reposicao@example.com")
    db = SessionLocal()
    try:
        user = db.query(Usuario).filter(Usuario.id == user_id).one()
        set_marketing_consent(db, user, True, source="teste")
        produto = Produto(nome="Bolsa esgotada", preco=129.9, estoque=0, ativo=True)
        db.add(produto)
        db.commit()
        db.refresh(produto)
        produto_id = produto.id
    finally:
        db.close()

    subscribed = client.post(
        f"/api/v1/marketing/estoque/{produto_id}",
        headers=auth_headers("cliente-reposicao"),
    )
    assert subscribed.status_code == 201
    db = SessionLocal()
    try:
        produto = db.query(Produto).filter(Produto.id == produto_id).one()
        produto.estoque = 5
        db.commit()
        assert notify_product_back_in_stock(db, produto) == 1
        assert notify_product_back_in_stock(db, produto) == 0
        interest = db.query(ProductStockInterest).filter(
            ProductStockInterest.user_id == user_id,
            ProductStockInterest.product_id == produto_id,
        ).one()
        assert interest.is_active is False
        assert interest.notified_at is not None
    finally:
        db.close()
    assert len(email_logs()) == 1


def test_admin_email_manual_exige_fluxo_de_aprovacao(client, monkeypatch):
    create_user("master-email-manual", MASTER_ADMIN_EMAIL, is_admin=True)
    recipient_user_id = create_user("manual-target", "manual-target@example.com")
    headers = auth_headers("master-email-manual")
    sent: list[dict[str, str | None]] = []

    class FakeEmailProvider:
        def send(self, to: str, subject: str, html: str | None = None, text: str | None = None):
            sent.append({"to": to, "subject": subject, "html": html, "text": text})

    admin_emails_module = importlib.import_module("app.routers.admin_emails")
    monkeypatch.setattr(admin_emails_module, "EmailProvider", FakeEmailProvider)

    criado = client.post(
        "/api/v1/admin/emails",
        json={
            "nome": "Campanha manual",
            "assunto": "Ola {{cliente_nome}} - {{assunto_extra}}",
            "evento": "manual",
            "status": "ativo",
            "html": "<p>{{cliente_nome}}</p><p>{{mensagem}}</p><p>{{loja_nome}}</p>",
        },
        headers=headers,
    )
    assert criado.status_code == 201

    response = client.post(
        f"/api/v1/admin/emails/{criado.json()['id']}/enviar",
        json={
            "usuario_ids": [recipient_user_id],
            "destinatarios": [
                {
                    "email": " Avulsa@Example.com ",
                    "variaveis": {"cliente_nome": "Avulsa"},
                }
            ],
            "variaveis": {"assunto_extra": "VIP", "mensagem": "Oferta liberada"},
        },
        headers=headers,
    )

    assert response.status_code == 409
    assert "/admin/marketing/campanhas" in response.json()["detail"]["message"]
    assert sent == []
    assert email_logs() == []


def test_admin_emails_crud_e_limite_de_um_ativo_por_evento(client):
    create_user("master-emails", MASTER_ADMIN_EMAIL, is_admin=True)
    headers = auth_headers("master-emails")
    payload = {
        "nome": "Confirmacao de pedido",
        "assunto": "Recebemos seu pedido {{pedido_numero}}",
        "evento": "pedido_criado",
        "status": "ativo",
        "html": "<table><tr><td>Ola {{cliente_nome}}</td></tr></table>",
    }

    sem_token = client.get("/api/v1/admin/emails")
    assert sem_token.status_code == 401

    invalido = client.post("/api/v1/admin/emails", json={}, headers=headers)
    assert invalido.status_code == 422
    assert invalido.json()["detail"]["message"] == "Campo obrigatorio: nome."

    criado = client.post("/api/v1/admin/emails", json=payload, headers=headers)
    assert criado.status_code == 201
    body = criado.json()
    assert body["nome"] == "Confirmacao de pedido"
    assert body["assunto"] == "Recebemos seu pedido {{pedido_numero}}"
    assert body["evento"] == "pedido_criado"
    assert body["status"] == "ativo"
    assert body["html"] == payload["html"]
    assert body["criado_em"] is not None
    assert body["atualizado_em"] is not None

    duplicado_ativo = client.post(
        "/api/v1/admin/emails",
        json={**payload, "nome": "Outro ativo"},
        headers=headers,
    )
    assert duplicado_ativo.status_code == 409
    assert duplicado_ativo.json()["detail"]["message"] == "Ja existe um template ativo para este evento."

    rascunho = client.post(
        "/api/v1/admin/emails",
        json={**payload, "nome": "Rascunho", "status": "rascunho"},
        headers=headers,
    )
    assert rascunho.status_code == 201

    lista = client.get("/api/v1/admin/emails", headers=headers)
    assert lista.status_code == 200
    assert {item["id"] for item in lista.json()} == {body["id"], rascunho.json()["id"]}

    atualizado = client.put(
        f"/api/v1/admin/emails/{rascunho.json()['id']}",
        json={**payload, "nome": "Manual ativo", "evento": "manual"},
        headers=headers,
    )
    assert atualizado.status_code == 200
    assert atualizado.json()["evento"] == "manual"
    assert atualizado.json()["status"] == "ativo"

    removido = client.delete(f"/api/v1/admin/emails/{body['id']}", headers=headers)
    assert removido.status_code == 204


def test_admin_emails_envia_teste_substituindo_variaveis(client, monkeypatch):
    create_user("master-email-teste", MASTER_ADMIN_EMAIL, is_admin=True)
    headers = auth_headers("master-email-teste")
    enviado = {}

    class FakeEmailProvider:
        def send(self, to: str, subject: str, html: str | None = None, text: str | None = None):
            enviado.update({"to": to, "subject": subject, "html": html, "text": text})

    admin_emails_module = importlib.import_module("app.routers.admin_emails")
    monkeypatch.setattr(admin_emails_module, "EmailProvider", FakeEmailProvider)

    criado = client.post(
        "/api/v1/admin/emails",
        json={
            "nome": "Teste envio",
            "assunto": "Pedido {{pedido_numero}} para {{cliente_nome}}",
            "evento": "manual",
            "status": "rascunho",
            "html": "<strong>{{cliente_nome}}</strong> - {{pedido_total}}",
        },
        headers=headers,
    )
    assert criado.status_code == 201

    response = client.post(
        f"/api/v1/admin/emails/{criado.json()['id']}/testar",
        json={
            "email_destino": " Cliente@Example.com ",
            "variaveis": {
                "cliente_nome": "Bia",
                "pedido_numero": "000123",
                "pedido_total": "R$ 149,90",
            },
        },
        headers=headers,
    )

    assert response.status_code == 200
    assert response.json() == {"message": "Email de teste enviado."}
    assert enviado["to"] == "cliente@example.com"
    assert enviado["subject"] == "Pedido 000123 para Bia"
    assert "<strong>Bia</strong> - R$ 149,90" in enviado["html"]
    assert 'data-bia-email-logo="true"' in enviado["html"]
    assert "bia-collections-logooficial.png" in enviado["html"]
    logs = email_logs()
    assert len(logs) == 1
    assert logs[0].event_key == "manual"
    assert logs[0].status == "enviado"
    assert logs[0].dedupe_key.startswith("teste:")


def test_seed_cria_templates_padrao_do_painel_admin(client):
    create_user("master-email-seed", MASTER_ADMIN_EMAIL, is_admin=True)

    seed_email_automation()

    response = client.get(
        "/api/v1/admin/emails",
        headers=auth_headers("master-email-seed"),
    )

    assert response.status_code == 200
    body = response.json()
    by_event = {item["evento"]: item for item in body}
    assert set(by_event) == {
        "boas_vindas",
        "pedido_criado",
        "pagamento_aprovado",
        "pagamento_recusado",
        "pagamento_pendente",
        "pagamento_expirado",
        "pedido_preparando",
        "pedido_enviado",
        "pedido_entregue",
        "pedido_cancelado",
        "reembolso_aprovado",
        "reembolso_processado",
        "nota_fiscal_recibo",
        "troca_devolucao_recebida",
        "troca_devolucao_aprovada",
        "troca_devolucao_recusada",
        "recuperacao_senha",
        "codigo_acesso",
        "senha_alterada",
        "dados_sensiveis_alterados",
        "confirmacao_alteracao_email",
        "novo_acesso",
        "produto_voltou_estoque",
        "carrinho_abandonado",
        "cupom_disponivel",
        "avaliacao_pedido",
        "interno_novo_pedido",
        "interno_pagamento_confirmado",
        "interno_estoque_baixo",
        "interno_troca_devolucao",
        "interno_falha_operacional",
        "manual",
    }
    assert by_event["pedido_criado"]["status"] == "ativo"
    assert by_event["manual"]["status"] == "rascunho"
    assert by_event["codigo_acesso"]["status"] == "ativo"
    assert by_event["pagamento_recusado"]["status"] == "ativo"
    assert by_event["pedido_preparando"]["status"] == "ativo"
    assert by_event["interno_estoque_baixo"]["status"] == "ativo"
    assert "Ver meus pedidos" in by_event["pagamento_aprovado"]["html"]
    assert "Ver Instagram" in by_event["pagamento_aprovado"]["html"]
    assert "Ir para a home da Bia Collections" in by_event["pagamento_aprovado"]["html"]
    assert "pedido_itens_html" in by_event["pagamento_aprovado"]["html"]
    assert "Tentar novamente" in by_event["pagamento_recusado"]["html"]
    assert "Ver Instagram" in by_event["pagamento_recusado"]["html"]
    assert "Ir para a home da Bia Collections" in by_event["pagamento_recusado"]["html"]
    assert "pedido_itens_html" in by_event["pagamento_recusado"]["html"]
    assert "Ainda dá tempo" in by_event["pagamento_recusado"]["html"]
    assert "Finalizar pagamento" in by_event["pagamento_pendente"]["html"]
    assert "Ver Instagram" in by_event["pagamento_pendente"]["html"]
    assert "Ir para a home da Bia Collections" in by_event["pagamento_pendente"]["html"]
    assert "pedido_itens_html" in by_event["pagamento_pendente"]["html"]
    assert "garantir seus produtos" in by_event["pagamento_pendente"]["html"]
    assert "Uma nova chance para escolher seus favoritos" in by_event["pagamento_expirado"]["html"]
    assert "pedido_itens_html" in by_event["pagamento_expirado"]["html"]
    assert "Valor do pedido expirado" in by_event["pagamento_expirado"]["html"]
    assert "Comprar novamente" in by_event["pagamento_expirado"]["html"]
    assert "Ver Instagram" in by_event["pagamento_expirado"]["html"]
    assert "Consultar meus pedidos" in by_event["pagamento_expirado"]["html"]
    assert "{{pedido_numero}}" in by_event["pedido_criado"]["assunto"]
    assert "{{cliente_nome}}" in by_event["pedido_criado"]["html"]
    assert "pedido_itens_html" in by_event["pedido_criado"]["html"]
    assert "pedido_itens_html|default" not in by_event["pedido_criado"]["html"]
    assert "|safe" not in by_event["pedido_criado"]["html"]
    assert "Ver meus pedidos" in by_event["pedido_criado"]["html"]
    assert "Ver Instagram" in by_event["pedido_criado"]["html"]
    assert "{{produto_nome}}" in by_event["produto_voltou_estoque"]["assunto"]
    assert "{{tipo_falha}}" in by_event["interno_falha_operacional"]["html"]
    assert 'data-bia-email-logo="true"' in by_event["pedido_criado"]["html"]
    assert "bia-collections-logooficial.png" in by_event["pedido_criado"]["html"]
    assert "Bia Collections" in by_event["pedido_criado"]["html"]
    assert "ACESSORIOS FEMININOS" not in by_event["pedido_criado"]["html"]
    assert "background: #111111" in by_event["pedido_criado"]["html"]
    for evento, template in by_event.items():
        assert 'data-bia-template-style="premium-v2"' in template["html"]
        if not evento.startswith("interno_") and evento not in {
            "recuperacao_senha",
            "codigo_acesso",
            "senha_alterada",
            "dados_sensiveis_alterados",
            "confirmacao_alteracao_email",
            "novo_acesso",
        }:
            assert "Ver Instagram" in template["html"]

    db = SessionLocal()
    try:
        automation_templates = db.query(EmailTemplate).filter(EmailTemplate.evento.is_(None)).all()
        assert automation_templates
        for template in automation_templates:
            assert 'data-bia-template-style="premium-v2"' in template.html_template
            if template.slug not in {
                "password-reset",
                "two-factor-code",
                "password-changed",
                "email-confirmation",
                "email-change-confirmation",
                "new-login-alert",
            }:
                assert "Ver Instagram" in template.html_template

        all_templates = db.query(EmailTemplate).all()
        forbidden_unaccented_copy = re.compile(
            r"\b(?:Ola|Voce|voce|Nao|nao|Codigo|Confirmacao|Preparacao|"
            r"Solicitacao|Atualizacao|Informacao|informacoes|Alteracao|"
            r"Atencao|Avaliacao|Experiencia|Opiniao|Confianca|Seguranca|"
            r"Recuperacao|Redefinicao|Visualizacao|Instituicao|Endereco|"
            r"enderecos|Analise|Beneficio|Botao|Devolucao|Diferenca|"
            r"Minimo|Verificacao|orientacoes|necessaria|possivel|sensivel|"
            r"disponivel|duvida|acoes)\b"
        )
        for template in all_templates:
            copy = " ".join(
                value
                for value in (
                    template.name,
                    template.nome,
                    template.subject,
                    template.preheader,
                    template.html,
                    template.html_template,
                    template.text_template,
                )
                if isinstance(value, str)
            )
            visible_copy = re.sub(r"{{[^{}]+}}", "", copy)
            assert forbidden_unaccented_copy.search(visible_copy) is None

        access_code = db.query(EmailTemplate).filter(
            EmailTemplate.slug == "admin-default-codigo-acesso"
        ).one()
        assert "{{codigo}}" in access_code.html
        assert "{{código}}" not in access_code.html

        expirado = db.query(EmailTemplate).filter(
            EmailTemplate.slug == "admin-default-pagamento-expirado"
        ).one()
        expirado.html = (
            "<p>O pedido nao seguira para preparo sem uma nova confirmacao de pagamento.</p>"
            "<p>Se ainda quiser os produtos, faca uma nova compra na loja.</p>"
        )
        expirado.html_template = expirado.html
        expirado.variables_schema = json.dumps(
            {"variables": ["cliente_nome", "pedido_numero", "pedido_total", "loja_nome", "loja_url"]}
        )
        db.commit()
    finally:
        db.close()

    seed_email_automation()
    db = SessionLocal()
    try:
        expirado_atualizado = db.query(EmailTemplate).filter(
            EmailTemplate.slug == "admin-default-pagamento-expirado"
        ).one()
        assert "Uma nova chance para escolher seus favoritos" in expirado_atualizado.html
        assert "Comprar novamente" in expirado_atualizado.html
        assert db.query(EmailTemplate).filter(EmailTemplate.evento.isnot(None)).count() == 32
    finally:
        db.close()


def test_todos_os_templates_padrao_tem_gramatica_revisada():
    forbidden = re.compile(
        r"\b(?:Ola|Voce|voce|Nao|nao|Ja|ja|Confirmacao|confirmacao|"
        r"Preparacao|preparacao|Solicitacao|solicitacao|Atualizacao|atualizacao|"
        r"Informacao|informacao|informacoes|Codigo|codigo|Seguranca|seguranca|"
        r"Recuperacao|recuperacao|Endereco|endereco|Numero|numero|Analise|analise|"
        r"proximo|proximos|orientacoes|necessaria|possivel|sensivel|disponivel|"
        r"duvida|duvidas|acao|acoes|Ate|ate|Apos|apos|Sera|sera|Faca|faca|"
        r"Atraves|atraves|recebera|acompanhara|seguira)\b"
    )

    for template in EMAIL_TEMPLATE_SEEDS + ADMIN_EMAIL_TEMPLATE_SEEDS:
        for field in (
            "name",
            "nome",
            "subject",
            "assunto",
            "preheader",
            "html",
            "html_template",
            "text_template",
        ):
            value = template.get(field)
            if isinstance(value, str):
                visible_copy = re.sub(r"{{[^{}]+}}", "", value)
                assert forbidden.search(visible_copy) is None, (
                    f"{template['slug']}.{field} ainda contém texto sem revisão"
                )

        serialized = json.dumps(template, ensure_ascii=False)
        assert "data-bia-e-mail-logo" not in serialized
        assert "está mensagem" not in serialized
        assert "está alteração" not in serialized


def test_revisao_gramatical_distingue_esta_de_esta_com_acento():
    reviewed = _review_portuguese_copy(
        "Ola, esta mensagem esta disponível. "
        "Se nao reconhece esta alteracao, nenhuma acao e necessaria."
    )

    assert reviewed == (
        "Olá, esta mensagem está disponível. "
        "Se não reconhece esta alteração, nenhuma ação é necessária."
    )


def test_email_direto_de_redefinicao_de_senha_tem_gramatica_revisada():
    message = password_reset_code_email("123456")

    assert message.subject == "Redefinição de senha - Bia Collections"
    assert "Use o código 123456" in message.text
    assert "não solicitou essa alteração" in message.text
    assert "solicitação" in message.html
    assert "recuperação de senha" in message.html


def test_seed_preserva_template_padrao_personalizado_manualmente(client):
    seed_email_automation()
    db = SessionLocal()
    try:
        template = db.query(EmailTemplate).filter(
            EmailTemplate.slug == "admin-default-pedido-preparando"
        ).one()
        template.html = "<html><body>CONTEUDO PERSONALIZADO DA LOJA</body></html>"
        template.html_template = template.html
        template.updated_at = datetime.now(timezone.utc) + timedelta(minutes=1)
        db.commit()
    finally:
        db.close()

    seed_email_automation()

    db = SessionLocal()
    try:
        template = db.query(EmailTemplate).filter(
            EmailTemplate.slug == "admin-default-pedido-preparando"
        ).one()
        assert template.html == "<html><body>CONTEUDO PERSONALIZADO DA LOJA</body></html>"
        assert template.html_template == template.html
    finally:
        db.close()


def test_fluxo_banners_home_admin_upload_ordem_static_e_auth(client):
    create_user("master", MASTER_ADMIN_EMAIL, is_admin=True)
    create_user("cliente-banner", "cliente-banner@example.com")
    headers = auth_headers("master")

    sem_token = client.get("/api/v1/admin/banners")
    assert sem_token.status_code == 401

    usuario_comum = client.get(
        "/api/v1/admin/banners",
        headers=auth_headers("cliente-banner"),
    )
    assert usuario_comum.status_code == 403

    banner_1 = client.post(
        "/api/v1/admin/banners",
        data={"titulo": "Banner Home 1", "link": "/produtos"},
        files={"imagem": ("banner-1.png", PNG_BYTES, "image/png")},
        headers=headers,
    )
    assert banner_1.status_code == 201
    body_1 = banner_1.json()
    assert body_1 == {
        "id": body_1["id"],
        "titulo": "Banner Home 1",
        "imagem_url": body_1["imagem_url"],
        "link": "/produtos",
        "ativo": True,
        "ordem": 1,
    }
    assert body_1["imagem_url"].startswith("/uploads/banners/")
    assert client.get(body_1["imagem_url"]).status_code == 200

    banner_2 = client.post(
        "/api/v1/admin/banners",
        data={"titulo": "Banner Home 2", "link": "/produtos"},
        files={"imagem": ("banner-2.png", PNG_BYTES, "image/png")},
        headers=headers,
    )
    assert banner_2.status_code == 201
    body_2 = banner_2.json()
    assert body_2["ordem"] == 2

    editado = client.put(
        f"/api/v1/admin/banners/{body_2['id']}",
        data={"titulo": "Banner Home 2 Editado", "link": "", "ativo": "false"},
        headers=headers,
    )
    assert editado.status_code == 200
    assert editado.json()["titulo"] == "Banner Home 2 Editado"
    assert editado.json()["link"] is None
    assert editado.json()["ativo"] is False
    assert editado.json()["imagem_url"] == body_2["imagem_url"]

    admin_list = client.get("/api/v1/admin/banners", headers=headers)
    assert admin_list.status_code == 200
    assert [banner["id"] for banner in admin_list.json()] == [body_1["id"], body_2["id"]]
    assert [banner["ativo"] for banner in admin_list.json()] == [True, False]

    public_list = client.get("/api/v1/banners")
    assert public_list.status_code == 200
    assert [banner["id"] for banner in public_list.json()] == [body_1["id"]]

    reordem = client.put(
        "/api/v1/admin/banners/ordem",
        json={"ids": [body_2["id"], body_1["id"]]},
        headers=headers,
    )
    assert reordem.status_code == 200
    assert reordem.json() == {"ok": True}

    admin_reordenado = client.get("/api/v1/admin/banners", headers=headers)
    assert [banner["id"] for banner in admin_reordenado.json()] == [body_2["id"], body_1["id"]]
    assert [banner["ordem"] for banner in admin_reordenado.json()] == [1, 2]

    removido = client.delete(f"/api/v1/admin/banners/{body_2['id']}", headers=headers)
    assert removido.status_code == 204

    db = SessionLocal()
    try:
        assert db.query(Banner).filter(Banner.id == body_2["id"]).first() is None
    finally:
        db.close()

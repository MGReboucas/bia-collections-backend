import importlib
import hashlib
import hmac
import json
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
from app.models.avaliacao import Avaliacao
from app.models.reset_senha import ResetSenha
from app.models.banner import Banner
from app.models.cupom import Cupom, CupomUsado
from app.models.pagamento import Pagamento
from app.models.pedido import Pedido
from app.models.produto import Categoria, Produto, ProdutoImagem
from app.models.two_factor import TwoFactorChallenge
from app.models.usuario import Usuario
from app.modules.email.models import EmailTemplate
from app.modules.email.seeds import seed_email_automation
from app.services.two_factor_service import hash_two_factor_token
from main import app

PASSWORD = "senha-segura-123"
auth_router_module = importlib.import_module("app.routers.auth")
admin_module = importlib.import_module("app.routers.admin")
email_module = importlib.import_module("app.core.email")


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
    assert captured["json"]["subject"] == "Seu codigo de acesso - Bia Collections"
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
    assert captured["json"]["subject"] == "Seu codigo de acesso - Bia Collections"
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
        files={"imagem": ("bolsas.webp", b"fake image", "image/webp")},
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
        files={"imagem": ("vestidos.png", b"fake image", "image/png")},
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
            ("imagem", ("legado.webp", b"legacy", "image/webp")),
            ("imagens", ("capa.webp", b"cover", "image/webp")),
            ("imagens", ("detalhe.png", b"detail", "image/png")),
            ("imagens", ("look.jpg", b"look", "image/jpeg")),
        ],
        headers=auth_headers("master"),
    )

    assert response.status_code == 201
    body = response.json()
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
    assert produtos_admin.json()["itens"][0]["imagens"] == body["imagens"]

    produtos_publicos = client.get("/api/v1/produtos")
    assert produtos_publicos.status_code == 200
    item = produtos_publicos.json()["itens"][0]
    assert item["imagem_url"] == "/uploads/produtos/capa.webp"
    assert item["imagens"] == body["imagens"]

    detalhe = client.get(f"/api/v1/produtos/{body['id']}")
    assert detalhe.status_code == 200
    assert detalhe.json()["imagens"] == body["imagens"]


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
            ("imagens", ("capa.webp", b"cover", "image/webp")),
            ("imagens", ("detalhe.png", b"detail", "image/png")),
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
            ("imagens", (f"imagem-{index}.webp", b"img", "image/webp"))
            for index in range(9)
        ],
        headers=headers,
    )
    assert too_many.status_code == 422
    assert "maximo 8 imagens" in too_many.json()["detail"]

    invalid_type = client.post(
        "/api/v1/admin/produtos",
        data=data,
        files={"imagens": ("arquivo.txt", b"text", "text/plain")},
        headers=headers,
    )
    assert invalid_type.status_code == 422
    assert "formato invalido" in invalid_type.json()["detail"]

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
    assert creates[0]["notification_url"] == "https://api.example.test/api/v1/pagamentos/webhook"
    assert creates[0]["metadata"] == {"pedido_numero": "0000001", "payment_flow": "pix"}
    payment = creates[0]["transactions"]["payments"][0]
    assert payment["amount"] == "60.00"
    assert payment["payment_method"] == {"id": "pix", "type": "bank_transfer"}
    assert email_events == []


def test_pagamento_pix_traduz_erro_credenciais_live():
    pagamentos_module = importlib.import_module("app.routers.pagamentos")

    message = pagamentos_module._mensagem_erro_mp({
        "message": "Unauthorized use of live credentials",
    })

    assert "credenciais de producao" in message
    assert "comprador real diferente" in message
    assert "Unauthorized use of live credentials" in message


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
        f"/api/v1/admin/emails/{criado.json()['id']}/teste",
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
    assert enviado["html"] == "<strong>Bia</strong> - R$ 149,90"


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
        "pedido_criado",
        "pagamento_aprovado",
        "pedido_enviado",
        "recuperacao_senha",
        "cupom_disponivel",
        "manual",
    }
    assert by_event["pedido_criado"]["status"] == "ativo"
    assert by_event["manual"]["status"] == "rascunho"
    assert "{{pedido_numero}}" in by_event["pedido_criado"]["assunto"]
    assert "{{cliente_nome}}" in by_event["pedido_criado"]["html"]

    seed_email_automation()
    db = SessionLocal()
    try:
        assert db.query(EmailTemplate).filter(EmailTemplate.evento.isnot(None)).count() == 6
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
        files={"imagem": ("banner-1.png", b"fake-png-1", "image/png")},
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
        files={"imagem": ("banner-2.png", b"fake-png-2", "image/png")},
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

import importlib
import hashlib
import hmac
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
from app.models.cupom import Cupom, CupomUsado
from app.models.pagamento import Pagamento
from app.models.pedido import Pedido
from app.models.produto import Categoria, Produto, ProdutoImagem
from app.models.two_factor import TwoFactorChallenge
from app.models.usuario import Usuario
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

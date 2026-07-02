import os
from pathlib import Path

TEST_DB_PATH = Path(__file__).resolve().parents[1] / "test_admin_security.db"
if TEST_DB_PATH.exists():
    TEST_DB_PATH.unlink()

os.environ["DATABASE_URL"] = f"sqlite:///{TEST_DB_PATH.as_posix()}"
os.environ["SECRET_KEY"] = "test-secret-key-for-admin-security-1234567890"
os.environ["MASTER_ADMIN_EMAIL"] = "reboucas444@gmail.com"

from fastapi.testclient import TestClient
import pytest

from app.core.security import create_access_token, get_password_hash
from app.database import Base, SessionLocal, engine
from app.dependencies import MASTER_ADMIN_EMAIL
from app.models.usuario import Usuario
from main import app

PASSWORD = "senha-segura-123"


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


def test_master_admin_recebe_200_e_is_admin_no_login_e_perfil(client):
    create_user("master", MASTER_ADMIN_EMAIL)

    login = client.post(
        "/api/v1/auth/login",
        json={"login": "master", "senha": PASSWORD},
    )
    assert login.status_code == 200
    assert login.json()["usuario"]["is_admin"] is True

    token = login.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}
    perfil = client.get("/api/v1/usuario/perfil", headers=headers)
    assert perfil.status_code == 200
    assert perfil.json()["is_admin"] is True

    usuarios = client.get("/api/v1/admin/usuarios", headers=headers)
    assert usuarios.status_code == 200


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

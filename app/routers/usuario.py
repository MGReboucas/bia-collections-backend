import os
import uuid

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import get_current_user
from app.models.usuario import Usuario
from app.schemas.usuario import UsuarioPerfil, AtualizarPerfil

router = APIRouter(prefix="/usuario", tags=["usuario"])

UPLOADS_DIR = "uploads"
ALLOWED_TYPES = {"image/jpeg", "image/png", "image/webp", "application/octet-stream"}
EXT_TO_MIME = {"jpg": "image/jpeg", "jpeg": "image/jpeg", "png": "image/png", "webp": "image/webp"}
MAX_SIZE = 5 * 1024 * 1024  # 5 MB


@router.get("/perfil", response_model=UsuarioPerfil)
def obter_perfil(current_user: Usuario = Depends(get_current_user)):
    return current_user


@router.put("/perfil", response_model=UsuarioPerfil)
def atualizar_perfil(
    data: AtualizarPerfil,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
):
    if data.email is not None and data.email != current_user.email:
        if "@" not in data.email:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Email inválido.",
            )
        existing = (
            db.query(Usuario)
            .filter(Usuario.email == data.email, Usuario.id != current_user.id)
            .first()
        )
        if existing:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Email já está em uso.",
            )
        current_user.email = data.email

    if data.nome_completo is not None:
        current_user.nome_completo = data.nome_completo
    if data.telefone is not None:
        current_user.telefone = data.telefone

    db.commit()
    db.refresh(current_user)
    return current_user


@router.post("/perfil/foto", response_model=UsuarioPerfil)
async def upload_foto(
    foto: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
):
    content_type = foto.content_type or ""
    # Fallback: infer type from extension
    if content_type == "application/octet-stream" or not content_type:
        ext_guess = (foto.filename or "").rsplit(".", 1)[-1].lower()
        content_type = EXT_TO_MIME.get(ext_guess, content_type)
    if content_type not in ALLOWED_TYPES - {"application/octet-stream"}:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail="Formato inválido. Use JPEG, PNG ou WebP.",
        )

    contents = await foto.read()
    if len(contents) > MAX_SIZE:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail="Imagem muito grande. Máximo 5 MB.",
        )

    ext = foto.filename.rsplit(".", 1)[-1].lower() if foto.filename and "." in foto.filename else "jpg"
    filename = f"avatar_{current_user.id}_{uuid.uuid4().hex[:8]}.{ext}"
    filepath = os.path.join(UPLOADS_DIR, filename)

    os.makedirs(UPLOADS_DIR, exist_ok=True)
    with open(filepath, "wb") as f:
        f.write(contents)

    # Remove foto anterior se era local
    if current_user.foto_url and current_user.foto_url.startswith("/uploads/"):
        old_path = current_user.foto_url.lstrip("/")
        if os.path.exists(old_path):
            os.remove(old_path)

    current_user.foto_url = f"/uploads/{filename}"
    db.commit()
    db.refresh(current_user)
    return current_user

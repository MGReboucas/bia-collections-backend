from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import get_current_user, is_master_admin_email
from app.models.usuario import Usuario
from app.schemas.usuario import UsuarioPerfil, AtualizarPerfil
from app.services.upload_service import upload_image, delete_old_image

router = APIRouter(prefix="/usuario", tags=["usuario"])


def _usuario_perfil_response(user: Usuario) -> UsuarioPerfil:
    perfil = UsuarioPerfil.model_validate(user)
    perfil.is_admin = is_master_admin_email(user.email)
    return perfil


@router.get("/perfil", response_model=UsuarioPerfil)
def obter_perfil(current_user: Usuario = Depends(get_current_user)):
    return _usuario_perfil_response(current_user)


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
    return _usuario_perfil_response(current_user)


@router.post("/perfil/foto", response_model=UsuarioPerfil)
async def upload_foto(
    foto: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
):
    # Remove foto anterior se for local (Cloudinary ignora)
    delete_old_image(current_user.foto_url)

    url = await upload_image(foto, folder="bia-collections/avatars")
    current_user.foto_url = url
    db.commit()
    db.refresh(current_user)
    return _usuario_perfil_response(current_user)


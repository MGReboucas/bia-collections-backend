"""
upload_service.py — Abstrai o armazenamento de arquivos.

Se CLOUDINARY_CLOUD_NAME estiver configurado no .env, faz upload para o Cloudinary
(storage persistente em produção). Caso contrário, salva localmente em /uploads
(útil para desenvolvimento local).
"""
import os
import uuid
from pathlib import Path

from fastapi import HTTPException, UploadFile

from app.core.config import settings

ALLOWED_TYPES = {"image/jpeg", "image/png", "image/webp"}
EXT_TO_MIME = {
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "png": "image/png",
    "webp": "image/webp",
}
MAX_SIZE = 5 * 1024 * 1024  # 5 MB

_cloudinary_configured = bool(
    settings.CLOUDINARY_CLOUD_NAME
    and settings.CLOUDINARY_API_KEY
    and settings.CLOUDINARY_API_SECRET
)

if _cloudinary_configured:
    import cloudinary
    import cloudinary.uploader

    cloudinary.config(
        cloud_name=settings.CLOUDINARY_CLOUD_NAME,
        api_key=settings.CLOUDINARY_API_KEY,
        api_secret=settings.CLOUDINARY_API_SECRET,
        secure=True,
    )


def _infer_content_type(file: UploadFile) -> str:
    content_type = file.content_type or ""
    if not content_type or content_type == "application/octet-stream":
        ext = (file.filename or "").rsplit(".", 1)[-1].lower()
        content_type = EXT_TO_MIME.get(ext, content_type)
    return content_type


async def upload_image(file: UploadFile, folder: str = "curadobem") -> str:
    """
    Valida e faz upload de uma imagem.
    Retorna a URL pública do arquivo.

    - Cloudinary configurado → URL permanente na nuvem
    - Sem Cloudinary → salva localmente e retorna caminho relativo /uploads/<file>
    """
    content_type = _infer_content_type(file)
    if content_type not in ALLOWED_TYPES:
        raise HTTPException(
            status_code=415,
            detail="Formato inválido. Use JPEG, PNG ou WebP.",
        )

    contents = await file.read()
    if len(contents) > MAX_SIZE:
        raise HTTPException(
            status_code=413,
            detail="Imagem muito grande. Máximo 5 MB.",
        )

    if _cloudinary_configured:
        return _upload_cloudinary(contents, folder)
    else:
        return _save_local(contents, file.filename or "upload.jpg")


def _upload_cloudinary(contents: bytes, folder: str) -> str:
    result = cloudinary.uploader.upload(
        contents,
        folder=folder,
        resource_type="image",
        overwrite=False,
        unique_filename=True,
        transformation=[
            {"width": 800, "height": 800, "crop": "limit", "quality": "auto:good"},
        ],
    )
    return result["secure_url"]


def _save_local(contents: bytes, original_filename: str) -> str:
    ext = original_filename.rsplit(".", 1)[-1].lower() if "." in original_filename else "jpg"
    filename = f"{uuid.uuid4().hex[:12]}.{ext}"
    upload_dir = Path("uploads")
    upload_dir.mkdir(exist_ok=True)
    (upload_dir / filename).write_bytes(contents)
    # Retorna caminho relativo com prefixo — clientes montam URL completa
    return f"/uploads/{filename}"


def delete_old_image(url: str | None) -> None:
    """Remove imagem antiga se era local. Cloudinary gerencia suas próprias."""
    if not url:
        return
    if url.startswith("/uploads/"):
        path = url.lstrip("/")
        if os.path.exists(path):
            try:
                os.remove(path)
            except OSError:
                pass
    # Para Cloudinary poderíamos chamar cloudinary.uploader.destroy(public_id)
    # mas como a URL é segura e o free tier é generoso, optamos por não deletar.

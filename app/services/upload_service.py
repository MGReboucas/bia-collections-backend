"""
upload_service.py — Abstrai o armazenamento de arquivos.

Se CLOUDINARY_CLOUD_NAME estiver configurado no .env, faz upload para o Cloudinary
(storage persistente em produção). Caso contrário, salva localmente em /uploads
(útil para desenvolvimento local).
"""
import os
import uuid
from pathlib import Path
from urllib.parse import unquote, urlparse

from fastapi import HTTPException, UploadFile

from app.core.config import settings

ALLOWED_TYPES = {"image/jpeg", "image/png", "image/webp"}
EXT_TO_MIME = {
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "png": "image/png",
    "webp": "image/webp",
}
MIME_TO_EXT = {
    "image/jpeg": "jpg",
    "image/png": "png",
    "image/webp": "webp",
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


def detect_image_mime(contents: bytes) -> str | None:
    if contents.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if contents.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if len(contents) >= 12 and contents[:4] == b"RIFF" and contents[8:12] == b"WEBP":
        return "image/webp"
    return None


def validate_image_bytes(contents: bytes) -> str:
    detected_type = detect_image_mime(contents)
    if detected_type not in ALLOWED_TYPES:
        raise HTTPException(
            status_code=415,
            detail="Arquivo invalido. Envie uma imagem JPEG, PNG ou WebP real.",
        )
    return detected_type


async def upload_image(file: UploadFile, folder: str = "bia-collections") -> str:
    """
    Valida e faz upload de uma imagem.
    Retorna a URL pública do arquivo.

    - Cloudinary configurado → URL permanente na nuvem
    - Sem Cloudinary → salva localmente e retorna caminho relativo /uploads/<file>
    """
    claimed_content_type = _infer_content_type(file)
    if claimed_content_type not in ALLOWED_TYPES:
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

    content_type = validate_image_bytes(contents)

    if _cloudinary_configured:
        return _upload_cloudinary(contents, folder)
    else:
        return _save_local(contents, file.filename or "upload.jpg", folder, content_type)


def _upload_cloudinary(contents: bytes, folder: str) -> str:
    result = cloudinary.uploader.upload(
        contents,
        folder=folder,
        resource_type="image",
        overwrite=False,
        unique_filename=True,
    )
    return result["secure_url"]


def _safe_folder_parts(folder: str) -> list[str]:
    parts = [
        part
        for part in folder.replace("\\", "/").split("/")
        if part and part not in {".", ".."}
    ]
    if parts and parts[0] == "bia-collections":
        parts = parts[1:]
    return parts


def _save_local(contents: bytes, original_filename: str, folder: str, content_type: str) -> str:
    ext = MIME_TO_EXT.get(content_type)
    if not ext:
        ext = original_filename.rsplit(".", 1)[-1].lower() if "." in original_filename else "jpg"
    filename = f"{uuid.uuid4().hex[:12]}.{ext}"
    folder_parts = _safe_folder_parts(folder)
    upload_dir = Path("uploads", *folder_parts)
    upload_dir.mkdir(parents=True, exist_ok=True)
    (upload_dir / filename).write_bytes(contents)
    # Retorna caminho relativo com prefixo — clientes montam URL completa
    path_parts = "/".join([*folder_parts, filename])
    return f"/uploads/{path_parts}"


def _cloudinary_public_id_from_url(url: str) -> str | None:
    parsed = urlparse(url)
    if "res.cloudinary.com" not in parsed.netloc:
        return None
    marker = "/image/upload/"
    if marker not in parsed.path:
        return None

    parts = unquote(parsed.path.split(marker, 1)[1]).split("/")
    version_index = next(
        (
            index
            for index, part in enumerate(parts)
            if part.startswith("v") and part[1:].isdigit()
        ),
        None,
    )
    if version_index is not None:
        parts = parts[version_index + 1:]
    if not parts:
        return None

    public_id = "/".join(parts)
    if "." in public_id:
        public_id = public_id.rsplit(".", 1)[0]
    return public_id or None


def delete_old_image(url: str | None) -> None:
    """Remove imagem antiga quando o storage permite."""
    if not url:
        return
    if url.startswith("/uploads/"):
        uploads_root = Path("uploads").resolve()
        path = Path(url.lstrip("/")).resolve()
        try:
            path.relative_to(uploads_root)
        except ValueError:
            return
        if os.path.exists(path):
            try:
                os.remove(path)
            except OSError:
                pass
        return

    if _cloudinary_configured:
        public_id = _cloudinary_public_id_from_url(url)
        if public_id:
            try:
                cloudinary.uploader.destroy(
                    public_id,
                    resource_type="image",
                    invalidate=True,
                )
            except Exception:
                pass

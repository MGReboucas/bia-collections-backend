import hashlib
import unicodedata

from fastapi import HTTPException, UploadFile
from sqlalchemy.orm import Session, joinedload

from app.models.avaliacao import Avaliacao, AvaliacaoFoto
from app.models.pedido import ItemPedido, Pedido
from app.models.produto import Produto
from app.models.usuario import Usuario
from app.services.upload_service import (
    ALLOWED_TYPES,
    EXT_TO_MIME,
    MAX_SIZE,
    delete_old_image,
    upload_image,
    validate_image_bytes,
)

MAX_AVALIACAO_FOTOS = 4
MAX_AVALIACAO_COMENTARIO = 1000
AVALIACAO_IMAGE_FOLDER = "avaliacoes"
AVALIACAO_STATUS_VALUES = {"pendente", "aprovada", "reprovada"}
AVALIACAO_STATUS_PUBLICO = "aprovada"
AVALIACAO_STATUS_INICIAL = "pendente"
AVALIACAO_STATUS_ADMIN_UPDATE = {"aprovada", "reprovada"}
ORDER_STATUSES_AVALIAVEIS = {"entregue", "concluido", "finalizado"}


def clean_optional_text(value: str | None) -> str | None:
    if value is None:
        return None
    text = value.strip()
    return text or None


def is_order_delivered(status: str | None) -> bool:
    normalized = unicodedata.normalize("NFKD", (status or "").strip().lower())
    normalized = "".join(char for char in normalized if not unicodedata.combining(char))
    return normalized in ORDER_STATUSES_AVALIAVEIS


def uploaded_files(*groups: list[UploadFile] | None) -> list[UploadFile]:
    files: list[UploadFile] = []
    for group in groups:
        files.extend(file for file in group or [] if file and file.filename)
    return files


async def deduplicate_upload_files(files: list[UploadFile]) -> list[UploadFile]:
    unique_files: list[UploadFile] = []
    seen: set[str] = set()
    for file in files:
        contents = await file.read()
        digest = hashlib.sha256(contents).hexdigest()
        await file.seek(0)
        if digest in seen:
            continue
        seen.add(digest)
        unique_files.append(file)
    return unique_files


def infer_upload_content_type(file: UploadFile) -> str:
    content_type = file.content_type or ""
    if not content_type or content_type == "application/octet-stream":
        ext = (file.filename or "").rsplit(".", 1)[-1].lower()
        content_type = EXT_TO_MIME.get(ext, content_type)
    return content_type


async def validate_avaliacao_images(files: list[UploadFile]) -> None:
    if len(files) > MAX_AVALIACAO_FOTOS:
        raise HTTPException(
            status_code=422,
            detail=f"Envie no maximo {MAX_AVALIACAO_FOTOS} fotos por avaliacao.",
        )

    for index, file in enumerate(files, start=1):
        content_type = infer_upload_content_type(file)
        if content_type not in ALLOWED_TYPES:
            raise HTTPException(
                status_code=422,
                detail=f"Foto {index}: formato invalido. Use JPEG, PNG ou WebP.",
            )

        contents = await file.read()
        if len(contents) > MAX_SIZE:
            raise HTTPException(
                status_code=422,
                detail=f"Foto {index}: tamanho maximo permitido e 5 MB.",
            )
        try:
            validate_image_bytes(contents)
        except HTTPException as exc:
            raise HTTPException(
                status_code=422,
                detail=f"Foto {index}: {exc.detail}",
            ) from exc
        await file.seek(0)


async def save_avaliacao_images(files: list[UploadFile]) -> list[str]:
    if not files:
        return []

    await validate_avaliacao_images(files)
    urls: list[str] = []
    for file in files:
        try:
            urls.append(await upload_image(file, folder=AVALIACAO_IMAGE_FOLDER))
        except HTTPException as exc:
            if exc.status_code in {413, 415}:
                raise HTTPException(status_code=422, detail=exc.detail) from exc
            raise
    return urls


def avaliacao_query(db: Session):
    return db.query(Avaliacao).options(
        joinedload(Avaliacao.produto),
        joinedload(Avaliacao.usuario),
        joinedload(Avaliacao.fotos),
    )


def avaliacao_response(avaliacao: Avaliacao) -> dict:
    fotos = [
        foto.imagem_url
        for foto in sorted(
            avaliacao.fotos or [],
            key=lambda item: (item.ordem if item.ordem is not None else 0, item.id or 0),
        )
    ]
    usuario = avaliacao.usuario
    usuario_nome = None
    if usuario:
        usuario_nome = usuario.nome_completo or usuario.username

    return {
        "id": avaliacao.id,
        "produto_id": avaliacao.produto_id,
        "produto_nome": avaliacao.produto.nome if avaliacao.produto else None,
        "usuario_nome": usuario_nome,
        "pedido_numero": avaliacao.pedido_numero,
        "nota": avaliacao.nota,
        "comentario": avaliacao.comentario,
        "status": avaliacao.status,
        "mostrar_home": bool(avaliacao.mostrar_home),
        "exibir_home": bool(avaliacao.mostrar_home),
        "destaque_home": bool(avaliacao.mostrar_home),
        "fotos": fotos,
        "imagens": fotos,
        "criado_em": avaliacao.criado_em.isoformat() if avaliacao.criado_em else "",
    }


def find_order_for_review(
    *,
    db: Session,
    usuario_id: int,
    produto_id: int,
    pedido_numero: str | None,
) -> Pedido:
    if pedido_numero:
        pedido = (
            db.query(Pedido)
            .filter(
                Pedido.numero == pedido_numero,
                Pedido.usuario_id == usuario_id,
            )
            .first()
        )
        if not pedido:
            raise HTTPException(
                status_code=403,
                detail="Pedido nao pertence ao usuario autenticado.",
            )
        if not is_order_delivered(pedido.status):
            raise HTTPException(
                status_code=409,
                detail="Avaliacao permitida apenas para pedido entregue, concluido ou finalizado.",
            )
        item = (
            db.query(ItemPedido.id)
            .filter(
                ItemPedido.pedido_id == pedido.id,
                ItemPedido.produto_id == produto_id,
            )
            .first()
        )
        if not item:
            raise HTTPException(
                status_code=422,
                detail="Produto nao pertence a este pedido.",
            )
        return pedido

    query = (
        db.query(Pedido)
        .join(ItemPedido)
        .filter(
            Pedido.usuario_id == usuario_id,
            ItemPedido.produto_id == produto_id,
        )
    )

    pedidos = query.order_by(Pedido.criado_em.desc()).all()
    if not pedidos:
        raise HTTPException(
            status_code=403,
            detail="Usuario so pode avaliar produto que comprou.",
        )

    delivered = [pedido for pedido in pedidos if is_order_delivered(pedido.status)]
    if not delivered:
        raise HTTPException(
            status_code=409,
            detail="Avaliacao permitida apenas para pedido entregue, concluido ou finalizado.",
        )

    for pedido in delivered:
        exists = (
            db.query(Avaliacao.id)
            .filter(
                Avaliacao.usuario_id == usuario_id,
                Avaliacao.produto_id == produto_id,
                Avaliacao.pedido_id == pedido.id,
            )
            .first()
        )
        if not exists:
            return pedido

    raise HTTPException(
        status_code=409,
        detail="Produto ja avaliado para os pedidos elegiveis.",
    )


def ensure_review_not_duplicate(
    *,
    db: Session,
    usuario_id: int,
    produto_id: int,
    pedido_id: int,
    pedido_numero: str,
) -> None:
    exists = (
        db.query(Avaliacao.id)
        .filter(
            Avaliacao.usuario_id == usuario_id,
            Avaliacao.produto_id == produto_id,
            (Avaliacao.pedido_numero == pedido_numero) | (Avaliacao.pedido_id == pedido_id),
        )
        .first()
    )
    if exists:
        raise HTTPException(
            status_code=409,
            detail="Produto ja avaliado neste pedido.",
        )


def ensure_product_exists(db: Session, produto_id: int) -> Produto:
    produto = db.query(Produto).filter(Produto.id == produto_id).first()
    if not produto:
        raise HTTPException(status_code=404, detail="Produto nao encontrado.")
    return produto


async def create_avaliacao(
    *,
    db: Session,
    current_user: Usuario,
    produto_id: int,
    pedido_numero: str | None,
    nota: int,
    comentario: str | None,
    files: list[UploadFile],
) -> Avaliacao:
    if nota < 1 or nota > 5:
        raise HTTPException(status_code=422, detail="Nota deve ser entre 1 e 5.")

    comentario_limpo = clean_optional_text(comentario)
    if comentario_limpo and len(comentario_limpo) > MAX_AVALIACAO_COMENTARIO:
        raise HTTPException(
            status_code=422,
            detail=f"Comentario deve ter no maximo {MAX_AVALIACAO_COMENTARIO} caracteres.",
        )

    unique_files = await deduplicate_upload_files(files)
    if not comentario_limpo and not unique_files:
        raise HTTPException(
            status_code=422,
            detail="Envie um comentario ou ao menos uma foto para avaliar o produto.",
        )

    ensure_product_exists(db, produto_id)
    pedido_numero_limpo = clean_optional_text(pedido_numero)
    if not pedido_numero_limpo:
        raise HTTPException(status_code=422, detail="pedido_numero e obrigatorio.")

    pedido = find_order_for_review(
        db=db,
        usuario_id=current_user.id,
        produto_id=produto_id,
        pedido_numero=pedido_numero_limpo,
    )
    ensure_review_not_duplicate(
        db=db,
        usuario_id=current_user.id,
        produto_id=produto_id,
        pedido_id=pedido.id,
        pedido_numero=pedido.numero,
    )

    image_urls = await save_avaliacao_images(unique_files)
    avaliacao = Avaliacao(
        produto_id=produto_id,
        usuario_id=current_user.id,
        pedido_id=pedido.id,
        pedido_numero=pedido.numero,
        nota=nota,
        comentario=comentario_limpo,
        status=AVALIACAO_STATUS_INICIAL,
    )
    avaliacao.fotos = [
        AvaliacaoFoto(imagem_url=image_url, ordem=index)
        for index, image_url in enumerate(image_urls)
    ]

    db.add(avaliacao)
    try:
        db.commit()
    except Exception:
        db.rollback()
        for image_url in image_urls:
            delete_old_image(image_url)
        raise

    return avaliacao_query(db).filter(Avaliacao.id == avaliacao.id).first()


def avaliacao_file_urls(avaliacao: Avaliacao) -> list[str]:
    return [foto.imagem_url for foto in avaliacao.fotos or [] if foto.imagem_url]


def delete_avaliacao_files(image_urls: list[str]) -> None:
    for image_url in image_urls:
        delete_old_image(image_url)

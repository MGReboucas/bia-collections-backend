import json
from datetime import date, datetime, timedelta, timezone
from typing import Any, List, Optional
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, Response, UploadFile, status
from pydantic import BaseModel, field_validator
from sqlalchemy import func
from sqlalchemy.orm import Session, joinedload

from app.database import get_db
from app.dependencies import (
    get_current_master_admin_user,
    is_master_admin_email,
    log_admin_access_denied,
)
from app.services.upload_service import (
    ALLOWED_TYPES,
    EXT_TO_MIME,
    MAX_SIZE,
    delete_old_image,
    upload_image,
)
from app.models.avaliacao import Avaliacao
from app.models.banner import Banner
from app.models.cupom import Cupom, CupomUsado
from app.models.duvida import Duvida
from app.models.pagamento import Pagamento
from app.models.pedido import Pedido, ItemPedido
from app.models.produto import Categoria, Produto, ProdutoImagem
from app.models.usuario import Usuario
from app.schemas.duvida import DuvidaOut
from app.services.frete_service import formatar_preco
from app.services.payment_status import (
    ORDER_STATUS_AGUARDANDO,
    ORDER_STATUS_EMAIL_EVENTS,
    ORDER_STATUSES,
    ORDER_STATUSES_OPERACIONAIS,
)
from app.services.avaliacao_service import (
    AVALIACAO_STATUS_ADMIN_UPDATE,
    AVALIACAO_STATUS_VALUES,
    avaliacao_file_urls,
    avaliacao_query,
    avaliacao_response,
    delete_avaliacao_files,
)
from app.modules.email.service import trigger_order_email_event

router = APIRouter(
    prefix="/admin",
    tags=["admin"],
    dependencies=[Depends(get_current_master_admin_user)],
)

MAX_PRODUCT_IMAGES = 8
PRODUCT_IMAGE_FOLDER = "bia-collections/produtos"


class CategoriaPayload(BaseModel):
    nome: str

    @field_validator("nome")
    @classmethod
    def nome_valido(cls, value: str) -> str:
        value = value.strip()
        if len(value) < 2:
            raise ValueError("Nome da categoria muito curto.")
        return value


class CupomPayload(BaseModel):
    codigo: str
    descricao: str
    tipo: str
    valor: float
    validade: date
    valor_minimo_pedido: float = 0
    ativo: bool = True
    max_usos: Optional[int] = None

    @field_validator("codigo")
    @classmethod
    def codigo_valido(cls, value: str) -> str:
        value = value.strip().upper()
        if not value:
            raise ValueError("Codigo do cupom e obrigatorio.")
        return value

    @field_validator("descricao")
    @classmethod
    def descricao_valida(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Descricao do cupom e obrigatoria.")
        return value

    @field_validator("tipo")
    @classmethod
    def tipo_valido(cls, value: str) -> str:
        if value not in {"porcentagem", "valor", "frete"}:
            raise ValueError("Tipo de cupom invalido.")
        return value

    @field_validator("valor_minimo_pedido")
    @classmethod
    def valor_minimo_valido(cls, value: float) -> float:
        if value < 0:
            raise ValueError("Valor minimo do pedido deve ser maior ou igual a zero.")
        return value

    @field_validator("max_usos")
    @classmethod
    def max_usos_valido(cls, value: Optional[int]) -> Optional[int]:
        if value is not None and value < 1:
            raise ValueError("Maximo de usos deve ser nulo ou inteiro maior ou igual a 1.")
        return value

    def validar_valor_por_tipo(self) -> None:
        if self.tipo == "porcentagem" and not (0 < self.valor <= 100):
            raise HTTPException(status_code=422, detail="Cupom de porcentagem deve ter valor maior que 0 e menor ou igual a 100.")
        if self.tipo == "valor" and self.valor <= 0:
            raise HTTPException(status_code=422, detail="Cupom de valor fixo deve ter valor maior que 0.")
        if self.tipo == "frete" and self.valor < 0:
            raise HTTPException(status_code=422, detail="Cupom de frete deve ter valor maior ou igual a 0.")


class RastreioPayload(BaseModel):
    codigo_rastreio: str

    @field_validator("codigo_rastreio")
    @classmethod
    def rastreio_valido(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Código de rastreio não pode ser vazio.")
        return value


class AvaliacaoStatusPayload(BaseModel):
    status: str

    @field_validator("status")
    @classmethod
    def status_valido(cls, value: str) -> str:
        if value not in AVALIACAO_STATUS_ADMIN_UPDATE:
            raise ValueError("Status de avaliação inválido.")
        return value


class BannerOrdemPayload(BaseModel):
    ids: List[int]


class StatusPedidoPayload(BaseModel):
    status: str

    @field_validator("status")
    @classmethod
    def status_valido(cls, value: str) -> str:
        if value not in ORDER_STATUSES:
            raise ValueError("Status de pedido inválido.")
        return value


class UsuarioAdminPayload(BaseModel):
    is_admin: bool


class RespostaDuvidaPayload(BaseModel):
    resposta: str

    @field_validator("resposta")
    @classmethod
    def resposta_valida(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("A resposta não pode ser vazia.")
        if len(value) > 2000:
            raise ValueError("A resposta deve ter no máximo 2000 caracteres.")
        return value


get_current_admin = get_current_master_admin_user


def _split_csv(value: Optional[str]) -> str:
    if not value:
        return "[]"
    items = [item.strip() for item in value.split(",") if item.strip()]
    return json.dumps(items, ensure_ascii=False)


def _clean_optional_text(value) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _normalize_image_url(value: str | None) -> str | None:
    text = _clean_optional_text(value)
    if not text:
        return None
    parsed = urlsplit(text)
    path = parsed.path or text
    return path.rstrip("/") or path


def _parse_json_or_csv_list(value: Optional[str]) -> list[Any]:
    if not value:
        return []
    raw = value.strip()
    if not raw:
        return []
    try:
        parsed = json.loads(raw)
    except ValueError:
        parsed = None
    if isinstance(parsed, list):
        return parsed
    return [item.strip() for item in raw.split(",") if item.strip()]


def _parse_image_keep_urls(value: Optional[str]) -> set[str]:
    return {
        normalized
        for normalized in (_normalize_image_url(str(item)) for item in _parse_json_or_csv_list(value))
        if normalized
    }


def _parse_optional_index(value: Optional[str]) -> int | None:
    text = _clean_optional_text(value)
    if text is None:
        return None
    try:
        index = int(text)
    except ValueError:
        return None
    return index if index >= 0 else None


def _parse_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    return str(value).strip().lower() in {"1", "true", "sim", "yes", "on"}


def _parse_image_metadata_items(value: Optional[str]) -> list[dict[str, Any]]:
    items = _parse_json_or_csv_list(value)
    parsed: list[dict[str, Any]] = []
    for index, item in enumerate(items):
        if not isinstance(item, dict):
            continue
        url = _clean_optional_text(item.get("url") or item.get("imagem_url"))
        ordem = item.get("ordem")
        try:
            ordem_int = int(ordem) if ordem is not None and str(ordem).strip() != "" else index
        except (TypeError, ValueError):
            ordem_int = index
        modelo = _clean_optional_text(
            item.get("modelo")
            or item.get("modelo_nome")
            or item.get("modeloNome")
        )
        cor = _clean_optional_text(
            item.get("cor")
            or item.get("cor_nome")
            or item.get("corNome")
            or item.get("modelo_cor")
            or item.get("modeloCor")
        )
        parsed.append(
            {
                "url": url,
                "url_key": _normalize_image_url(url),
                "ordem": ordem_int,
                "principal": _parse_bool(item.get("principal") if "principal" in item else item.get("capa")),
                "modelo_nome": modelo,
                "modelo_cor": cor,
                "cor_nome": cor,
            }
        )
    return parsed


def _parse_indexed_text_list(value: Optional[str]) -> list[str | None]:
    if not value:
        return []
    raw = value.strip()
    if not raw:
        return []
    if raw.startswith("["):
        try:
            parsed = json.loads(raw)
        except ValueError:
            parsed = None
        if isinstance(parsed, list):
            return [_clean_optional_text(item) for item in parsed]
    return [_clean_optional_text(item) for item in raw.split(",")]


def _first_indexed_value(values: list[str | None], index: int) -> str | None:
    if index >= len(values):
        return None
    return values[index]


def _image_metadata(
    *,
    modelos: Optional[str] = None,
    modelos_nomes: Optional[str] = None,
    modelo_cores: Optional[str] = None,
    cores_nomes: Optional[str] = None,
) -> list[dict[str, str | None]]:
    modelo_values = _parse_indexed_text_list(modelos)
    modelo_nome_values = _parse_indexed_text_list(modelos_nomes)
    modelo_cor_values = _parse_indexed_text_list(modelo_cores)
    cor_nome_values = _parse_indexed_text_list(cores_nomes)
    total = max(
        len(modelo_values),
        len(modelo_nome_values),
        len(modelo_cor_values),
        len(cor_nome_values),
        0,
    )
    return [
        {
            "modelo_nome": _first_indexed_value(modelo_nome_values, index)
            or _first_indexed_value(modelo_values, index),
            "modelo_cor": _first_indexed_value(modelo_cor_values, index),
            "cor_nome": _first_indexed_value(cor_nome_values, index),
        }
        for index in range(total)
    ]


def _legacy_metadata_to_items(metadata: list[dict[str, str | None]]) -> list[dict[str, Any]]:
    return [
        {
            "url": None,
            "url_key": None,
            "ordem": index,
            "principal": index == 0,
            "modelo_nome": item.get("modelo_nome"),
            "modelo_cor": item.get("modelo_cor"),
            "cor_nome": item.get("cor_nome"),
        }
        for index, item in enumerate(metadata)
    ]


def _has_image_metadata(metadata: list[dict[str, str | None]]) -> bool:
    return any(any(value is not None for value in item.values()) for item in metadata)


def _uploaded_files(files: List[UploadFile] | None) -> List[UploadFile]:
    return [file for file in files or [] if file and file.filename]


def _infer_upload_content_type(file: UploadFile) -> str:
    content_type = file.content_type or ""
    if not content_type or content_type == "application/octet-stream":
        ext = (file.filename or "").rsplit(".", 1)[-1].lower()
        content_type = EXT_TO_MIME.get(ext, content_type)
    return content_type


async def _validate_product_images(files: List[UploadFile]) -> None:
    if len(files) > MAX_PRODUCT_IMAGES:
        raise HTTPException(
            status_code=422,
            detail=f"Envie no maximo {MAX_PRODUCT_IMAGES} imagens por produto.",
        )

    for index, file in enumerate(files, start=1):
        content_type = _infer_upload_content_type(file)
        if content_type not in ALLOWED_TYPES:
            raise HTTPException(
                status_code=422,
                detail=f"Imagem {index}: formato invalido. Use JPEG, PNG ou WebP.",
            )

        contents = await file.read()
        if len(contents) > MAX_SIZE:
            raise HTTPException(
                status_code=422,
                detail=f"Imagem {index}: tamanho maximo permitido e 5 MB.",
            )
        await file.seek(0)


async def _save_product_images(files: List[UploadFile]) -> List[str]:
    if not files:
        return []

    await _validate_product_images(files)
    urls = []
    for file in files:
        try:
            urls.append(await upload_image(file, folder=PRODUCT_IMAGE_FOLDER))
        except HTTPException as exc:
            if exc.status_code in {413, 415}:
                raise HTTPException(status_code=422, detail=exc.detail) from exc
            raise
    return urls


def _build_product_image_models(
    image_urls: List[str],
    metadata: list[dict[str, Any]] | None = None,
) -> List[ProdutoImagem]:
    metadata = metadata or []
    return [
        ProdutoImagem(
            imagem_url=image_url,
            ordem=int(metadata[index].get("ordem", index)) if index < len(metadata) else index,
            principal=(
                bool(metadata[index].get("principal"))
                if index < len(metadata) and metadata[index].get("principal") is not None
                else index == 0
            ),
            modelo_nome=(metadata[index].get("modelo_nome") if index < len(metadata) else None),
            modelo_cor=(metadata[index].get("modelo_cor") if index < len(metadata) else None),
            cor_nome=(metadata[index].get("cor_nome") if index < len(metadata) else None),
        )
        for index, image_url in enumerate(image_urls)
    ]


def _apply_product_image_metadata(
    produto: Produto,
    metadata: list[dict[str, Any]],
) -> None:
    imagens = sorted(
        produto.imagens or [],
        key=lambda imagem: (
            imagem.ordem if imagem.ordem is not None else 0,
            imagem.id or 0,
        ),
    )
    for index, imagem in enumerate(imagens):
        if index >= len(metadata):
            break
        imagem.modelo_nome = metadata[index].get("modelo_nome")
        imagem.modelo_cor = metadata[index].get("modelo_cor")
        imagem.cor_nome = metadata[index].get("cor_nome")


def _apply_metadata_to_image(imagem: ProdutoImagem, metadata: dict[str, Any]) -> None:
    imagem.ordem = int(metadata.get("ordem") if metadata.get("ordem") is not None else imagem.ordem or 0)
    imagem.modelo_nome = metadata.get("modelo_nome")
    imagem.modelo_cor = metadata.get("modelo_cor")
    imagem.cor_nome = metadata.get("cor_nome")


def _sync_product_images(
    *,
    produto: Produto,
    kept_urls: set[str] | None,
    new_image_urls: list[str],
    metadata_items: list[dict[str, Any]],
    principal_url: str | None,
    principal_index: int | None,
) -> tuple[set[str], list[str]]:
    existing_images = sorted(
        produto.imagens or [],
        key=lambda imagem: (
            imagem.ordem if imagem.ordem is not None else 0,
            imagem.id or 0,
        ),
    )
    old_urls = _product_image_urls(produto)
    existing_by_url = {
        normalized: imagem
        for imagem in existing_images
        if (normalized := _normalize_image_url(imagem.imagem_url))
    }
    metadata_by_url = {
        item["url_key"]: item
        for item in metadata_items
        if item.get("url_key")
    }
    metadata_without_url = [item for item in metadata_items if not item.get("url_key")]

    if kept_urls is None:
        selected_existing = existing_images
    else:
        selected_existing = [
            imagem
            for imagem in existing_images
            if _normalize_image_url(imagem.imagem_url) in kept_urls
        ]

    final_images: list[ProdutoImagem] = []
    for index, imagem in enumerate(selected_existing):
        metadata = metadata_by_url.get(_normalize_image_url(imagem.imagem_url))
        if metadata is None and index < len(metadata_without_url):
            metadata = metadata_without_url[index]
        if metadata is not None:
            _apply_metadata_to_image(imagem, metadata)
        final_images.append(imagem)

    new_start = len(final_images)
    for index, image_url in enumerate(new_image_urls):
        metadata = metadata_by_url.get(_normalize_image_url(image_url))
        if metadata is None:
            metadata_index = new_start + index
            if metadata_index < len(metadata_without_url):
                metadata = metadata_without_url[metadata_index]
        imagem = ProdutoImagem(
            imagem_url=image_url,
            ordem=metadata.get("ordem", new_start + index) if metadata else new_start + index,
            principal=False,
            modelo_nome=metadata.get("modelo_nome") if metadata else None,
            modelo_cor=metadata.get("modelo_cor") if metadata else None,
            cor_nome=metadata.get("cor_nome") if metadata else None,
        )
        final_images.append(imagem)

    final_images.sort(key=lambda imagem: (imagem.ordem if imagem.ordem is not None else 0, imagem.id or 0))
    for index, imagem in enumerate(final_images):
        imagem.ordem = index

    principal_key = _normalize_image_url(principal_url)
    principal_image: ProdutoImagem | None = None
    if principal_key:
        principal_image = next(
            (imagem for imagem in final_images if _normalize_image_url(imagem.imagem_url) == principal_key),
            None,
        )
    if principal_image is None and principal_index is not None and principal_index < len(final_images):
        principal_image = final_images[principal_index]
    if principal_image is None:
        principal_metadata = next(
            (item for item in metadata_items if item.get("principal")),
            None,
        )
        if principal_metadata:
            metadata_key = principal_metadata.get("url_key")
            if metadata_key:
                principal_image = existing_by_url.get(metadata_key) or next(
                    (
                        imagem
                        for imagem in final_images
                        if _normalize_image_url(imagem.imagem_url) == metadata_key
                    ),
                    None,
                )
            else:
                principal_ordem = principal_metadata.get("ordem")
                if isinstance(principal_ordem, int) and principal_ordem < len(final_images):
                    principal_image = final_images[principal_ordem]
    if principal_image is None:
        principal_image = next((imagem for imagem in final_images if imagem.principal), None)
    if principal_image is None and final_images:
        principal_image = final_images[0]

    for imagem in final_images:
        imagem.principal = imagem is principal_image
    produto.imagens = final_images
    produto.imagem_url = principal_image.imagem_url if principal_image else None
    return old_urls, [imagem.imagem_url for imagem in final_images]


def _produto_imagens_response(produto: Produto) -> list[dict]:
    imagens = sorted(
        produto.imagens or [],
        key=lambda imagem: (
            imagem.ordem if imagem.ordem is not None else 0,
            imagem.id or 0,
        ),
    )
    return [
        {
            "id": imagem.id,
            "imagem_url": imagem.imagem_url,
            "url": imagem.imagem_url,
            "ordem": imagem.ordem,
            "principal": imagem.principal,
            "capa": imagem.principal,
            "modelo_nome": imagem.modelo_nome,
            "modelo_cor": imagem.modelo_cor,
            "cor_nome": imagem.cor_nome,
            "modelo": imagem.modelo_nome,
            "cor": imagem.cor_nome or imagem.modelo_cor,
        }
        for imagem in imagens
    ]


def _produto_imagem_url(produto: Produto, imagens: list[dict]) -> str | None:
    if produto.imagem_url:
        return produto.imagem_url
    if imagens:
        return imagens[0]["imagem_url"]
    return None


def _product_image_urls(produto: Produto) -> set[str]:
    urls = {imagem.imagem_url for imagem in produto.imagens or [] if imagem.imagem_url}
    if produto.imagem_url:
        urls.add(produto.imagem_url)
    return urls


def _delete_replaced_product_images(old_urls: set[str], new_urls: List[str]) -> None:
    for url in old_urls - set(new_urls):
        delete_old_image(url)


async def _save_category_image(file: UploadFile | None) -> str | None:
    if not file or not file.filename:
        return None
    return await upload_image(file, folder="bia-collections/categorias")


def _categoria_response(categoria: Categoria) -> dict:
    return {
        "id": categoria.id,
        "nome": categoria.nome,
        "imagem_url": categoria.imagem_url,
    }


def _produto_response(produto: Produto) -> dict:
    imagens = _produto_imagens_response(produto)
    return {
        "id": produto.id,
        "nome": produto.nome,
        "descricao": produto.descricao,
        "preco": produto.preco,
        "preco_formatado": formatar_preco(produto.preco),
        "preco_promocional": produto.preco_promocional,
        "estoque": produto.estoque,
        "categoria": produto.categoria.nome if produto.categoria else None,
        "imagem_url": _produto_imagem_url(produto, imagens),
        "imagens": imagens,
        "tamanhos": json.loads(produto.tamanhos) if produto.tamanhos else [],
        "cores": json.loads(produto.cores) if produto.cores else [],
    }


def _usuario_admin_response(usuario: Usuario) -> dict:
    return {
        "id": usuario.id,
        "username": usuario.username,
        "email": usuario.email,
        "nome_completo": usuario.nome_completo,
        "telefone": usuario.telefone,
        "criado_em": usuario.criado_em.isoformat() if usuario.criado_em else "",
        "is_admin": is_master_admin_email(usuario.email) or bool(getattr(usuario, "is_admin", False)),
    }


def _pagamento_admin_response(pagamento: Pagamento | None) -> dict | None:
    if not pagamento:
        return None
    return {
        "tipo": pagamento.tipo,
        "status": pagamento.status,
        "mp_status": pagamento.mp_status,
        "mp_payment_id": pagamento.mp_payment_id,
        "mp_preference_id": pagamento.mp_preference_id,
        "valor": pagamento.valor,
        "atualizado_em": pagamento.atualizado_em.isoformat() if pagamento.atualizado_em else None,
    }


@router.get("/stats")
def stats(
    db: Session = Depends(get_db),
    _: Usuario = Depends(get_current_admin),
):
    receita_total = (
        db.query(func.coalesce(func.sum(Pedido.total), 0.0))
        .filter(Pedido.status.in_(list(ORDER_STATUSES_OPERACIONAIS)))
        .scalar()
    )
    pedidos_pendentes = db.query(Pedido).filter(Pedido.status == ORDER_STATUS_AGUARDANDO).count()

    return {
        "total_pedidos": db.query(Pedido).count(),
        "pedidos_pendentes": pedidos_pendentes,
        "total_usuarios": db.query(Usuario).count(),
        "total_produtos": db.query(Produto).filter(Produto.ativo.is_(True)).count(),
        "total_categorias": db.query(Categoria).count(),
        "receita_total": float(receita_total or 0),
        "receita_formatada": formatar_preco(float(receita_total or 0)),
    }


@router.get("/grafico")
def grafico_receita(
    dias: int = Query(7, ge=1, le=365),
    db: Session = Depends(get_db),
    _: Usuario = Depends(get_current_admin),
):
    hoje = datetime.now(timezone.utc).date()
    inicio = hoje - timedelta(days=dias - 1)
    inicio_dt = datetime.combine(inicio, datetime.min.time()).replace(tzinfo=timezone.utc)

    pedidos = (
        db.query(Pedido)
        .filter(
            Pedido.status.in_(list(ORDER_STATUSES_OPERACIONAIS)),
            Pedido.criado_em >= inicio_dt,
        )
        .all()
    )

    dados: dict = {}
    for i in range(dias):
        dia = inicio + timedelta(days=i)
        dados[dia] = {"receita": 0.0, "pedidos": 0}

    for pedido in pedidos:
        dia = pedido.criado_em.astimezone(timezone.utc).date()
        if dia in dados:
            dados[dia]["receita"] += pedido.total
            dados[dia]["pedidos"] += 1

    return [
        {
            "data": dia.strftime("%d/%m"),
            "receita": round(dados[dia]["receita"], 2),
            "pedidos": dados[dia]["pedidos"],
        }
        for dia in sorted(dados.keys())
    ]


@router.get("/pedidos")
def listar_pedidos_admin(
    status: Optional[str] = Query(None),
    incluir_pendentes: bool = Query(False),
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=100),
    db: Session = Depends(get_db),
    _: Usuario = Depends(get_current_admin),
):
    query = db.query(Pedido).options(joinedload(Pedido.itens)).order_by(Pedido.criado_em.desc())
    if status:
        query = query.filter(Pedido.status == status)
    elif not incluir_pendentes:
        query = query.filter(Pedido.status.in_(list(ORDER_STATUSES_OPERACIONAIS)))

    pedidos = query.offset((page - 1) * limit).limit(limit).all()
    pagamentos_por_pedido = {}
    for pagamento in (
        db.query(Pagamento)
        .filter(Pagamento.pedido_numero.in_([pedido.numero for pedido in pedidos]))
        .order_by(Pagamento.id.desc())
        .all()
    ):
        pagamentos_por_pedido.setdefault(pagamento.pedido_numero, pagamento)
    return [
        {
            "numero": pedido.numero,
            "data": pedido.criado_em.isoformat() if pedido.criado_em else "",
            "status": pedido.status,
            "total_formatado": formatar_preco(pedido.total),
            "total_itens": sum(item.quantidade for item in pedido.itens),
            "pagamento": _pagamento_admin_response(pagamentos_por_pedido.get(pedido.numero)),
        }
        for pedido in pedidos
    ]


@router.put("/pedidos/{numero}/status")
def atualizar_status_pedido(
    numero: str,
    data: StatusPedidoPayload,
    db: Session = Depends(get_db),
    _: Usuario = Depends(get_current_admin),
):
    pedido = db.query(Pedido).filter(Pedido.numero == numero).first()
    if not pedido:
        raise HTTPException(status_code=404, detail="Pedido não encontrado.")

    old_status = pedido.status
    pedido.status = data.status
    db.commit()
    db.refresh(pedido)
    event_key = ORDER_STATUS_EMAIL_EVENTS.get(data.status)
    if event_key and old_status != data.status:
        trigger_order_email_event(db, event_key, pedido)
    return {"numero": pedido.numero, "status": pedido.status}


@router.get("/pedidos/{numero}")
def detalhe_pedido_admin(
    numero: str,
    db: Session = Depends(get_db),
    _: Usuario = Depends(get_current_admin),
):
    pedido = (
        db.query(Pedido)
        .options(joinedload(Pedido.itens), joinedload(Pedido.usuario))
        .filter(Pedido.numero == numero)
        .first()
    )
    if not pedido:
        raise HTTPException(status_code=404, detail="Pedido não encontrado.")

    pagamento = (
        db.query(Pagamento)
        .filter(Pagamento.pedido_numero == pedido.numero)
        .order_by(Pagamento.id.desc())
        .first()
    )

    endereco = None
    if pedido.endereco_cep:
        endereco = {
            "cep": pedido.endereco_cep,
            "rua": pedido.endereco_rua,
            "numero": pedido.endereco_numero,
            "complemento": pedido.endereco_complemento,
            "bairro": pedido.endereco_bairro,
            "cidade": pedido.endereco_cidade,
            "estado": pedido.endereco_estado,
        }

    return {
        "numero": pedido.numero,
        "data": pedido.criado_em.isoformat() if pedido.criado_em else "",
        "status": pedido.status,
        "forma_pagamento": pedido.forma_pagamento,
        "subtotal": pedido.subtotal if pedido.subtotal is not None else pedido.total,
        "subtotal_formatado": formatar_preco(pedido.subtotal if pedido.subtotal is not None else pedido.total),
        "valor_frete": pedido.valor_frete or 0.0,
        "valor_frete_formatado": formatar_preco(pedido.valor_frete or 0.0),
        "tipo_frete": pedido.tipo_frete,
        "prazo_frete": pedido.prazo_frete,
        "total": pedido.total,
        "total_formatado": formatar_preco(pedido.total),
        "desconto_aplicado": pedido.desconto_aplicado,
        "cupom_codigo": pedido.cupom_codigo,
        "codigo_rastreio": pedido.codigo_rastreio,
        "pagamento": _pagamento_admin_response(pagamento),
        "usuario_nome": pedido.usuario.nome_completo if pedido.usuario else None,
        "usuario_email": pedido.usuario.email if pedido.usuario else None,
        "itens": [
            {
                "produto_id": item.produto_id,
                "nome_produto": item.nome_produto,
                "preco_unitario": item.preco_unitario,
                "tamanho": item.tamanho,
                "cor": item.cor,
                "quantidade": item.quantidade,
            }
            for item in pedido.itens
        ],
        "endereco": endereco,
    }


@router.put("/pedidos/{numero}/rastreio")
def atualizar_rastreio_pedido(
    numero: str,
    data: RastreioPayload,
    db: Session = Depends(get_db),
    _: Usuario = Depends(get_current_admin),
):
    pedido = db.query(Pedido).filter(Pedido.numero == numero).first()
    if not pedido:
        raise HTTPException(status_code=404, detail="Pedido não encontrado.")

    pedido.codigo_rastreio = data.codigo_rastreio
    db.commit()
    db.refresh(pedido)
    trigger_order_email_event(
        db,
        "tracking_code_available",
        pedido,
        extra={"tracking_code": pedido.codigo_rastreio or ""},
    )
    return {"numero": pedido.numero, "codigo_rastreio": pedido.codigo_rastreio}


@router.get("/usuarios")
def listar_usuarios(
    db: Session = Depends(get_db),
    _: Usuario = Depends(get_current_admin),
):
    usuarios = db.query(Usuario).order_by(Usuario.criado_em.desc()).all()
    return [_usuario_admin_response(usuario) for usuario in usuarios]


@router.put("/usuarios/{usuario_id}/admin")
def atualizar_admin_usuario(
    usuario_id: int,
    data: UsuarioAdminPayload,
    request: Request,
    db: Session = Depends(get_db),
    current_admin: Usuario = Depends(get_current_admin),
):
    usuario = db.query(Usuario).filter(Usuario.id == usuario_id).first()
    if not usuario:
        raise HTTPException(status_code=404, detail="Usuario nao encontrado.")

    if usuario.id == current_admin.id or is_master_admin_email(usuario.email):
        log_admin_access_denied(
            current_admin,
            request.url.path,
            "tentativa_alterar_usuario_mestre",
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Nao e permitido alterar o privilegio do usuario mestre.",
        )

    usuario.is_admin = data.is_admin
    db.commit()
    db.refresh(usuario)
    return _usuario_admin_response(usuario)


@router.delete("/usuarios/{usuario_id}", status_code=status.HTTP_204_NO_CONTENT)
def deletar_usuario(
    usuario_id: int,
    request: Request,
    db: Session = Depends(get_db),
    current_admin: Usuario = Depends(get_current_admin),
):
    usuario = db.query(Usuario).filter(Usuario.id == usuario_id).first()
    if not usuario:
        raise HTTPException(status_code=404, detail="Usuario nao encontrado.")

    if usuario.id == current_admin.id or is_master_admin_email(usuario.email):
        log_admin_access_denied(
            current_admin,
            request.url.path,
            "tentativa_excluir_usuario_mestre",
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Nao e permitido excluir o usuario mestre.",
        )

    db.delete(usuario)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/categorias", status_code=status.HTTP_201_CREATED)
async def criar_categoria(
    request: Request,
    db: Session = Depends(get_db),
    _: Usuario = Depends(get_current_admin),
):
    content_type = request.headers.get("content-type", "")
    imagem = None
    imagem_url = None

    if content_type.startswith(("multipart/form-data", "application/x-www-form-urlencoded")):
        form = await request.form()
        nome = form.get("nome")
        candidate = form.get("imagem") or form.get("foto")
        if getattr(candidate, "filename", None):
            imagem = candidate
        imagem_url_value = form.get("imagem_url")
        imagem_url = str(imagem_url_value).strip() if imagem_url_value else None
    else:
        try:
            body = await request.json()
        except ValueError:
            body = {}
        nome = body.get("nome") if isinstance(body, dict) else None
        imagem_url_value = body.get("imagem_url") if isinstance(body, dict) else None
        imagem_url = str(imagem_url_value).strip() if imagem_url_value else None

    try:
        data = CategoriaPayload(nome=str(nome or ""))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="Nome da categoria muito curto.") from exc

    exists = db.query(Categoria).filter(func.lower(Categoria.nome) == data.nome.lower()).first()
    if exists:
        raise HTTPException(status_code=409, detail="Categoria já cadastrada.")

    img = await _save_category_image(imagem)
    categoria = Categoria(nome=data.nome, imagem_url=img or imagem_url)
    db.add(categoria)
    db.commit()
    db.refresh(categoria)
    return _categoria_response(categoria)


@router.put("/categorias/{categoria_id}")
async def atualizar_categoria(
    categoria_id: int,
    nome: str = Form(...),
    imagem: UploadFile | None = File(None),
    db: Session = Depends(get_db),
    _: Usuario = Depends(get_current_admin),
):
    categoria = db.query(Categoria).filter(Categoria.id == categoria_id).first()
    if not categoria:
        raise HTTPException(status_code=404, detail="Categoria nao encontrada.")

    try:
        data = CategoriaPayload(nome=nome)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="Nome da categoria muito curto.") from exc

    exists = (
        db.query(Categoria)
        .filter(
            func.lower(Categoria.nome) == data.nome.lower(),
            Categoria.id != categoria_id,
        )
        .first()
    )
    if exists:
        raise HTTPException(status_code=409, detail="Categoria ja cadastrada.")

    old_image_url = categoria.imagem_url
    new_image_url = await _save_category_image(imagem)

    categoria.nome = data.nome
    if new_image_url:
        categoria.imagem_url = new_image_url

    db.commit()
    db.refresh(categoria)

    if new_image_url and old_image_url and old_image_url != new_image_url:
        delete_old_image(old_image_url)

    return _categoria_response(categoria)


@router.delete("/categorias/{categoria_id}", status_code=status.HTTP_204_NO_CONTENT)
def deletar_categoria(
    categoria_id: int,
    db: Session = Depends(get_db),
    _: Usuario = Depends(get_current_admin),
):
    categoria = db.query(Categoria).filter(Categoria.id == categoria_id).first()
    if not categoria:
        raise HTTPException(status_code=404, detail="Categoria não encontrada.")
    if (
        db.query(Produto)
        .filter(Produto.categoria_id == categoria.id, Produto.ativo.is_(True))
        .first()
    ):
        raise HTTPException(status_code=409, detail="Categoria possui produtos vinculados.")

    db.query(Produto).filter(
        Produto.categoria_id == categoria.id,
        Produto.ativo.is_not(True),
    ).update({Produto.categoria_id: None}, synchronize_session=False)
    db.delete(categoria)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/produtos")
def listar_produtos_admin(
    busca: Optional[str] = Query(None),
    categoria_id: Optional[int] = Query(None),
    ativo: Optional[bool] = Query(None),
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=100),
    db: Session = Depends(get_db),
    _: Usuario = Depends(get_current_admin),
):
    query = db.query(Produto).options(
        joinedload(Produto.categoria),
        joinedload(Produto.imagens),
    )

    if busca:
        query = query.filter(Produto.nome.ilike(f"%{busca}%"))
    if categoria_id is not None:
        query = query.filter(Produto.categoria_id == categoria_id)
    if ativo is not None:
        query = query.filter(Produto.ativo.is_(ativo))

    total = query.count()
    produtos = (
        query.order_by(Produto.criado_em.desc())
        .offset((page - 1) * limit)
        .limit(limit)
        .all()
    )
    return {
        "total": total,
        "page": page,
        "limit": limit,
        "itens": [_produto_response(produto) for produto in produtos],
    }


@router.post("/produtos", status_code=status.HTTP_201_CREATED)
async def criar_produto(
    nome: str = Form(...),
    descricao: str = Form(""),
    preco: float = Form(...),
    preco_promocional: Optional[float] = Form(None),
    estoque: Optional[int] = Form(None),
    categoria_id: str = Form(""),
    tamanhos: str = Form(""),
    cores: str = Form(""),
    ativo: bool = Form(True),
    imagem: UploadFile | None = File(None),
    imagens: List[UploadFile] | None = File(None),
    modelos: Optional[str] = Form(None),
    modelos_nomes: Optional[str] = Form(None),
    modelo_cores: Optional[str] = Form(None),
    cores_nomes: Optional[str] = Form(None),
    db: Session = Depends(get_db),
    _: Usuario = Depends(get_current_admin),
):
    image_files = _uploaded_files(imagens) or _uploaded_files([imagem] if imagem else None)
    image_urls = await _save_product_images(image_files)
    image_metadata = _image_metadata(
        modelos=modelos,
        modelos_nomes=modelos_nomes,
        modelo_cores=modelo_cores,
        cores_nomes=cores_nomes,
    )
    produto = Produto(
        nome=nome.strip(),
        descricao=descricao.strip() or None,
        preco=preco,
        preco_promocional=preco_promocional,
        estoque=estoque,
        categoria_id=int(categoria_id) if categoria_id else None,
        imagem_url=image_urls[0] if image_urls else None,
        imagens=_build_product_image_models(image_urls, image_metadata),
        tamanhos=_split_csv(tamanhos),
        cores=_split_csv(cores),
        ativo=ativo,
    )
    db.add(produto)
    db.commit()
    db.refresh(produto)
    return _produto_response(produto)


@router.put("/produtos/{produto_id}")
async def atualizar_produto(
    produto_id: int,
    nome: str = Form(...),
    descricao: Optional[str] = Form(None),
    preco: float = Form(...),
    preco_promocional: Optional[float] = Form(None),
    estoque: Optional[int] = Form(None),
    categoria_id: str = Form(""),
    tamanhos: str = Form(""),
    cores: str = Form(""),
    ativo: bool = Form(True),
    imagem: UploadFile | None = File(None),
    imagens: List[UploadFile] | None = File(None),
    modelos: Optional[str] = Form(None),
    modelos_nomes: Optional[str] = Form(None),
    modelo_cores: Optional[str] = Form(None),
    cores_nomes: Optional[str] = Form(None),
    imagens_manter: Optional[str] = Form(None),
    imagem_principal_url: Optional[str] = Form(None),
    capa_url: Optional[str] = Form(None),
    imagem_principal_index: Optional[str] = Form(None),
    capa_indice: Optional[str] = Form(None),
    imagens_metadata: Optional[str] = Form(None),
    db: Session = Depends(get_db),
    _: Usuario = Depends(get_current_admin),
):
    produto = (
        db.query(Produto)
        .options(joinedload(Produto.imagens))
        .filter(Produto.id == produto_id)
        .first()
    )
    if not produto:
        raise HTTPException(status_code=404, detail="Produto não encontrado.")

    image_files = _uploaded_files(imagens) or _uploaded_files([imagem] if imagem else None)
    image_urls = await _save_product_images(image_files) if image_files else []
    legacy_image_metadata = _image_metadata(
        modelos=modelos,
        modelos_nomes=modelos_nomes,
        modelo_cores=modelo_cores,
        cores_nomes=cores_nomes,
    )
    metadata_items = _parse_image_metadata_items(imagens_metadata)
    if not metadata_items:
        metadata_items = _legacy_metadata_to_items(legacy_image_metadata)
    if imagens_manter is not None:
        keep_urls = _parse_image_keep_urls(imagens_manter)
    elif image_files:
        keep_urls = set()
    else:
        keep_urls = None
    explicit_principal_url = _clean_optional_text(imagem_principal_url) or _clean_optional_text(capa_url)
    imagem_principal_index_value = _parse_optional_index(imagem_principal_index)
    explicit_principal_index = (
        imagem_principal_index_value
        if imagem_principal_index_value is not None
        else _parse_optional_index(capa_indice)
    )
    should_sync_images = any(
        [
            image_files,
            imagens_manter is not None,
            imagens_metadata is not None,
            explicit_principal_url is not None,
            explicit_principal_index is not None,
        ]
    )

    produto.nome = nome.strip()
    descricao_limpa = _clean_optional_text(descricao)
    if descricao_limpa is not None:
        produto.descricao = descricao_limpa
    produto.preco = preco
    produto.preco_promocional = preco_promocional
    produto.estoque = estoque
    produto.categoria_id = int(categoria_id) if categoria_id else None
    produto.tamanhos = _split_csv(tamanhos)
    produto.cores = _split_csv(cores)
    produto.ativo = ativo
    if should_sync_images:
        old_image_urls, final_image_urls = _sync_product_images(
            produto=produto,
            kept_urls=keep_urls,
            new_image_urls=image_urls,
            metadata_items=metadata_items,
            principal_url=explicit_principal_url,
            principal_index=explicit_principal_index,
        )
    elif _has_image_metadata(legacy_image_metadata):
        _apply_product_image_metadata(produto, legacy_image_metadata)
        old_image_urls, final_image_urls = set(), []
    else:
        old_image_urls, final_image_urls = set(), []

    db.commit()
    db.refresh(produto)
    if should_sync_images:
        _delete_replaced_product_images(old_image_urls, final_image_urls)
    return _produto_response(produto)


@router.delete("/produtos/{produto_id}", status_code=status.HTTP_204_NO_CONTENT)
def deletar_produto(
    produto_id: int,
    db: Session = Depends(get_db),
    _: Usuario = Depends(get_current_admin),
):
    produto = db.query(Produto).filter(Produto.id == produto_id).first()
    if not produto:
        raise HTTPException(status_code=404, detail="Produto não encontrado.")

    produto.ativo = False
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/cupons")
def listar_cupons_admin(
    incluir_deletados: bool = Query(False),
    db: Session = Depends(get_db),
    _: Usuario = Depends(get_current_admin),
):
    query = db.query(Cupom)
    if not incluir_deletados:
        query = query.filter(Cupom.deletado_em.is_(None))
    cupons = query.order_by(Cupom.validade.desc()).all()
    return [
        {
            "id": cupom.id,
            "codigo": cupom.codigo,
            "descricao": cupom.descricao,
            "tipo": cupom.tipo,
            "valor": cupom.valor,
            "validade": cupom.validade.isoformat(),
            "ativo": cupom.ativo,
            "valor_minimo_pedido": cupom.valor_minimo_pedido,
            "max_usos": cupom.max_usos,
            "total_usos": cupom.total_usos,
        }
        for cupom in cupons
    ]


def _cupom_response(cupom: Cupom) -> dict:
    return {
        "id": cupom.id,
        "codigo": cupom.codigo,
        "descricao": cupom.descricao,
        "tipo": cupom.tipo,
        "valor": cupom.valor,
        "validade": cupom.validade.isoformat(),
        "ativo": cupom.ativo,
        "valor_minimo_pedido": cupom.valor_minimo_pedido,
        "max_usos": cupom.max_usos,
        "total_usos": cupom.total_usos,
    }


@router.post("/cupons", status_code=status.HTTP_201_CREATED)
def criar_cupom_admin(
    data: CupomPayload,
    db: Session = Depends(get_db),
    _: Usuario = Depends(get_current_admin),
):
    data.validar_valor_por_tipo()
    exists = db.query(Cupom).filter(Cupom.codigo == data.codigo).first()
    if exists:
        raise HTTPException(status_code=409, detail="Cupom já cadastrado.")

    cupom = Cupom(
        codigo=data.codigo,
        descricao=data.descricao,
        tipo=data.tipo,
        valor=data.valor,
        validade=data.validade,
        ativo=data.ativo,
        valor_minimo_pedido=data.valor_minimo_pedido,
        max_usos=data.max_usos,
        total_usos=0,
    )
    db.add(cupom)
    db.commit()
    db.refresh(cupom)
    return _cupom_response(cupom)


@router.put("/cupons/{cupom_id}")
def atualizar_cupom_admin(
    cupom_id: int,
    data: CupomPayload,
    db: Session = Depends(get_db),
    _: Usuario = Depends(get_current_admin),
):
    data.validar_valor_por_tipo()
    cupom = db.query(Cupom).filter(Cupom.id == cupom_id, Cupom.deletado_em.is_(None)).first()
    if not cupom:
        raise HTTPException(status_code=404, detail="Cupom não encontrado.")

    exists = (
        db.query(Cupom)
        .filter(Cupom.codigo == data.codigo, Cupom.id != cupom_id)
        .first()
    )
    if exists:
        raise HTTPException(status_code=409, detail="Cupom ja cadastrado.")

    # Não permitir alterar código se já tiver usos registrados
    if cupom.codigo != data.codigo and cupom.total_usos > 0:
        raise HTTPException(
            status_code=409,
            detail="Não é possível alterar o código de um cupom que já foi utilizado.",
        )

    cupom.codigo = data.codigo
    cupom.descricao = data.descricao
    cupom.tipo = data.tipo
    cupom.valor = data.valor
    cupom.validade = data.validade
    cupom.ativo = data.ativo
    cupom.valor_minimo_pedido = data.valor_minimo_pedido
    cupom.max_usos = data.max_usos
    db.commit()
    db.refresh(cupom)
    return _cupom_response(cupom)


@router.delete("/cupons/{cupom_id}", status_code=status.HTTP_204_NO_CONTENT)
def deletar_cupom_admin(
    cupom_id: int,
    db: Session = Depends(get_db),
    _: Usuario = Depends(get_current_admin),
):
    cupom = db.query(Cupom).filter(Cupom.id == cupom_id, Cupom.deletado_em.is_(None)).first()
    if not cupom:
        raise HTTPException(status_code=404, detail="Cupom não encontrado.")

    if db.query(CupomUsado).filter(CupomUsado.cupom_id == cupom.id).first():
        cupom.ativo = False
        cupom.deletado_em = datetime.now(timezone.utc)
    else:
        db.delete(cupom)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/duvidas", response_model=List[DuvidaOut])
def listar_duvidas_admin(
    status: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    _: Usuario = Depends(get_current_admin),
):
    query = db.query(Duvida).order_by(Duvida.criado_em.desc())
    if status in ("pendente", "respondida"):
        query = query.filter(Duvida.status == status)
    return query.all()


@router.put("/duvidas/{duvida_id}", response_model=DuvidaOut)
def responder_duvida_admin(
    duvida_id: int,
    data: RespostaDuvidaPayload,
    db: Session = Depends(get_db),
    _: Usuario = Depends(get_current_admin),
):
    duvida = db.query(Duvida).filter(Duvida.id == duvida_id).first()
    if not duvida:
        raise HTTPException(status_code=404, detail="Dúvida não encontrada.")

    duvida.resposta = data.resposta
    duvida.status = "respondida"
    duvida.respondida_em = datetime.now(timezone.utc)
    db.commit()
    db.refresh(duvida)
    return duvida


# ── Avaliações ────────────────────────────────────────────────────────────────

@router.get("/avaliacoes")
def listar_avaliacoes_admin(
    status: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    _: Usuario = Depends(get_current_admin),
):
    query = avaliacao_query(db).order_by(Avaliacao.criado_em.desc())
    if status in AVALIACAO_STATUS_VALUES:
        query = query.filter(Avaliacao.status == status)

    return [avaliacao_response(avaliacao) for avaliacao in query.all()]


@router.put("/avaliacoes/{avaliacao_id}/status")
def atualizar_status_avaliacao(
    avaliacao_id: int,
    data: AvaliacaoStatusPayload,
    db: Session = Depends(get_db),
    _: Usuario = Depends(get_current_admin),
):
    avaliacao = avaliacao_query(db).filter(Avaliacao.id == avaliacao_id).first()
    if not avaliacao:
        raise HTTPException(status_code=404, detail="Avaliação não encontrada.")

    avaliacao.status = data.status
    db.commit()
    return avaliacao_response(
        avaliacao_query(db).filter(Avaliacao.id == avaliacao_id).first()
    )


@router.delete("/avaliacoes/{avaliacao_id}", status_code=status.HTTP_204_NO_CONTENT)
def deletar_avaliacao(
    avaliacao_id: int,
    db: Session = Depends(get_db),
    _: Usuario = Depends(get_current_admin),
):
    avaliacao = avaliacao_query(db).filter(Avaliacao.id == avaliacao_id).first()
    if not avaliacao:
        raise HTTPException(status_code=404, detail="Avaliação não encontrada.")

    image_urls = avaliacao_file_urls(avaliacao)
    db.delete(avaliacao)
    db.commit()
    delete_avaliacao_files(image_urls)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ── Banners ───────────────────────────────────────────────────────────────────

async def _save_banner_image(file: UploadFile | None) -> str | None:
    if not file or not file.filename:
        return None
    return await upload_image(file, folder="banners")


def _banner_response(banner: Banner) -> dict:
    return {
        "id": banner.id,
        "titulo": banner.titulo,
        "imagem_url": banner.imagem_url,
        "link": banner.link,
        "ativo": banner.ativo,
        "ordem": banner.ordem,
    }


@router.get("/banners")
def listar_banners_admin(
    db: Session = Depends(get_db),
    _: Usuario = Depends(get_current_admin),
):
    banners = db.query(Banner).order_by(Banner.ordem).all()
    return [_banner_response(b) for b in banners]


@router.post("/banners", status_code=status.HTTP_201_CREATED)
async def criar_banner(
    titulo: str = Form(...),
    link: Optional[str] = Form(None),
    imagem: UploadFile = File(...),
    db: Session = Depends(get_db),
    _: Usuario = Depends(get_current_admin),
):
    titulo_limpo = titulo.strip()
    if not titulo_limpo:
        raise HTTPException(status_code=422, detail="Titulo e obrigatorio.")

    img = await _save_banner_image(imagem)
    if not img:
        raise HTTPException(status_code=422, detail="Imagem e obrigatoria.")

    max_ordem = db.query(func.coalesce(func.max(Banner.ordem), 0)).scalar() or 0
    banner = Banner(
        titulo=titulo_limpo,
        imagem_url=img,
        link=link.strip() if link else None,
        ativo=True,
        ordem=max_ordem + 1,
    )
    db.add(banner)
    db.commit()
    db.refresh(banner)
    return _banner_response(banner)


@router.put("/banners/ordem")
def reordenar_banners(
    data: BannerOrdemPayload,
    db: Session = Depends(get_db),
    _: Usuario = Depends(get_current_admin),
):
    ids = data.ids
    if len(ids) != len(set(ids)):
        raise HTTPException(status_code=422, detail="Lista de ids contem duplicados.")

    found_ids = (
        {banner_id for (banner_id,) in db.query(Banner.id).filter(Banner.id.in_(ids)).all()}
        if ids
        else set()
    )
    missing_ids = set(ids) - found_ids
    if missing_ids:
        raise HTTPException(status_code=404, detail="Um ou mais banners nao foram encontrados.")

    for posicao, banner_id in enumerate(ids, start=1):
        db.query(Banner).filter(Banner.id == banner_id).update(
            {Banner.ordem: posicao, Banner.atualizado_em: datetime.now(timezone.utc)},
            synchronize_session=False,
        )
    db.commit()
    return {"ok": True}


@router.put("/banners/{banner_id}")
async def atualizar_banner(
    banner_id: int,
    titulo: str = Form(...),
    link: Optional[str] = Form(None),
    ativo: Optional[bool] = Form(None),
    imagem: UploadFile | None = File(None),
    db: Session = Depends(get_db),
    _: Usuario = Depends(get_current_admin),
):
    banner = db.query(Banner).filter(Banner.id == banner_id).first()
    if not banner:
        raise HTTPException(status_code=404, detail="Banner não encontrado.")

    titulo_limpo = titulo.strip()
    if not titulo_limpo:
        raise HTTPException(status_code=422, detail="Titulo e obrigatorio.")

    old_image_url = banner.imagem_url
    img = await _save_banner_image(imagem)
    banner.titulo = titulo_limpo
    banner.link = link.strip() if link else None
    if ativo is not None:
        banner.ativo = ativo
    if img:
        banner.imagem_url = img

    db.commit()
    db.refresh(banner)
    if img and old_image_url and old_image_url != img:
        delete_old_image(old_image_url)
    return _banner_response(banner)


@router.delete("/banners/{banner_id}", status_code=status.HTTP_204_NO_CONTENT)
def deletar_banner(
    banner_id: int,
    db: Session = Depends(get_db),
    _: Usuario = Depends(get_current_admin),
):
    banner = db.query(Banner).filter(Banner.id == banner_id).first()
    if not banner:
        raise HTTPException(status_code=404, detail="Banner não encontrado.")

    old_image_url = banner.imagem_url
    db.delete(banner)
    db.commit()
    delete_old_image(old_image_url)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


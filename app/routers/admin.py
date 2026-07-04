import json
from datetime import date, datetime, timezone
from typing import List, Optional

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
from app.services.upload_service import upload_image
from app.models.cupom import Cupom, CupomUsado
from app.models.duvida import Duvida
from app.models.pedido import Pedido
from app.models.produto import Categoria, Produto
from app.models.usuario import Usuario
from app.schemas.duvida import DuvidaOut
from app.schemas.pedido import PedidoListItem
from app.services.frete_service import formatar_preco

router = APIRouter(
    prefix="/admin",
    tags=["admin"],
    dependencies=[Depends(get_current_master_admin_user)],
)

ORDER_STATUSES = {
    "Aguardando pagamento",
    "Pago",
    "Preparando",
    "Enviado",
    "Entregue",
    "Cancelado",
}


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

    @field_validator("codigo")
    @classmethod
    def codigo_valido(cls, value: str) -> str:
        value = value.strip().upper()
        if len(value) < 3:
            raise ValueError("Código do cupom muito curto.")
        return value

    @field_validator("tipo")
    @classmethod
    def tipo_valido(cls, value: str) -> str:
        if value not in {"porcentagem", "valor", "frete"}:
            raise ValueError("Tipo de cupom inválido.")
        return value


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


async def _save_product_image(file: UploadFile | None) -> str | None:
    if not file or not file.filename:
        return None
    return await upload_image(file, folder="bia-collections/produtos")


def _produto_response(produto: Produto) -> dict:
    return {
        "id": produto.id,
        "nome": produto.nome,
        "descricao": produto.descricao,
        "preco": produto.preco,
        "preco_formatado": formatar_preco(produto.preco),
        "categoria": produto.categoria.nome if produto.categoria else None,
        "imagem_url": produto.imagem_url,
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


@router.get("/stats")
def stats(
    db: Session = Depends(get_db),
    _: Usuario = Depends(get_current_admin),
):
    receita_total = (
        db.query(func.coalesce(func.sum(Pedido.total), 0.0))
        .filter(Pedido.status.in_(["Pago", "Preparando", "Enviado", "Entregue"]))
        .scalar()
    )
    pedidos_pendentes = db.query(Pedido).filter(Pedido.status == "Aguardando pagamento").count()

    return {
        "total_pedidos": db.query(Pedido).count(),
        "pedidos_pendentes": pedidos_pendentes,
        "total_usuarios": db.query(Usuario).count(),
        "total_produtos": db.query(Produto).filter(Produto.ativo.is_(True)).count(),
        "total_categorias": db.query(Categoria).count(),
        "receita_total": float(receita_total or 0),
        "receita_formatada": formatar_preco(float(receita_total or 0)),
    }


@router.get("/pedidos", response_model=List[PedidoListItem])
def listar_pedidos_admin(
    status: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=100),
    db: Session = Depends(get_db),
    _: Usuario = Depends(get_current_admin),
):
    query = db.query(Pedido).options(joinedload(Pedido.itens)).order_by(Pedido.criado_em.desc())
    if status:
        query = query.filter(Pedido.status == status)

    pedidos = query.offset((page - 1) * limit).limit(limit).all()
    return [
        PedidoListItem(
            numero=pedido.numero,
            data=pedido.criado_em.isoformat() if pedido.criado_em else "",
            status=pedido.status,
            total_formatado=formatar_preco(pedido.total),
            total_itens=sum(item.quantidade for item in pedido.itens),
        )
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

    pedido.status = data.status
    db.commit()
    return {"numero": pedido.numero, "status": pedido.status}


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
def criar_categoria(
    data: CategoriaPayload,
    db: Session = Depends(get_db),
    _: Usuario = Depends(get_current_admin),
):
    exists = db.query(Categoria).filter(func.lower(Categoria.nome) == data.nome.lower()).first()
    if exists:
        raise HTTPException(status_code=409, detail="Categoria já cadastrada.")

    categoria = Categoria(nome=data.nome)
    db.add(categoria)
    db.commit()
    db.refresh(categoria)
    return {"id": categoria.id, "nome": categoria.nome}


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


@router.post("/produtos", status_code=status.HTTP_201_CREATED)
async def criar_produto(
    nome: str = Form(...),
    descricao: str = Form(""),
    preco: float = Form(...),
    categoria_id: str = Form(""),
    tamanhos: str = Form(""),
    cores: str = Form(""),
    ativo: bool = Form(True),
    imagem: UploadFile | None = File(None),
    db: Session = Depends(get_db),
    _: Usuario = Depends(get_current_admin),
):
    img = await _save_product_image(imagem)
    produto = Produto(
        nome=nome.strip(),
        descricao=descricao.strip() or None,
        preco=preco,
        categoria_id=int(categoria_id) if categoria_id else None,
        imagem_url=img,
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
    descricao: str = Form(""),
    preco: float = Form(...),
    categoria_id: str = Form(""),
    tamanhos: str = Form(""),
    cores: str = Form(""),
    ativo: bool = Form(True),
    imagem: UploadFile | None = File(None),
    db: Session = Depends(get_db),
    _: Usuario = Depends(get_current_admin),
):
    produto = db.query(Produto).filter(Produto.id == produto_id).first()
    if not produto:
        raise HTTPException(status_code=404, detail="Produto não encontrado.")

    img = await _save_product_image(imagem)
    produto.nome = nome.strip()
    produto.descricao = descricao.strip() or None
    produto.preco = preco
    produto.categoria_id = int(categoria_id) if categoria_id else None
    produto.tamanhos = _split_csv(tamanhos)
    produto.cores = _split_csv(cores)
    produto.ativo = ativo
    if img:
        produto.imagem_url = img

    db.commit()
    db.refresh(produto)
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
    db: Session = Depends(get_db),
    _: Usuario = Depends(get_current_admin),
):
    cupons = db.query(Cupom).order_by(Cupom.validade.desc()).all()
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
        }
        for cupom in cupons
    ]


@router.post("/cupons", status_code=status.HTTP_201_CREATED)
def criar_cupom_admin(
    data: CupomPayload,
    db: Session = Depends(get_db),
    _: Usuario = Depends(get_current_admin),
):
    exists = db.query(Cupom).filter(Cupom.codigo == data.codigo).first()
    if exists:
        raise HTTPException(status_code=409, detail="Cupom já cadastrado.")

    cupom = Cupom(**data.model_dump())
    db.add(cupom)
    db.commit()
    db.refresh(cupom)
    return {
        "id": cupom.id,
        "codigo": cupom.codigo,
        "descricao": cupom.descricao,
        "tipo": cupom.tipo,
        "valor": cupom.valor,
        "validade": cupom.validade.isoformat(),
        "ativo": cupom.ativo,
        "valor_minimo_pedido": cupom.valor_minimo_pedido,
    }


@router.delete("/cupons/{cupom_id}", status_code=status.HTTP_204_NO_CONTENT)
def deletar_cupom_admin(
    cupom_id: int,
    db: Session = Depends(get_db),
    _: Usuario = Depends(get_current_admin),
):
    cupom = db.query(Cupom).filter(Cupom.id == cupom_id).first()
    if not cupom:
        raise HTTPException(status_code=404, detail="Cupom não encontrado.")

    if db.query(CupomUsado).filter(CupomUsado.cupom_id == cupom.id).first():
        cupom.ativo = False
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

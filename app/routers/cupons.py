from datetime import date

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session, joinedload
from typing import List

from app.database import get_db
from app.dependencies import get_current_user
from app.models.usuario import Usuario
from app.models.cupom import Cupom, CupomUsado
from app.schemas.cupom import (
    CuponsResponse,
    ValidarCupomRequest,
    ValidarCupomResponse,
    CupomAtivo,
    CupomUsadoResponse,
)
from app.services.frete_service import formatar_preco

router = APIRouter(prefix="/cupons", tags=["cupons"])


def _formatar_validade(cupom: Cupom) -> str:
    hoje = date.today()
    if cupom.validade < hoje:
        return f"Expirou em {cupom.validade.strftime('%d/%m/%Y')}"
    return f"Válido até {cupom.validade.strftime('%d/%m/%Y')}"


def _formatar_valor_cupom(cupom: Cupom) -> str:
    if cupom.tipo == "porcentagem":
        return f"{int(cupom.valor)}%"
    if cupom.tipo == "frete":
        return "Frete grátis"
    return formatar_preco(cupom.valor)


@router.get("", response_model=CuponsResponse)
def listar_cupons(
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
):
    hoje = date.today()

    # IDs of coupons already used by this user
    usados_ids = {
        row.cupom_id
        for row in db.query(CupomUsado.cupom_id)
        .filter(CupomUsado.usuario_id == current_user.id)
        .all()
    }

    # Active coupons not yet used by this user
    ativos_query = db.query(Cupom).filter(
        Cupom.ativo.is_(True),
        Cupom.validade >= hoje,
    )
    if usados_ids:
        ativos_query = ativos_query.filter(~Cupom.id.in_(usados_ids))

    ativos: List[CupomAtivo] = [
        CupomAtivo(
            codigo=c.codigo,
            descricao=c.descricao,
            tipo=c.tipo,
            valor=_formatar_valor_cupom(c),
            validade=_formatar_validade(c),
        )
        for c in ativos_query.all()
    ]

    # Coupons used by this user — eager-load cupom + pedido to avoid N+1
    usos = (
        db.query(CupomUsado)
        .options(joinedload(CupomUsado.cupom), joinedload(CupomUsado.pedido))
        .filter(CupomUsado.usuario_id == current_user.id)
        .all()
    )
    usados: List[CupomUsadoResponse] = [
        CupomUsadoResponse(
            codigo=uso.cupom.codigo,
            descricao=uso.cupom.descricao,
            tipo=uso.cupom.tipo,
            valor=_formatar_valor_cupom(uso.cupom),
            validade=_formatar_validade(uso.cupom),
            pedido=f"Pedido nº {uso.pedido.numero}" if uso.pedido else "Pedido não encontrado",
        )
        for uso in usos
    ]

    return CuponsResponse(ativos=ativos, usados=usados)


@router.post("/validar", response_model=ValidarCupomResponse)
def validar_cupom(
    data: ValidarCupomRequest,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
):
    cupom = db.query(Cupom).filter(
        Cupom.codigo == data.codigo.upper(),
        Cupom.ativo.is_(True),
    ).first()

    if not cupom:
        return ValidarCupomResponse(valido=False, mensagem="Cupom não encontrado ou inativo.")

    if cupom.validade < date.today():
        return ValidarCupomResponse(valido=False, mensagem="Cupom expirado.")

    if data.total_pedido < cupom.valor_minimo_pedido:
        return ValidarCupomResponse(
            valido=False,
            mensagem=f"Pedido mínimo de {formatar_preco(cupom.valor_minimo_pedido)} para este cupom.",
        )

    if cupom.max_usos is not None and cupom.total_usos >= cupom.max_usos:
        return ValidarCupomResponse(valido=False, mensagem="Cupom esgotado.")

    ja_usado = db.query(CupomUsado).filter(
        CupomUsado.cupom_id == cupom.id,
        CupomUsado.usuario_id == current_user.id,
    ).first()
    if ja_usado:
        return ValidarCupomResponse(valido=False, mensagem="Cupom já utilizado.")

    if cupom.tipo == "porcentagem":
        valor_desconto = round(data.total_pedido * (cupom.valor / 100), 2)
        mensagem = f"Cupom aplicado: {int(cupom.valor)}% de desconto"
    elif cupom.tipo == "valor":
        valor_desconto = min(cupom.valor, data.total_pedido)
        mensagem = f"Cupom aplicado: {formatar_preco(cupom.valor)} de desconto"
    elif cupom.tipo == "frete":
        valor_desconto = max(data.valor_frete, 0.0)
        mensagem = "Cupom aplicado: Frete grátis"
    else:
        valor_desconto = 0.0
        mensagem = "Cupom aplicado."

    return ValidarCupomResponse(
        valido=True,
        tipo=cupom.tipo,
        valor_desconto=valor_desconto,
        mensagem=mensagem,
    )

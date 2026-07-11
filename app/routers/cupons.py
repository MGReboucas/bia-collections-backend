from fastapi import APIRouter, Depends, HTTPException
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
from app.services.cupom_service import (
    descricao_desconto,
    hoje_sao_paulo,
    resposta_validacao_invalida,
    validar_cupom_para_total,
)
from app.services.frete_service import formatar_preco

router = APIRouter(prefix="/cupons", tags=["cupons"])


def _formatar_valor_cupom(cupom: Cupom) -> str:
    if cupom.tipo == "porcentagem":
        return f"{int(cupom.valor)}%"
    if cupom.tipo == "frete":
        return "Frete gratis"
    return formatar_preco(cupom.valor)


@router.get("", response_model=CuponsResponse)
def listar_cupons(
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
):
    hoje = hoje_sao_paulo()

    usados_ids = {
        row.cupom_id
        for row in db.query(CupomUsado.cupom_id)
        .filter(CupomUsado.usuario_id == current_user.id)
        .all()
    }

    ativos_query = db.query(Cupom).filter(
        Cupom.ativo.is_(True),
        Cupom.deletado_em.is_(None),
        Cupom.validade >= hoje,
        (Cupom.max_usos.is_(None)) | (Cupom.total_usos < Cupom.max_usos),
    )
    if usados_ids:
        ativos_query = ativos_query.filter(~Cupom.id.in_(usados_ids))

    ativos: List[CupomAtivo] = [
        CupomAtivo(
            codigo=c.codigo,
            descricao=c.descricao,
            tipo=c.tipo,
            valor=_formatar_valor_cupom(c),
            validade=c.validade.isoformat(),
        )
        for c in ativos_query.order_by(Cupom.validade.asc()).all()
    ]

    usos = (
        db.query(CupomUsado)
        .options(joinedload(CupomUsado.cupom), joinedload(CupomUsado.pedido))
        .filter(CupomUsado.usuario_id == current_user.id)
        .order_by(CupomUsado.usado_em.desc())
        .all()
    )
    usados: List[CupomUsadoResponse] = [
        CupomUsadoResponse(
            codigo=uso.cupom.codigo,
            descricao=uso.cupom.descricao,
            tipo=uso.cupom.tipo,
            valor=_formatar_valor_cupom(uso.cupom),
            pedido=f"Pedido {uso.pedido.numero}" if uso.pedido else "Pedido nao encontrado",
            usado_em=uso.usado_em.isoformat() if uso.usado_em else "",
        )
        for uso in usos
        if uso.cupom
    ]

    return CuponsResponse(ativos=ativos, usados=usados)


@router.post("/validar", response_model=ValidarCupomResponse)
def validar_cupom(
    data: ValidarCupomRequest,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
):
    try:
        cupom, valor_desconto = validar_cupom_para_total(
            db=db,
            usuario=current_user,
            codigo=data.codigo,
            total=data.total,
            valor_frete=data.valor_frete,
        )
    except HTTPException as exc:
        return ValidarCupomResponse(**resposta_validacao_invalida(data.codigo, str(exc.detail)))

    total_com_desconto = round(max(data.total - valor_desconto, 0.0), 2)
    return ValidarCupomResponse(
        valido=True,
        codigo=cupom.codigo,
        descricao=cupom.descricao,
        tipo=cupom.tipo,
        valor_desconto=valor_desconto,
        desconto_formatado=formatar_preco(valor_desconto),
        total_com_desconto=total_com_desconto,
        total_formatado=formatar_preco(total_com_desconto),
        mensagem=f"Cupom aplicado: {descricao_desconto(cupom, valor_desconto)}",
    )

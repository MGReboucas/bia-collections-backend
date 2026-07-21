from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, joinedload
from typing import List

from app.database import get_db
from app.dependencies import get_current_user, is_user_active
from app.models.usuario import Usuario
from app.models.cupom import Cupom, CupomResgatado, CupomUsado
from app.schemas.cupom import (
    CuponsResponse,
    ValidarCupomRequest,
    ValidarCupomResponse,
    CupomAtivo,
    CupomUsadoResponse,
    AdicionarCupomRequest,
    AdicionarCupomResponse,
)
from app.services.cupom_service import (
    resposta_validacao_invalida,
    validar_cupom_para_total,
    cupom_disponivel,
    normalizar_codigo_cupom,
)
from app.services.frete_service import formatar_preco
from app.modules.email.service import trigger_coupon_available_email_event

router = APIRouter(prefix="/cupons", tags=["cupons"])


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
    usados_ids = {
        row.cupom_id
        for row in db.query(CupomUsado.cupom_id)
        .filter(CupomUsado.usuario_id == current_user.id)
        .all()
    }

    resgates = (
        db.query(CupomResgatado)
        .options(joinedload(CupomResgatado.cupom))
        .filter(CupomResgatado.usuario_id == current_user.id)
        .order_by(CupomResgatado.resgatado_em.desc())
        .all()
    )

    ativos: List[CupomAtivo] = [
        CupomAtivo(
            codigo=resgate.cupom.codigo,
            descricao=resgate.cupom.descricao,
            tipo=resgate.cupom.tipo,
            valor=_formatar_valor_cupom(resgate.cupom),
            validade=resgate.cupom.validade.isoformat(),
            valor_minimo_pedido=resgate.cupom.valor_minimo_pedido or 0.0,
            resgatado_em=resgate.resgatado_em.isoformat() if resgate.resgatado_em else None,
        )
        for resgate in resgates
        if resgate.cupom
        and resgate.cupom.id not in usados_ids
        and cupom_disponivel(resgate.cupom)
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


@router.post("/adicionar", response_model=AdicionarCupomResponse)
def adicionar_cupom_a_conta(
    data: AdicionarCupomRequest,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
):
    if not is_user_active(current_user):
        raise HTTPException(status_code=403, detail="Sua conta precisa estar ativa para adicionar cupons.")

    codigo = normalizar_codigo_cupom(data.codigo)
    cupom = (
        db.query(Cupom)
        .filter(Cupom.codigo == codigo, Cupom.deletado_em.is_(None))
        .first()
    )
    if not cupom or not cupom_disponivel(cupom):
        raise HTTPException(status_code=422, detail="Cupom inexistente, inativo, expirado ou esgotado.")

    ja_usado = (
        db.query(CupomUsado)
        .filter(CupomUsado.cupom_id == cupom.id, CupomUsado.usuario_id == current_user.id)
        .first()
    )
    if ja_usado:
        raise HTTPException(status_code=409, detail="Este cupom já foi utilizado por sua conta.")

    existente = (
        db.query(CupomResgatado)
        .filter(
            CupomResgatado.cupom_id == cupom.id,
            CupomResgatado.usuario_id == current_user.id,
        )
        .first()
    )
    ja_adicionado = existente is not None

    if not existente:
        existente = CupomResgatado(cupom_id=cupom.id, usuario_id=current_user.id)
        db.add(existente)
        try:
            db.commit()
        except IntegrityError as exc:
            db.rollback()
            existente = (
                db.query(CupomResgatado)
                .filter(
                    CupomResgatado.cupom_id == cupom.id,
                    CupomResgatado.usuario_id == current_user.id,
                )
                .first()
            )
            if not existente:
                raise HTTPException(
                    status_code=409,
                    detail="Não foi possível adicionar este cupom à sua conta.",
                ) from exc
            ja_adicionado = True
        else:
            db.refresh(existente)
            trigger_coupon_available_email_event(db, cupom, current_user)

    return AdicionarCupomResponse(
        mensagem="Cupom já estava na sua conta." if ja_adicionado else "Cupom adicionado à sua conta.",
        ja_adicionado=ja_adicionado,
        cupom=CupomAtivo(
            codigo=cupom.codigo,
            descricao=cupom.descricao,
            tipo=cupom.tipo,
            valor=_formatar_valor_cupom(cupom),
            validade=cupom.validade.isoformat(),
            valor_minimo_pedido=cupom.valor_minimo_pedido or 0.0,
            resgatado_em=existente.resgatado_em.isoformat() if existente.resgatado_em else None,
        ),
    )


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
        mensagem="Cupom aplicado com sucesso.",
    )

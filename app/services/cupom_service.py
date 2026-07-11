from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import HTTPException
from sqlalchemy import or_, update
from sqlalchemy.orm import Session

from app.models.cupom import Cupom, CupomUsado
from app.models.pedido import Pedido
from app.models.usuario import Usuario
from app.services.frete_service import formatar_preco

try:
    SAO_PAULO_TZ = ZoneInfo("America/Sao_Paulo")
except ZoneInfoNotFoundError:
    SAO_PAULO_TZ = timezone(timedelta(hours=-3), name="America/Sao_Paulo")


def hoje_sao_paulo() -> date:
    return datetime.now(SAO_PAULO_TZ).date()


def normalizar_codigo_cupom(codigo: str | None) -> str:
    return (codigo or "").strip().upper()


def cupom_expirado(cupom: Cupom) -> bool:
    return cupom.validade < hoje_sao_paulo()


def cupom_disponivel(cupom: Cupom) -> bool:
    if not cupom.ativo:
        return False
    if cupom.deletado_em is not None:
        return False
    if cupom_expirado(cupom):
        return False
    if cupom.max_usos is not None and (cupom.total_usos or 0) >= cupom.max_usos:
        return False
    return True


def calcular_desconto_cupom(cupom: Cupom, total: float, valor_frete: float = 0.0) -> float:
    total = round(max(total or 0.0, 0.0), 2)
    valor_frete = round(max(valor_frete or 0.0, 0.0), 2)

    if cupom.tipo == "porcentagem":
        return round(total * (cupom.valor / 100), 2)
    if cupom.tipo == "valor":
        return round(min(cupom.valor, total), 2)
    if cupom.tipo == "frete":
        return round(min(valor_frete, total), 2)
    return 0.0


def descricao_desconto(cupom: Cupom, valor_desconto: float) -> str:
    if cupom.tipo == "porcentagem":
        return f"{int(cupom.valor)}% de desconto"
    if cupom.tipo == "frete":
        return "Frete gratis"
    return f"{formatar_preco(valor_desconto)} de desconto"


def validar_cupom_para_total(
    db: Session,
    usuario: Usuario,
    codigo: str,
    total: float,
    valor_frete: float = 0.0,
    impedir_reuso_usuario: bool = True,
) -> tuple[Cupom, float]:
    codigo_normalizado = normalizar_codigo_cupom(codigo)
    if not codigo_normalizado:
        raise HTTPException(status_code=422, detail="Codigo do cupom e obrigatorio.")

    cupom = (
        db.query(Cupom)
        .filter(Cupom.codigo == codigo_normalizado, Cupom.deletado_em.is_(None))
        .first()
    )
    if not cupom or not cupom.ativo:
        raise HTTPException(status_code=422, detail="Cupom inexistente ou inativo.")
    if cupom_expirado(cupom):
        raise HTTPException(status_code=422, detail="Cupom expirado.")
    if cupom.max_usos is not None and (cupom.total_usos or 0) >= cupom.max_usos:
        raise HTTPException(status_code=422, detail="Cupom esgotado.")
    if total < (cupom.valor_minimo_pedido or 0.0):
        raise HTTPException(
            status_code=422,
            detail=f"Pedido minimo de {formatar_preco(cupom.valor_minimo_pedido or 0.0)} para este cupom.",
        )

    if impedir_reuso_usuario:
        ja_usado = (
            db.query(CupomUsado)
            .filter(CupomUsado.cupom_id == cupom.id, CupomUsado.usuario_id == usuario.id)
            .first()
        )
        if ja_usado:
            raise HTTPException(status_code=422, detail="Cupom ja utilizado.")

    return cupom, calcular_desconto_cupom(cupom, total, valor_frete)


def reservar_uso_cupom(db: Session, cupom: Cupom) -> None:
    result = db.execute(
        update(Cupom)
        .where(
            Cupom.id == cupom.id,
            Cupom.ativo.is_(True),
            Cupom.deletado_em.is_(None),
            or_(Cupom.max_usos.is_(None), Cupom.total_usos < Cupom.max_usos),
        )
        .values(total_usos=Cupom.total_usos + 1)
    )
    if result.rowcount != 1:
        raise HTTPException(status_code=409, detail="Cupom esgotado.")
    db.refresh(cupom)


def registrar_cupom_usado(
    db: Session,
    *,
    cupom: Cupom,
    usuario: Usuario,
    pedido: Pedido,
) -> None:
    exists = (
        db.query(CupomUsado)
        .filter(
            CupomUsado.cupom_id == cupom.id,
            CupomUsado.usuario_id == usuario.id,
            CupomUsado.pedido_id == pedido.id,
        )
        .first()
    )
    if exists:
        return
    db.add(CupomUsado(cupom_id=cupom.id, usuario_id=usuario.id, pedido_id=pedido.id))


def resposta_validacao_invalida(codigo: str, mensagem: str) -> dict:
    return {
        "valido": False,
        "codigo": normalizar_codigo_cupom(codigo),
        "descricao": mensagem,
        "tipo": "",
        "valor_desconto": 0.0,
        "desconto_formatado": formatar_preco(0.0),
        "total_com_desconto": 0.0,
        "total_formatado": formatar_preco(0.0),
        "mensagem": mensagem,
    }

from sqlalchemy.orm import Session

from app.models.pedido import Pedido


def gerar_numero_pedido(db: Session) -> str:
    """Gera número de pedido sequencial com zero-padding de 7 dígitos."""
    ultimo = db.query(Pedido).order_by(Pedido.id.desc()).first()
    if ultimo is None:
        proximo = 1
    else:
        try:
            proximo = int(ultimo.numero) + 1
        except (ValueError, TypeError):
            proximo = db.query(Pedido).count() + 1
    return str(proximo).zfill(7)

from sqlalchemy import Column, Integer, String, Float, DateTime, ForeignKey
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.database import Base


class Pagamento(Base):
    __tablename__ = "pagamentos"

    id = Column(Integer, primary_key=True, index=True)
    pedido_numero = Column(String(20), ForeignKey("pedidos.numero"), nullable=False, index=True)
    tipo = Column(String(30), nullable=False, default="pix")  # pix | checkout_pro
    valor = Column(Float, nullable=True)
    idempotency_key = Column(String(120), nullable=True, index=True)
    # PIX
    mp_payment_id = Column(String(100), nullable=True, index=True)
    mp_order_id = Column(String(100), nullable=True, index=True)
    pix_qr_code = Column(String(2000), nullable=True)       # copia-e-cola
    pix_qr_code_base64 = Column(String(5000), nullable=True)  # imagem
    pix_expiracao = Column(DateTime(timezone=True), nullable=True)
    # Checkout Pro (cartão/boleto)
    mp_preference_id = Column(String(100), nullable=True)
    checkout_url = Column(String(500), nullable=True)       # sandbox
    checkout_url_prod = Column(String(500), nullable=True)  # produção
    # Status
    status = Column(String(50), default="pendente")  # pendente | aprovado | recusado | cancelado
    mp_status = Column(String(50), nullable=True)
    criado_em = Column(DateTime(timezone=True), server_default=func.now())
    atualizado_em = Column(DateTime(timezone=True), onupdate=func.now())

    pedido = relationship("Pedido", backref="pagamento")

from sqlalchemy import Column, Integer, String, Float, Boolean, Date, DateTime, ForeignKey
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.database import Base


class Cupom(Base):
    __tablename__ = "cupons"

    id = Column(Integer, primary_key=True, index=True)
    codigo = Column(String(50), unique=True, nullable=False, index=True)
    descricao = Column(String(255), nullable=False)
    tipo = Column(String(20), nullable=False)  # 'porcentagem' | 'valor' | 'frete'
    valor = Column(Float, nullable=False)
    validade = Column(Date, nullable=False)
    ativo = Column(Boolean, default=True)
    valor_minimo_pedido = Column(Float, default=0.0)
    max_usos = Column(Integer, nullable=True)
    total_usos = Column(Integer, default=0, nullable=False)

    usos = relationship("CupomUsado", back_populates="cupom")


class CupomUsado(Base):
    __tablename__ = "cupons_usados"

    id = Column(Integer, primary_key=True, index=True)
    cupom_id = Column(Integer, ForeignKey("cupons.id"), nullable=False, index=True)
    usuario_id = Column(Integer, ForeignKey("usuarios.id"), nullable=False, index=True)
    pedido_id = Column(Integer, ForeignKey("pedidos.id"), nullable=False, index=True)
    usado_em = Column(DateTime(timezone=True), server_default=func.now())

    cupom = relationship("Cupom", back_populates="usos")
    usuario = relationship("Usuario", back_populates="cupons_usados")
    pedido = relationship("Pedido", back_populates="cupons_usados")

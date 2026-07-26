from sqlalchemy import Column, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.database import Base


class SolicitacaoPosVenda(Base):
    __tablename__ = "solicitacoes_pos_venda"
    __table_args__ = (
        UniqueConstraint("protocolo", name="uq_solicitacoes_pos_venda_protocolo"),
    )

    id = Column(Integer, primary_key=True, index=True)
    protocolo = Column(String(40), nullable=False, unique=True, index=True)
    pedido_id = Column(Integer, ForeignKey("pedidos.id"), nullable=False, index=True)
    usuario_id = Column(Integer, ForeignKey("usuarios.id"), nullable=False, index=True)
    tipo = Column(String(20), nullable=False)
    motivo = Column(Text, nullable=False)
    status = Column(String(20), nullable=False, default="recebida", index=True)
    motivo_recusa = Column(Text, nullable=True)
    criado_em = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    atualizado_em = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    pedido = relationship("Pedido", back_populates="solicitacoes_pos_venda")
    usuario = relationship("Usuario")


class DocumentoPedido(Base):
    __tablename__ = "documentos_pedido"
    __table_args__ = (
        UniqueConstraint("pedido_id", "tipo", name="uq_documentos_pedido_tipo"),
    )

    id = Column(Integer, primary_key=True, index=True)
    pedido_id = Column(Integer, ForeignKey("pedidos.id"), nullable=False, index=True)
    tipo = Column(String(20), nullable=False)
    numero = Column(String(80), nullable=True)
    url = Column(String(1000), nullable=False)
    criado_em = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    pedido = relationship("Pedido", back_populates="documentos")


class ReembolsoPedido(Base):
    __tablename__ = "reembolsos_pedido"

    id = Column(Integer, primary_key=True, index=True)
    pedido_id = Column(Integer, ForeignKey("pedidos.id"), nullable=False, index=True)
    status = Column(String(20), nullable=False, default="aprovado", index=True)
    valor = Column(Float, nullable=False)
    prazo_dias_uteis = Column(Integer, nullable=True)
    criado_em = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    atualizado_em = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    pedido = relationship("Pedido", back_populates="reembolsos")

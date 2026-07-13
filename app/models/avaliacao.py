from sqlalchemy import Boolean, Column, Integer, String, Text, DateTime, ForeignKey, UniqueConstraint
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.database import Base


class Avaliacao(Base):
    __tablename__ = "avaliacoes"
    __table_args__ = (
        UniqueConstraint(
            "produto_id",
            "usuario_id",
            "pedido_id",
            name="uq_avaliacoes_produto_usuario_pedido",
        ),
    )

    id = Column(Integer, primary_key=True, index=True)
    produto_id = Column(Integer, ForeignKey("produtos.id"), nullable=False, index=True)
    usuario_id = Column(Integer, ForeignKey("usuarios.id"), nullable=False, index=True)
    pedido_id = Column(Integer, ForeignKey("pedidos.id"), nullable=True, index=True)
    pedido_numero = Column(String(20), nullable=True, index=True)
    nota = Column(Integer, nullable=False)  # 1-5
    comentario = Column(Text, nullable=True)
    status = Column(String(20), default="pendente")  # pendente | aprovada | reprovada
    mostrar_home = Column(Boolean, nullable=False, default=False, server_default="0")
    criado_em = Column(DateTime(timezone=True), server_default=func.now())
    atualizado_em = Column(DateTime(timezone=True), onupdate=func.now(), nullable=True)

    produto = relationship("Produto", back_populates="avaliacoes")
    usuario = relationship("Usuario", back_populates="avaliacoes")
    pedido = relationship("Pedido", back_populates="avaliacoes")
    fotos = relationship(
        "AvaliacaoFoto",
        back_populates="avaliacao",
        cascade="all, delete-orphan",
        order_by="AvaliacaoFoto.ordem",
    )


class AvaliacaoFoto(Base):
    __tablename__ = "avaliacao_fotos"

    id = Column(Integer, primary_key=True, index=True)
    avaliacao_id = Column(
        Integer,
        ForeignKey("avaliacoes.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    imagem_url = Column(String(500), nullable=False)
    ordem = Column(Integer, nullable=False, default=0)
    criado_em = Column(DateTime(timezone=True), server_default=func.now())

    avaliacao = relationship("Avaliacao", back_populates="fotos")

from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.database import Base


class Avaliacao(Base):
    __tablename__ = "avaliacoes"

    id = Column(Integer, primary_key=True, index=True)
    produto_id = Column(Integer, ForeignKey("produtos.id"), nullable=False, index=True)
    usuario_id = Column(Integer, ForeignKey("usuarios.id"), nullable=False, index=True)
    nota = Column(Integer, nullable=False)  # 1-5
    comentario = Column(Text, nullable=True)
    status = Column(String(20), default="pendente")  # pendente | aprovada | reprovada
    criado_em = Column(DateTime(timezone=True), server_default=func.now())

    produto = relationship("Produto", back_populates="avaliacoes")
    usuario = relationship("Usuario", back_populates="avaliacoes")

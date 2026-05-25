from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.database import Base


class Duvida(Base):
    __tablename__ = "duvidas"

    id = Column(Integer, primary_key=True, index=True)
    usuario_id = Column(Integer, ForeignKey("usuarios.id"), nullable=False)
    produto_id = Column(Integer, nullable=True)
    produto_nome = Column(String(255), nullable=True)
    pergunta = Column(Text, nullable=False)
    resposta = Column(Text, nullable=True)
    status = Column(String(20), default="pendente")  # pendente | respondida
    criado_em = Column(DateTime(timezone=True), server_default=func.now())
    respondida_em = Column(DateTime(timezone=True), nullable=True)

    usuario = relationship("Usuario", back_populates="duvidas")

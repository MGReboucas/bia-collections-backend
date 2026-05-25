from sqlalchemy import Column, Integer, String, DateTime
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.database import Base


class Usuario(Base):
    __tablename__ = "usuarios"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String(100), unique=True, index=True, nullable=False)
    email = Column(String(255), unique=True, index=True, nullable=False)
    senha_hash = Column(String(255), nullable=False)
    nome_completo = Column(String(255), nullable=True)
    telefone = Column(String(20), nullable=True)
    foto_url = Column(String(500), nullable=True)
    criado_em = Column(DateTime(timezone=True), server_default=func.now())

    pedidos = relationship("Pedido", back_populates="usuario")
    enderecos = relationship("Endereco", back_populates="usuario")
    cupons_usados = relationship("CupomUsado", back_populates="usuario")
    duvidas = relationship("Duvida", back_populates="usuario")

from sqlalchemy import Boolean, Column, DateTime, Integer, String
from sqlalchemy.sql import func

from app.database import Base


class Banner(Base):
    __tablename__ = "banners"

    id = Column(Integer, primary_key=True, index=True)
    titulo = Column(String(255), nullable=False)
    imagem_url = Column(String(500), nullable=False)
    link = Column(String(500), nullable=True)
    ativo = Column(Boolean, default=True, nullable=False)
    ordem = Column(Integer, default=0, nullable=False)
    criado_em = Column(DateTime(timezone=True), server_default=func.now())
    atualizado_em = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

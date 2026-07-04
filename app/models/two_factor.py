from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.database import Base


class TwoFactorChallenge(Base):
    __tablename__ = "login_2fa_challenges"

    id = Column(Integer, primary_key=True, index=True)
    usuario_id = Column(Integer, ForeignKey("usuarios.id"), nullable=False, index=True)
    token_hash = Column(String(64), unique=True, nullable=False, index=True)
    codigo_hash = Column(String(255), nullable=False)
    expira_em = Column(DateTime(timezone=True), nullable=False, index=True)
    usado = Column(Boolean, nullable=False, default=False, server_default="0")
    tentativas = Column(Integer, nullable=False, default=0, server_default="0")
    ultimo_envio_em = Column(DateTime(timezone=True), nullable=False)
    reenvio_janela_inicio = Column(DateTime(timezone=True), nullable=False)
    reenvios_na_janela = Column(Integer, nullable=False, default=0, server_default="0")
    criado_em = Column(DateTime(timezone=True), server_default=func.now())
    atualizado_em = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    usuario = relationship("Usuario", back_populates="desafios_2fa")

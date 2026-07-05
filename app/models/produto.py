from sqlalchemy import Column, Integer, String, Float, Boolean, DateTime, ForeignKey, Text
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.database import Base


class Categoria(Base):
    __tablename__ = "categorias"

    id = Column(Integer, primary_key=True, index=True)
    nome = Column(String(100), nullable=False, unique=True)
    imagem_url = Column(String(500), nullable=True)

    produtos = relationship("Produto", back_populates="categoria")


class Produto(Base):
    __tablename__ = "produtos"

    id = Column(Integer, primary_key=True, index=True)
    nome = Column(String(255), nullable=False)
    descricao = Column(Text, nullable=True)
    preco = Column(Float, nullable=False)
    categoria_id = Column(Integer, ForeignKey("categorias.id"), nullable=True, index=True)
    imagem_url = Column(String(500), nullable=True)
    tamanhos = Column(String(500), default="[]")  # JSON serialized list
    cores = Column(String(500), default="[]")      # JSON serialized list
    preco_promocional = Column(Float, nullable=True)
    estoque = Column(Integer, nullable=True)
    ativo = Column(Boolean, default=True)
    criado_em = Column(DateTime(timezone=True), server_default=func.now())

    categoria = relationship("Categoria", back_populates="produtos")
    itens_pedido = relationship("ItemPedido", back_populates="produto")
    avaliacoes = relationship("Avaliacao", back_populates="produto")
    imagens = relationship(
        "ProdutoImagem",
        back_populates="produto",
        cascade="all, delete-orphan",
    )


class ProdutoImagem(Base):
    __tablename__ = "produto_imagens"

    id = Column(Integer, primary_key=True, index=True)
    produto_id = Column(
        Integer,
        ForeignKey("produtos.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    imagem_url = Column(String(500), nullable=False)
    ordem = Column(Integer, nullable=False, default=0)
    principal = Column(Boolean, nullable=False, default=False)
    criado_em = Column(DateTime(timezone=True), server_default=func.now())

    produto = relationship("Produto", back_populates="imagens")

from sqlalchemy import Column, Integer, String, Float, DateTime, ForeignKey
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.database import Base


class Pedido(Base):
    __tablename__ = "pedidos"

    id = Column(Integer, primary_key=True, index=True)
    numero = Column(String(20), unique=True, nullable=False, index=True)
    usuario_id = Column(Integer, ForeignKey("usuarios.id"), nullable=False, index=True)
    status = Column(String(50), default="Aguardando pagamento")
    forma_pagamento = Column(String(50), nullable=False)
    subtotal = Column(Float, nullable=True)
    valor_frete = Column(Float, nullable=False, default=0.0)
    tipo_frete = Column(String(50), nullable=True)
    prazo_frete = Column(String(100), nullable=True)
    total = Column(Float, nullable=False)
    # Endereço snapshot
    endereco_cep = Column(String(20))
    endereco_rua = Column(String(255))
    endereco_numero = Column(String(20))
    endereco_complemento = Column(String(100), nullable=True)
    endereco_bairro = Column(String(100))
    endereco_cidade = Column(String(100))
    endereco_estado = Column(String(2))
    cupom_codigo = Column(String(50), nullable=True)
    desconto_aplicado = Column(Float, default=0.0)
    codigo_rastreio = Column(String(100), nullable=True)
    criado_em = Column(DateTime(timezone=True), server_default=func.now())

    usuario = relationship("Usuario", back_populates="pedidos")
    itens = relationship("ItemPedido", back_populates="pedido")
    cupons_usados = relationship("CupomUsado", back_populates="pedido")


class ItemPedido(Base):
    __tablename__ = "itens_pedido"

    id = Column(Integer, primary_key=True, index=True)
    pedido_id = Column(Integer, ForeignKey("pedidos.id"), nullable=False, index=True)
    produto_id = Column(Integer, ForeignKey("produtos.id"), nullable=False, index=True)
    nome_produto = Column(String(255), nullable=False)
    preco_unitario = Column(Float, nullable=False)
    tamanho = Column(String(20), nullable=True)
    cor = Column(String(50), nullable=True)
    quantidade = Column(Integer, nullable=False, default=1)

    pedido = relationship("Pedido", back_populates="itens")
    produto = relationship("Produto", back_populates="itens_pedido")

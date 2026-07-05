from pydantic import BaseModel, Field
from typing import Optional, List


class ProdutoImagemOut(BaseModel):
    id: int
    imagem_url: str
    ordem: int
    principal: bool

    model_config = {"from_attributes": True}


class ProdutoListItem(BaseModel):
    id: int
    nome: str
    preco: float
    preco_formatado: str
    preco_promocional: Optional[float] = None
    estoque: Optional[int] = None
    categoria: Optional[str] = None
    imagem_url: Optional[str] = None
    imagens: List[ProdutoImagemOut] = Field(default_factory=list)
    tamanhos: List[str] = Field(default_factory=list)
    cores: List[str] = Field(default_factory=list)


class ProdutoDetalhe(BaseModel):
    id: int
    nome: str
    descricao: Optional[str] = None
    preco: float
    preco_formatado: str
    preco_promocional: Optional[float] = None
    estoque: Optional[int] = None
    categoria: Optional[str] = None
    imagem_url: Optional[str] = None
    imagens: List[ProdutoImagemOut] = Field(default_factory=list)
    tamanhos: List[str] = Field(default_factory=list)
    cores: List[str] = Field(default_factory=list)


class ProdutoListResponse(BaseModel):
    total: int
    page: int
    limit: int
    itens: List[ProdutoListItem]

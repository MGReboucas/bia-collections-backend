from pydantic import BaseModel
from typing import Optional, List


class ProdutoListItem(BaseModel):
    id: int
    nome: str
    preco: float
    preco_formatado: str
    preco_promocional: Optional[float] = None
    estoque: Optional[int] = None
    categoria: Optional[str] = None
    imagem_url: Optional[str] = None
    tamanhos: List[str] = []
    cores: List[str] = []


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
    tamanhos: List[str] = []
    cores: List[str] = []


class ProdutoListResponse(BaseModel):
    total: int
    page: int
    limit: int
    itens: List[ProdutoListItem]

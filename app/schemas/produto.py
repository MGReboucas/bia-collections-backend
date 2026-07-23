from pydantic import BaseModel, Field, model_validator
from typing import Optional, List


class ProdutoImagemOut(BaseModel):
    id: int
    imagem_url: str
    url: Optional[str] = None
    ordem: int
    principal: bool
    capa: Optional[bool] = None
    modelo_nome: Optional[str] = None
    modelo_cor: Optional[str] = None
    cor_nome: Optional[str] = None
    modelo: Optional[str] = None
    cor: Optional[str] = None

    @model_validator(mode="after")
    def preencher_aliases(self):
        if self.url is None:
            self.url = self.imagem_url
        if self.capa is None:
            self.capa = self.principal
        if self.modelo is None:
            self.modelo = self.modelo_nome
        if self.cor is None:
            self.cor = self.cor_nome or self.modelo_cor
        return self

    model_config = {"from_attributes": True}


class ProdutoListItem(BaseModel):
    id: int
    nome: str
    preco: float
    preco_formatado: str
    preco_promocional: Optional[float] = None
    estoque: Optional[int] = None
    ativo: bool
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
    ativo: bool
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

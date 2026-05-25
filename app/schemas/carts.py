from pydantic import BaseModel
from typing import List, Optional
from datetime import datetime


class CartItemResponse(BaseModel):
    id: int
    product_id: int
    nome_produto: str
    quantidade: int
    preco_unitario: float


class CartResponse(BaseModel):
    cart_id: Optional[int] = None
    items: List[CartItemResponse] = []
    total: float = 0.0

from pydantic import BaseModel
from typing import Optional
from datetime import datetime


class ProductVariationResponse(BaseModel):
    id: int
    product_id: Optional[int] = None
    nome_variacao: Optional[str] = None
    preco_adicional: float = 0.0
    estoque: int = 0
    created_at: Optional[datetime] = None

    model_config = {"from_attributes": True}

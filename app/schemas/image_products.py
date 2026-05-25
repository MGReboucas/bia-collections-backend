from pydantic import BaseModel
from typing import Optional
from datetime import datetime


class ImageProductResponse(BaseModel):
    id: int
    product_id: Optional[int] = None
    url: str
    created_at: Optional[datetime] = None

    model_config = {"from_attributes": True}

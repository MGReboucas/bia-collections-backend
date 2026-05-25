from pydantic import BaseModel


class CartItemAdd(BaseModel):
    product_id: int
    quantidade: int = 1

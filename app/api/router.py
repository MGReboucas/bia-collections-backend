from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import List, Optional

from app.core.dependences import get_db, get_current_user
from app.core.security import verify_password, get_password_hash, create_access_token
from app.models.model import Client, Product, Category, Cart, CartItem, Address
from app.schemas.client import ClientRegister, ClientLogin, ClientResponse, TokenResponse
from app.schemas.products import ProductBase
from app.schemas.categories import CategoryBase
from app.schemas.addresses import AddressCreate, AddressResponse
from app.schemas.carts import CartResponse, CartItemResponse
from app.schemas.carts_itens import CartItemAdd

router = APIRouter()


# ── Auth ──────────────────────────────────────────────────────────────────────

@router.post("/auth/register", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
def register(data: ClientRegister, db: Session = Depends(get_db)):
    if db.query(Client).filter(Client.email == data.email).first():
        raise HTTPException(status_code=400, detail="Email já cadastrado")
    if db.query(Client).filter(Client.cpf == data.cpf).first():
        raise HTTPException(status_code=400, detail="CPF já cadastrado")

    client = Client(
        nome_cliente=data.nome_cliente,
        email=data.email,
        telefone=data.telefone,
        cpf=data.cpf,
        senha_hash=get_password_hash(data.senha),
        aceitou_politica_privacidade=data.aceitou_politica_privacidade,
        aceitou_termos_uso=data.aceitou_termos_uso,
    )
    db.add(client)
    db.commit()
    db.refresh(client)

    token = create_access_token({"sub": str(client.id)})
    return TokenResponse(access_token=token, client=ClientResponse.model_validate(client))


@router.post("/auth/login", response_model=TokenResponse)
def login(data: ClientLogin, db: Session = Depends(get_db)):
    client = db.query(Client).filter(Client.email == data.email).first()
    if not client or not verify_password(data.senha, client.senha_hash):
        raise HTTPException(status_code=401, detail="Email ou senha inválidos")

    token = create_access_token({"sub": str(client.id)})
    return TokenResponse(access_token=token, client=ClientResponse.model_validate(client))


# ── Current user ──────────────────────────────────────────────────────────────

@router.get("/me", response_model=ClientResponse)
def get_profile(current_user: Client = Depends(get_current_user)):
    return current_user


# ── Products ──────────────────────────────────────────────────────────────────

@router.get("/products", response_model=List[ProductBase])
def list_products(category_id: Optional[int] = None, db: Session = Depends(get_db)):
    query = db.query(Product)
    if category_id:
        query = query.filter(Product.categoria_id == category_id)
    return query.all()


@router.get("/products/{product_id}", response_model=ProductBase)
def get_product(product_id: int, db: Session = Depends(get_db)):
    product = db.query(Product).filter(Product.id == product_id).first()
    if not product:
        raise HTTPException(status_code=404, detail="Produto não encontrado")
    return product


# ── Categories ────────────────────────────────────────────────────────────────

@router.get("/categories", response_model=List[CategoryBase])
def list_categories(db: Session = Depends(get_db)):
    return db.query(Category).all()


# ── Cart ──────────────────────────────────────────────────────────────────────

@router.get("/cart", response_model=CartResponse)
def get_cart(current_user: Client = Depends(get_current_user), db: Session = Depends(get_db)):
    cart = db.query(Cart).filter(Cart.client_id == current_user.id, Cart.status == "open").first()
    if not cart:
        return CartResponse()

    items = [
        CartItemResponse(
            id=item.id,
            product_id=item.product_id,
            nome_produto=item.product.nome_produto,
            quantidade=item.quantidade,
            preco_unitario=item.preco_unitario,
        )
        for item in cart.items
    ]
    total = sum(i.quantidade * i.preco_unitario for i in cart.items)
    return CartResponse(cart_id=cart.id, items=items, total=total)


@router.post("/cart/items", status_code=status.HTTP_201_CREATED)
def add_to_cart(body: CartItemAdd, current_user: Client = Depends(get_current_user), db: Session = Depends(get_db)):
    product = db.query(Product).filter(Product.id == body.product_id).first()
    if not product:
        raise HTTPException(status_code=404, detail="Produto não encontrado")

    cart = db.query(Cart).filter(Cart.client_id == current_user.id, Cart.status == "open").first()
    if not cart:
        cart = Cart(client_id=current_user.id)
        db.add(cart)
        db.commit()
        db.refresh(cart)

    existing = db.query(CartItem).filter(CartItem.cart_id == cart.id, CartItem.product_id == body.product_id).first()
    if existing:
        existing.quantidade += body.quantidade
    else:
        db.add(CartItem(cart_id=cart.id, product_id=body.product_id, quantidade=body.quantidade, preco_unitario=product.preco))
    db.commit()
    return {"message": "Item adicionado ao carrinho"}


@router.delete("/cart/items/{item_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_from_cart(item_id: int, current_user: Client = Depends(get_current_user), db: Session = Depends(get_db)):
    cart = db.query(Cart).filter(Cart.client_id == current_user.id, Cart.status == "open").first()
    if not cart:
        raise HTTPException(status_code=404, detail="Carrinho não encontrado")

    item = db.query(CartItem).filter(CartItem.id == item_id, CartItem.cart_id == cart.id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Item não encontrado")

    db.delete(item)
    db.commit()


# ── Addresses ─────────────────────────────────────────────────────────────────

@router.get("/me/addresses", response_model=List[AddressResponse])
def get_addresses(current_user: Client = Depends(get_current_user), db: Session = Depends(get_db)):
    return db.query(Address).filter(Address.client_id == current_user.id).all()


@router.post("/me/addresses", response_model=AddressResponse, status_code=status.HTTP_201_CREATED)
def add_address(body: AddressCreate, current_user: Client = Depends(get_current_user), db: Session = Depends(get_db)):
    addr = Address(client_id=current_user.id, **body.model_dump())
    db.add(addr)
    db.commit()
    db.refresh(addr)
    return addr

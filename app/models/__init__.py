# Import all models so SQLAlchemy registers them with Base before create_all()
from app.models.usuario import Usuario  # noqa: F401
from app.models.reset_senha import ResetSenha  # noqa: F401
from app.models.two_factor import TwoFactorChallenge  # noqa: F401
from app.models.produto import Categoria, Produto  # noqa: F401
from app.models.pedido import Pedido, ItemPedido  # noqa: F401
from app.models.endereco import Endereco  # noqa: F401
from app.models.cupom import Cupom, CupomUsado  # noqa: F401
from app.models.duvida import Duvida  # noqa: F401
from app.models.pagamento import Pagamento  # noqa: F401
# Legacy models (kept for backward compatibility)
from app.models.model import (  # noqa: F401
    Client, Category, Product, ImageProduct,
    ProductVariation, Address, Cart, CartItem,
)

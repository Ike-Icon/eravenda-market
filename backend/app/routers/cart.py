# pyright: reportMissingImports=false

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from .. import models, schemas, auth
from ..database import get_db

router = APIRouter(prefix="/cart", tags=["cart"])


def _get_or_create_cart(db: Session, user: models.User) -> models.Cart:
    cart = db.query(models.Cart).filter(models.Cart.user_id == user.id).first()
    if not cart:
        cart = models.Cart(user_id=user.id)
        db.add(cart)
        db.commit()
        db.refresh(cart)
    return cart


def _color_stock(product: models.Product, color: str | None):
    if not color:
        return None
    for item in (product.colors or []):
        if isinstance(item, dict) and str(item.get("name", "")).strip() == color.strip():
            try:
                stock = max(0, int(item.get("stock", 0)))
            except (TypeError, ValueError):
                stock = 0
            return stock if bool(item.get("available", stock > 0)) else 0
    return None


def _size_stock(product: models.Product, size: str | None):
    if not size:
        return None
    for item in (product.sizes or []):
        if isinstance(item, dict) and str(item.get("label", "")).strip() == size.strip():
            try:
                stock = max(0, int(item.get("stock", 0)))
            except (TypeError, ValueError):
                stock = 0
            return stock if bool(item.get("available", stock > 0)) else 0
    return None


def _find_option(product: models.Product, option: str | None):
    if not option:
        return None
    for item in (product.options or []):
        if isinstance(item, dict) and str(item.get("label", "")).strip() == option.strip():
            return item
    return None


def _option_stock(product: models.Product, option: str | None):
    match = _find_option(product, option)
    if match is None:
        return None
    try:
        stock = max(0, int(match.get("stock", 0)))
    except (TypeError, ValueError):
        stock = 0
    return stock if bool(match.get("available", stock > 0)) else 0


def _effective_option_price(option: dict, fallback) -> float:
    discount = option.get("discount_price")
    price = option.get("price")
    try:
        price_val = float(price) if price is not None else float(fallback)
    except (TypeError, ValueError):
        price_val = float(fallback)
    if discount not in (None, ""):
        try:
            discount_val = float(discount)
            if 0 < discount_val < price_val:
                return discount_val
        except (TypeError, ValueError):
            pass
    return price_val


def _item_unit_price(item: "models.CartItem") -> float:
    match = _find_option(item.product, item.option)
    if match is not None:
        return _effective_option_price(match, item.product.price)
    return float(item.product.discount_price or item.product.price)


def _validate_item_stock(product: models.Product, quantity: int, color: str | None, option: str | None = None, size: str | None = None):
    # Color, size and option are all optional at cart time — a guest, or
    # anyone who hasn't picked a variant yet, can still add the item; we
    # just fall back to checking whichever stock figure we do have a pick
    # for, and the product's overall stock when nothing was picked at all.
    if product.options and option:
        option_stock = _option_stock(product, option)
        if option_stock is None:
            raise HTTPException(status_code=400, detail="Please select an available option")
        if option_stock < quantity:
            raise HTTPException(status_code=400, detail="Not enough stock for the selected option")

    if product.colors and color:
        variant_stock = _color_stock(product, color)
        if variant_stock is None:
            raise HTTPException(status_code=400, detail="Please select an available product color")
        if variant_stock < quantity:
            raise HTTPException(status_code=400, detail="Not enough stock for the selected color")

    if product.sizes and size:
        size_stock = _size_stock(product, size)
        if size_stock is None:
            raise HTTPException(status_code=400, detail="Please select an available size")
        if size_stock < quantity:
            raise HTTPException(status_code=400, detail="Not enough stock for the selected size")

    if not ((product.options and option) or (product.colors and color) or (product.sizes and size)):
        if product.stock_quantity < quantity:
            raise HTTPException(status_code=400, detail="Not enough stock for the requested quantity")


def _serialize(cart: models.Cart) -> schemas.CartOut:
    subtotal = sum(_item_unit_price(item) * item.quantity for item in cart.items)
    return schemas.CartOut(id=cart.id, items=cart.items, subtotal=subtotal)


@router.get("", response_model=schemas.CartOut)
def get_cart(db: Session = Depends(get_db), current_user: models.User = Depends(auth.get_current_user)):
    cart = _get_or_create_cart(db, current_user)
    return _serialize(cart)


@router.post("/items", response_model=schemas.CartOut, status_code=201)
def add_item(
    payload: schemas.CartItemIn,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_user),
):
    cart = _get_or_create_cart(db, current_user)

    product = db.query(models.Product).filter(models.Product.id == payload.product_id).first()
    if not product or product.status != models.ProductStatus.approved:
        raise HTTPException(status_code=404, detail="Product not available")
    _validate_item_stock(product, payload.quantity, payload.color, payload.option, payload.size)

    existing = db.query(models.CartItem).filter(
        models.CartItem.cart_id == cart.id,
        models.CartItem.product_id == payload.product_id,
        models.CartItem.color == payload.color,
        models.CartItem.option == payload.option,
        models.CartItem.size == payload.size,
    ).first()

    if existing:
        existing.quantity += payload.quantity
    else:
        db.add(models.CartItem(
            cart_id=cart.id, product_id=payload.product_id, quantity=payload.quantity,
            color=payload.color, option=payload.option, size=payload.size,
        ))

    db.commit()
    db.refresh(cart)
    return _serialize(cart)


@router.put("/items/{item_id}", response_model=schemas.CartOut)
def update_item(
    item_id: str,
    payload: schemas.CartItemIn,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_user),
):
    cart = _get_or_create_cart(db, current_user)
    item = db.query(models.CartItem).filter(
        models.CartItem.id == item_id, models.CartItem.cart_id == cart.id
    ).first()
    if not item:
        raise HTTPException(status_code=404, detail="Cart item not found")

    _validate_item_stock(item.product, payload.quantity, item.color, item.option, item.size)
    item.quantity = payload.quantity
    db.commit()
    db.refresh(cart)
    return _serialize(cart)


@router.delete("/items/{item_id}", response_model=schemas.CartOut)
def remove_item(
    item_id: str,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_user),
):
    cart = _get_or_create_cart(db, current_user)
    item = db.query(models.CartItem).filter(
        models.CartItem.id == item_id, models.CartItem.cart_id == cart.id
    ).first()
    if not item:
        raise HTTPException(status_code=404, detail="Cart item not found")

    db.delete(item)
    db.commit()
    db.refresh(cart)
    return _serialize(cart)

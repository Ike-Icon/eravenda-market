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


def _serialize(cart: models.Cart) -> schemas.CartOut:
    subtotal = sum(
        float(item.product.discount_price or item.product.price) * item.quantity for item in cart.items
    )
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
    if product.stock_quantity < payload.quantity:
        raise HTTPException(status_code=400, detail="Not enough stock for the requested quantity")

    existing = db.query(models.CartItem).filter(
        models.CartItem.cart_id == cart.id, models.CartItem.product_id == payload.product_id
    ).first()

    if existing:
        existing.quantity += payload.quantity
    else:
        db.add(models.CartItem(cart_id=cart.id, product_id=payload.product_id, quantity=payload.quantity))

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

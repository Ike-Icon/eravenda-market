from collections import defaultdict
from fastapi import APIRouter, Depends, HTTPException  # type: ignore[reportMissingImports]
from sqlalchemy.orm import Session  # type: ignore[reportMissingImports]

from .. import models, schemas, auth
from ..database import get_db
from ..utils import generate_order_number

router = APIRouter(prefix="/orders", tags=["orders"])

DELIVERY_FEE_FLAT = 15.00  # GHS, flat rate for the MVP


@router.post("/checkout", response_model=list[schemas.OrderOut], status_code=201)
def checkout(
    payload: schemas.CheckoutRequest,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_user),
):
    address = db.query(models.Address).filter(
        models.Address.id == payload.address_id, models.Address.user_id == current_user.id
    ).first()
    if not address:
        raise HTTPException(status_code=404, detail="Delivery address not found")

    cart = db.query(models.Cart).filter(models.Cart.user_id == current_user.id).first()
    if not cart or not cart.items:
        raise HTTPException(status_code=400, detail="Your cart is empty")

    # Group items by store, since each seller gets a separate order
    items_by_store = defaultdict(list)
    for item in cart.items:
        if item.product.stock_quantity < item.quantity:
            raise HTTPException(
                status_code=400, detail=f"{item.product.name} no longer has enough stock"
            )
        items_by_store[item.product.store_id].append(item)

    created_orders = []

    for store_id, items in items_by_store.items():
        store = db.query(models.Store).filter(models.Store.id == store_id).first()
        subtotal = sum(float(item.product.discount_price or item.product.price) * item.quantity for item in items)
        commission_amount = round(subtotal * float(store.commission_rate) / 100, 2)
        total_amount = subtotal + DELIVERY_FEE_FLAT

        order = models.Order(
            order_number=generate_order_number(),
            buyer_id=current_user.id,
            store_id=store_id,
            address_id=address.id,
            subtotal=subtotal,
            delivery_fee=DELIVERY_FEE_FLAT,
            commission_amount=commission_amount,
            total_amount=total_amount,
            status=models.OrderStatus.pending,
        )
        db.add(order)
        db.flush()  # get order.id before inserting items

        for item in items:
            unit_price = float(item.product.discount_price or item.product.price)
            db.add(models.OrderItem(
                order_id=order.id,
                product_id=item.product_id,
                product_name=item.product.name,
                unit_price=unit_price,
                quantity=item.quantity,
                line_total=round(unit_price * item.quantity, 2),
            ))
            item.product.stock_quantity -= item.quantity
            db.delete(item)

        created_orders.append(order)

    db.commit()
    for order in created_orders:
        db.refresh(order)

    return created_orders


@router.get("", response_model=list[schemas.OrderOut])
def my_orders(db: Session = Depends(get_db), current_user: models.User = Depends(auth.get_current_user)):
    return db.query(models.Order).filter(models.Order.buyer_id == current_user.id).order_by(
        models.Order.created_at.desc()
    ).all()


@router.get("/store/mine", response_model=list[schemas.OrderOut])
def store_orders(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.require_role(models.UserRole.seller)),
):
    if not current_user.store:
        raise HTTPException(status_code=400, detail="You don't have a store yet")
    return db.query(models.Order).filter(models.Order.store_id == current_user.store.id).order_by(
        models.Order.created_at.desc()
    ).all()


@router.get("/{order_id}", response_model=schemas.OrderOut)
def get_order(
    order_id: str,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_user),
):
    order = db.query(models.Order).filter(models.Order.id == order_id).first()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")

    is_buyer = order.buyer_id == current_user.id
    is_seller = current_user.store and order.store_id == current_user.store.id
    if not (is_buyer or is_seller or current_user.role == models.UserRole.admin):
        raise HTTPException(status_code=403, detail="You can't view this order")

    return order


@router.put("/{order_id}/status", response_model=schemas.OrderOut)
def update_order_status(
    order_id: str,
    payload: schemas.OrderStatusUpdate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.require_role(models.UserRole.seller)),
):
    order = db.query(models.Order).filter(
        models.Order.id == order_id, models.Order.store_id == current_user.store.id
    ).first()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")

    order.status = payload.status
    db.commit()
    db.refresh(order)
    return order

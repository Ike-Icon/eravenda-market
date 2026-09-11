from collections import defaultdict
from fastapi import APIRouter, Depends, HTTPException  # type: ignore[reportMissingImports]
from sqlalchemy.orm import Session  # type: ignore[reportMissingImports]

from .. import models, schemas, auth
from ..database import get_db
from ..utils import generate_order_number

router = APIRouter(prefix="/orders", tags=["orders"])

# Commission is assessed per item, so an order can accurately preserve the
# rate in effect for a mixed-price basket even if the policy changes later.
COMMISSION_TIERS = (
    (1000.00, 3.0),    # products under GHS 1,000
    (10000.00, 4.0),   # products GHS 1,000 – 10,000
    (float("inf"), 5.0),  # products above GHS 10,000
)


def commission_rate_for(unit_price: float) -> float:
    """Return the platform commission percentage for one product unit."""
    for upper_bound, rate in COMMISSION_TIERS:
        if unit_price < upper_bound:
            return rate
    return COMMISSION_TIERS[-1][1]


def _location(value: str | None) -> str:
    return (value or "").strip().casefold()


def delivery_fee_for(address: models.Address, store: models.Store) -> float:
    """Location-tier delivery price; Sunyani deliveries remain the local base."""
    buyer_city, seller_city = _location(address.city), _location(store.city)
    buyer_region, seller_region = _location(address.region), _location(store.region)
    if buyer_city == "sunyani" and seller_city == "sunyani":
        # Same neighbourhood has the shortest local run; another Sunyani
        # sub-town remains a local delivery, but is priced as a longer trip.
        if _location(address.sub_town) and _location(address.sub_town) == _location(store.sub_town):
            return 8.00
        return 10.00
    if buyer_city == seller_city and buyer_city:
        return 18.00
    # A city or sub-town beyond the Sunyani delivery base incurs the extended fee.
    if buyer_region and buyer_region == seller_region:
        return 30.00
    return 45.00


def cart_delivery_quotes(cart: models.Cart, address: models.Address, db: Session) -> list[dict]:
    store_ids = {item.product.store_id for item in cart.items}
    stores = db.query(models.Store).filter(models.Store.id.in_(store_ids)).all()
    return [
        {"store_id": store.id, "store_name": store.store_name, "delivery_fee": delivery_fee_for(address, store)}
        for store in stores
    ]


@router.post("/delivery-quote", response_model=schemas.DeliveryQuoteOut)
def delivery_quote(
    payload: schemas.DeliveryQuoteRequest,
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
        return schemas.DeliveryQuoteOut(delivery_fee=0, store_count=0, breakdown=[])
    breakdown = cart_delivery_quotes(cart, address, db)
    return schemas.DeliveryQuoteOut(
        delivery_fee=round(sum(row["delivery_fee"] for row in breakdown), 2),
        store_count=len(breakdown),
        breakdown=breakdown,
    )


def _variant_stock(product: models.Product, color: str | None):
    if not product.colors:
        return None
    if not color:
        raise HTTPException(status_code=400, detail=f"Please select a color for {product.name}")
    for variant in product.colors:
        if isinstance(variant, dict) and str(variant.get("name", "")).strip() == color.strip():
            try:
                stock = max(0, int(variant.get("stock", 0)))
            except (TypeError, ValueError):
                stock = 0
            return variant, stock if bool(variant.get("available", stock > 0)) else 0
    raise HTTPException(status_code=400, detail=f"Selected color is unavailable for {product.name}")


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
        variant_info = _variant_stock(item.product, item.color)
        if variant_info is not None:
            _, variant_stock = variant_info
            if variant_stock < item.quantity:
                raise HTTPException(status_code=400, detail=f"{item.product.name} no longer has enough stock in {item.color}")
        elif item.product.stock_quantity < item.quantity:
            raise HTTPException(status_code=400, detail=f"{item.product.name} no longer has enough stock")
        items_by_store[item.product.store_id].append(item)

    created_orders = []

    for store_id, items in items_by_store.items():
        store = db.query(models.Store).filter(models.Store.id == store_id).first()
        subtotal = sum(float(item.product.discount_price or item.product.price) * item.quantity for item in items)
        delivery_fee = delivery_fee_for(address, store)
        commission_amount = round(sum(
            float(item.product.discount_price or item.product.price) * item.quantity
            * commission_rate_for(float(item.product.discount_price or item.product.price)) / 100
            for item in items
        ), 2)
        total_amount = subtotal + delivery_fee

        order = models.Order(
            order_number=generate_order_number(),
            buyer_id=current_user.id,
            store_id=store_id,
            address_id=address.id,
            subtotal=subtotal,
            delivery_fee=delivery_fee,
            commission_amount=commission_amount,
            total_amount=total_amount,
            payment_method=payload.payment_method,
            status=models.OrderStatus.pending,
        )
        db.add(order)
        db.flush()  # get order.id before inserting items

        for item in items:
            unit_price = float(item.product.discount_price or item.product.price)
            rate = commission_rate_for(unit_price)
            line_total = round(unit_price * item.quantity, 2)
            db.add(models.OrderItem(
                order_id=order.id,
                product_id=item.product_id,
                product_name=item.product.name,
                unit_price=unit_price,
                quantity=item.quantity,
                line_total=line_total,
                commission_rate=rate,
                commission_amount=round(line_total * rate / 100, 2),
                color=item.color,
            ))
            variant_info = _variant_stock(item.product, item.color)
            if variant_info is not None:
                variant, _ = variant_info
                variant["stock"] = max(0, int(variant.get("stock", 0)) - item.quantity)
                variant["available"] = variant["stock"] > 0
                # Keep the legacy aggregate stock field in sync with variant inventory.
                item.product.colors = list(item.product.colors)
                item.product.stock_quantity = sum(max(0, int(v.get("stock", 0))) for v in item.product.colors if isinstance(v, dict))
            else:
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


@router.post("/{order_id}/cancel", response_model=schemas.OrderOut)
def cancel_pending_order(
    order_id: str,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_user),
):
    """Allow the buyer to cancel only before the seller starts processing."""
    order = db.query(models.Order).filter(
        models.Order.id == order_id, models.Order.buyer_id == current_user.id
    ).with_for_update().first()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    if order.status != models.OrderStatus.pending:
        raise HTTPException(
            status_code=400,
            detail="This order can no longer be cancelled because it is already being processed.",
        )

    # Checkout reserves stock immediately. Returning it here keeps inventory
    # accurate when a pending order is cancelled before payment/fulfilment.
    for item in order.items:
        product = db.query(models.Product).filter(models.Product.id == item.product_id).first()
        if product:
            variant_info = _variant_stock(product, item.color) if product.colors else None
            if variant_info is not None:
                variant, _ = variant_info
                variant["stock"] = max(0, int(variant.get("stock", 0))) + item.quantity
                variant["available"] = variant["stock"] > 0
                product.colors = list(product.colors)
                product.stock_quantity = sum(max(0, int(v.get("stock", 0))) for v in product.colors if isinstance(v, dict))
            else:
                product.stock_quantity += item.quantity

    order.status = models.OrderStatus.cancelled
    db.commit()
    db.refresh(order)
    return order


@router.get("/search", response_model=schemas.OrderOut)
def search_my_order(
    order_id: str,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_user),
):
    """Find one of the signed-in buyer's orders by order number or database ID."""
    value = (order_id or "").strip()
    if not value:
        raise HTTPException(status_code=400, detail="Enter an order ID or order number")

    order = db.query(models.Order).filter(
        models.Order.buyer_id == current_user.id,
        models.Order.order_number == value,
    ).first()

    if not order:
        try:
            order = db.query(models.Order).filter(
                models.Order.buyer_id == current_user.id,
                models.Order.id == value,
            ).first()
        except Exception:
            order = None

    if not order:
        raise HTTPException(status_code=404, detail="Order not found. Check the order ID and try again.")
    return order


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
    ).with_for_update().first()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    if order.status != models.OrderStatus.pending and payload.status == models.OrderStatus.pending:
        raise HTTPException(status_code=400, detail="An order cannot be moved back to pending once processing has started")

    order.status = payload.status
    db.commit()
    db.refresh(order)
    return order

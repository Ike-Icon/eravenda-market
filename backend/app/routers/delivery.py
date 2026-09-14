from datetime import datetime
import logging

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session, joinedload

from .. import auth, models, schemas
from ..database import get_db
from ..email_utils import ADMIN_NOTIFICATION_EMAIL, send_email

router = APIRouter(prefix="/delivery", tags=["delivery"])
logger = logging.getLogger("eravenda.delivery")


def _profile_for_user(db: Session, current_user: models.User) -> models.DeliveryProfile:
    profile = db.query(models.DeliveryProfile).filter(models.DeliveryProfile.user_id == current_user.id).first()
    if not profile:
        raise HTTPException(status_code=404, detail="You do not have a delivery partner profile yet")
    return profile


def _delivery_order_row(order, assignment, buyer, store):
    return schemas.DeliveryOrderOut(
        id=order.id, order_number=order.order_number, status=order.status,
        buyer_name=buyer.full_name, buyer_phone=buyer.phone, buyer_email=buyer.email,
        delivery_location=(order.address.area or order.address.sub_town or order.address.city) if order.address else None,
        store_name=store.store_name, total_amount=order.total_amount, delivery_fee=order.delivery_fee,
        assignment_note=assignment.assignment_note, assigned_at=assignment.assigned_at,
        created_at=order.created_at, shipped_at=order.shipped_at, delivered_at=order.delivered_at,
    )


def _send_delivery_confirmation(order, buyer, store, delivery_person):
    seller = store.owner
    subject = f"Delivery completed for order {order.order_number}"
    body = (
        f"Delivery confirmation\n\n"
        f"Order: {order.order_number}\n"
        f"Buyer: {buyer.full_name}\n"
        f"Buyer phone: {buyer.phone or 'Not provided'}\n"
        f"Store: {store.store_name}\n"
        f"Delivery person: {delivery_person.user.full_name}\n"
        f"Delivery phone: {delivery_person.user.phone or 'Not provided'}\n"
        f"Delivered at: {order.delivered_at}\n\n"
        "The order has been marked as delivered in the EraVenda system."
    )
    recipients = {
        ADMIN_NOTIFICATION_EMAIL,
        buyer.email,
        seller.email if seller else None,
    }
    for recipient in recipients:
        if not recipient:
            continue
        try:
            send_email(recipient, subject, body)
        except Exception:
            logger.exception("Could not send delivery confirmation for order %s to %s", order.order_number, recipient)


@router.post("/register", response_model=schemas.DeliveryProfileOut, status_code=201)
def register_delivery_person(
    payload: schemas.DeliveryRegistration,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_user),
):
    if not payload.terms_accepted:
        raise HTTPException(status_code=400, detail="Please accept the delivery partner terms before submitting")
    existing = db.query(models.DeliveryProfile).filter(models.DeliveryProfile.user_id == current_user.id).first()
    if existing:
        raise HTTPException(status_code=400, detail="You already have a delivery partner profile")
    profile = models.DeliveryProfile(
        user_id=current_user.id,
        company_name=payload.company_name.strip() if payload.company_name else None,
        location=payload.location.strip(),
        vehicle_type=payload.vehicle_type.strip(),
        license_number=payload.license_number.strip() if payload.license_number else None,
        availability=payload.availability.strip() or "available",
        terms_accepted_at=datetime.utcnow(),
    )
    db.add(profile)
    db.commit()
    db.refresh(profile)
    return profile


@router.get("/me", response_model=schemas.DeliveryProfileOut)
def my_delivery_profile(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_user),
):
    return _profile_for_user(db, current_user)


@router.get("/dashboard", response_model=schemas.DeliveryDashboardOut)
def delivery_dashboard(db: Session = Depends(get_db), current_user: models.User = Depends(auth.get_current_user)):
    profile = _profile_for_user(db, current_user)
    rows = (db.query(models.Order, models.OrderDeliveryAssignment, models.User, models.Store)
            .join(models.OrderDeliveryAssignment, models.Order.id == models.OrderDeliveryAssignment.order_id)
            .join(models.User, models.Order.buyer_id == models.User.id)
            .join(models.Store, models.Order.store_id == models.Store.id)
            .options(joinedload(models.Order.address))
            .filter(models.OrderDeliveryAssignment.delivery_person_id == profile.id)
            .order_by(models.Order.created_at.desc()).all())
    active, completed = [], []
    for order, assignment, buyer, store in rows:
        row = _delivery_order_row(order, assignment, buyer, store)
        if order.status == models.OrderStatus.delivered:
            completed.append(row)
        elif order.status not in {models.OrderStatus.cancelled, models.OrderStatus.refunded}:
            active.append(row)
    return schemas.DeliveryDashboardOut(
        profile=profile, active_orders=active, completed_orders=completed,
        total_deliveries=len(completed), active_delivery_count=len(active),
        amount_received=round(sum(float(row.delivery_fee or 0) for row in completed), 2),
    )


@router.put("/orders/{order_id}/status", response_model=schemas.DeliveryOrderOut)
def update_delivery_order_status(order_id: str, payload: schemas.DeliveryOrderStatusUpdate, db: Session = Depends(get_db), current_user: models.User = Depends(auth.get_current_user)):
    profile = _profile_for_user(db, current_user)
    row = (db.query(models.Order, models.OrderDeliveryAssignment, models.User, models.Store)
           .join(models.OrderDeliveryAssignment, models.Order.id == models.OrderDeliveryAssignment.order_id)
           .join(models.User, models.Order.buyer_id == models.User.id)
           .join(models.Store, models.Order.store_id == models.Store.id)
           .options(joinedload(models.Order.address))
           .filter(models.Order.id == order_id, models.OrderDeliveryAssignment.delivery_person_id == profile.id).first())
    if not row:
        raise HTTPException(status_code=404, detail="Assigned order not found")
    order, assignment, buyer, store = row
    allowed = {models.OrderStatus.processing: {models.OrderStatus.shipped}, models.OrderStatus.shipped: {models.OrderStatus.delivered}}
    if payload.status not in allowed.get(order.status, set()):
        raise HTTPException(status_code=400, detail="This order cannot move to that delivery status")
    order.status = payload.status
    if payload.status == models.OrderStatus.shipped and not order.shipped_at:
        order.shipped_at = datetime.utcnow()
    if payload.status == models.OrderStatus.delivered and not order.delivered_at:
        order.delivered_at = datetime.utcnow()
    db.commit()
    db.refresh(order)
    if payload.status == models.OrderStatus.delivered:
        _send_delivery_confirmation(order, buyer, store, profile)
    return _delivery_order_row(order, assignment, buyer, store)
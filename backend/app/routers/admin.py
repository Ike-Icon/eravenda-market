from fastapi import APIRouter, Depends, HTTPException  # pyright: ignore[reportMissingImports]
from fastapi.responses import FileResponse  # pyright: ignore[reportMissingImports]
from pathlib import Path
from sqlalchemy.orm import Session  # pyright: ignore[reportMissingImports]
from sqlalchemy import func  # pyright: ignore[reportMissingImports]
from sqlalchemy.exc import IntegrityError  # pyright: ignore[reportMissingImports]

from .. import models, schemas, auth
from ..database import get_db

router = APIRouter(prefix="/admin", tags=["admin"], dependencies=[Depends(auth.require_role(models.UserRole.admin))])


@router.get("/stores/pending", response_model=list[schemas.StoreOut])
def pending_stores(db: Session = Depends(get_db)):
    return db.query(models.Store).filter(models.Store.status == models.StoreStatus.pending).all()


@router.get("/stores", response_model=list[schemas.StoreOut])
def all_stores(db: Session = Depends(get_db)):
    """Every store regardless of status, for the admin dashboard's
    store-management view (approve, reject, or suspend any store)."""
    return db.query(models.Store).order_by(models.Store.created_at.desc()).all()


@router.put("/stores/{store_id}/approve", response_model=schemas.StoreOut)
def approve_store(store_id: str, db: Session = Depends(get_db)):
    store = db.query(models.Store).filter(models.Store.id == store_id).first()
    if not store:
        raise HTTPException(status_code=404, detail="Store not found")
    store.status = models.StoreStatus.approved
    store.rejection_reason = None
    store.owner.role = models.UserRole.seller
    db.commit()
    db.refresh(store)
    return store


@router.put("/stores/{store_id}/reject", response_model=schemas.StoreOut)
def reject_store(store_id: str, payload: schemas.StoreDecision, db: Session = Depends(get_db)):
    store = db.query(models.Store).filter(models.Store.id == store_id).first()
    if not store:
        raise HTTPException(status_code=404, detail="Store not found")
    store.status = models.StoreStatus.rejected
    store.rejection_reason = payload.rejection_reason
    db.commit()
    db.refresh(store)
    return store


@router.get("/services/pending", response_model=list[schemas.HandymanOut])
def pending_service_workers(db: Session = Depends(get_db)):
    return db.query(models.HandymanProfile).filter(models.HandymanProfile.status == models.ServiceStatus.pending).all()


@router.put("/services/{profile_id}/approve", response_model=schemas.HandymanOut)
def approve_service_worker(profile_id: str, verified_pro: bool = False, background_checked: bool = False, db: Session = Depends(get_db)):
    profile = db.query(models.HandymanProfile).filter(models.HandymanProfile.id == profile_id).first()
    if not profile:
        raise HTTPException(status_code=404, detail="Service application not found")
    profile.status = models.ServiceStatus.approved
    profile.verified_pro = verified_pro
    profile.background_checked = background_checked
    db.commit(); db.refresh(profile)
    return profile


@router.get("/services/{profile_id}/resume")
def download_worker_resume(profile_id: str, db: Session = Depends(get_db)):
    profile = db.query(models.HandymanProfile).filter(models.HandymanProfile.id == profile_id).first()
    if not profile or not profile.resume_path or not Path(profile.resume_path).is_file():
        raise HTTPException(status_code=404, detail="Resume not available")
    return FileResponse(profile.resume_path, filename=Path(profile.resume_path).name)


@router.put("/services/bookings/{booking_id}", response_model=schemas.ServiceBookingOut)
def update_service_booking(booking_id: str, payload: schemas.ServiceBookingUpdate, db: Session = Depends(get_db)):
    booking = db.query(models.ServiceBooking).filter(models.ServiceBooking.id == booking_id).first()
    if not booking:
        raise HTTPException(status_code=404, detail="Service booking not found")
    if payload.quoted_amount is not None:
        booking.quoted_amount = payload.quoted_amount
    if payload.escrow_amount is not None:
        booking.escrow_amount = payload.escrow_amount
        booking.commission_amount = round(payload.escrow_amount * 0.02, 2)
    booking.status = payload.status
    db.commit(); db.refresh(booking)
    return booking


@router.put("/stores/{store_id}/suspend", response_model=schemas.StoreOut)
def suspend_store(store_id: str, db: Session = Depends(get_db)):
    store = db.query(models.Store).filter(models.Store.id == store_id).first()
    if not store:
        raise HTTPException(status_code=404, detail="Store not found")
    store.status = models.StoreStatus.suspended
    db.commit()
    db.refresh(store)
    return store


@router.get("/services/workers", response_model=list[schemas.HandymanOut])
def all_service_workers(db: Session = Depends(get_db)):
    return (db.query(models.HandymanProfile)
            .options(__import__("sqlalchemy.orm", fromlist=["selectinload"]).selectinload(models.HandymanProfile.portfolio))
            .order_by(models.HandymanProfile.created_at.desc()).all())


@router.get("/services/bookings", response_model=list[schemas.AdminServiceBookingOut])
def service_requests(db: Session = Depends(get_db)):
    rows = (db.query(models.ServiceBooking, models.HandymanProfile, models.User)
            .join(models.HandymanProfile, models.ServiceBooking.handyman_id == models.HandymanProfile.id)
            .join(models.User, models.ServiceBooking.client_id == models.User.id)
            .order_by(models.ServiceBooking.created_at.desc()).all())
    result = []
    for booking, worker, client in rows:
        professional = worker.user
        result.append(schemas.AdminServiceBookingOut(
            id=booking.id, handyman_id=worker.id, professional_name=worker.professional_name,
            company_name=worker.company_name, professional_email=professional.email,
            professional_phone=professional.phone, client_name=client.full_name,
            client_email=client.email, client_phone=client.phone, details=booking.details,
            location=booking.location, preferred_contact=booking.preferred_contact,
            contact_details=booking.contact_details, quoted_amount=booking.quoted_amount,
            status=booking.status, created_at=booking.created_at
        ))
    return result


@router.get("/services/reviews", response_model=list[schemas.AdminServiceReviewOut])
def service_reviews(db: Session = Depends(get_db)):
    rows = (db.query(models.ServiceReview, models.HandymanProfile, models.User)
            .join(models.HandymanProfile, models.ServiceReview.handyman_id == models.HandymanProfile.id)
            .join(models.User, models.ServiceReview.client_id == models.User.id)
            .order_by(models.ServiceReview.created_at.desc()).all())
    return [schemas.AdminServiceReviewOut(id=r.id, booking_id=r.booking_id, handyman_id=r.handyman_id, professional_name=w.professional_name, client_name=u.full_name, rating=r.rating, comment=r.comment, created_at=r.created_at) for r,w,u in rows]


@router.put("/services/{profile_id}/reject", response_model=schemas.HandymanOut)
def reject_service_worker(profile_id: str, db: Session = Depends(get_db)):
    profile = db.query(models.HandymanProfile).filter(models.HandymanProfile.id == profile_id).first()
    if not profile:
        raise HTTPException(status_code=404, detail="Service application not found")
    profile.status = models.ServiceStatus.rejected
    profile.verified_pro = False
    profile.background_checked = False
    db.commit(); db.refresh(profile)
    return profile


@router.put("/services/{profile_id}/suspend", response_model=schemas.HandymanOut)
def suspend_service_worker(profile_id: str, db: Session = Depends(get_db)):
    profile = db.query(models.HandymanProfile).filter(models.HandymanProfile.id == profile_id).first()
    if not profile:
        raise HTTPException(status_code=404, detail="Professional profile not found")
    profile.status = models.ServiceStatus.suspended
    db.commit(); db.refresh(profile)
    return profile


@router.put("/services/{profile_id}/reinstate", response_model=schemas.HandymanOut)
def reinstate_service_worker(profile_id: str, db: Session = Depends(get_db)):
    profile = db.query(models.HandymanProfile).filter(models.HandymanProfile.id == profile_id).first()
    if not profile:
        raise HTTPException(status_code=404, detail="Professional profile not found")
    profile.status = models.ServiceStatus.approved
    db.commit(); db.refresh(profile)
    return profile


@router.delete("/services/{profile_id}", status_code=204)
def delete_service_worker(profile_id: str, db: Session = Depends(get_db)):
    profile = db.query(models.HandymanProfile).filter(models.HandymanProfile.id == profile_id).first()
    if not profile:
        raise HTTPException(status_code=404, detail="Professional profile not found")
    try:
        db.delete(profile)
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=400,
            detail="Can't delete this professional — they have existing bookings or reviews. Suspend the profile instead.",
        )


@router.get("/products/pending", response_model=list[schemas.ProductOut])
def pending_products(db: Session = Depends(get_db)):
    return db.query(models.Product).filter(models.Product.status == models.ProductStatus.pending).all()


@router.put("/products/{product_id}/approve", response_model=schemas.ProductOut)
def approve_product(product_id: str, db: Session = Depends(get_db)):
    product = db.query(models.Product).filter(models.Product.id == product_id).first()
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")
    product.status = models.ProductStatus.approved
    product.rejection_reason = None
    db.commit()
    db.refresh(product)
    return product


@router.put("/products/{product_id}/reject", response_model=schemas.ProductOut)
def reject_product(product_id: str, payload: schemas.StoreDecision, db: Session = Depends(get_db)):
    product = db.query(models.Product).filter(models.Product.id == product_id).first()
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")
    product.status = models.ProductStatus.rejected
    product.rejection_reason = payload.rejection_reason
    db.commit()
    db.refresh(product)
    return product


@router.patch("/products/{product_id}/status", response_model=schemas.ProductOut)
def set_product_status(product_id: str, payload: schemas.ProductStatusUpdate, db: Session = Depends(get_db)):
    """General-purpose moderation: approve, reject, or unpublish (out_of_stock)
    a product in one endpoint, for the admin dashboard's quick actions."""
    product = db.query(models.Product).filter(models.Product.id == product_id).first()
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")
    product.status = payload.status
    product.rejection_reason = payload.rejection_reason
    db.commit()
    db.refresh(product)
    return product


@router.delete("/products/{product_id}", status_code=204)
def delete_product(product_id: str, db: Session = Depends(get_db)):
    """Admin hard-delete, distinct from the seller's own delete endpoint —
    this works on any store's product, for clear policy violations."""
    product = db.query(models.Product).filter(models.Product.id == product_id).first()
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")
    try:
        db.delete(product)
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=400,
            detail="Can't delete this product — it's part of an existing order. Reject it instead to hide it from buyers.",
        )


@router.get("/products/tracking")
def product_tracking(db: Session = Depends(get_db)):
    products = (db.query(models.Product)
                .join(models.Store, models.Product.store_id == models.Store.id)
                .order_by(models.Product.updated_at.desc())
                .limit(300).all())
    return [{
        "id": p.id, "name": p.name, "sku": p.sku, "store_name": p.store.store_name if p.store else "",
        "price": float(p.discount_price if p.discount_price is not None else p.price),
        "stock_quantity": p.stock_quantity, "status": p.status.value,
        "updated_at": p.updated_at,
    } for p in products]


@router.get("/payments/tracking")
def payment_tracking(db: Session = Depends(get_db)):
    rows = (db.query(models.Payment, models.Order, models.User, models.Store)
            .join(models.Order, models.Payment.order_id == models.Order.id)
            .join(models.User, models.Order.buyer_id == models.User.id)
            .join(models.Store, models.Order.store_id == models.Store.id)
            .order_by(models.Payment.created_at.desc())
            .limit(300).all())
    return [{
        "id": payment.id, "order_number": order.order_number, "buyer_name": buyer.full_name,
        "buyer_email": buyer.email, "store_name": store.store_name, "provider": payment.provider,
        "reference": payment.provider_reference, "amount": float(payment.amount), "currency": payment.currency,
        "status": payment.status.value, "paid_at": payment.paid_at, "created_at": payment.created_at,
    } for payment, order, buyer, store in rows]


@router.get("/orders/cod-pending")
def cod_pending_orders(db: Session = Depends(get_db)):
    """COD orders that have been delivered but have no payment record yet."""
    paid_order_ids = db.query(models.Payment.order_id).subquery()
    rows = (db.query(models.Order, models.User, models.Store)
            .join(models.User, models.Order.buyer_id == models.User.id)
            .join(models.Store, models.Order.store_id == models.Store.id)
            .filter(models.Order.payment_method == models.PaymentMethod.cash_on_delivery)
            .filter(~models.Order.id.in_(db.query(paid_order_ids.c.order_id)))
            .filter(models.Order.status.in_([
                models.OrderStatus.delivered,
                models.OrderStatus.processing,
                models.OrderStatus.shipped,
            ]))
            .order_by(models.Order.created_at.desc())
            .all())
    return [{
        "id": order.id, "order_number": order.order_number,
        "buyer_name": buyer.full_name, "buyer_email": buyer.email,
        "store_name": store.store_name, "total_amount": float(order.total_amount),
        "status": order.status.value, "created_at": order.created_at,
    } for order, buyer, store in rows]


@router.post("/payments/cod-record")
def record_cod_payment(payload: schemas.CODPaymentRecord, db: Session = Depends(get_db)):
    """Admin records a cash-on-delivery payment for bookkeeping."""
    import uuid
    order = db.query(models.Order).filter(models.Order.id == payload.order_id).first()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    if order.payment_method != models.PaymentMethod.cash_on_delivery:
        raise HTTPException(status_code=400, detail="This order was not placed with cash on delivery")
    existing = db.query(models.Payment).filter(models.Payment.order_id == payload.order_id).first()
    if existing:
        raise HTTPException(status_code=400, detail="A payment record already exists for this order")
    reference = payload.reference or f"COD-{order.order_number}"
    payment = models.Payment(
        id=str(uuid.uuid4()),
        order_id=order.id,
        provider="cash_on_delivery",
        provider_reference=reference,
        amount=payload.amount,
        currency="GHS",
        status=models.PaymentStatus.success,
        paid_at=func.now(),
    )
    db.add(payment)
    if order.status != models.OrderStatus.delivered:
        order.status = models.OrderStatus.paid
    db.commit()
    db.refresh(payment)
    return {"id": payment.id, "order_number": order.order_number, "amount": float(payment.amount), "reference": payment.provider_reference, "status": payment.status.value}


@router.get("/users", response_model=list[schemas.UserOut])
def list_users(db: Session = Depends(get_db)):
    return db.query(models.User).order_by(models.User.created_at.desc()).all()


@router.put("/users/{user_id}/suspend", response_model=schemas.UserOut)
def suspend_user(user_id: str, db: Session = Depends(get_db)):
    user = db.query(models.User).filter(models.User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    user.is_active = False
    db.commit()
    db.refresh(user)
    return user


@router.put("/users/{user_id}/reactivate", response_model=schemas.UserOut)
def reactivate_user(user_id: str, db: Session = Depends(get_db)):
    user = db.query(models.User).filter(models.User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    user.is_active = True
    db.commit()
    db.refresh(user)
    return user


@router.delete("/users/{user_id}", status_code=204)
def delete_user(user_id: str, current_admin: models.User = Depends(auth.require_role(models.UserRole.admin)), db: Session = Depends(get_db)):
    if user_id == current_admin.id:
        raise HTTPException(status_code=400, detail="You can't delete your own admin account")
    user = db.query(models.User).filter(models.User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    try:
        db.delete(user)
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=400,
            detail="Can't delete this user — they (or their store) have existing orders. Suspend the account instead.",
        )


@router.get("/stats")
def platform_stats(db: Session = Depends(get_db)):
    total_orders = db.query(func.count(models.Order.id)).scalar() or 0
    total_revenue = db.query(func.coalesce(func.sum(models.Order.commission_amount), 0)).filter(
        models.Order.status != models.OrderStatus.cancelled
    ).scalar()
    total_sellers = db.query(func.count(models.Store.id)).filter(
        models.Store.status == models.StoreStatus.approved
    ).scalar() or 0
    total_products = db.query(func.count(models.Product.id)).filter(
        models.Product.status == models.ProductStatus.approved
    ).scalar() or 0
    pending_stores_count = db.query(func.count(models.Store.id)).filter(
        models.Store.status == models.StoreStatus.pending
    ).scalar() or 0
    pending_products_count = db.query(func.count(models.Product.id)).filter(
        models.Product.status == models.ProductStatus.pending
    ).scalar() or 0
    total_categories = db.query(func.count(models.Category.id)).scalar() or 0
    total_users = db.query(func.count(models.User.id)).scalar() or 0
    service_pending = db.query(func.count(models.HandymanProfile.id)).filter(models.HandymanProfile.status == models.ServiceStatus.pending).scalar() or 0
    service_active = db.query(func.count(models.HandymanProfile.id)).filter(models.HandymanProfile.status == models.ServiceStatus.approved).scalar() or 0
    service_requests = db.query(func.count(models.ServiceBooking.id)).filter(models.ServiceBooking.status != models.ServiceBookingStatus.cancelled).scalar() or 0
    service_reviews_count = db.query(func.count(models.ServiceReview.id)).scalar() or 0
    service_average = db.query(func.avg(models.ServiceReview.rating)).scalar() or 0

    return {
        "total_orders": total_orders,
        "platform_revenue": float(total_revenue or 0),
        "active_sellers": total_sellers,
        "active_products": total_products,
        "pending_store_approvals": pending_stores_count,
        "pending_product_approvals": pending_products_count,
        "total_categories": total_categories,
        "total_users": total_users,
        "service_pending": service_pending,
        "service_active": service_active,
        "service_requests": service_requests,
        "service_reviews": service_reviews_count,
        "service_average_rating": float(service_average),
    }

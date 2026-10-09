from datetime import datetime, timedelta
from calendar import monthrange
from fastapi import APIRouter, Depends, HTTPException  # pyright: ignore[reportMissingImports]
from fastapi.responses import FileResponse  # pyright: ignore[reportMissingImports]
from pydantic import BaseModel, Field  # pyright: ignore[reportMissingImports]
from pathlib import Path
from sqlalchemy.orm import Session, selectinload  # pyright: ignore[reportMissingImports]
from sqlalchemy import func, or_  # pyright: ignore[reportMissingImports]
from sqlalchemy.exc import IntegrityError  # pyright: ignore[reportMissingImports]

from .. import models, schemas, auth, delivery_fees
from ..database import get_db
from ..service_pricing import service_charge_for, service_commission_for
from ..email_utils import send_email, SITE_URL, SUPPORT_EMAIL
from .products import _sync_stock_from_variants
from .. import wholesale
import logging

logger = logging.getLogger("eravenda.admin")


def _product_thumbnail_items(product: models.Product) -> list[dict]:
    """Single-item list for send_email's `items` param — the product's own
    primary photo, for the approve/reject emails below."""
    primary = next((img for img in (product.images or []) if img.is_primary), None)
    image = primary or (product.images[0] if product.images else None)
    return [{"name": product.name, "image_url": image.image_url if image else None}]

router = APIRouter(prefix="/admin", tags=["admin"], dependencies=[Depends(auth.require_role(models.UserRole.admin))])


@router.get("/delivery-people", response_model=list[schemas.DeliveryProfileOut])
def delivery_people(db: Session = Depends(get_db)):
    return db.query(models.DeliveryProfile).order_by(models.DeliveryProfile.created_at.desc()).all()


@router.put("/delivery-people/{profile_id}/approve", response_model=schemas.DeliveryProfileOut)
def approve_delivery_person(profile_id: str, db: Session = Depends(get_db)):
    profile = db.query(models.DeliveryProfile).filter(models.DeliveryProfile.id == profile_id).first()
    if not profile:
        raise HTTPException(status_code=404, detail="Delivery profile not found")
    profile.status = models.DeliveryStatus.approved
    profile.rejection_reason = None
    profile.user.role = models.UserRole.delivery
    db.commit(); db.refresh(profile)
    return profile


@router.put("/delivery-people/{profile_id}/reject", response_model=schemas.DeliveryProfileOut)
def reject_delivery_person(profile_id: str, payload: schemas.StoreDecision, db: Session = Depends(get_db)):
    profile = db.query(models.DeliveryProfile).filter(models.DeliveryProfile.id == profile_id).first()
    if not profile:
        raise HTTPException(status_code=404, detail="Delivery profile not found")
    profile.status = models.DeliveryStatus.rejected
    profile.rejection_reason = payload.rejection_reason
    db.commit(); db.refresh(profile)

    try:
        reason_line = f"\nReason given: {payload.rejection_reason}\n" if payload.rejection_reason else ""
        send_email(
            profile.user.email,
            "Update on your EraVenda delivery partner application",
            (
                f"Hi {profile.user.full_name.split(' ')[0]},\n\n"
                "Your delivery partner application wasn't approved this time.\n"
                f"{reason_line}\n"
                f"You can review the details and submit a new application any time here:\n{SITE_URL}/delivery/register\n\n"
                f"If you'd like more feedback, just reply to this email or reach us at support.\n\n"
                "— The EraVenda Market team"
            ),
        )
    except Exception:
        logger.exception("Could not send delivery rejection email to %s", profile.user.email)

    return profile


@router.put("/delivery-people/{profile_id}/suspend", response_model=schemas.DeliveryProfileOut)
def suspend_delivery_person(profile_id: str, db: Session = Depends(get_db)):
    profile = db.query(models.DeliveryProfile).filter(models.DeliveryProfile.id == profile_id).first()
    if not profile:
        raise HTTPException(status_code=404, detail="Delivery profile not found")
    profile.status = models.DeliveryStatus.suspended
    db.commit(); db.refresh(profile)
    return profile


@router.put("/delivery-people/{profile_id}/reinstate", response_model=schemas.DeliveryProfileOut)
def reinstate_delivery_person(profile_id: str, db: Session = Depends(get_db)):
    profile = db.query(models.DeliveryProfile).filter(models.DeliveryProfile.id == profile_id).first()
    if not profile:
        raise HTTPException(status_code=404, detail="Delivery profile not found")
    profile.status = models.DeliveryStatus.approved
    profile.rejection_reason = None
    profile.user.role = models.UserRole.delivery
    db.commit(); db.refresh(profile)
    return profile


@router.delete("/delivery-people/{profile_id}", status_code=204)
def delete_delivery_person(profile_id: str, db: Session = Depends(get_db)):
    """Removes a delivery partner's profile from the list entirely. Only the
    delivery-partner profile is removed — the underlying user account (and
    their own order history as a buyer, if any) is left alone; their role
    is simply reverted to buyer so they lose delivery-partner access."""
    profile = db.query(models.DeliveryProfile).filter(models.DeliveryProfile.id == profile_id).first()
    if not profile:
        raise HTTPException(status_code=404, detail="Delivery profile not found")
    user = profile.user
    try:
        db.delete(profile)
        db.flush()
        if user and user.role == models.UserRole.delivery:
            user.role = models.UserRole.buyer
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=400,
            detail="Can't delete this delivery partner — they have existing or past delivery assignments. Suspend them instead.",
        )


@router.get("/delivery-orders")
def delivery_orders(db: Session = Depends(get_db)):
    rows = (db.query(models.Order, models.User, models.Store, models.OrderDeliveryAssignment)
            .join(models.User, models.Order.buyer_id == models.User.id)
            .join(models.Store, models.Order.store_id == models.Store.id)
            .outerjoin(models.OrderDeliveryAssignment, models.Order.id == models.OrderDeliveryAssignment.order_id)
            .filter(models.Order.status.notin_([models.OrderStatus.delivered, models.OrderStatus.cancelled, models.OrderStatus.refunded]))
            .order_by(models.Order.created_at.desc()).limit(300).all())
    return [{
        "id": order.id, "order_number": order.order_number, "buyer_name": buyer.full_name,
        "buyer_phone": buyer.phone, "buyer_email": buyer.email, "store_name": store.store_name,
        "status": order.status.value, "total_amount": float(order.total_amount),
        "created_at": order.created_at,
        "delivery_person_id": assignment.delivery_person_id if assignment else None,
    } for order, buyer, store, assignment in rows]


@router.put("/orders/{order_id}/delivery-assignment")
def assign_delivery_person(order_id: str, payload: schemas.DeliveryAssignmentRequest, db: Session = Depends(get_db)):
    order = db.query(models.Order).filter(models.Order.id == order_id).first()
    profile = (db.query(models.DeliveryProfile)
               .filter(models.DeliveryProfile.id == payload.delivery_person_id,
                       models.DeliveryProfile.status == models.DeliveryStatus.approved).first())
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    if not profile:
        raise HTTPException(status_code=400, detail="Choose an approved delivery person")
    assignment = db.query(models.OrderDeliveryAssignment).filter(models.OrderDeliveryAssignment.order_id == order.id).first()
    if assignment:
        assignment.delivery_person_id = profile.id
        assignment.assignment_note = payload.assignment_note
    else:
        assignment = models.OrderDeliveryAssignment(order_id=order.id, delivery_person_id=profile.id, assignment_note=payload.assignment_note)
        db.add(assignment)
    db.commit()
    db.refresh(order)
    return schemas.OrderOut.model_validate(order)


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

    try:
        send_email(
            store.owner.email,
            "Your EraVenda store has been approved!",
            (
                f"Hi {(store.owner.full_name or '').split(' ')[0] or 'there'},\n\n"
                f"Good news — {store.store_name} is now approved and live on EraVenda Market.\n\n"
                "Add your products and they'll go live after a quick review, same as your store did.\n\n"
                f"Go to your seller dashboard:\n{SITE_URL}/seller/dashboard.html\n\n"
                "— The EraVenda Market team"
            ),
        )
    except Exception:
        logger.exception("Could not send store approval email for store %s", store.id)
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

    try:
        reason_line = f"\nReason given: {payload.rejection_reason}\n" if payload.rejection_reason else ""
        send_email(
            store.owner.email,
            "Update on your EraVenda store application",
            (
                f"Hi {(store.owner.full_name or '').split(' ')[0] or 'there'},\n\n"
                f"Your store application for {store.store_name} wasn't approved this time.\n"
                f"{reason_line}\n"
                f"You're welcome to update your details and reapply any time here:\n{SITE_URL}/seller/dashboard.html\n\n"
                f"If you'd like more feedback, just reply to this email or reach us at {SUPPORT_EMAIL}.\n\n"
                "— The EraVenda Market team"
            ),
        )
    except Exception:
        logger.exception("Could not send store rejection email for store %s", store.id)
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

    try:
        send_email(
            profile.user.email,
            "You're approved on EraVenda Services!",
            (
                f"Hi {(profile.user.full_name or '').split(' ')[0] or 'there'},\n\n"
                f"Good news — your {profile.custom_job_title or profile.job_title} profile is now "
                "approved and live. Clients can find and book you starting now.\n\n"
                f"Go to your dashboard:\n{SITE_URL}/professional/dashboard.html\n\n"
                "— The EraVenda Market team"
            ),
        )
    except Exception:
        logger.exception("Could not send service-worker approval email for profile %s", profile.id)
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
    if payload.quoted_amount is not None or payload.escrow_amount is not None:
        base_amount = float(payload.escrow_amount if payload.escrow_amount is not None else payload.quoted_amount)
        booking.quoted_amount = base_amount
        booking.escrow_amount = service_charge_for(base_amount)
        booking.commission_amount = service_commission_for(base_amount)
        booking.payout_amount = base_amount
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
            .options(selectinload(models.ServiceBooking.photos), selectinload(models.ServiceBooking.review))
            .order_by(models.ServiceBooking.created_at.desc()).all())
    result = []
    for booking, worker, client in rows:
        professional = worker.user
        review = booking.review
        result.append(schemas.AdminServiceBookingOut(
            id=booking.id, handyman_id=worker.id, professional_name=worker.professional_name,
            company_name=worker.company_name, professional_email=professional.email,
            professional_phone=professional.phone, client_name=client.full_name,
            client_email=client.email, client_phone=client.phone, details=booking.details,
            location=booking.location, preferred_contact=booking.preferred_contact,
            contact_details=booking.contact_details, quoted_amount=booking.quoted_amount,
            escrow_amount=booking.escrow_amount, commission_amount=booking.commission_amount,
            payout_amount=booking.payout_amount, payout_status=booking.payout_status,
            payout_held=booking.payout_held, payout_note=booking.payout_note,
            paid_at=booking.paid_at, payout_released_at=booking.payout_released_at,
            photo_count=len(booking.photos), rating=review.rating if review else None,
            review_comment=review.comment if review else None,
            status=booking.status, created_at=booking.created_at
        ))
    return result


@router.get("/services/bookings/{booking_id}/photos", response_model=list[schemas.ServiceJobPhotoOut])
def admin_booking_photos(booking_id: str, db: Session = Depends(get_db)):
    """Work-verification photos for an admin to audit before releasing a payout."""
    booking = (db.query(models.ServiceBooking).options(selectinload(models.ServiceBooking.photos))
               .filter(models.ServiceBooking.id == booking_id).first())
    if not booking:
        raise HTTPException(status_code=404, detail="Service booking not found")
    return sorted(booking.photos, key=lambda p: p.created_at)


@router.put("/services/bookings/{booking_id}/payout", response_model=schemas.AdminServiceBookingOut)
def set_booking_payout(booking_id: str, payload: schemas.ServicePayoutAction, db: Session = Depends(get_db)):
    """Manually release or hold a handyman's payout — the audit control for
    disputed or unverified work. Release requires the seeker to have paid."""
    booking = (db.query(models.ServiceBooking).options(selectinload(models.ServiceBooking.photos), selectinload(models.ServiceBooking.review))
               .filter(models.ServiceBooking.id == booking_id).first())
    if not booking:
        raise HTTPException(status_code=404, detail="Service booking not found")

    if payload.action == "release":
        if booking.status != models.ServiceBookingStatus.completed:
            raise HTTPException(status_code=400, detail="Payout can only be released after the seeker has paid")
        booking.payout_status = models.PayoutStatus.paid
        booking.payout_held = False
        booking.status = models.ServiceBookingStatus.released
        booking.payout_released_at = datetime.utcnow()
        booking.payout_note = payload.note
    else:  # hold
        booking.payout_held = True
        booking.payout_note = payload.note or "Payout held for review"

    db.commit(); db.refresh(booking)
    worker = db.query(models.HandymanProfile).filter(models.HandymanProfile.id == booking.handyman_id).first()
    professional = worker.user if worker else None
    review = booking.review
    return schemas.AdminServiceBookingOut(
        id=booking.id, handyman_id=booking.handyman_id, professional_name=worker.professional_name if worker else None,
        company_name=worker.company_name if worker else None, professional_email=professional.email if professional else None,
        professional_phone=professional.phone if professional else None, client_name=booking.client.full_name,
        client_email=booking.client.email, client_phone=booking.client.phone, details=booking.details,
        location=booking.location, preferred_contact=booking.preferred_contact,
        contact_details=booking.contact_details, quoted_amount=booking.quoted_amount,
        escrow_amount=booking.escrow_amount, commission_amount=booking.commission_amount,
        payout_amount=booking.payout_amount, payout_status=booking.payout_status,
        payout_held=booking.payout_held, payout_note=booking.payout_note,
        paid_at=booking.paid_at, payout_released_at=booking.payout_released_at,
        photo_count=len(booking.photos), rating=review.rating if review else None,
        review_comment=review.comment if review else None,
        status=booking.status, created_at=booking.created_at,
    )


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

    try:
        send_email(
            profile.user.email,
            "Update on your EraVenda Services application",
            (
                f"Hi {(profile.user.full_name or '').split(' ')[0] or 'there'},\n\n"
                "Your service professional application wasn't approved this time.\n\n"
                f"You're welcome to update your details and reapply any time here:\n{SITE_URL}/services/register\n\n"
                f"If you'd like more feedback, just reply to this email or reach us at {SUPPORT_EMAIL}.\n\n"
                "— The EraVenda Market team"
            ),
        )
    except Exception:
        logger.exception("Could not send service-worker rejection email for profile %s", profile.id)
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


@router.get("/products/pending")
def pending_products(db: Session = Depends(get_db)):
    products = (db.query(models.Product)
                .filter(models.Product.status == models.ProductStatus.pending)
                .options(selectinload(models.Product.store).selectinload(models.Store.owner))
                .order_by(models.Product.created_at.desc())
                .all())
    return [{
        "id": p.id, "name": p.name, "sku": p.sku, "description": p.description,
        "price": float(p.price), "stock_quantity": p.stock_quantity,
        "store_name": p.store.store_name if p.store else "",
        "seller_name": p.store.owner.full_name if p.store and p.store.owner else "",
        "seller_email": p.store.owner.email if p.store and p.store.owner else "",
        "seller_phone": p.store.owner.phone if p.store and p.store.owner else "",
        "created_at": p.created_at,
    } for p in products]


@router.put("/products/{product_id}/approve", response_model=schemas.ProductOut)
def approve_product(product_id: str, db: Session = Depends(get_db)):
    product = db.query(models.Product).filter(models.Product.id == product_id).first()
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")
    product.status = models.ProductStatus.approved
    product.rejection_reason = None
    db.commit()
    db.refresh(product)

    try:
        owner = product.store.owner
        send_email(
            owner.email,
            f"Your product is live: {product.name}",
            (
                f"Hi {(owner.full_name or '').split(' ')[0] or 'there'},\n\n"
                f"{product.name} has been approved and is now visible to buyers on EraVenda Market.\n\n"
                f"View your listing:\n{SITE_URL}/product/{product.id}\n\n"
                "— The EraVenda Market team"
            ),
            items=_product_thumbnail_items(product),
        )
    except Exception:
        logger.exception("Could not send product approval email for product %s", product.id)
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

    try:
        owner = product.store.owner
        reason_line = f"\nReason given: {payload.rejection_reason}\n" if payload.rejection_reason else ""
        send_email(
            owner.email,
            f"Your product listing needs changes: {product.name}",
            (
                f"Hi {(owner.full_name or '').split(' ')[0] or 'there'},\n\n"
                f"{product.name} wasn't approved this time.\n"
                f"{reason_line}\n"
                f"You can edit and resubmit it any time here:\n{SITE_URL}/seller/products.html\n\n"
                f"If you'd like more feedback, just reply to this email or reach us at {SUPPORT_EMAIL}.\n\n"
                "— The EraVenda Market team"
            ),
            items=_product_thumbnail_items(product),
        )
    except Exception:
        logger.exception("Could not send product rejection email for product %s", product.id)
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


@router.put("/products/{product_id}", response_model=schemas.ProductOut)
def admin_update_product(product_id: str, payload: schemas.ProductUpdate, db: Session = Depends(get_db)):
    """Lets an admin edit any seller's product directly — for fixing a listing
    (wrong price, bad description, broken sizes) without going back and forth
    with the seller. Unlike the seller's own PUT /products/{id}, this isn't
    restricted to products in the admin's own store."""
    product = db.query(models.Product).filter(models.Product.id == product_id).first()
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")

    if payload.category_id is not None:
        category = db.query(models.Category).filter(models.Category.id == payload.category_id).first()
        if not category:
            raise HTTPException(status_code=404, detail="Category not found")

    for field, value in payload.model_dump(exclude_unset=True).items():
        if field == "sales_type" and value is None:
            continue
        setattr(product, field, value)

    wholesale.apply_sales_type_rules(product)
    _sync_stock_from_variants(product)
    db.commit()
    db.refresh(product)
    return product


@router.post("/products/{product_id}/images", response_model=schemas.ProductImageOut, status_code=201)
def admin_add_product_image(product_id: str, image_url: str, is_primary: bool = False, db: Session = Depends(get_db)):
    """Admin equivalent of the seller's own image-upload endpoint, without
    the store-ownership restriction, so the admin edit page can add photos
    to any seller's product."""
    product = db.query(models.Product).filter(models.Product.id == product_id).first()
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")

    if is_primary:
        db.query(models.ProductImage).filter(models.ProductImage.product_id == product_id).update(
            {"is_primary": False}
        )

    next_order = (db.query(func.max(models.ProductImage.sort_order))
                  .filter(models.ProductImage.product_id == product_id).scalar() or 0) + 1
    image = models.ProductImage(product_id=product_id, image_url=image_url, is_primary=is_primary, sort_order=next_order)
    db.add(image)
    db.commit()
    db.refresh(image)
    return image


@router.delete("/products/{product_id}/images/{image_id}", status_code=204)
def admin_delete_product_image(product_id: str, image_id: str, db: Session = Depends(get_db)):
    """Admin equivalent of the seller's own image-delete endpoint — no
    store-ownership restriction, so admins can clean up any product's photos."""
    image = db.query(models.ProductImage).filter(
        models.ProductImage.id == image_id, models.ProductImage.product_id == product_id
    ).first()
    if not image:
        raise HTTPException(status_code=404, detail="Image not found")
    was_primary = image.is_primary
    db.delete(image)
    db.flush()
    if was_primary:
        next_image = (db.query(models.ProductImage)
                      .filter(models.ProductImage.product_id == product_id)
                      .order_by(models.ProductImage.sort_order).first())
        if next_image:
            next_image.is_primary = True
    db.commit()


@router.put("/products/{product_id}/images/reorder", response_model=list[schemas.ProductImageOut])
def admin_reorder_product_images(product_id: str, payload: schemas.ProductImageReorder, db: Session = Depends(get_db)):
    images = {img.id: img for img in db.query(models.ProductImage).filter(models.ProductImage.product_id == product_id).all()}
    if not images:
        raise HTTPException(status_code=404, detail="Product not found or has no images")
    if set(payload.image_ids) != set(images.keys()):
        raise HTTPException(status_code=400, detail="image_ids must include every image on this product, exactly once")

    for position, image_id in enumerate(payload.image_ids):
        images[image_id].sort_order = position
        images[image_id].is_primary = (position == 0)
    db.commit()
    return (db.query(models.ProductImage).filter(models.ProductImage.product_id == product_id)
            .order_by(models.ProductImage.sort_order).all())


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
                .options(__import__("sqlalchemy.orm", fromlist=["joinedload"]).joinedload(models.Product.store).joinedload(models.Store.owner))
                .order_by(models.Product.updated_at.desc())
                .limit(300).all())
    return [{
        "id": p.id, "name": p.name, "sku": p.sku, "store_id": p.store_id, "category_id": p.category_id,
        "store_name": p.store.store_name if p.store else "",
        "seller_name": p.store.owner.full_name if p.store and p.store.owner else "",
        "seller_email": p.store.owner.email if p.store and p.store.owner else "",
        "seller_phone": p.store.owner.phone if p.store and p.store.owner else "",
        "price": float(p.discount_price if p.discount_price is not None else p.price),
        "stock_quantity": p.stock_quantity, "status": p.status.value, "badge_keys": p.badge_keys or [],
        "cod_eligible": p.cod_eligible,
        "sales_type": p.sales_type or "retail",
        "wholesale_min_quantity": p.wholesale_min_quantity,
        "updated_at": p.updated_at,
    } for p in products]


@router.get("/products/{product_id}", response_model=schemas.ProductOut)
def admin_get_product(product_id: str, db: Session = Depends(get_db)):
    """Full product detail for the admin edit form — same shape as the
    seller's own product page, so the same edit UI can be reused. Placed
    after the fixed /products/tracking path so it doesn't shadow it."""
    product = db.query(models.Product).filter(models.Product.id == product_id).first()
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")
    return product


# ---------- WHOLESALE MONITORING ----------
# Read-only views over wholesale products and orders. Retail orders are never
# touched; "order_type=all" or "retail" just lets the admin compare. Editing a
# wholesale product's price/minimum/stock goes through the existing
# PUT /admin/products/{id}, which keeps the same validation as the seller side.

WHOLESALE_OPEN_STATUSES = (
    models.OrderStatus.pending, models.OrderStatus.paid,
    models.OrderStatus.processing, models.OrderStatus.shipped,
)
WHOLESALE_CLOSED_STATUSES = (models.OrderStatus.cancelled, models.OrderStatus.refunded)


@router.get("/wholesale/summary")
def wholesale_summary(db: Session = Depends(get_db)):
    """Headline numbers. Pending = not yet delivered and not cancelled
    (pending/paid/processing/shipped); Completed = delivered; Cancelled =
    cancelled or refunded. Sales exclude cancelled/refunded orders."""
    W = models.Order.order_type == "wholesale"

    def order_count(statuses):
        return db.query(func.count(models.Order.id)).filter(W, models.Order.status.in_(statuses)).scalar() or 0

    sales = db.query(func.coalesce(func.sum(models.Order.subtotal), 0)).filter(
        W, ~models.Order.status.in_(WHOLESALE_CLOSED_STATUSES)).scalar() or 0
    wholesale_products = db.query(func.count(models.Product.id)).filter(models.Product.sales_type == "wholesale").scalar() or 0
    live_products = db.query(func.count(models.Product.id)).filter(
        models.Product.sales_type == "wholesale", models.Product.status == models.ProductStatus.approved).scalar() or 0
    sellers = db.query(func.count(func.distinct(models.Product.store_id))).filter(
        models.Product.sales_type == "wholesale").scalar() or 0
    return {
        "wholesale_products": wholesale_products,
        "wholesale_products_live": live_products,
        "wholesale_sellers": sellers,
        "wholesale_orders": db.query(func.count(models.Order.id)).filter(W).scalar() or 0,
        "pending_orders": order_count(WHOLESALE_OPEN_STATUSES),
        "completed_orders": order_count((models.OrderStatus.delivered,)),
        "cancelled_orders": order_count(WHOLESALE_CLOSED_STATUSES),
        "wholesale_sales": float(sales),
        "retail_orders": db.query(func.count(models.Order.id)).filter(models.Order.order_type == "retail").scalar() or 0,
    }


@router.get("/wholesale/products")
def wholesale_products(
    store_id: str | None = None,
    seller_id: str | None = None,
    q: str | None = None,
    sales_type: str = "wholesale",
    db: Session = Depends(get_db),
):
    if sales_type not in ("wholesale", "retail", "all"):
        raise HTTPException(status_code=400, detail="sales_type must be wholesale, retail or all")
    query = (db.query(models.Product).join(models.Store, models.Product.store_id == models.Store.id)
             .options(selectinload(models.Product.store).selectinload(models.Store.owner)))
    if sales_type != "all":
        query = query.filter(models.Product.sales_type == sales_type)
    if store_id:
        query = query.filter(models.Product.store_id == store_id)
    if seller_id:
        query = query.filter(models.Store.owner_id == seller_id)
    if q:
        query = query.filter(models.Product.name.ilike(f"%{q.strip()}%"))
    rows = query.order_by(models.Product.updated_at.desc()).limit(500).all()
    return [{
        "id": p.id, "name": p.name, "sku": p.sku, "status": p.status.value,
        "sales_type": p.sales_type or "retail",
        "wholesale_price": float(p.price) if p.is_wholesale else None,
        "price": float(p.price),
        "wholesale_min_quantity": p.wholesale_min_quantity,
        "stock_quantity": p.stock_quantity,
        "store_id": p.store_id,
        "store_name": p.store.store_name if p.store else "",
        "seller_id": p.store.owner_id if p.store else None,
        "seller_name": p.store.owner.full_name if p.store and p.store.owner else "",
        "updated_at": p.updated_at,
    } for p in rows]


@router.get("/wholesale/orders")
def wholesale_orders(
    order_type: str = "wholesale",
    status: str | None = None,  # pending | completed | cancelled (groups) or an exact order status
    store_id: str | None = None,
    seller_id: str | None = None,
    product_id: str | None = None,
    q: str | None = None,  # order number or buyer name/email
    date_from: str | None = None,  # YYYY-MM-DD
    date_to: str | None = None,
    db: Session = Depends(get_db),
):
    if order_type not in ("wholesale", "retail", "all"):
        raise HTTPException(status_code=400, detail="order_type must be wholesale, retail or all")
    query = (db.query(models.Order)
             .join(models.Store, models.Order.store_id == models.Store.id)
             .join(models.User, models.Order.buyer_id == models.User.id)
             .options(selectinload(models.Order.items), selectinload(models.Order.store).selectinload(models.Store.owner)))
    if order_type != "all":
        query = query.filter(models.Order.order_type == order_type)
    if status:
        groups = {"pending": WHOLESALE_OPEN_STATUSES, "completed": (models.OrderStatus.delivered,), "cancelled": WHOLESALE_CLOSED_STATUSES}
        if status in groups:
            query = query.filter(models.Order.status.in_(groups[status]))
        else:
            try:
                query = query.filter(models.Order.status == models.OrderStatus(status))
            except ValueError:
                raise HTTPException(status_code=400, detail="Unknown order status")
    if store_id:
        query = query.filter(models.Order.store_id == store_id)
    if seller_id:
        query = query.filter(models.Store.owner_id == seller_id)
    if product_id:
        query = query.filter(models.Order.id.in_(
            db.query(models.OrderItem.order_id).filter(models.OrderItem.product_id == product_id)))
    if q:
        like = f"%{q.strip()}%"
        query = query.filter(or_(models.Order.order_number.ilike(like), models.User.full_name.ilike(like), models.User.email.ilike(like)))
    try:
        if date_from:
            query = query.filter(models.Order.created_at >= datetime.strptime(date_from, "%Y-%m-%d"))
        if date_to:
            query = query.filter(models.Order.created_at < datetime.strptime(date_to, "%Y-%m-%d") + timedelta(days=1))
    except ValueError:
        raise HTTPException(status_code=400, detail="Dates must be in YYYY-MM-DD format")

    orders = query.order_by(models.Order.created_at.desc()).limit(500).all()
    buyers = {u.id: u for u in db.query(models.User).filter(models.User.id.in_({o.buyer_id for o in orders})).all()} if orders else {}
    result = []
    for o in orders:
        buyer = buyers.get(o.buyer_id)
        owner = o.store.owner if o.store else None
        lines = [{
            "product_id": i.product_id, "product_name": i.product_name, "unit_price": float(i.unit_price),
            "quantity": i.quantity, "line_total": float(i.line_total),
            "minimum_quantity": i.wholesale_min_quantity,
        } for i in o.items]
        # Minimum is counted per product across variant lines, same as checkout.
        per_product: dict[str, int] = {}
        for i in o.items:
            per_product[i.product_id] = per_product.get(i.product_id, 0) + i.quantity
        met = all(
            per_product[i.product_id] >= i.wholesale_min_quantity
            for i in o.items if i.wholesale_min_quantity
        ) if o.order_type == "wholesale" else None
        result.append({
            "id": o.id, "order_number": o.order_number, "order_type": o.order_type,
            "status": o.status.value, "created_at": o.created_at,
            "buyer_id": o.buyer_id, "buyer_name": buyer.full_name if buyer else "", "buyer_email": buyer.email if buyer else "",
            "store_id": o.store_id, "store_name": o.store.store_name if o.store else "",
            "seller_id": o.store.owner_id if o.store else None, "seller_name": owner.full_name if owner else "",
            "total_quantity": o.total_quantity, "order_value": float(o.subtotal), "total_amount": float(o.total_amount),
            "met_minimum": met, "items": lines,
        })
    return result


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
        "payment_method": order.payment_method.value, "commission_amount": float(order.commission_amount),
        "delivery_fee": float(order.delivery_fee),
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

    # Same admin/buyer/seller emails an online payment triggers — see
    # _notify_product_payment's docstring for why this calls the notification
    # half only, not _finalize_product_payment (which would override the
    # already-delivered guard above).
    from .payments import _notify_product_payment
    try:
        _notify_product_payment(db, payment, order)
    except Exception:
        logger.exception("Could not send COD payment notifications for order %s", order.id)

    return {"id": payment.id, "order_number": order.order_number, "amount": float(payment.amount), "reference": payment.provider_reference, "status": payment.status.value}


@router.get("/users", response_model=list[schemas.UserOut])
def list_users(db: Session = Depends(get_db)):
    users = db.query(models.User).order_by(models.User.created_at.desc()).all()
    # A handyman isn't a UserRole — see the field's docstring in schemas.py —
    # so "is this user a professional" is answered by a second, cheap query
    # rather than N+1 queries or a join that complicates the ordering above.
    professional_ids = {
        row[0] for row in db.query(models.HandymanProfile.user_id).all()
    }
    out = []
    for user in users:
        item = schemas.UserOut.model_validate(user)
        item.is_professional = user.id in professional_ids
        out.append(item)
    return out


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
def platform_stats(
    db: Session = Depends(get_db),
    end_month: str | None = None,  # "YYYY-MM" — last month of the trailing-12 window; defaults to the current month
    show_all: bool = False,  # ignore the 12-month window and bucket every month since the first paid transaction
):
    total_orders = db.query(func.count(models.Order.id)).scalar() or 0
    paid_product_rows = (db.query(models.Payment, models.Order)
                         .join(models.Order, models.Payment.order_id == models.Order.id)
                         .filter(models.Payment.status == models.PaymentStatus.success)
                         .all())
    paid_service_rows = (db.query(models.ServiceBooking)
                         .filter(models.ServiceBooking.status.in_([
                             models.ServiceBookingStatus.completed,
                             models.ServiceBookingStatus.released,
                         ]))
                         .filter(models.ServiceBooking.paid_at.isnot(None))
                         .all())
    product_income = sum(float(payment.amount or 0) for payment, _order in paid_product_rows)
    product_commissions = sum(float(order.commission_amount or 0) for _payment, order in paid_product_rows)
    service_income = sum(float(booking.escrow_amount or 0) for booking in paid_service_rows)
    service_commissions = sum(float(booking.commission_amount or 0) for booking in paid_service_rows)
    total_commissions = product_commissions + service_commissions
    # Seller subscriptions and promoted listings are platform revenue too, but
    # they are not commissions, so they get their own lines.
    def _charge_total(kind: str) -> float:
        return float(db.query(func.coalesce(func.sum(models.StoreCharge.amount), 0)).filter(
            models.StoreCharge.kind == kind, models.StoreCharge.status == models.PaymentStatus.success,
        ).scalar() or 0)
    subscription_revenue = _charge_total("subscription")
    promotion_revenue = _charge_total("promotion")
    paid_charge_rows = (db.query(models.StoreCharge)
                        .filter(models.StoreCharge.status == models.PaymentStatus.success)
                        .all())

    try:
        anchor_month = (datetime.strptime(end_month, "%Y-%m") if end_month
                         else datetime.utcnow()).replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    except ValueError:
        raise HTTPException(status_code=400, detail="end_month must be in YYYY-MM format")

    if show_all:
        all_paid_dates = [p.paid_at for p, _o in paid_product_rows if p.paid_at] + \
                          [b.paid_at for b in paid_service_rows if b.paid_at] + \
                          [c.paid_at for c in paid_charge_rows if c.paid_at]
        earliest = min(all_paid_dates) if all_paid_dates else anchor_month
        months_span = (anchor_month.year - earliest.year) * 12 + (anchor_month.month - earliest.month)
    else:
        months_span = 11  # trailing 12 months (11 months back + the anchor month itself)

    monthly = []
    for month_offset in range(months_span, -1, -1):
        year, month = anchor_month.year, anchor_month.month - month_offset
        while month <= 0:
            year -= 1
            month += 12
        while month > 12:
            year += 1
            month -= 12
        month_start = anchor_month.replace(year=year, month=month)
        last_day = monthrange(year, month)[1]
        month_end = month_start.replace(day=last_day, hour=23, minute=59, second=59, microsecond=999999)
        month_products = [
            (payment, order) for payment, order in paid_product_rows
            if payment.paid_at and month_start <= payment.paid_at <= month_end
        ]
        month_services = [
            booking for booking in paid_service_rows
            if booking.paid_at and month_start <= booking.paid_at <= month_end
        ]
        month_product_income = sum(float(payment.amount or 0) for payment, _order in month_products)
        month_product_commission = sum(float(order.commission_amount or 0) for _payment, order in month_products)
        month_service_income = sum(float(booking.escrow_amount or 0) for booking in month_services)
        month_service_commission = sum(float(booking.commission_amount or 0) for booking in month_services)
        month_charges = [c for c in paid_charge_rows if c.paid_at and month_start <= c.paid_at <= month_end]
        month_subs = [c for c in month_charges if c.kind == "subscription"]
        month_promos = [c for c in month_charges if c.kind == "promotion"]
        monthly.append({
            "month": month_start.strftime("%Y-%m"),
            "subscription_revenue": sum(float(c.amount or 0) for c in month_subs),
            "promotion_revenue": sum(float(c.amount or 0) for c in month_promos),
            "subscriptions_sold": len(month_subs),
            "promotions_sold": len(month_promos),
            "product_income": month_product_income,
            "product_commissions": month_product_commission,
            "service_income": month_service_income,
            "service_commissions": month_service_commission,
            "total_income": month_product_income + month_service_income,
            "total_commissions": month_product_commission + month_service_commission,
            "orders": len(month_products),
            "bookings": len(month_services),
        })
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

    now = datetime.utcnow()
    this_month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    sub_charges = [c for c in paid_charge_rows if c.kind == "subscription"]
    promo_charges = [c for c in paid_charge_rows if c.kind == "promotion"]
    all_subs = db.query(models.SellerSubscription).all()
    live_subs = [x for x in all_subs if x.status == "active" and x.current_period_end > now]
    all_promos = db.query(models.PromotedListing).filter(models.PromotedListing.status != "pending").all()
    live_promos = [x for x in all_promos if x.status == "active" and x.starts_at and x.ends_at and x.starts_at <= now < x.ends_at]
    monetization = {
        "subscriptions": {
            "revenue_total": subscription_revenue,
            "revenue_this_month": sum(float(c.amount or 0) for c in sub_charges if c.paid_at and c.paid_at >= this_month_start),
            "active_subscribers": len(live_subs),
            "paid_active": len([x for x in live_subs if not x.granted_by_admin]),
            "granted_active": len([x for x in live_subs if x.granted_by_admin]),
            "ended_or_expired": len(all_subs) - len(live_subs),
            "total_stores_ever": len(all_subs),
            "payments": len(sub_charges),
            "months_sold": sum(max(0, c.quantity or 0) for c in sub_charges),
            "monthly_recurring": round(sum(float(x.monthly_fee or 0) for x in live_subs if not x.granted_by_admin), 2),
            "avg_payment": round(subscription_revenue / len(sub_charges), 2) if sub_charges else 0.0,
        },
        "promotions": {
            "revenue_total": promotion_revenue,
            "revenue_this_month": sum(float(c.amount or 0) for c in promo_charges if c.paid_at and c.paid_at >= this_month_start),
            "live_now": len(live_promos),
            "live_product": len([x for x in live_promos if x.product_id]),
            "live_store_wide": len([x for x in live_promos if not x.product_id]),
            "paid_total": len(promo_charges),
            "granted_total": len([x for x in all_promos if x.granted_by_admin]),
            "weeks_sold": sum(max(0, c.quantity or 0) for c in promo_charges),
            "avg_spend": round(promotion_revenue / len(promo_charges), 2) if promo_charges else 0.0,
            "stores_promoting": len({x.store_id for x in live_promos}),
        },
    }

    return {
        "total_orders": total_orders,
        "monetization": monetization,
        "platform_revenue": float(total_commissions) + subscription_revenue + promotion_revenue,
        "overall": {
            "product_income": product_income,
            "product_commissions": product_commissions,
            "service_income": service_income,
            "service_commissions": service_commissions,
            "total_income": product_income + service_income,
            "total_commissions": total_commissions,
            "subscription_revenue": subscription_revenue,
            "promotion_revenue": promotion_revenue,
            "paid_orders": len(paid_product_rows),
            "paid_bookings": len(paid_service_rows),
        },
        "monthly": monthly,
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

@router.get("/traffic")
def traffic_and_purchases(db: Session = Depends(get_db)):
    """Visits next to purchases, for the dashboard's "Traffic & purchases"
    card. A visitor is one browser (random ID, see models.SiteVisit). A paid
    order is one that reached paid, processing, shipped or delivered; orders
    are dated by when they were placed. Ghana is on UTC all year, so the
    "today" boundary here is also midnight in Ghana."""
    now = datetime.utcnow()
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    paid_statuses = [
        models.OrderStatus.paid,
        models.OrderStatus.processing,
        models.OrderStatus.shipped,
        models.OrderStatus.delivered,
    ]

    def period(since: datetime | None) -> dict:
        visits = db.query(models.SiteVisit)
        orders = db.query(models.Order).filter(models.Order.status != models.OrderStatus.cancelled)
        if since is not None:
            visits = visits.filter(models.SiteVisit.created_at >= since)
            orders = orders.filter(models.Order.created_at >= since)
        paid = orders.filter(models.Order.status.in_(paid_statuses))
        visitors = visits.with_entities(func.count(func.distinct(models.SiteVisit.visitor_id))).scalar() or 0
        buyers = paid.with_entities(func.count(func.distinct(models.Order.buyer_id))).scalar() or 0
        return {
            "visitors": visitors,
            "page_views": visits.count(),
            "orders_placed": orders.count(),
            "paid_orders": paid.count(),
            "buyers": buyers,
            "conversion_pct": round(buyers / visitors * 100, 1) if visitors else None,
        }

    week_start = now - timedelta(days=7)
    top_pages = (
        db.query(models.SiteVisit.path, func.count(models.SiteVisit.id).label("views"))
        .filter(models.SiteVisit.created_at >= week_start)
        .group_by(models.SiteVisit.path)
        .order_by(func.count(models.SiteVisit.id).desc())
        .limit(5)
        .all()
    )
    return {
        "today": period(today_start),
        "last_7_days": period(week_start),
        "last_30_days": period(now - timedelta(days=30)),
        "all_time": period(None),
        "top_pages_7_days": [{"path": path, "views": views} for path, views in top_pages],
        "tracking_since": db.query(func.min(models.SiteVisit.created_at)).scalar(),
    }


class WeightBandIn(BaseModel):
    up_to_kg: float | None = None
    surcharge: float


class DeliveryFeesIn(BaseModel):
    base_city: str = Field(min_length=1, max_length=100)
    fee_same_neighbourhood: float = Field(ge=0, le=delivery_fees.MAX_FEE)
    fee_base_city_other_area: float = Field(ge=0, le=delivery_fees.MAX_FEE)
    fee_same_city: float = Field(ge=0, le=delivery_fees.MAX_FEE)
    fee_same_region: float = Field(ge=0, le=delivery_fees.MAX_FEE)
    fee_other_region: float = Field(ge=0, le=delivery_fees.MAX_FEE)
    # Optional so a dashboard page opened before this update can still save.
    free_delivery_enabled: bool | None = None
    free_delivery_min_order: float | None = Field(default=None, gt=0, le=100000)
    weight_pricing_enabled: bool
    default_item_weight_kg: float = Field(gt=0, le=delivery_fees.MAX_WEIGHT_KG)
    weight_bands: list[WeightBandIn]


def _delivery_fees_out(row: models.DeliveryFeeSettings) -> dict:
    return {
        "base_city": row.base_city,
        **{key: float(getattr(row, key)) for key in delivery_fees.DISTANCE_BAND_LABELS},
        "distance_labels": delivery_fees.DISTANCE_BAND_LABELS,
        "free_delivery_enabled": bool(row.free_delivery_enabled),
        "free_delivery_min_order": float(row.free_delivery_min_order),
        "weight_pricing_enabled": bool(row.weight_pricing_enabled),
        "default_item_weight_kg": float(row.default_item_weight_kg),
        "weight_bands": delivery_fees.bands_of(row),
        "updated_at": row.updated_at,
        "updated_by": row.updated_by,
    }


@router.get("/delivery-fees")
def get_delivery_fees(db: Session = Depends(get_db)):
    return _delivery_fees_out(delivery_fees.get_settings(db))


@router.put("/delivery-fees")
def update_delivery_fees(
    payload: DeliveryFeesIn,
    db: Session = Depends(get_db),
    current_admin: models.User = Depends(auth.get_current_user),
):
    """Save new delivery fee rules. They apply to every quote and order from
    this moment; orders already placed keep the fee they were charged."""
    bands = [{"up_to_kg": b.up_to_kg, "surcharge": b.surcharge} for b in payload.weight_bands]
    problems = delivery_fees.validate_bands(bands)
    if problems:
        raise HTTPException(status_code=422, detail=" ".join(problems))
    row = delivery_fees.get_settings(db)
    row.base_city = payload.base_city.strip()
    for key in delivery_fees.DISTANCE_BAND_LABELS:
        setattr(row, key, getattr(payload, key))
    if payload.free_delivery_enabled is not None:
        row.free_delivery_enabled = payload.free_delivery_enabled
    if payload.free_delivery_min_order is not None:
        row.free_delivery_min_order = payload.free_delivery_min_order
    row.weight_pricing_enabled = payload.weight_pricing_enabled
    row.default_item_weight_kg = payload.default_item_weight_kg
    row.weight_bands = bands
    row.updated_by = current_admin.full_name or current_admin.email
    db.commit()
    db.refresh(row)
    return _delivery_fees_out(row)


@router.get("/stats/top-stores")
def top_stores_by_revenue(limit: int = 8, db: Session = Depends(get_db)):
    """Stores ranked by paid product income, for the admin income/commission
    analysis view. Only counts successful payments, same as /admin/stats."""
    rows = (
        db.query(
            models.Store.id,
            models.Store.store_name,
            func.sum(models.Payment.amount).label("income"),
            func.sum(models.Order.commission_amount).label("commission"),
            func.count(func.distinct(models.Order.id)).label("orders"),
        )
        .join(models.Order, models.Order.store_id == models.Store.id)
        .join(models.Payment, models.Payment.order_id == models.Order.id)
        .filter(models.Payment.status == models.PaymentStatus.success)
        .group_by(models.Store.id, models.Store.store_name)
        .order_by(func.sum(models.Payment.amount).desc())
        .limit(limit)
        .all()
    )
    return [
        {
            "store_id": r.id,
            "store_name": r.store_name,
            "income": float(r.income or 0),
            "commission": float(r.commission or 0),
            "orders": r.orders,
        }
        for r in rows
    ]


# -------------------- Publicity badges --------------------
BADGE_CATALOG = {
    "verified": {"label": "Verified", "icon": "badge-check", "tone": "brand"},
    "top-rated": {"label": "Top Rated", "icon": "star", "tone": "amber"},
    "award-winner": {"label": "Award Winner", "icon": "trophy", "tone": "violet"},
    "customer-choice": {"label": "Customer Choice", "icon": "heart", "tone": "rose"},
    "trusted": {"label": "Trusted Seller", "icon": "shield-check", "tone": "blue"},
    "safety-checked": {"label": "Safety Checked", "icon": "shield", "tone": "emerald"},
    "best-value": {"label": "Best Value", "icon": "badge-dollar-sign", "tone": "green"},
    "new-and-rising": {"label": "New & Rising", "icon": "trending-up", "tone": "indigo"},
    "community-favorite": {"label": "Community Favorite", "icon": "users", "tone": "orange"},
    "quality-pick": {"label": "Quality Pick", "icon": "gem", "tone": "purple"},
}

@router.get("/badges/catalog")
def badge_catalog(current_user: models.User = Depends(auth.require_role(models.UserRole.admin))):
    return BADGE_CATALOG

@router.patch("/stores/{store_id}/badges")
def set_store_badges(store_id: str, payload: dict, db: Session = Depends(get_db), current_user: models.User = Depends(auth.require_role(models.UserRole.admin))):
    store = db.query(models.Store).filter(models.Store.id == store_id).first()
    if not store: raise HTTPException(status_code=404, detail="Store not found")
    keys = [k for k in (payload.get("badge_keys") or []) if k in BADGE_CATALOG]
    store.badge_keys = keys
    db.commit(); db.refresh(store)
    return {"badge_keys": keys}

@router.patch("/products/{product_id}/badges")
def set_product_badges(product_id: str, payload: dict, db: Session = Depends(get_db), current_user: models.User = Depends(auth.require_role(models.UserRole.admin))):
    product = db.query(models.Product).filter(models.Product.id == product_id).first()
    if not product: raise HTTPException(status_code=404, detail="Product not found")
    keys = [k for k in (payload.get("badge_keys") or []) if k in BADGE_CATALOG]
    product.badge_keys = keys
    db.commit(); db.refresh(product)
    return {"badge_keys": keys}

@router.patch("/professionals/{handyman_id}/badges")
def set_professional_badges(handyman_id: str, payload: dict, db: Session = Depends(get_db), current_user: models.User = Depends(auth.require_role(models.UserRole.admin))):
    worker = db.query(models.HandymanProfile).filter(models.HandymanProfile.id == handyman_id).first()
    if not worker: raise HTTPException(status_code=404, detail="Professional not found")
    keys = [k for k in (payload.get("badge_keys") or []) if k in BADGE_CATALOG]
    worker.badge_keys = keys
    db.commit(); db.refresh(worker)
    return {"badge_keys": keys}

@router.patch("/professionals/{handyman_id}/safety-rating")
def set_professional_safety_rating(handyman_id: str, payload: dict, db: Session = Depends(get_db)):
    worker = db.query(models.HandymanProfile).filter(models.HandymanProfile.id == handyman_id).first()
    if not worker: raise HTTPException(status_code=404, detail="Professional not found")
    try: value = float(payload.get("safety_rating"))
    except (TypeError, ValueError): raise HTTPException(status_code=400, detail="Safety rating must be a number")
    if not 0 <= value <= 5: raise HTTPException(status_code=400, detail="Safety rating must be between 0 and 5")
    worker.safety_rating = value
    db.commit(); return {"safety_rating": value}

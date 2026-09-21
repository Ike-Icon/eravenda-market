from datetime import datetime
from calendar import monthrange
from fastapi import APIRouter, Depends, HTTPException  # pyright: ignore[reportMissingImports]
from fastapi.responses import FileResponse  # pyright: ignore[reportMissingImports]
from pathlib import Path
from sqlalchemy.orm import Session, selectinload  # pyright: ignore[reportMissingImports]
from sqlalchemy import func  # pyright: ignore[reportMissingImports]
from sqlalchemy.exc import IntegrityError  # pyright: ignore[reportMissingImports]

from .. import models, schemas, auth
from ..database import get_db
from ..service_pricing import service_charge_for, service_commission_for
from ..email_utils import send_email, SITE_URL
from .products import _sync_stock_from_variants
import logging

logger = logging.getLogger("eravenda.admin")

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
    """Permanently remove a delivery profile and its linked user account."""
    profile = (db.query(models.DeliveryProfile)
               .filter(models.DeliveryProfile.id == profile_id)
               .first())
    if not profile:
        raise HTTPException(status_code=404, detail="Delivery profile not found")
    user = profile.user
    try:
        # Remove the profile first, then the account, so it disappears from both lists.
        db.delete(profile)
        db.flush()
        db.delete(user)
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=400,
            detail="Can't delete this delivery person because they have existing delivery assignments. Suspend the account instead.",
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
                .join(models.Store, models.Product.store_id == models.Store.id)
                .options(__import__("sqlalchemy.orm", fromlist=["joinedload"]).joinedload(models.Product.store).joinedload(models.Store.owner))
                .filter(models.Product.status == models.ProductStatus.pending)
                .order_by(models.Product.created_at.desc())
                .all())
    return [{
        "id": p.id, "store_id": p.store_id, "category_id": p.category_id,
        "name": p.name, "slug": p.slug, "description": p.description,
        "brand": p.brand, "condition": p.condition.value, "sku": p.sku,
        "price": float(p.discount_price if p.discount_price is not None else p.price),
        "stock_quantity": p.stock_quantity, "status": p.status.value,
        "rejection_reason": p.rejection_reason,
        "seller": {
            "name": p.store.owner.full_name if p.store and p.store.owner else "Unknown seller",
            "email": p.store.owner.email if p.store and p.store.owner else "",
            "phone": p.store.owner.phone if p.store and p.store.owner else None,
            "store_name": p.store.store_name if p.store else "",
            "city": p.store.city if p.store else None,
            "region": p.store.region if p.store else None,
        },
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
        setattr(product, field, value)

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
        "id": p.id, "name": p.name, "sku": p.sku, "store_name": p.store.store_name if p.store else "",
        "seller_name": p.store.owner.full_name if p.store and p.store.owner else "",
        "seller_email": p.store.owner.email if p.store and p.store.owner else "",
        "seller_phone": p.store.owner.phone if p.store and p.store.owner else "",
        "price": float(p.discount_price if p.discount_price is not None else p.price),
        "stock_quantity": p.stock_quantity, "status": p.status.value, "badge_keys": p.badge_keys or [],
        "cod_eligible": p.cod_eligible,
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
def platform_stats(period: str = "last12", db: Session = Depends(get_db)):
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

    current_month = datetime.utcnow().replace(day=1, hour=0, minute=0, second=0, microsecond=0)

    # Supported views: last12 (default), all, or a specific YYYY-MM month.
    selected_month = None
    if period not in {"last12", "all"}:
        try:
            selected_month = datetime.strptime(period, "%Y-%m").replace(day=1)
        except ValueError:
            period = "last12"

    if period == "all":
        paid_dates = [
            *(payment.paid_at for payment, _order in paid_product_rows if payment.paid_at),
            *(booking.paid_at for booking in paid_service_rows if booking.paid_at),
        ]
        first_month = min(paid_dates).replace(day=1, hour=0, minute=0, second=0, microsecond=0) if paid_dates else current_month
        month_count = (current_month.year - first_month.year) * 12 + current_month.month - first_month.month + 1
        month_offsets = range(month_count - 1, -1, -1)
    elif selected_month is not None:
        first_month = selected_month
        month_offsets = range(0, 1)
    else:
        month_offsets = range(11, -1, -1)

    monthly = []
    for month_offset in month_offsets:
        if selected_month is not None:
            year, month = selected_month.year, selected_month.month
        else:
            year, month = current_month.year, current_month.month - month_offset
            while month <= 0:
                year -= 1
                month += 12
        month_start = current_month.replace(year=year, month=month)
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
        monthly.append({
            "month": month_start.strftime("%Y-%m"),
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

    return {
        "total_orders": total_orders,
        "platform_revenue": float(total_commissions),
        "overall": {
            "product_income": product_income,
            "product_commissions": product_commissions,
            "service_income": service_income,
            "service_commissions": service_commissions,
            "total_income": product_income + service_income,
            "total_commissions": total_commissions,
            "paid_orders": len(paid_product_rows),
            "paid_bookings": len(paid_service_rows),
        },
        "monthly": monthly,
        "period": period,
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

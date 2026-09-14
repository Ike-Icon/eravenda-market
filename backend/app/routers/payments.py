import os
import logging
from datetime import datetime

import httpx  # type: ignore[reportMissingImports]
from fastapi import APIRouter, Depends, HTTPException  # type: ignore[reportMissingImports]
from sqlalchemy.orm import Session  # type: ignore[reportMissingImports]

from .. import models, schemas, auth
from ..database import get_db
from ..email_utils import ADMIN_NOTIFICATION_EMAIL, send_email
from ..service_pricing import service_commission_for

router = APIRouter(prefix="/payments", tags=["payments"])

PAYSTACK_SECRET_KEY = os.getenv("PAYSTACK_SECRET_KEY", "")
PAYSTACK_BASE_URL = "https://api.paystack.co"
SITE_URL = os.getenv("SITE_URL", "http://localhost:8000")
logger = logging.getLogger("eravenda.payments")


def _paystack_headers() -> dict:
    if not PAYSTACK_SECRET_KEY:
        raise HTTPException(
            status_code=500,
            detail="Payments aren't configured yet — set PAYSTACK_SECRET_KEY in the backend's .env.",
        )
    return {"Authorization": f"Bearer {PAYSTACK_SECRET_KEY}", "Content-Type": "application/json"}


def _call_paystack(method: str, path: str, **kwargs) -> dict:
    """Isolated so it's easy to mock in tests — this is the only function
    that actually talks to Paystack's network."""
    try:
        with httpx.Client(timeout=15.0) as client:
            res = client.request(method, f"{PAYSTACK_BASE_URL}{path}", headers=_paystack_headers(), **kwargs)
    except httpx.RequestError:
        raise HTTPException(status_code=502, detail="Could not reach Paystack. Please try again.")

    data = res.json()
    if not data.get("status"):
        raise HTTPException(status_code=502, detail=data.get("message", "Paystack rejected the request."))
    return data["data"]


@router.post("/initialize", response_model=schemas.PaymentInitOut)
def initialize_payment(
    payload: schemas.PaymentInitRequest,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_user),
):
    order = db.query(models.Order).filter(models.Order.id == payload.order_id).first()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    if order.buyer_id != current_user.id:
        raise HTTPException(status_code=403, detail="This isn't your order")
    if order.status != models.OrderStatus.pending:
        raise HTTPException(status_code=400, detail=f"This order is already {order.status.value}")

    # A buyer may switch a pending pay-on-delivery order to online payment
    # later. Once online payment is initialized, the order is treated as a
    # mobile-money payment order.
    order.payment_method = models.PaymentMethod.mobile_money
    amount_pesewas = int(round(float(order.total_amount) * 100))
    reference = f"ERV-{order.order_number}-{os.urandom(3).hex()}"

    data = _call_paystack(
        "POST", "/transaction/initialize",
        json={
            "email": current_user.email,
            "amount": amount_pesewas,
            "reference": reference,
            "currency": "GHS",
            "callback_url": f"{SITE_URL}/payments/callback",
            "metadata": {"order_id": order.id, "order_number": order.order_number},
        },
    )

    payment = models.Payment(
        order_id=order.id,
        provider="paystack",
        provider_reference=reference,
        amount=order.total_amount,
        currency="GHS",
        status=models.PaymentStatus.pending,
    )
    db.add(payment)
    db.commit()

    return schemas.PaymentInitOut(
        authorization_url=data["authorization_url"],
        access_code=data["access_code"],
        reference=reference,
    )


@router.get("/verify/{reference}", response_model=schemas.PaymentVerifyOut)
def verify_payment(
    reference: str,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_user),
):
    payment = db.query(models.Payment).filter(models.Payment.provider_reference == reference).first()
    if not payment:
        raise HTTPException(status_code=404, detail="Payment not found")

    order = db.query(models.Order).filter(models.Order.id == payment.order_id).first()
    if order.buyer_id != current_user.id and current_user.role != models.UserRole.admin:
        raise HTTPException(status_code=403, detail="You can't view this payment")

    # Idempotent: if we've already confirmed this one, don't hit Paystack again.
    if payment.status == models.PaymentStatus.success:
        return schemas.PaymentVerifyOut(
            status=payment.status, order_id=order.id, order_status=order.status,
            amount=float(payment.amount), reference=reference,
        )

    data = _call_paystack("GET", f"/transaction/verify/{reference}")

    expected_pesewas = int(round(float(payment.amount) * 100))
    paid_successfully = data.get("status") == "success" and data.get("amount") == expected_pesewas

    if paid_successfully:
        payment.status = models.PaymentStatus.success
        payment.paid_at = datetime.utcnow()
        order.status = models.OrderStatus.paid
    else:
        payment.status = models.PaymentStatus.failed

    db.commit()

    if paid_successfully:
        try:
            buyer = db.query(models.User).filter(models.User.id == order.buyer_id).first()
            product_summary = ", ".join(
                f"{item.product_name} x{item.quantity}" for item in order.items
            ) or "Product order"
            subject_summary = " ".join(product_summary.split())
            send_email(
                to=ADMIN_NOTIFICATION_EMAIL,
                subject=f"[Eravenda Market] Product payment received: {subject_summary[:90]}",
                body=(
                    "A product order payment has been confirmed.\n\n"
                    f"Order number: {order.order_number}\n"
                    f"Payment reference: {reference}\n"
                    f"Amount: GHS {float(payment.amount):.2f}\n"
                    f"Buyer: {buyer.full_name if buyer else 'Unknown'}\n"
                    f"Buyer email: {buyer.email if buyer else 'Unknown'}\n"
                    f"Products: {product_summary}\n"
                ),
                reply_to=buyer.email if buyer else None,
            )
        except Exception:
            logger.exception("Could not send product-payment notification for order %s", order.id)

    return schemas.PaymentVerifyOut(
        status=payment.status, order_id=order.id, order_status=order.status,
        amount=float(payment.amount), reference=reference,
    )


# ---------- SERVICE BOOKING PAYMENTS ----------
# Handyman jobs are paid exclusively on-platform: the seeker reviews the
# completed work (rating + photos) and pays here; Eravenda holds the funds
# until an admin releases the net payout to the handyman.

@router.post("/service/initialize", response_model=schemas.PaymentInitOut)
def initialize_service_payment(
    payload: schemas.ServicePaymentInitRequest,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_user),
):
    booking = db.query(models.ServiceBooking).filter(models.ServiceBooking.id == payload.booking_id).first()
    if not booking:
        raise HTTPException(status_code=404, detail="Service booking not found")
    if booking.client_id != current_user.id:
        raise HTTPException(status_code=403, detail="This isn't your service booking")
    if booking.status not in {models.ServiceBookingStatus.completion_requested, models.ServiceBookingStatus.completed}:
        raise HTTPException(status_code=400, detail="You can pay once the handyman has requested completion sign-off")
    if not booking.escrow_amount or float(booking.escrow_amount) <= 0:
        raise HTTPException(status_code=400, detail="No job amount has been set for this booking yet")

    amount_pesewas = int(round(float(booking.escrow_amount) * 100))
    reference = f"ERVSVC-{booking.id[:8]}-{os.urandom(3).hex()}"

    data = _call_paystack(
        "POST", "/transaction/initialize",
        json={
            "email": current_user.email,
            "amount": amount_pesewas,
            "reference": reference,
            "currency": "GHS",
            "callback_url": f"{SITE_URL}/payments/callback",
            "metadata": {"booking_id": booking.id, "type": "service_booking"},
        },
    )

    payment = models.ServicePayment(
        booking_id=booking.id,
        provider="paystack",
        provider_reference=reference,
        amount=booking.escrow_amount,
        currency="GHS",
        status=models.PaymentStatus.pending,
    )
    db.add(payment)
    db.commit()

    return schemas.PaymentInitOut(
        authorization_url=data["authorization_url"],
        access_code=data["access_code"],
        reference=reference,
    )


@router.get("/service/verify/{reference}", response_model=schemas.ServicePaymentVerifyOut)
def verify_service_payment(
    reference: str,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_user),
):
    payment = db.query(models.ServicePayment).filter(models.ServicePayment.provider_reference == reference).first()
    if not payment:
        raise HTTPException(status_code=404, detail="Payment not found")

    booking = db.query(models.ServiceBooking).filter(models.ServiceBooking.id == payment.booking_id).first()
    if booking.client_id != current_user.id and current_user.role != models.UserRole.admin:
        raise HTTPException(status_code=403, detail="You can't view this payment")

    if payment.status == models.PaymentStatus.success:
        return schemas.ServicePaymentVerifyOut(
            status=payment.status, booking_id=booking.id, booking_status=booking.status,
            amount=float(payment.amount), reference=reference,
        )

    data = _call_paystack("GET", f"/transaction/verify/{reference}")

    expected_pesewas = int(round(float(payment.amount) * 100))
    paid_successfully = data.get("status") == "success" and data.get("amount") == expected_pesewas

    if paid_successfully:
        payment.status = models.PaymentStatus.success
        payment.paid_at = datetime.utcnow()
        booking.status = models.ServiceBookingStatus.completed
        booking.paid_at = payment.paid_at
        base_amount = float(booking.quoted_amount or 0)
        if not base_amount:
            base_amount = round(float(booking.escrow_amount) - float(booking.commission_amount or 0), 2)
        booking.commission_amount = service_commission_for(base_amount)
        booking.payout_amount = base_amount
        booking.payout_status = models.PayoutStatus.pending
    else:
        payment.status = models.PaymentStatus.failed

    db.commit()

    if paid_successfully:
        try:
            client = db.query(models.User).filter(models.User.id == booking.client_id).first()
            handyman = booking.handyman
            job_summary = (booking.details or "Handyman service").strip()
            subject_summary = " ".join(job_summary.split())
            send_email(
                to=ADMIN_NOTIFICATION_EMAIL,
                subject=f"[Eravenda Services] Handyman payment received: {subject_summary[:90]}",
                body=(
                    "A handyman booking payment has been confirmed.\n\n"
                    f"Booking ID: {booking.id}\n"
                    f"Payment reference: {reference}\n"
                    f"Amount: GHS {float(payment.amount):.2f}\n"
                    f"Client: {client.full_name if client else 'Unknown'}\n"
                    f"Client email: {client.email if client else 'Unknown'}\n"
                    f"Handyman: {handyman.professional_name or handyman.job_title}\n"
                    f"Job requested: {job_summary}\n"
                ),
                reply_to=client.email if client else None,
            )
        except Exception:
            logger.exception("Could not send handyman-payment notification for booking %s", booking.id)

    return schemas.ServicePaymentVerifyOut(
        status=payment.status, booking_id=booking.id, booking_status=booking.status,
        amount=float(payment.amount), reference=reference,
    )

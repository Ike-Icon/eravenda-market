import os
from datetime import datetime

import httpx  # type: ignore[reportMissingImports]
from fastapi import APIRouter, Depends, HTTPException  # type: ignore[reportMissingImports]
from sqlalchemy.orm import Session  # type: ignore[reportMissingImports]

from .. import models, schemas, auth
from ..database import get_db

router = APIRouter(prefix="/payments", tags=["payments"])

PAYSTACK_SECRET_KEY = os.getenv("PAYSTACK_SECRET_KEY", "")
PAYSTACK_BASE_URL = "https://api.paystack.co"
SITE_URL = os.getenv("SITE_URL", "http://localhost:8000")


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

    return schemas.PaymentVerifyOut(
        status=payment.status, order_id=order.id, order_status=order.status,
        amount=float(payment.amount), reference=reference,
    )

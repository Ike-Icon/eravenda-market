"""
Receipt delivery: lookup, download response and email.

The PDF itself is drawn by receipt_pdf.py (framework-free). This module is the part that touches the database and
email, shared by every entry point so they can never disagree:

  * buyer download        GET  /api/orders/{id}/receipt            (the order's own buyer only)
  * buyer email resend    POST /api/orders/{id}/receipt/email      (to the buyer's own account email)
  * admin download        GET  /api/admin/orders/{id}/receipt      (admin only, any order)
  * admin email resend    POST /api/admin/orders/{id}/receipt/email
  * automatic email       attached to the payment confirmation (payments._notify_product_payment)

A receipt exists only once a payment is confirmed (online, or cash-on-delivery recorded by an admin). It is rendered
on demand from the order and payment rows, so there is nothing stored that could go stale and no migration.
"""

import logging
import time
import uuid

from fastapi import HTTPException, Response
from sqlalchemy.orm import Session

from . import models
from .email_utils import SITE_URL, SUPPORT_EMAIL, EmailDeliveryError, send_email
from .receipt_pdf import build_receipt_pdf, fmt_dt, money, receipt_filename, receipt_number

logger = logging.getLogger("eravenda.receipts")

NOT_READY = "A receipt is available once the payment for this order has been confirmed."
# "Email me this receipt" can't be used to spam an inbox or burn the email quota: one send per order per minute.
EMAIL_COOLDOWN_SECONDS = 60
_last_emailed: dict[str, float] = {}


def find_order(db: Session, order_id: str) -> models.Order | None:
    """The order with this id, or None. A malformed id is just 'not found' (a bad UUID would otherwise raise a
    database error)."""
    try:
        uuid.UUID(str(order_id))
    except (ValueError, AttributeError, TypeError):
        return None
    return db.query(models.Order).filter(models.Order.id == str(order_id)).first()


def render_receipt(db: Session, order: models.Order, payment: models.Payment | None = None) -> tuple[bytes, str]:
    """(pdf bytes, filename). `payment` can be passed by a caller that has just confirmed one, so the receipt never
    depends on a possibly stale `order.payments`. Raises HTTP 400 if no payment is confirmed yet."""
    payment = payment or order.receipt_payment
    if payment is None:
        raise HTTPException(status_code=400, detail=NOT_READY)
    buyer = db.query(models.User).filter(models.User.id == order.buyer_id).first()
    pdf = build_receipt_pdf(order=order, payment=payment, buyer=buyer, store=order.store, address=order.address)
    return pdf, receipt_filename(order)


def receipt_response(db: Session, order: models.Order) -> Response:
    pdf, filename = render_receipt(db, order)
    return Response(
        content=pdf,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            # Personal financial document: never let a proxy or the browser cache keep a copy.
            "Cache-Control": "private, no-store",
            "X-Content-Type-Options": "nosniff",
        },
    )


def receipt_attachments(db: Session, order: models.Order, payment: models.Payment | None = None) -> list[dict]:
    """The receipt as an email attachment list, or [] if it can't be built. A receipt problem must never stop the
    payment confirmation email itself from going out."""
    try:
        pdf, filename = render_receipt(db, order, payment)
    except Exception:
        logger.exception("Could not build the receipt PDF for order %s", getattr(order, "id", "?"))
        return []
    return [{"filename": filename, "content": pdf, "content_type": "application/pdf"}]


def email_receipt(db: Session, order: models.Order) -> str:
    """Email the receipt to the order's buyer and return the address used. Always the buyer's own account email,
    whoever asks (so an admin 'resend' can't redirect a receipt elsewhere)."""
    payment = order.receipt_payment
    if payment is None:
        raise HTTPException(status_code=400, detail=NOT_READY)
    buyer = db.query(models.User).filter(models.User.id == order.buyer_id).first()
    if not buyer or not buyer.email:
        raise HTTPException(status_code=400, detail="This order's buyer has no email address on file.")

    now = time.monotonic()
    last = _last_emailed.get(order.id)
    if last is not None and now - last < EMAIL_COOLDOWN_SECONDS:
        wait = int(EMAIL_COOLDOWN_SECONDS - (now - last)) + 1
        raise HTTPException(status_code=429, detail=f"This receipt was just emailed. Please wait {wait} seconds before sending it again.")

    attachments = receipt_attachments(db, order, payment)
    if not attachments:
        raise HTTPException(status_code=500, detail="We couldn't prepare the receipt just now. Please try again.")
    first_name = (buyer.full_name or "").strip().split(" ")[0] or "there"
    currency = payment.currency or "GHS"
    try:
        send_email(
            to=buyer.email,
            subject=f"Your EraVenda receipt for order {order.order_number}",
            body=(
                f"Hi {first_name},\n\n"
                f"Your receipt for order {order.order_number} is attached as a PDF.\n\n"
                f"Receipt no.: {receipt_number(order)}\n"
                f"Amount paid: {money(payment.amount, currency)}\n"
                f"Paid on: {fmt_dt(payment.paid_at or payment.created_at)}\n\n"
                f"You can download it again any time from your orders page:\n{SITE_URL}/orders.html\n\n"
                "— The EraVenda Market team"
            ),
            reply_to=SUPPORT_EMAIL,
            attachments=attachments,
        )
    except EmailDeliveryError:
        logger.exception("Receipt email failed for order %s", order.id)
        raise HTTPException(status_code=502, detail="We couldn't send the email right now. Please try again in a moment.")
    _last_emailed[order.id] = now
    return buyer.email

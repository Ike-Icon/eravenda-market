"""Activation logic for seller subscriptions and promotions, shared by the
seller payment flow (verify endpoint + Paystack webhook) and the admin
"grant" actions, so a paid and a granted plan end up identical."""

import logging
from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from . import models
from .email_utils import ADMIN_NOTIFICATION_EMAIL, SITE_URL, send_email
from .platform_settings import get_settings

logger = logging.getLogger("eravenda.billing")

SUBSCRIPTION_PERIOD_DAYS = 30


def activate_subscription(
    db: Session, store: models.Store, months: int, fee: float, rate: float, granted: bool = False,
) -> models.SellerSubscription:
    """Create or extend the store's subscription. Extends from the current end
    date when it's still live (renewing early never wastes paid days), else
    starts now. The rate and fee are re-snapshotted on every call."""
    now = datetime.utcnow()
    sub = db.query(models.SellerSubscription).filter(models.SellerSubscription.store_id == store.id).first()
    extra = timedelta(days=SUBSCRIPTION_PERIOD_DAYS * months)
    if sub is None:
        sub = models.SellerSubscription(
            store_id=store.id, started_at=now, current_period_end=now + extra,
            monthly_fee=fee, commission_rate=rate, status="active", granted_by_admin=granted,
        )
        db.add(sub)
    else:
        live = sub.status == "active" and sub.current_period_end > now
        sub.current_period_end = (sub.current_period_end if live else now) + extra
        if not live:
            sub.started_at = now
        sub.status = "active"
        sub.monthly_fee = fee
        sub.commission_rate = rate
        sub.granted_by_admin = granted
    db.commit()
    db.refresh(sub)
    return sub


def activate_promotion(db: Session, promo: models.PromotedListing) -> models.PromotedListing:
    now = datetime.utcnow()
    promo.status = "active"
    promo.starts_at = now
    promo.ends_at = now + timedelta(days=7 * promo.weeks)
    db.commit()
    db.refresh(promo)
    return promo


def finalize_store_charge(db: Session, charge: models.StoreCharge) -> None:
    """Marks a seller payment as paid and switches on what it bought. Safe to
    call twice (verify and webhook can both arrive): the second call is a no-op."""
    if charge.status == models.PaymentStatus.success:
        return
    charge.status = models.PaymentStatus.success
    charge.paid_at = datetime.utcnow()
    store = db.query(models.Store).filter(models.Store.id == charge.store_id).first()

    summary = ""
    if charge.kind == "subscription" and store:
        months = max(1, charge.quantity)
        fee = round(float(charge.amount) / months, 2)
        settings = get_settings(db)
        sub = activate_subscription(db, store, months, fee, float(settings.subscription_commission_rate))
        summary = f"Seller subscription, {months} month(s), active until {sub.current_period_end:%d %b %Y}"
    elif charge.kind == "promotion" and charge.target_id:
        promo = db.query(models.PromotedListing).filter(models.PromotedListing.id == charge.target_id).first()
        if promo:
            promo = activate_promotion(db, promo)
            what = promo.product.name if promo.product else "all products in the category"
            summary = f"Promoted listing ({what}), {promo.weeks} week(s), live until {promo.ends_at:%d %b %Y}"
    db.commit()

    store_name = store.store_name if store else "Unknown store"
    try:
        send_email(
            to=ADMIN_NOTIFICATION_EMAIL,
            subject=f"[Eravenda Market] {charge.kind.title()} payment received from {store_name}",
            body=(
                f"{summary or charge.kind}\n\nStore: {store_name}\n"
                f"Amount: GHS {float(charge.amount):.2f}\nReference: {charge.provider_reference}\n"
            ),
        )
    except Exception:
        logger.exception("Could not send admin notification for charge %s", charge.id)
    owner = store.owner if store else None
    if owner and owner.email:
        try:
            send_email(
                to=owner.email,
                subject=f"Your EraVenda {charge.kind} is active",
                body=(
                    f"Hi {(owner.full_name or 'there').split(' ')[0]},\n\n"
                    f"We received your payment of GHS {float(charge.amount):.2f}.\n{summary}\n\n"
                    f"Manage it any time from {SITE_URL}/seller/growth.html\n\n— The EraVenda Market team"
                ),
            )
        except Exception:
            logger.exception("Could not send seller confirmation for charge %s", charge.id)

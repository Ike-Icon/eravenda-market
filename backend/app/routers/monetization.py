# pyright: reportMissingImports=false
"""Seller subscription plan and paid promoted listings.

Two routers live here:
  router        /api/monetization        seller-facing (buy a plan, buy a promotion)
  admin_router  /api/admin/monetization  admin-only controls for every setting,
                                         plus manual grants and revenue totals

Payments go through the same Paystack helpers as orders and handyman jobs
(references ERVSUB-... and ERVPRO-...), and are confirmed by either the verify
endpoint below or the Paystack webhook in payments.py."""

import os
from datetime import datetime, date, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func
from sqlalchemy.orm import Session

from .. import models, auth
from ..database import get_db
from ..email_utils import SITE_URL
from ..platform_settings import (
    PENDING_PROMO_HOLD_MINUTES, PROMO_PRICE_CEILING, PROMO_PRICE_FLOOR, STORE_PIN_PRODUCT_LIMIT,
    active_subscription, category_subtree_ids, get_settings, promo_is_live, promotion_price, promotions_open,
)
from ..product_pricing import PRODUCT_COMMISSION_RATE_CAP
from ..store_billing import activate_promotion, activate_subscription, finalize_store_charge
from .payments import _call_paystack

router = APIRouter(prefix="/monetization", tags=["monetization"])
admin_router = APIRouter(
    prefix="/admin/monetization", tags=["admin-monetization"],
    dependencies=[Depends(auth.require_role(models.UserRole.admin))],
)

SELLER_ROLE = auth.require_role(models.UserRole.seller)


def _my_store(user: models.User) -> models.Store:
    if not user.store:
        raise HTTPException(status_code=400, detail="You need a store first")
    return user.store


def _approved_store(user: models.User) -> models.Store:
    store = _my_store(user)
    if store.status != models.StoreStatus.approved:
        raise HTTPException(status_code=403, detail="Your store must be approved first")
    return store


def _promo_state(promo: models.PromotedListing) -> str:
    now = datetime.utcnow()
    if promo.status == "cancelled":
        return "cancelled"
    if promo.status == "pending":
        return "pending"
    if promo.ends_at and promo.ends_at <= now:
        return "expired"
    return "live" if promo_is_live(promo) else "scheduled"


def _promo_out(promo: models.PromotedListing) -> dict:
    return {
        "id": promo.id,
        "store_id": promo.store_id,
        "store_name": promo.store.store_name if promo.store else None,
        "product_id": promo.product_id,
        "product_name": promo.product.name if promo.product else None,
        "category_id": promo.category_id,
        "category_name": promo.category.name if promo.category else None,
        "scope": "product" if promo.product_id else "store",
        "weeks": promo.weeks,
        "weekly_price": float(promo.weekly_price or 0),
        "total_amount": float(promo.total_amount or 0),
        "state": _promo_state(promo),
        "granted_by_admin": bool(promo.granted_by_admin),
        "starts_at": promo.starts_at.isoformat() if promo.starts_at else None,
        "ends_at": promo.ends_at.isoformat() if promo.ends_at else None,
        "created_at": promo.created_at.isoformat() if promo.created_at else None,
    }


def _sub_out(sub: models.SellerSubscription) -> dict:
    now = datetime.utcnow()
    live = sub.status == "active" and sub.current_period_end > now
    return {
        "id": sub.id,
        "store_id": sub.store_id,
        "store_name": sub.store.store_name if sub.store else None,
        "state": "active" if live else ("ended" if sub.status == "ended" else "expired"),
        "monthly_fee": float(sub.monthly_fee or 0),
        "commission_rate": float(sub.commission_rate or 0),
        "started_at": sub.started_at.isoformat() if sub.started_at else None,
        "current_period_end": sub.current_period_end.isoformat() if sub.current_period_end else None,
        "days_left": max(0, (sub.current_period_end - now).days) if live else 0,
        "granted_by_admin": bool(sub.granted_by_admin),
    }


def _settings_out(s: models.PlatformSettings) -> dict:
    return {
        "product_commission_rate": float(s.product_commission_rate),
        "commission_rate_cap": PRODUCT_COMMISSION_RATE_CAP,
        "subscription_enabled": bool(s.subscription_enabled),
        "subscription_monthly_fee": float(s.subscription_monthly_fee),
        "subscription_commission_rate": float(s.subscription_commission_rate),
        "promotions_enabled": bool(s.promotions_enabled),
        "promotions_open_from": s.promotions_open_from.isoformat() if s.promotions_open_from else None,
        "promotions_open_now": promotions_open(s),
        "promo_product_weekly_price": float(s.promo_product_weekly_price),
        "promo_store_weekly_price": float(s.promo_store_weekly_price),
        "promo_price_floor": PROMO_PRICE_FLOOR,
        "promo_price_ceiling": PROMO_PRICE_CEILING,
        "promo_max_weeks": s.promo_max_weeks,
        "promo_slots_per_category": s.promo_slots_per_category,
        "store_pin_product_limit": STORE_PIN_PRODUCT_LIMIT,
    }


def _slots_in_use(db: Session, category_id: str) -> int:
    now = datetime.utcnow()
    hold_cutoff = now - timedelta(minutes=PENDING_PROMO_HOLD_MINUTES)
    live = db.query(func.count(models.PromotedListing.id)).filter(
        models.PromotedListing.category_id == category_id,
        models.PromotedListing.status == "active",
        models.PromotedListing.ends_at > now,
    ).scalar() or 0
    held = db.query(func.count(models.PromotedListing.id)).filter(
        models.PromotedListing.category_id == category_id,
        models.PromotedListing.status == "pending",
        models.PromotedListing.created_at >= hold_cutoff,
    ).scalar() or 0
    return live + held


# ============================================================
# Seller-facing
# ============================================================
@router.get("/overview")
def overview(db: Session = Depends(get_db), user: models.User = Depends(SELLER_ROLE)):
    store = _my_store(user)
    settings = get_settings(db)
    now = datetime.utcnow()
    sub = active_subscription(db, store.id)
    std = float(settings.product_commission_rate)
    plan_rate = float(settings.subscription_commission_rate)
    fee = float(settings.subscription_monthly_fee)
    saving_per_100 = std - plan_rate
    break_even = round(fee * 100 / saving_per_100, 2) if saving_per_100 > 0 else None

    sales_30d = db.query(func.coalesce(func.sum(models.Order.subtotal), 0)).filter(
        models.Order.store_id == store.id,
        models.Order.created_at >= now - timedelta(days=30),
        models.Order.status.in_([
            models.OrderStatus.paid, models.OrderStatus.processing,
            models.OrderStatus.shipped, models.OrderStatus.delivered,
        ]),
    ).scalar() or 0
    sales_30d = float(sales_30d)

    products = db.query(models.Product).filter(
        models.Product.store_id == store.id, models.Product.status == models.ProductStatus.approved,
    ).order_by(models.Product.name).all()
    categories = {}
    for p in products:
        if p.category:
            categories[p.category_id] = p.category.name
    promos = db.query(models.PromotedListing).filter(
        models.PromotedListing.store_id == store.id, models.PromotedListing.status != "pending",
    ).order_by(models.PromotedListing.created_at.desc()).limit(30).all()

    return {
        "store_status": store.status.value,
        "settings": _settings_out(settings),
        "your_rate": min(std, float(sub.commission_rate)) if sub else std,
        "subscription": _sub_out(sub) if sub else None,
        "plan": {
            "available": bool(settings.subscription_enabled),
            "monthly_fee": fee, "commission_rate": plan_rate, "standard_rate": std,
            "break_even_monthly_sales": break_even,
            "your_sales_30d": sales_30d,
            "commission_30d_standard": round(sales_30d * std / 100, 2),
            "commission_30d_with_plan": round(sales_30d * plan_rate / 100 + fee, 2),
        },
        "promotions_open": promotions_open(settings),
        "promotions": [_promo_out(p) for p in promos],
        "products": [{"id": p.id, "name": p.name, "category_id": p.category_id} for p in products],
        "categories": [{"id": cid, "name": name} for cid, name in sorted(categories.items(), key=lambda kv: kv[1])],
    }


class SubscriptionInit(BaseModel):
    months: int = Field(default=1, ge=1, le=12)


def _start_charge(db, store, user, kind, amount, quantity, reference_prefix, target_id=None):
    reference = f"{reference_prefix}-{store.id[:8]}-{os.urandom(3).hex()}"
    data = _call_paystack(
        "POST", "/transaction/initialize",
        json={
            "email": user.email,
            "amount": int(round(amount * 100)),
            "reference": reference,
            "currency": "GHS",
            "callback_url": f"{SITE_URL}/payments/callback",
            "metadata": {"store_id": store.id, "type": f"seller_{kind}"},
        },
    )
    db.add(models.StoreCharge(
        store_id=store.id, kind=kind, target_id=target_id, quantity=quantity, provider="paystack",
        provider_reference=reference, amount=amount, currency="GHS", status=models.PaymentStatus.pending,
    ))
    db.commit()
    return {"authorization_url": data["authorization_url"], "access_code": data["access_code"], "reference": reference}


@router.post("/subscription/initialize")
def initialize_subscription(
    payload: SubscriptionInit, db: Session = Depends(get_db), user: models.User = Depends(SELLER_ROLE),
):
    store = _approved_store(user)
    settings = get_settings(db)
    if not settings.subscription_enabled:
        raise HTTPException(status_code=400, detail="Seller subscriptions aren't open right now")
    amount = round(float(settings.subscription_monthly_fee) * payload.months, 2)
    return _start_charge(db, store, user, "subscription", amount, payload.months, "ERVSUB")


class PromotionInit(BaseModel):
    product_id: Optional[str] = None  # omit to promote the whole store in a category
    category_id: Optional[str] = None  # required when product_id is omitted
    weeks: int = Field(default=1, ge=1, le=12)


@router.post("/promotions/initialize")
def initialize_promotion(
    payload: PromotionInit, db: Session = Depends(get_db), user: models.User = Depends(SELLER_ROLE),
):
    store = _approved_store(user)
    settings = get_settings(db)
    if not promotions_open(settings):
        raise HTTPException(status_code=400, detail="Promoted listings aren't open yet")
    if payload.weeks > settings.promo_max_weeks:
        raise HTTPException(status_code=400, detail=f"You can buy at most {settings.promo_max_weeks} weeks at a time")

    now = datetime.utcnow()
    if payload.product_id:
        product = db.query(models.Product).filter(
            models.Product.id == payload.product_id, models.Product.store_id == store.id,
        ).first()
        if not product or product.status != models.ProductStatus.approved:
            raise HTTPException(status_code=400, detail="Pick one of your approved products")
        category_id = product.category_id
        already = db.query(models.PromotedListing).filter(
            models.PromotedListing.product_id == product.id,
            models.PromotedListing.status == "active", models.PromotedListing.ends_at > now,
        ).first()
        if already:
            raise HTTPException(status_code=400, detail=f"That product is already promoted until {already.ends_at:%d %b %Y}")
    else:
        if not payload.category_id:
            raise HTTPException(status_code=400, detail="Choose a category to promote your store in")
        category_id = payload.category_id
        has_products = db.query(models.Product.id).filter(
            models.Product.store_id == store.id, models.Product.status == models.ProductStatus.approved,
            models.Product.category_id.in_(category_subtree_ids(db, category_id)),
        ).first()
        if not has_products:
            raise HTTPException(status_code=400, detail="You have no approved products in that category")
        already = db.query(models.PromotedListing).filter(
            models.PromotedListing.store_id == store.id, models.PromotedListing.product_id.is_(None),
            models.PromotedListing.category_id == category_id,
            models.PromotedListing.status == "active", models.PromotedListing.ends_at > now,
        ).first()
        if already:
            raise HTTPException(status_code=400, detail=f"Your store is already promoted there until {already.ends_at:%d %b %Y}")

    if _slots_in_use(db, category_id) >= settings.promo_slots_per_category:
        raise HTTPException(status_code=409, detail="All promoted spots in that category are taken right now. Try again when one frees up.")

    weekly = promotion_price(settings, is_store_wide=not payload.product_id)
    total = round(weekly * payload.weeks, 2)
    promo = models.PromotedListing(
        store_id=store.id, product_id=payload.product_id, category_id=category_id, weeks=payload.weeks,
        weekly_price=weekly, total_amount=total, status="pending",
    )
    db.add(promo)
    db.flush()
    return _start_charge(db, store, user, "promotion", total, payload.weeks, "ERVPRO", target_id=promo.id)


@router.get("/verify/{reference}")
def verify_charge(reference: str, db: Session = Depends(get_db), user: models.User = Depends(auth.get_current_user)):
    charge = db.query(models.StoreCharge).filter(models.StoreCharge.provider_reference == reference).first()
    if not charge:
        raise HTTPException(status_code=404, detail="Payment not found")
    store = db.query(models.Store).filter(models.Store.id == charge.store_id).first()
    if user.role != models.UserRole.admin and (not store or store.owner_id != user.id):
        raise HTTPException(status_code=403, detail="You can't view this payment")

    if charge.status != models.PaymentStatus.success:
        data = _call_paystack("GET", f"/transaction/verify/{reference}")
        expected = int(round(float(charge.amount) * 100))
        if data.get("status") == "success" and data.get("amount") == expected:
            finalize_store_charge(db, charge)
        else:
            charge.status = models.PaymentStatus.failed
            db.commit()
    return {"status": charge.status, "kind": charge.kind, "amount": float(charge.amount), "reference": reference}


# ============================================================
# Admin
# ============================================================
class SettingsUpdate(BaseModel):
    product_commission_rate: Optional[float] = Field(default=None, ge=0, le=PRODUCT_COMMISSION_RATE_CAP)
    subscription_enabled: Optional[bool] = None
    subscription_monthly_fee: Optional[float] = Field(default=None, gt=0, le=10000)
    subscription_commission_rate: Optional[float] = Field(default=None, ge=0, le=PRODUCT_COMMISSION_RATE_CAP)
    promotions_enabled: Optional[bool] = None
    promotions_open_from: Optional[str] = None  # YYYY-MM-DD, or "" to remove the date gate
    promo_product_weekly_price: Optional[float] = Field(default=None, ge=PROMO_PRICE_FLOOR, le=PROMO_PRICE_CEILING)
    promo_store_weekly_price: Optional[float] = Field(default=None, ge=PROMO_PRICE_FLOOR, le=PROMO_PRICE_CEILING)
    promo_max_weeks: Optional[int] = Field(default=None, ge=1, le=12)
    promo_slots_per_category: Optional[int] = Field(default=None, ge=1, le=20)


@admin_router.get("/settings")
def admin_get_settings(db: Session = Depends(get_db)):
    return _settings_out(get_settings(db))


@admin_router.put("/settings")
def admin_update_settings(payload: SettingsUpdate, db: Session = Depends(get_db)):
    settings = get_settings(db)
    changes = payload.model_dump(exclude_unset=True) if hasattr(payload, "model_dump") else payload.dict(exclude_unset=True)
    if "promotions_open_from" in changes:
        raw = (changes.pop("promotions_open_from") or "").strip()
        try:
            settings.promotions_open_from = date.fromisoformat(raw) if raw else None
        except ValueError:
            raise HTTPException(status_code=400, detail="Open-from date must be YYYY-MM-DD")
    for key, value in changes.items():
        if value is not None:
            setattr(settings, key, value)
    if float(settings.subscription_commission_rate) >= float(settings.product_commission_rate):
        db.rollback()
        raise HTTPException(
            status_code=400,
            detail="The subscription commission rate must be lower than the standard rate, otherwise subscribing saves nothing.",
        )
    db.commit()
    db.refresh(settings)
    return _settings_out(settings)


@admin_router.get("/subscriptions")
def admin_subscriptions(db: Session = Depends(get_db)):
    rows = db.query(models.SellerSubscription).order_by(models.SellerSubscription.current_period_end.desc()).all()
    return [_sub_out(r) for r in rows]


class SubscriptionGrant(BaseModel):
    store_id: str
    months: int = Field(default=1, ge=1, le=12)
    commission_rate: Optional[float] = Field(default=None, ge=0, le=PRODUCT_COMMISSION_RATE_CAP)


@admin_router.post("/subscriptions/grant")
def admin_grant_subscription(payload: SubscriptionGrant, db: Session = Depends(get_db)):
    store = db.query(models.Store).filter(models.Store.id == payload.store_id).first()
    if not store:
        raise HTTPException(status_code=404, detail="Store not found")
    settings = get_settings(db)
    rate = payload.commission_rate if payload.commission_rate is not None else float(settings.subscription_commission_rate)
    sub = activate_subscription(db, store, payload.months, 0.0, rate, granted=True)
    return _sub_out(sub)


@admin_router.put("/subscriptions/{subscription_id}/end")
def admin_end_subscription(subscription_id: str, db: Session = Depends(get_db)):
    sub = db.query(models.SellerSubscription).filter(models.SellerSubscription.id == subscription_id).first()
    if not sub:
        raise HTTPException(status_code=404, detail="Subscription not found")
    sub.status = "ended"
    db.commit()
    return _sub_out(sub)


@admin_router.get("/promotions")
def admin_promotions(db: Session = Depends(get_db)):
    rows = db.query(models.PromotedListing).filter(
        models.PromotedListing.status != "pending"
    ).order_by(models.PromotedListing.created_at.desc()).limit(200).all()
    return [_promo_out(r) for r in rows]


class PromotionGrant(BaseModel):
    store_id: str
    product_id: Optional[str] = None
    category_id: Optional[str] = None
    weeks: int = Field(default=1, ge=1, le=12)


@admin_router.post("/promotions/grant")
def admin_grant_promotion(payload: PromotionGrant, db: Session = Depends(get_db)):
    store = db.query(models.Store).filter(models.Store.id == payload.store_id).first()
    if not store:
        raise HTTPException(status_code=404, detail="Store not found")
    if payload.product_id:
        product = db.query(models.Product).filter(
            models.Product.id == payload.product_id, models.Product.store_id == store.id,
        ).first()
        if not product:
            raise HTTPException(status_code=400, detail="That product doesn't belong to this store")
        category_id = product.category_id
    else:
        if not payload.category_id or not db.query(models.Category).filter(models.Category.id == payload.category_id).first():
            raise HTTPException(status_code=400, detail="Choose a category")
        category_id = payload.category_id
    promo = models.PromotedListing(
        store_id=store.id, product_id=payload.product_id, category_id=category_id, weeks=payload.weeks,
        weekly_price=0, total_amount=0, status="pending", granted_by_admin=True,
    )
    db.add(promo)
    db.flush()
    return _promo_out(activate_promotion(db, promo))


@admin_router.get("/promotions/diagnostics")
def admin_promotion_diagnostics(db: Session = Depends(get_db)):
    """For every non-cancelled promotion: is it showing on the storefront, and
    if not, which condition is blocking it. Mirrors the exact rules used by
    live_promoted_products() so the answer matches what shoppers see."""
    from ..home_feed import live_promoted_products

    now = datetime.utcnow()
    rows = db.query(models.PromotedListing).filter(
        models.PromotedListing.status != "cancelled"
    ).order_by(models.PromotedListing.created_at.desc()).limit(100).all()
    shown_ids = {p.id for p in live_promoted_products(db)}

    out = []
    for promo in rows:
        blockers = []
        if promo.status != "active":
            blockers.append(f"status is '{promo.status}' (payment not completed or not activated)")
        if not promo.starts_at or not promo.ends_at:
            blockers.append("no start/end dates set")
        else:
            if promo.starts_at > now:
                blockers.append(f"starts in the future ({promo.starts_at:%Y-%m-%d %H:%M} UTC)")
            if promo.ends_at <= now:
                blockers.append(f"expired on {promo.ends_at:%Y-%m-%d %H:%M} UTC")
        if not promo.store or promo.store.status != models.StoreStatus.approved:
            blockers.append("store is not approved")
        if promo.product_id:
            product = promo.product
            if not product:
                blockers.append("product no longer exists")
            elif product.status != models.ProductStatus.approved:
                blockers.append(f"product is '{product.status.value if hasattr(product.status, 'value') else product.status}', not approved")
        else:
            count = db.query(func.count(models.Product.id)).filter(
                models.Product.store_id == promo.store_id,
                models.Product.status == models.ProductStatus.approved,
            ).scalar() or 0
            if not count:
                blockers.append("store has no approved products to show")
        out.append({
            "id": promo.id,
            "store": promo.store.store_name if promo.store else None,
            "scope": "product" if promo.product_id else "store-wide",
            "product": promo.product.name if promo.product else None,
            "status": promo.status,
            "starts_at": promo.starts_at.isoformat() if promo.starts_at else None,
            "ends_at": promo.ends_at.isoformat() if promo.ends_at else None,
            "showing_on_storefront": bool(not blockers),
            "blockers": blockers,
        })
    return {
        "server_time_utc": now.isoformat(),
        "live_products_on_storefront": len(shown_ids),
        "promotions": out,
    }


@admin_router.put("/promotions/{promotion_id}/cancel")
def admin_cancel_promotion(promotion_id: str, db: Session = Depends(get_db)):
    promo = db.query(models.PromotedListing).filter(models.PromotedListing.id == promotion_id).first()
    if not promo:
        raise HTTPException(status_code=404, detail="Promotion not found")
    promo.status = "cancelled"
    db.commit()
    return _promo_out(promo)


@admin_router.get("/revenue")
def admin_revenue(db: Session = Depends(get_db)):
    now = datetime.utcnow()
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

    def total(kind, since=None):
        q = db.query(func.coalesce(func.sum(models.StoreCharge.amount), 0)).filter(
            models.StoreCharge.kind == kind, models.StoreCharge.status == models.PaymentStatus.success,
        )
        if since:
            q = q.filter(models.StoreCharge.paid_at >= since)
        return float(q.scalar() or 0)

    active_subs = db.query(models.SellerSubscription).filter(
        models.SellerSubscription.status == "active", models.SellerSubscription.current_period_end > now,
    ).all()
    live_promos = db.query(func.count(models.PromotedListing.id)).filter(
        models.PromotedListing.status == "active", models.PromotedListing.ends_at > now,
    ).scalar() or 0
    return {
        "subscription_total": total("subscription"),
        "subscription_this_month": total("subscription", month_start),
        "promotion_total": total("promotion"),
        "promotion_this_month": total("promotion", month_start),
        "active_subscribers": len(active_subs),
        "monthly_recurring": round(sum(float(s.monthly_fee or 0) for s in active_subs if not s.granted_by_admin), 2),
        "live_promotions": live_promos,
    }

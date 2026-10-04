"""Admin-controlled money settings, plus the read helpers that turn them into
answers ("is this store subscribed?", "can promotions be bought today?").

Kept free of router imports so product_pricing, the routers and main.py can
all import it without circular-import trouble."""

from datetime import datetime, date

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from . import models

# Hard limits, enforced in code the same way PRODUCT_COMMISSION_RATE_CAP is:
# the admin form can't push a price outside the range promised to sellers.
PROMO_PRICE_FLOOR = 20.0
PROMO_PRICE_CEILING = 50.0
# A store-wide pin shows at most this many of the store's products per category.
STORE_PIN_PRODUCT_LIMIT = 4
# An unpaid promotion holds its category slot for this long, then frees it.
PENDING_PROMO_HOLD_MINUTES = 30


def get_settings(db: Session) -> models.PlatformSettings:
    row = db.get(models.PlatformSettings, 1)
    if row is None:
        row = models.PlatformSettings(id=1, promotions_open_from=date(2027, 1, 14))
        db.add(row)
        try:
            db.commit()
        except IntegrityError:  # another worker seeded it first
            db.rollback()
            row = db.get(models.PlatformSettings, 1)
        else:
            db.refresh(row)
    return row


def active_subscription(db: Session, store_id: str) -> models.SellerSubscription | None:
    """The store's live subscription, or None. It stays live until its paid
    period ends even if the admin later switches new sign-ups off, because the
    seller already paid for that period."""
    sub = (
        db.query(models.SellerSubscription)
        .filter(models.SellerSubscription.store_id == store_id)
        .first()
    )
    if sub and sub.status == "active" and sub.current_period_end > datetime.utcnow():
        return sub
    return None


def promotions_open(settings: models.PlatformSettings) -> bool:
    if not settings.promotions_enabled:
        return False
    if settings.promotions_open_from and date.today() < settings.promotions_open_from:
        return False
    return True


def promo_is_live(promo: models.PromotedListing) -> bool:
    now = datetime.utcnow()
    return bool(
        promo.status == "active" and promo.starts_at and promo.ends_at
        and promo.starts_at <= now < promo.ends_at
    )


def promotion_price(settings: models.PlatformSettings, is_store_wide: bool) -> float:
    price = float(settings.promo_store_weekly_price if is_store_wide else settings.promo_product_weekly_price)
    return round(min(max(price, PROMO_PRICE_FLOOR), PROMO_PRICE_CEILING), 2)


def category_subtree_ids(db: Session, category_id: str) -> list[str]:
    child_ids = [r[0] for r in db.query(models.Category.id).filter(models.Category.parent_id == category_id).all()]
    return [category_id] + child_ids


def pinned_product_ids(db: Session, category_ids: list[str]) -> list[str]:
    """Product ids to show first when buyers browse the given category (the
    category plus its children), oldest live promotion first, no duplicates.
    The caller keeps only the ids that are in its own result set, so filters
    such as search text or Pay on Delivery still apply to pinned items."""
    now = datetime.utcnow()
    promos = (
        db.query(models.PromotedListing)
        .filter(
            models.PromotedListing.status == "active",
            models.PromotedListing.starts_at <= now,
            models.PromotedListing.ends_at > now,
            models.PromotedListing.category_id.in_(category_ids),
        )
        .order_by(models.PromotedListing.starts_at.asc())
        .all()
    )
    ordered: list[str] = []
    for promo in promos:
        if promo.product_id:
            candidates = [promo.product_id]
        else:
            candidates = [
                r[0] for r in db.query(models.Product.id)
                .filter(
                    models.Product.store_id == promo.store_id,
                    models.Product.status == models.ProductStatus.approved,
                    models.Product.category_id.in_(category_subtree_ids(db, promo.category_id)),
                )
                .order_by(models.Product.created_at.desc())
                .limit(STORE_PIN_PRODUCT_LIMIT)
                .all()
            ]
        for pid in candidates:
            if pid not in ordered:
                ordered.append(pid)
    return ordered

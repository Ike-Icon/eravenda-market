"""Product commission policy. Handyman pricing lives separately in service_pricing.py."""

from sqlalchemy.orm import Session

from . import models
from .platform_settings import get_settings, active_subscription, promotions_open

# Platform-wide rule: no product category commission rate may ever exceed this.
# standard_product_rate() enforces this in code (not just in the numbers below),
# so a future edit to PRODUCT_CATEGORY_RATES can't accidentally break the promise
# made to sellers in the Terms of Service / FAQ / seller onboarding copy.
PRODUCT_COMMISSION_RATE_CAP = 10.0

# Flat standard rate for every category and item, with no vendor- or
# time-limited discount. The live value is the admin-editable
# platform_settings.product_commission_rate (Admin dashboard > Monetization);
# PRODUCT_DEFAULT_RATE is only the fallback used when no database session is
# available, and the value a fresh database is seeded with. It was 5% at
# launch and became 7% on 4 Oct 2026. Category overrides can be reintroduced
# here (e.g. "groceries": 4.5) — any entry is still capped by
# PRODUCT_COMMISSION_RATE_CAP below.
PRODUCT_DEFAULT_RATE = 7.0
PRODUCT_CATEGORY_RATES: dict[str, float] = {}


def _category_key(product: models.Product) -> str | None:
    names = []
    category = product.category
    while category:
        names.append(category.name.casefold())
        category = category.parent
    text = " ".join(names)
    if any(word in text for word in ("grocery", "groceries", "food", "beverage", "perishable")):
        return "groceries"
    if any(word in text for word in ("electronic", "phone", "computer", "mobile", "gadget")):
        return "electronics"
    if any(word in text for word in ("fashion", "beauty", "clothing", "shoe", "accessory")):
        return "fashion"
    if any(word in text for word in ("home", "kitchen", "household", "furniture")):
        return "home"
    return None


def standard_product_rate(product: models.Product, db: Session | None = None) -> float:
    base = float(get_settings(db).product_commission_rate) if db is not None else PRODUCT_DEFAULT_RATE
    rate = PRODUCT_CATEGORY_RATES.get(_category_key(product), base)
    # Hard ceiling: never let a category rate (current or future) exceed the cap.
    return min(rate, PRODUCT_COMMISSION_RATE_CAP)


def product_commission_rate(product: models.Product, store: models.Store, db: Session) -> float:
    """Standard rate for everyone, or the store's subscription rate while it
    has a live subscription (whichever is lower, so a subscriber is never
    charged more than a non-subscriber). Products only: handyman commission
    lives in service_pricing.py."""
    rate = standard_product_rate(product, db)
    subscription = active_subscription(db, store.id)
    if subscription is not None:
        rate = min(rate, float(subscription.commission_rate))
    return round(min(rate, PRODUCT_COMMISSION_RATE_CAP), 2)


def launch_policy_summary(db: Session | None = None) -> dict:
    summary = {
        "standard_rate": PRODUCT_DEFAULT_RATE,
        "category_rates": PRODUCT_CATEGORY_RATES,
        "category_rate_cap": PRODUCT_COMMISSION_RATE_CAP,
        "subscription": None,
        "promotions": None,
    }
    if db is not None:
        settings = get_settings(db)
        summary["standard_rate"] = float(settings.product_commission_rate)
        summary["subscription"] = {
            "enabled": bool(settings.subscription_enabled),
            "monthly_fee": float(settings.subscription_monthly_fee),
            "commission_rate": float(settings.subscription_commission_rate),
        }
        summary["promotions"] = {
            "open": promotions_open(settings),
            "open_from": settings.promotions_open_from.isoformat() if settings.promotions_open_from else None,
            "product_weekly_price": float(settings.promo_product_weekly_price),
            "store_weekly_price": float(settings.promo_store_weekly_price),
        }
    return summary

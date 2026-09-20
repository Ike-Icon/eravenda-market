"""Product commission policy. Handyman pricing lives separately in service_pricing.py."""

import os
from datetime import date, datetime, timedelta

from sqlalchemy.orm import Session

from . import models

# Platform-wide rule: no product category commission rate may ever exceed this.
# standard_product_rate() enforces this in code (not just in the numbers below),
# so a future edit to PRODUCT_CATEGORY_RATES can't accidentally break the promise
# made to sellers in the Terms of Service / FAQ / seller onboarding copy.
PRODUCT_COMMISSION_RATE_CAP = 10.0

PRODUCT_DEFAULT_RATE = 8.0
PRODUCT_CATEGORY_RATES = {
    "groceries": 4.5,
    "electronics": 6.5,
    "home": 9.5,
    "fashion": 10.0,
}
LAUNCH_START_DATE = date.fromisoformat(os.getenv("COMMISSION_LAUNCH_START_DATE", "2026-10-14"))
LAUNCH_DURATION_DAYS = int(os.getenv("COMMISSION_LAUNCH_DURATION_DAYS", "90"))
LAUNCH_VENDOR_CAP = int(os.getenv("COMMISSION_LAUNCH_VENDOR_CAP", "20"))


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


def standard_product_rate(product: models.Product) -> float:
    rate = PRODUCT_CATEGORY_RATES.get(_category_key(product), PRODUCT_DEFAULT_RATE)
    # Hard ceiling: never let a category rate (current or future) exceed the cap.
    return min(rate, PRODUCT_COMMISSION_RATE_CAP)


def launch_discount_applies(store: models.Store, db: Session, today: date | None = None) -> bool:
    today = today or date.today()
    launch_end = LAUNCH_START_DATE + timedelta(days=LAUNCH_DURATION_DAYS)
    if not (LAUNCH_START_DATE <= today < launch_end):
        return False
    vendor_rank = db.query(models.Store).filter(models.Store.created_at <= store.created_at).count()
    return vendor_rank <= LAUNCH_VENDOR_CAP


def product_commission_rate(product: models.Product, store: models.Store, db: Session) -> float:
    rate = standard_product_rate(product)
    if launch_discount_applies(store, db):
        rate /= 2
    return round(rate, 2)


def launch_policy_summary() -> dict:
    return {
        "standard_rate": PRODUCT_DEFAULT_RATE,
        "category_rates": PRODUCT_CATEGORY_RATES,
        "category_rate_cap": PRODUCT_COMMISSION_RATE_CAP,
        "launch_start_date": LAUNCH_START_DATE.isoformat(),
        "launch_end_date": (LAUNCH_START_DATE + timedelta(days=LAUNCH_DURATION_DAYS)).isoformat(),
        "launch_vendor_cap": LAUNCH_VENDOR_CAP,
        "discount": "Half the standard rate for the first 90 days or first 20 vendors, whichever comes first.",
    }

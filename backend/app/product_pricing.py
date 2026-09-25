"""Product commission policy. Handyman pricing lives separately in service_pricing.py."""

from sqlalchemy.orm import Session

from . import models

# Platform-wide rule: no product category commission rate may ever exceed this.
# standard_product_rate() enforces this in code (not just in the numbers below),
# so a future edit to PRODUCT_CATEGORY_RATES can't accidentally break the promise
# made to sellers in the Terms of Service / FAQ / seller onboarding copy.
PRODUCT_COMMISSION_RATE_CAP = 10.0

# Flat launch rate: 5% across every category and item, with no vendor- or
# time-limited discount. Isaac's call for the public launch, to be revisited
# and possibly split back into per-category rates later. Category overrides
# can be reintroduced here (e.g. "groceries": 4.5) whenever that happens —
# any entry is still capped by PRODUCT_COMMISSION_RATE_CAP below.
PRODUCT_DEFAULT_RATE = 5.0
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


def standard_product_rate(product: models.Product) -> float:
    rate = PRODUCT_CATEGORY_RATES.get(_category_key(product), PRODUCT_DEFAULT_RATE)
    # Hard ceiling: never let a category rate (current or future) exceed the cap.
    return min(rate, PRODUCT_COMMISSION_RATE_CAP)


def product_commission_rate(product: models.Product, store: models.Store, db: Session) -> float:
    return round(standard_product_rate(product), 2)


def launch_policy_summary() -> dict:
    return {
        "standard_rate": PRODUCT_DEFAULT_RATE,
        "category_rates": PRODUCT_CATEGORY_RATES,
        "category_rate_cap": PRODUCT_COMMISSION_RATE_CAP,
    }

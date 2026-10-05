"""Delivery fee rules the admin controls, and the maths that turns them into a
price. orders.py calls delivery_fee_for() for the checkout quote and again when
the order is placed, so the buyer is always charged what they were quoted.

Kept free of router imports so orders.py and admin.py can both use it."""

from __future__ import annotations

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from . import models

MAX_FEE = 1000.0          # no single fee or surcharge may exceed GHS 1,000
MAX_WEIGHT_KG = 1000.0
MAX_BANDS = 6

# These reproduce the prices that were hardcoded before the admin could edit
# them, so deploying this changes no fee.
DEFAULT_DISTANCE_FEES = {
    "fee_same_neighbourhood": 8.0,
    "fee_base_city_other_area": 10.0,
    "fee_same_city": 18.0,
    "fee_same_region": 30.0,
    "fee_other_region": 45.0,
}
# Pre-filled suggestions. The weight charge stays off until the admin turns it on.
DEFAULT_WEIGHT_BANDS = [
    {"up_to_kg": 5, "surcharge": 0},
    {"up_to_kg": 20, "surcharge": 5},
    {"up_to_kg": 50, "surcharge": 15},
    {"up_to_kg": None, "surcharge": 30},
]

DISTANCE_BAND_LABELS = {
    "fee_same_neighbourhood": "Same neighbourhood in the base city",
    "fee_base_city_other_area": "Base city, different neighbourhood",
    "fee_same_city": "Same city (outside the base city)",
    "fee_same_region": "Same region, different city",
    "fee_other_region": "Different region",
}


def get_settings(db: Session) -> models.DeliveryFeeSettings:
    row = db.get(models.DeliveryFeeSettings, 1)
    if row is None:
        row = models.DeliveryFeeSettings(id=1, weight_bands=[dict(b) for b in DEFAULT_WEIGHT_BANDS])
        db.add(row)
        try:
            db.commit()
        except IntegrityError:  # another worker seeded it first
            db.rollback()
            row = db.get(models.DeliveryFeeSettings, 1)
        else:
            db.refresh(row)
    return row


def bands_of(settings: models.DeliveryFeeSettings) -> list[dict]:
    return settings.weight_bands or [dict(b) for b in DEFAULT_WEIGHT_BANDS]


def _loc(value: str | None) -> str:
    return (value or "").strip().casefold()


def distance_band(address: models.Address, store: models.Store, settings: models.DeliveryFeeSettings) -> str:
    """Which of the five fee fields applies to this buyer/store pair."""
    base = _loc(settings.base_city)
    buyer_city, seller_city = _loc(address.city), _loc(store.city)
    if base and buyer_city == base and seller_city == base:
        buyer_area = _loc(address.sub_town)
        if buyer_area and buyer_area == _loc(store.sub_town):
            return "fee_same_neighbourhood"
        return "fee_base_city_other_area"
    if buyer_city and buyer_city == seller_city:
        return "fee_same_city"
    buyer_region, seller_region = _loc(address.region), _loc(store.region)
    if buyer_region and buyer_region == seller_region:
        return "fee_same_region"
    return "fee_other_region"


def weight_surcharge(total_kg: float, settings: models.DeliveryFeeSettings) -> float:
    """Extra charge for a store order of this total weight. A weight sitting
    exactly on a band's limit falls in that band (5 kg is in 'up to 5 kg')."""
    if not settings.weight_pricing_enabled:
        return 0.0
    for band in bands_of(settings):
        limit = band.get("up_to_kg")
        if limit is None or total_kg <= float(limit):
            return float(band.get("surcharge") or 0)
    return 0.0


def order_weight_kg(items, settings: models.DeliveryFeeSettings) -> float:
    """Total weight of one store's cart items. A product with no weight set
    counts as the admin's default item weight."""
    default = float(settings.default_item_weight_kg or 0)
    total = 0.0
    for item in items:
        unit = item.product.weight_kg
        total += (float(unit) if unit is not None else default) * item.quantity
    return round(total, 2)


# The two bands that are a delivery inside the base city.
BASE_CITY_BANDS = ("fee_same_neighbourhood", "fee_base_city_other_area")


def qualifies_for_free_delivery(band: str, subtotal: float, settings: models.DeliveryFeeSettings) -> bool:
    """Free when the rule is on, both the buyer and the store are in the base
    city, and the store's order subtotal is strictly above the minimum (an
    order of exactly the minimum still pays)."""
    return bool(
        settings.free_delivery_enabled
        and band in BASE_CITY_BANDS
        and subtotal > float(settings.free_delivery_min_order)
    )


def delivery_fee_for(address: models.Address, store: models.Store, items, db: Session, subtotal: float = 0.0) -> dict:
    """Fee for one store's order, with its parts so the dashboard and the
    checkout can explain it. subtotal is what that store's items cost the
    buyer (after discounts), used only for the free-delivery rule."""
    settings = get_settings(db)
    band = distance_band(address, store, settings)
    distance_fee = float(getattr(settings, band))
    weight = order_weight_kg(items, settings)
    surcharge = weight_surcharge(weight, settings)
    free = qualifies_for_free_delivery(band, subtotal, settings)
    return {
        "delivery_fee": 0.0 if free else round(distance_fee + surcharge, 2),
        "free_delivery": free,
        "distance_fee": round(distance_fee, 2),
        "distance_band": band,
        "weight_kg": weight,
        "weight_surcharge": round(surcharge, 2),
    }


def validate_bands(bands: list[dict]) -> list[str]:
    """Plain-English problems with a weight band list, empty when it is fine."""
    problems: list[str] = []
    if not bands:
        return ["Add at least one weight band."]
    if len(bands) > MAX_BANDS:
        return [f"Use at most {MAX_BANDS} weight bands."]
    previous = 0.0
    for i, band in enumerate(bands, start=1):
        limit, charge = band.get("up_to_kg"), band.get("surcharge")
        last = i == len(bands)
        if charge is None or not (0 <= float(charge) <= MAX_FEE):
            problems.append(f"Band {i}: the charge must be between 0 and {MAX_FEE:g}.")
        if last:
            if limit is not None:
                problems.append("The last band must be 'and above' (leave its weight limit empty).")
        else:
            if limit is None or not (previous < float(limit) <= MAX_WEIGHT_KG):
                problems.append(f"Band {i}: the weight limit must be above the previous band's limit ({previous:g} kg) and at most {MAX_WEIGHT_KG:g} kg.")
            else:
                previous = float(limit)
    return problems

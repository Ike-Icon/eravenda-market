"""Product selection for the storefront's discovery surfaces.

Two jobs live here:

  fair_random_products   - the home page's product rails. Previously these were
                           "newest first", so a seller who uploaded most recently
                           owned the page. Now every seller with approved
                           products gets an equal turn, in a fresh random order
                           on every page load.
  live_promoted_products - products that sellers have paid to promote right now
                           (single-product promotions plus store-wide pins),
                           used by the home page, /promoted, the catalogue and
                           the product page.
"""

import random
from datetime import datetime
from typing import Iterable, Optional

from sqlalchemy import func
from sqlalchemy.orm import Session

from . import models
from .platform_settings import STORE_PIN_PRODUCT_LIMIT, category_subtree_ids

# Upper bound on candidate rows pulled per request. Large enough that every
# store is represented for any realistic catalogue, small enough that the home
# page never loads the whole products table.
_CANDIDATE_CAP = 1500


def _visible_products(db: Session):
    """Approved products from stores that are still approved (a suspended
    store's listings must not appear anywhere on the storefront)."""
    return (
        db.query(models.Product)
        .join(models.Store, models.Store.id == models.Product.store_id)
        .filter(
            models.Product.status == models.ProductStatus.approved,
            models.Store.status == models.StoreStatus.approved,
            # The home page rails are the Retail marketplace; wholesale
            # products live under /products?type=wholesale.
            models.Product.sales_type == "retail",
        )
    )


def fair_random_products(
    db: Session,
    limit: int,
    *filters,
    exclude_ids: Optional[Iterable[str]] = None,
) -> list[models.Product]:
    """Return up to `limit` approved products in random order, with sellers
    taking turns so none can crowd the others out.

    How: shuffle the candidates in SQL, group them by store, shuffle the store
    order, then deal one product per store per round until `limit` is reached.
    A store with 200 products therefore gets the same number of slots as a
    store with 2, until the small stores run out. The picked set is shuffled
    once more so the page does not read as "store A, store B, store C, ...".

    Extra SQLAlchemy `filters` narrow the pool (e.g. discounted only).
    """
    query = _visible_products(db).with_entities(models.Product.id, models.Product.store_id)
    for f in filters:
        query = query.filter(f)
    excluded = set(exclude_ids or [])
    if excluded:
        query = query.filter(~models.Product.id.in_(excluded))
    rows = query.order_by(func.random()).limit(_CANDIDATE_CAP).all()

    by_store: dict[str, list[str]] = {}
    for product_id, store_id in rows:
        by_store.setdefault(store_id, []).append(product_id)

    store_order = list(by_store.keys())
    random.shuffle(store_order)

    picked: list[str] = []
    while len(picked) < limit and by_store:
        for store_id in store_order:
            queue = by_store.get(store_id)
            if not queue:
                continue
            picked.append(queue.pop())
            if len(picked) >= limit:
                break
        by_store = {s: q for s, q in by_store.items() if q}
        store_order = [s for s in store_order if s in by_store]

    random.shuffle(picked)
    if not picked:
        return []
    products = {p.id: p for p in db.query(models.Product).filter(models.Product.id.in_(picked)).all()}
    return [products[pid] for pid in picked if pid in products]


def live_promoted_products(
    db: Session,
    limit: Optional[int] = None,
    category_ids: Optional[list[str]] = None,
    store_id: Optional[str] = None,
    exclude_ids: Optional[Iterable[str]] = None,
) -> list[models.Product]:
    """Products behind a live promotion, each flagged `is_sponsored = True`.

    Live = status 'active' and now between starts_at and ends_at, on a store
    that is still approved, for a product that is still approved. A store-wide
    promotion contributes up to STORE_PIN_PRODUCT_LIMIT of that store's
    products in the promoted category (random picks, so a big catalogue
    rotates through). Result order is shuffled so promoters rotate fairly
    instead of the same sponsor always leading.

    category_ids limits it to those categories (and their children),
    store_id to one store's promotions.
    """
    now = datetime.utcnow()
    query = (
        db.query(models.PromotedListing)
        .join(models.Store, models.Store.id == models.PromotedListing.store_id)
        .filter(
            models.PromotedListing.status == "active",
            models.PromotedListing.starts_at <= now,
            models.PromotedListing.ends_at > now,
            models.Store.status == models.StoreStatus.approved,
        )
    )
    if category_ids:
        query = query.filter(models.PromotedListing.category_id.in_(category_ids))
    if store_id:
        query = query.filter(models.PromotedListing.store_id == store_id)
    promos = query.all()

    excluded = set(exclude_ids or [])
    candidate_ids: list[str] = []
    seen: set[str] = set()

    def add(pid: str) -> None:
        if pid not in seen and pid not in excluded:
            seen.add(pid)
            candidate_ids.append(pid)

    for promo in promos:
        if promo.product_id:
            add(promo.product_id)
        else:
            rows = (
                db.query(models.Product.id)
                .filter(
                    models.Product.store_id == promo.store_id,
                    models.Product.status == models.ProductStatus.approved,
                    models.Product.category_id.in_(category_subtree_ids(db, promo.category_id)),
                )
                .order_by(func.random())
                .limit(STORE_PIN_PRODUCT_LIMIT)
                .all()
            )
            for (pid,) in rows:
                add(pid)

    if not candidate_ids:
        return []
    products = (
        db.query(models.Product)
        .filter(
            models.Product.id.in_(candidate_ids),
            models.Product.status == models.ProductStatus.approved,
        )
        .all()
    )
    random.shuffle(products)
    if limit:
        products = products[:limit]
    for p in products:
        p.is_sponsored = True
    return products

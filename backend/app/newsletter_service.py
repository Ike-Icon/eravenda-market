# pyright: reportMissingImports=false
"""
Weekly "new-arrival alerts" digest.

Builds a plain-language summary of products approved and stores approved in
the last 7 days, then emails it to every active subscriber from the footer
signup form. There are two ways to trigger a send, both call
send_weekly_digest() below so there is exactly one place that decides what
counts as "new" and how the email reads:

  - an admin clicking "Send weekly digest now" (routers/newsletter.py,
    /api/newsletter/admin/send-weekly)
  - a scheduled job hitting /api/newsletter/cron/send-weekly with the shared
    NEWSLETTER_CRON_SECRET — point a free GitHub Actions cron, or a Render
    Cron Job, at that endpoint once a week. See docs/newsletter-cron.md.
"""

import logging
import os
from datetime import datetime, timedelta

from sqlalchemy.orm import Session, selectinload  # type: ignore[reportMissingImports]

from . import models
from .email_utils import send_email

logger = logging.getLogger("eravenda.newsletter")

SITE_URL = os.getenv("SITE_URL", "https://www.eravenda.com")
DIGEST_WINDOW_DAYS = 7
MAX_ITEMS_PER_SECTION = 6


def _build_digest(db: Session) -> dict:
    since = datetime.utcnow() - timedelta(days=DIGEST_WINDOW_DAYS)

    products = (
        db.query(models.Product)
        .options(selectinload(models.Product.store))
        .filter(models.Product.status == models.ProductStatus.approved)
        .filter(models.Product.created_at >= since)
        .order_by(models.Product.created_at.desc())
        .limit(MAX_ITEMS_PER_SECTION)
        .all()
    )

    stores = (
        db.query(models.Store)
        .filter(models.Store.status == models.StoreStatus.approved)
        .filter(models.Store.created_at >= since)
        .order_by(models.Store.created_at.desc())
        .limit(MAX_ITEMS_PER_SECTION)
        .all()
    )

    deals = [
        p for p in products
        if p.discount_price is not None and p.discount_price < p.price
    ]

    return {"products": products, "stores": stores, "deals": deals}


def has_new_content(digest: dict) -> bool:
    return bool(digest["products"] or digest["stores"])


def _render_digest_text(digest: dict, unsubscribe_url: str) -> str:
    lines = ["This week on Eravenda Market:", ""]

    if digest["products"]:
        lines.append("NEW ARRIVALS")
        for p in digest["products"]:
            price = f"₵{p.discount_price}" if p.discount_price is not None else f"₵{p.price}"
            store_name = p.store.store_name if p.store else "Eravenda Market"
            lines.append(f"- {p.name} ({store_name}) — {price}")
            lines.append(f"  {SITE_URL}/product/{p.id}")
        lines.append("")

    if digest["deals"]:
        lines.append("DEALS THIS WEEK")
        for p in digest["deals"]:
            lines.append(f"- {p.name}: was ₵{p.price}, now ₵{p.discount_price}")
            lines.append(f"  {SITE_URL}/product/{p.id}")
        lines.append("")

    if digest["stores"]:
        lines.append("NEW SELLERS")
        for s in digest["stores"]:
            lines.append(f"- {s.store_name}")
            lines.append(f"  {SITE_URL}/store/{s.id}")
        lines.append("")

    lines.append(f"Browse everything: {SITE_URL}/products")
    lines.append("")
    lines.append(f"Don't want these emails? Unsubscribe any time: {unsubscribe_url}")

    return "\n".join(lines)


def send_weekly_digest(db: Session) -> dict:
    """Builds the digest once, then emails every active subscriber. Returns
    a small summary dict so both the admin button and the cron endpoint can
    report what happened."""
    digest = _build_digest(db)

    if not has_new_content(digest):
        logger.info("Newsletter: nothing new in the last %s days, skipping send.", DIGEST_WINDOW_DAYS)
        return {"sent": 0, "failed": 0, "subscriber_count": 0, "skipped_reason": "no_new_content"}

    subscribers = (
        db.query(models.NewsletterSubscriber)
        .filter(models.NewsletterSubscriber.is_active.is_(True))
        .all()
    )

    sent = 0
    failed = 0
    now = datetime.utcnow()

    for subscriber in subscribers:
        unsubscribe_url = f"{SITE_URL}/api/newsletter/unsubscribe?token={subscriber.unsubscribe_token}"
        body = _render_digest_text(digest, unsubscribe_url)
        try:
            send_email(
                to=subscriber.email,
                subject="New arrivals on Eravenda Market this week",
                body=body,
            )
            subscriber.last_sent_at = now
            sent += 1
        except Exception:
            logger.exception("Failed to send newsletter to %s", subscriber.email)
            failed += 1

    db.commit()
    return {"sent": sent, "failed": failed, "subscriber_count": len(subscribers)}

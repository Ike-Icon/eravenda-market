# pyright: reportMissingImports=false
"""
Weekly "new-arrival alerts" digest.

Builds a summary of products and stores approved in the last 7 days and
emails it to every active subscriber from the footer signup form. Every send
goes through send_weekly_digest() below, so one place decides what counts as
"new", who gets emailed and how the email looks:

  - the admin dashboard's "Send digest now" and "Send test to me" buttons
    (routers/newsletter.py, /api/newsletter/admin/...)
  - the scheduled GitHub Actions job hitting /api/newsletter/cron/send-weekly
    with the shared NEWSLETTER_CRON_SECRET. See docs/newsletter-cron.md.

Safe to run twice: a subscriber who already got a digest in the last
SEND_COOLDOWN_DAYS days is skipped, so a retried cron run or a double click
can't email anyone twice, and a run that failed halfway picks up the people
it missed. Only one send runs at a time (database advisory lock).
"""

import logging
from contextlib import contextmanager
from datetime import datetime, timedelta
from html import escape

from sqlalchemy import text  # type: ignore[reportMissingImports]
from sqlalchemy.orm import Session, selectinload  # type: ignore[reportMissingImports]

from . import models
from . import email_utils
from .database import engine
from .email_utils import (
    BATCH_MAX,
    EMAIL_FLYER_URL,
    SITE_URL,
    EmailDeliveryError,
    send_email_batch,
)

logger = logging.getLogger("eravenda.newsletter")

DIGEST_WINDOW_DAYS = 7
MAX_ITEMS_PER_SECTION = 6
# Someone emailed less than this long ago is skipped (unless force=True).
# Six days, so a Monday 08:00 run always reaches everyone the previous
# Monday's run reached.
SEND_COOLDOWN_DAYS = 6
_LOCK_KEY = 727401


class NewsletterSendError(Exception):
    """The send couldn't start. status_code is what the HTTP layer should return."""

    def __init__(self, message: str, status_code: int = 400):
        super().__init__(message)
        self.message = message
        self.status_code = status_code


# ---------- what goes in the digest ----------

def _build_digest(db: Session, latest: bool = False) -> dict:
    """latest=True ignores the 7-day window and takes the newest approved
    items, so an admin can preview the email on a quiet week."""
    since = datetime.utcnow() - timedelta(days=DIGEST_WINDOW_DAYS)

    product_q = (
        db.query(models.Product)
        .options(selectinload(models.Product.store), selectinload(models.Product.images))
        .filter(models.Product.status == models.ProductStatus.approved)
    )
    store_q = db.query(models.Store).filter(models.Store.status == models.StoreStatus.approved)
    if not latest:
        product_q = product_q.filter(models.Product.created_at >= since)
        store_q = store_q.filter(models.Store.created_at >= since)

    products = product_q.order_by(models.Product.created_at.desc()).limit(MAX_ITEMS_PER_SECTION).all()
    stores = store_q.order_by(models.Store.created_at.desc()).limit(MAX_ITEMS_PER_SECTION).all()
    deals = [p for p in products if _has_deal(p)]
    return {"products": products, "stores": stores, "deals": deals}


def has_new_content(digest: dict) -> bool:
    return bool(digest["products"] or digest["stores"])


def _has_deal(p) -> bool:
    return p.discount_price is not None and p.discount_price < p.price


def _money(value) -> str:
    return f"₵{float(value):,.2f}"


def _effective_price(p) -> str:
    return _money(p.discount_price if _has_deal(p) else p.price)


def _image_url(p) -> str | None:
    images = p.images or []
    primary = next((img for img in images if img.is_primary), None) or (images[0] if images else None)
    return primary.image_url if primary else None


def _subject(digest: dict) -> str:
    n = len(digest["products"])
    if n:
        return f"{n} new arrival{'s' if n != 1 else ''} on Eravenda Market this week"
    return "New sellers on Eravenda Market this week"


# ---------- plain-text version ----------

def _render_digest_text(digest: dict, unsubscribe_url: str) -> str:
    lines = ["This week on Eravenda Market:", ""]

    if digest["products"]:
        lines.append("NEW ARRIVALS")
        for p in digest["products"]:
            store_name = p.store.store_name if p.store else "Eravenda Market"
            lines.append(f"- {p.name} ({store_name}) - {_effective_price(p)}")
            lines.append(f"  {SITE_URL}/product/{p.id}")
        lines.append("")

    if digest["deals"]:
        lines.append("DEALS THIS WEEK")
        for p in digest["deals"]:
            lines.append(f"- {p.name}: was {_money(p.price)}, now {_money(p.discount_price)}")
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


# ---------- HTML version ----------

_BORDER = "border-top:1px solid #eceae2;"


def _thumb_html(url: str | None, link: str) -> str:
    if url:
        inner = (
            f'<img src="{escape(url)}" width="64" height="64" alt="" '
            'style="display:block;width:64px;height:64px;object-fit:cover;'
            'border-radius:6px;border:1px solid #e3e1d8;">'
        )
    else:
        inner = (
            '<div style="width:64px;height:64px;border-radius:6px;background:#eef3f0;'
            'border:1px solid #d8e5de;"></div>'
        )
    return f'<a href="{escape(link)}" style="text-decoration:none;">{inner}</a>'


def _product_row_html(p) -> str:
    link = f"{SITE_URL}/product/{p.id}"
    store_name = p.store.store_name if p.store else "Eravenda Market"
    was = (
        f' <span style="color:#8a948e;text-decoration:line-through;font-size:12px;">{_money(p.price)}</span>'
        if _has_deal(p)
        else ""
    )
    return f"""<tr>
  <td width="76" style="padding:12px 0;{_BORDER}vertical-align:top;">{_thumb_html(_image_url(p), link)}</td>
  <td style="padding:12px 0 12px 12px;{_BORDER}vertical-align:top;font-size:14px;line-height:1.4;">
    <a href="{escape(link)}" style="color:#0b2d20;font-weight:700;text-decoration:none;">{escape(p.name)}</a>
    <div style="color:#5b6b63;font-size:13px;margin-top:2px;">{escape(store_name)}</div>
    <div style="margin-top:4px;"><strong style="color:#1c6b4f;">{_effective_price(p)}</strong>{was}</div>
  </td>
</tr>"""


def _store_row_html(s) -> str:
    link = f"{SITE_URL}/store/{s.id}"
    logo = getattr(s, "logo_url", None)
    return f"""<tr>
  <td width="76" style="padding:12px 0;{_BORDER}vertical-align:top;">{_thumb_html(logo, link)}</td>
  <td style="padding:12px 0 12px 12px;{_BORDER}vertical-align:middle;font-size:14px;">
    <a href="{escape(link)}" style="color:#0b2d20;font-weight:700;text-decoration:none;">{escape(s.store_name)}</a>
  </td>
</tr>"""


def _section_html(title: str, rows_html: str) -> str:
    return f"""<h2 style="margin:28px 0 4px;font-size:16px;color:#0b2d20;">{title}</h2>
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="border-collapse:collapse;">{rows_html}</table>"""


def _render_digest_html(digest: dict, unsubscribe_url: str, note: str | None = None) -> str:
    sections = []
    if digest["products"]:
        sections.append(_section_html("New arrivals", "".join(_product_row_html(p) for p in digest["products"])))
    if digest["deals"]:
        sections.append(_section_html("Deals this week", "".join(_product_row_html(p) for p in digest["deals"])))
    if digest["stores"]:
        sections.append(_section_html("New sellers", "".join(_store_row_html(s) for s in digest["stores"])))

    note_html = (
        f'<p style="background:#fff7e0;border:1px solid #f1d98a;border-radius:6px;padding:10px 12px;'
        f'font-size:13px;color:#6b5200;">{escape(note)}</p>'
        if note
        else ""
    )
    return f"""<!doctype html>
<html lang="en">
  <body style="margin:0;background:#f4f4f4;font-family:Arial,Helvetica,sans-serif;color:#24352e;">
    <div style="padding:20px 12px;">
      <div style="max-width:600px;margin:0 auto;background:#ffffff;border:1px solid #d8e5de;border-radius:10px;overflow:hidden;">
        <img src="{escape(EMAIL_FLYER_URL)}" alt="Eravenda Market" style="display:block;width:100%;max-width:600px;height:auto;border:0;">
        <div style="padding:8px 24px 24px;line-height:1.6;font-size:15px;">
          {note_html}
          <p style="margin:16px 0 0;">Here is what is new on Eravenda Market this week.</p>
          {''.join(sections)}
          <p style="text-align:center;margin:28px 0 8px;">
            <a href="{SITE_URL}/products" style="display:inline-block;background:#1c6b4f;color:#ffffff;font-weight:700;text-decoration:none;padding:12px 24px;border-radius:8px;">Browse everything</a>
          </p>
        </div>
        <div style="padding:16px 24px;background:#f5f6f2;border-top:1px solid #e3e1d8;font-size:12px;color:#6b7a72;text-align:center;line-height:1.5;">
          You get this because you signed up for new-arrival alerts at Eravenda Market.<br>
          <a href="{escape(unsubscribe_url)}" style="color:#1c6b4f;">Unsubscribe</a>
        </div>
      </div>
    </div>
  </body>
</html>"""


# ---------- sending ----------

@contextmanager
def _single_send_lock():
    """Only one real send at a time (cron plus a click, or two cron retries).
    Uses its own connection because a Postgres advisory lock belongs to the
    connection that took it, and the session's connection goes back to the
    pool on every commit."""
    if engine.dialect.name != "postgresql":
        yield
        return
    with engine.connect() as conn:
        got = conn.execute(text("SELECT pg_try_advisory_lock(:k)"), {"k": _LOCK_KEY}).scalar()
        if not got:
            conn.rollback()
            raise NewsletterSendError("A newsletter send is already running. Wait a few minutes and check again.", 409)
        try:
            yield
        finally:
            conn.execute(text("SELECT pg_advisory_unlock(:k)"), {"k": _LOCK_KEY})
            conn.commit()


def send_weekly_digest(db: Session, *, force: bool = False, test_email: str | None = None) -> dict:
    """Emails the digest and returns a summary dict:

        sent, failed, subscriber_count (active subscribers), skipped_recently,
        test (bool), error (str or None), skipped_reason (only when skipped)

    force=True ignores the cooldown. test_email sends one copy to that
    address only, never marks anyone as emailed, and falls back to the newest
    items when nothing is new so the layout can be previewed on a quiet week.
    Raises NewsletterSendError when the send can't start (email not set up,
    nothing to preview, another send already running)."""
    if not email_utils.email_configured():
        raise NewsletterSendError(
            "Email is not set up on the server: RESEND_API_KEY is missing. "
            "Add it (and FROM_EMAIL) in the Render Environment tab and redeploy.",
            503,
        )
    if test_email:
        return _send(db, force=True, test_email=test_email)
    with _single_send_lock():
        return _send(db, force=force, test_email=None)


def _send(db: Session, *, force: bool, test_email: str | None) -> dict:
    digest = _build_digest(db)
    note = None
    if not has_new_content(digest):
        if not test_email:
            logger.info("Newsletter: nothing new in the last %s days, skipping send.", DIGEST_WINDOW_DAYS)
            active = db.query(models.NewsletterSubscriber).filter(models.NewsletterSubscriber.is_active.is_(True)).count()
            return {
                "sent": 0, "failed": 0, "subscriber_count": active, "skipped_recently": 0,
                "test": False, "error": None, "skipped_reason": "no_new_content",
            }
        digest = _build_digest(db, latest=True)
        if not has_new_content(digest):
            raise NewsletterSendError("There are no approved products or stores yet, so there is nothing to preview.", 400)
        note = "Preview: nothing new was approved in the last 7 days, so this shows the newest items."

    now = datetime.utcnow()
    subject = _subject(digest)
    skipped_recently = 0
    active_count = 1

    if test_email:
        targets = [(None, test_email, f"{SITE_URL}/")]
        subject = f"[TEST] {subject}"
    else:
        subscribers = (
            db.query(models.NewsletterSubscriber)
            .filter(models.NewsletterSubscriber.is_active.is_(True))
            .all()
        )
        active_count = len(subscribers)
        cutoff = now - timedelta(days=SEND_COOLDOWN_DAYS)
        due = [s for s in subscribers if force or s.last_sent_at is None or s.last_sent_at < cutoff]
        skipped_recently = active_count - len(due)
        targets = [
            (s, s.email, f"{SITE_URL}/api/newsletter/unsubscribe?token={s.unsubscribe_token}")
            for s in due
        ]

    sent = failed = 0
    error = None
    for start in range(0, len(targets), BATCH_MAX):
        chunk = targets[start:start + BATCH_MAX]
        messages = []
        for sub, email, unsubscribe_url in chunk:
            message = {
                "to": email,
                "subject": subject,
                "body": _render_digest_text(digest, unsubscribe_url),
                "html": _render_digest_html(digest, unsubscribe_url, note),
            }
            if sub is not None:
                message["headers"] = {
                    "List-Unsubscribe": f"<{unsubscribe_url}>",
                    "List-Unsubscribe-Post": "List-Unsubscribe=One-Click",
                }
            messages.append(message)
        try:
            results = send_email_batch(messages)
        except EmailDeliveryError as exc:
            logger.error("Newsletter send stopped: %s", exc)
            error = str(exc)
            failed += len(targets) - start
            break
        for (sub, _email, _url), ok in zip(chunk, results):
            if ok:
                sent += 1
                if sub is not None:
                    sub.last_sent_at = now
            else:
                failed += 1
        db.commit()

    logger.info("Newsletter: sent=%s failed=%s skipped_recently=%s", sent, failed, skipped_recently)
    return {
        "sent": sent, "failed": failed, "subscriber_count": active_count,
        "skipped_recently": skipped_recently, "test": bool(test_email), "error": error,
    }

# pyright: reportMissingImports=false
"""
Admin Email center: write a message once and send it to one audience at a time.

Audiences (never mixed in a single send):
  users          buyer accounts, minus anyone who is also a seller or a professional
  sellers        owners of approved stores (pending ones too when include_pending)
  professionals  approved handyman/service professionals (pending too when include_pending)
  subscribers    people who signed up through the footer's new-arrival alerts
  user           one account the admin picks by name or email (any role)

A person who is a seller AND a buyer is only in "sellers", and a professional
is only in "professionals", so nobody gets the same announcement twice and
each audience is exactly the group the admin named.

How a send works
  * The page asks for a preview first. Preview and send use the same
    render_message(), so what the admin sees is what recipients get.
  * "Send test to me" goes to the admin's own address only.
  * A real send creates an email_campaigns row and delivers in a background
    thread (the HTTP request returns at once, so a long list can't time out),
    100 recipients per Resend batch call, updating the row as it goes. The
    admin page polls that row for progress.
  * One real send at a time, and the same message to the same audience can't
    be started twice within 10 minutes (double-click / retry guard).
  * Delivery stops immediately when Resend refuses the API key or sender
    domain (nothing else could succeed), and the campaign says why.

Writing the message
  Plain text. Blank line = new paragraph. **bold** and [link text](https://...)
  are supported. Placeholders are filled per recipient:
      {{first_name}}  {{full_name}}  {{store_name}} (sellers)  {{job_title}} (professionals)
  An optional call-to-action button can be added (label + https link).
"""

import logging
import re
import threading
import time
import uuid
from datetime import datetime, timedelta
from html import escape

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from . import models
from . import email_utils
from .database import SessionLocal
from .email_utils import (
    BATCH_MAX,
    EMAIL_FLYER_URL,
    SITE_URL,
    EmailConfigError,
    EmailDeliveryError,
    send_email_batch,
)

logger = logging.getLogger("eravenda.broadcast")

AUDIENCES = {
    "users": {
        "label": "Users",
        "description": "Buyer accounts (sellers and professionals are in their own groups).",
        "placeholders": ["first_name", "full_name"],
    },
    "sellers": {
        "label": "Sellers",
        "description": "Owners of approved stores.",
        "placeholders": ["first_name", "full_name", "store_name"],
        "pending_label": "Also include sellers whose store is still awaiting approval",
    },
    "professionals": {
        "label": "Professionals",
        "description": "Approved handyman / service professionals.",
        "placeholders": ["first_name", "full_name", "job_title"],
        "pending_label": "Also include professionals who are still awaiting approval",
    },
    "user": {
        "label": "One user",
        "description": "Pick a single account by name or email and send them a personal message.",
        "placeholders": ["first_name", "full_name"],
    },
    "subscribers": {
        "label": "Newsletter subscribers",
        "description": "People who signed up for new-arrival alerts in the site footer. Each email has an unsubscribe link.",
        "placeholders": ["first_name"],
    },
}
ALL_PLACEHOLDERS = {"first_name", "full_name", "store_name", "job_title"}
_PLACEHOLDER_RE = re.compile(r"\{\{\s*([a-zA-Z_]+)\s*\}\}")

MAX_RECIPIENTS = 5000          # safety ceiling for a single send
BATCH_PAUSE_SECONDS = 0.6      # keeps well under Resend's request-rate limit
DUPLICATE_WINDOW = timedelta(minutes=10)
STALE_SENDING_AFTER = timedelta(minutes=60)


class BroadcastError(Exception):
    """A problem the admin can fix. status_code is what the HTTP layer returns."""

    def __init__(self, message: str, status_code: int = 400):
        super().__init__(message)
        self.message = message
        self.status_code = status_code


# --------------------------------------------------------------------------
# Recipients
# --------------------------------------------------------------------------

def _first_name(full_name: str | None) -> str:
    parts = (full_name or "").strip().split()
    return parts[0] if parts else "there"


def _person(email: str, full_name: str | None, **extra) -> dict:
    return {
        "email": (email or "").strip(),
        "full_name": (full_name or "").strip() or "there",
        "first_name": _first_name(full_name),
        "store_name": extra.get("store_name") or "your store",
        "job_title": extra.get("job_title") or "professional",
        "unsubscribe_url": extra.get("unsubscribe_url"),
    }


def _single_user(db: Session, user_id: str | None) -> dict:
    """The one chosen account, or a plain-language reason it can't be emailed."""
    if not user_id:
        raise BroadcastError("Choose which user to email first.")
    try:
        uuid.UUID(str(user_id))
    except ValueError:
        raise BroadcastError("Choose a valid user from the search results.")
    user = db.query(models.User).filter(models.User.id == str(user_id)).first()
    if not user:
        raise BroadcastError("That user could not be found.", 404)
    if not user.is_active:
        raise BroadcastError("That account is deactivated, so it can't be emailed.")
    return _person(user.email, user.full_name)


def preview_people(db: Session, message: dict) -> list[dict]:
    """Recipients to base a preview on. A single-user message with nobody
    chosen yet previews with a sample person instead of failing."""
    if message["audience"] == "user" and not message.get("user_id"):
        return []
    return resolve_recipients(
        db, message["audience"], message.get("include_pending", False), message.get("user_id")
    )


def resolve_recipients(
    db: Session, audience: str, include_pending: bool = False, user_id: str | None = None
) -> list[dict]:
    """Everyone in the audience, one entry per email address (case-insensitive)."""
    if audience not in AUDIENCES:
        raise BroadcastError("Unknown audience.")

    people: list[dict] = []

    if audience == "user":
        people = [_single_user(db, user_id)]

    elif audience == "users":
        rows = (
            db.query(models.User)
            .filter(
                models.User.role == models.UserRole.buyer,
                models.User.is_active.is_(True),
                ~models.User.id.in_(select(models.Store.owner_id)),
                ~models.User.id.in_(select(models.HandymanProfile.user_id)),
            )
            .order_by(models.User.created_at)
            .all()
        )
        people = [_person(u.email, u.full_name) for u in rows]

    elif audience == "sellers":
        statuses = [models.StoreStatus.approved]
        if include_pending:
            statuses.append(models.StoreStatus.pending)
        rows = (
            db.query(models.User, models.Store.store_name)
            .join(models.Store, models.Store.owner_id == models.User.id)
            .filter(models.Store.status.in_(statuses), models.User.is_active.is_(True))
            .order_by(models.Store.created_at)
            .all()
        )
        people = [_person(u.email, u.full_name, store_name=store_name) for u, store_name in rows]

    elif audience == "professionals":
        statuses = [models.ServiceStatus.approved]
        if include_pending:
            statuses.append(models.ServiceStatus.pending)
        rows = (
            db.query(models.User, models.HandymanProfile)
            .join(models.HandymanProfile, models.HandymanProfile.user_id == models.User.id)
            .filter(models.HandymanProfile.status.in_(statuses), models.User.is_active.is_(True))
            .order_by(models.HandymanProfile.created_at)
            .all()
        )
        people = [
            _person(
                u.email,
                p.professional_name or u.full_name,
                job_title=p.custom_job_title or p.job_title,
            )
            for u, p in rows
        ]

    else:  # subscribers
        rows = (
            db.query(models.NewsletterSubscriber)
            .filter(models.NewsletterSubscriber.is_active.is_(True))
            .order_by(models.NewsletterSubscriber.subscribed_at)
            .all()
        )
        people = [
            _person(s.email, None, unsubscribe_url=f"{SITE_URL}/api/newsletter/unsubscribe?token={s.unsubscribe_token}")
            for s in rows
        ]

    seen: set[str] = set()
    unique = []
    for person in people:
        key = person["email"].lower()
        if key and "@" in key and key not in seen:
            seen.add(key)
            unique.append(person)
    return unique


def audience_summary(db: Session) -> list[dict]:
    """Counts for the audience picker, including how many more would be
    reached by also including applicants who are still pending."""
    out = []
    for key, meta in AUDIENCES.items():
        if key == "user":
            # Not a group: the count is whoever the admin picks (shown as 1 once chosen).
            out.append({
                "key": key, "label": meta["label"], "description": meta["description"],
                "placeholders": meta["placeholders"], "count": 0, "pending_label": None,
            })
            continue
        entry = {
            "key": key,
            "label": meta["label"],
            "description": meta["description"],
            "placeholders": meta["placeholders"],
            "count": len(resolve_recipients(db, key)),
            "pending_label": meta.get("pending_label"),
        }
        if meta.get("pending_label"):
            entry["count_with_pending"] = len(resolve_recipients(db, key, include_pending=True))
        out.append(entry)
    return out


# --------------------------------------------------------------------------
# Writing and rendering
# --------------------------------------------------------------------------

def check_message(message: dict) -> None:
    """Raises BroadcastError with a plain-language reason when the message
    can't be sent as written."""
    audience = message["audience"]
    allowed = set(AUDIENCES[audience]["placeholders"])
    text = f"{message['subject']}\n{message['body']}"
    unknown = sorted({m for m in _PLACEHOLDER_RE.findall(text) if m not in allowed})
    if unknown:
        names = ", ".join("{{" + n + "}}" for n in unknown)
        ok = ", ".join("{{" + n + "}}" for n in AUDIENCES[audience]["placeholders"])
        raise BroadcastError(f"{names} can't be used for {AUDIENCES[audience]['label']}. Available here: {ok}.")

    label, url = message.get("button_label"), message.get("button_url")
    if bool(label) != bool(url):
        raise BroadcastError("A button needs both a label and a link. Fill in both, or clear both.")
    if url and not re.match(r"^https?://[^\s]+$", url, re.I):
        raise BroadcastError("The button link must start with https:// (or http://).")
    for _text, link in _LINK_RE.findall(message["body"]):
        if not re.match(r"^https?://", link, re.I):
            raise BroadcastError(f"The link “{link}” must start with https:// (or http://).")


_LINK_RE = re.compile(r"\[([^\]\n]{1,200})\]\(([^)\s]{1,500})\)")
_BOLD_RE = re.compile(r"\*\*(.+?)\*\*", re.S)


def _fill(template: str, person: dict) -> str:
    return _PLACEHOLDER_RE.sub(lambda m: str(person.get(m.group(1), "")), template)


def _body_to_html(body: str) -> str:
    """Escape first, then turn the small set of supported markup into HTML,
    so nothing an admin (or a placeholder value) types can inject markup."""
    safe = escape(body)
    safe = _LINK_RE.sub(
        lambda m: f'<a href="{m.group(2)}" style="color:#1c6b4f;font-weight:600;">{m.group(1)}</a>', safe
    )
    safe = _BOLD_RE.sub(r"<strong>\1</strong>", safe)
    paragraphs = [p for p in re.split(r"\n\s*\n", safe.strip()) if p.strip()]
    return "".join(
        f'<p style="margin:0 0 14px;">{p.strip().replace(chr(10), "<br>")}</p>' for p in paragraphs
    )


def _body_to_text(body: str) -> str:
    text = _LINK_RE.sub(lambda m: f"{m.group(1)}: {m.group(2)}", body)
    return _BOLD_RE.sub(r"\1", text).strip()


def render_message(message: dict, person: dict) -> dict:
    """Returns {"subject", "body" (plain text), "html", "headers"} for one recipient."""
    subject = _fill(message["subject"], person)
    body = _fill(message["body"], person)
    button_label, button_url = message.get("button_label"), message.get("button_url")

    text = _body_to_text(body)
    if button_label and button_url:
        text += f"\n\n{button_label}: {button_url}"

    unsubscribe_url = person.get("unsubscribe_url")
    if unsubscribe_url:
        text += f"\n\nDon't want these emails? Unsubscribe any time: {unsubscribe_url}"
        footer = (
            'You get this because you signed up for new-arrival alerts at Eravenda Market.<br>'
            f'<a href="{escape(unsubscribe_url)}" style="color:#1c6b4f;">Unsubscribe</a>'
        )
    else:
        footer = (
            "You get this because you have an account on Eravenda Market.<br>"
            f'Questions? Reply to this email or write to {escape(email_utils.SUPPORT_EMAIL)}.'
        )

    button_html = ""
    if button_label and button_url:
        button_html = (
            '<p style="text-align:center;margin:26px 0 6px;">'
            f'<a href="{escape(button_url)}" style="display:inline-block;background:#1c6b4f;color:#ffffff;'
            f'font-weight:700;text-decoration:none;padding:12px 24px;border-radius:8px;">{escape(button_label)}</a></p>'
        )

    html = f"""<!doctype html>
<html lang="en">
  <body style="margin:0;background:#f4f4f4;font-family:Arial,Helvetica,sans-serif;color:#24352e;">
    <div style="padding:20px 12px;">
      <div style="max-width:600px;margin:0 auto;background:#ffffff;border:1px solid #d8e5de;border-radius:10px;overflow:hidden;">
        <img src="{escape(EMAIL_FLYER_URL)}" alt="Eravenda Market" style="display:block;width:100%;max-width:600px;height:auto;border:0;">
        <div style="padding:20px 24px 24px;line-height:1.6;font-size:15px;">
          {_body_to_html(body)}
          {button_html}
        </div>
        <div style="padding:16px 24px;background:#f5f6f2;border-top:1px solid #e3e1d8;font-size:12px;color:#6b7a72;text-align:center;line-height:1.5;">
          {footer}
        </div>
      </div>
    </div>
  </body>
</html>"""

    headers = {}
    if unsubscribe_url:
        headers = {
            "List-Unsubscribe": f"<{unsubscribe_url}>",
            "List-Unsubscribe-Post": "List-Unsubscribe=One-Click",
        }
    return {"subject": subject, "body": text, "html": html, "headers": headers}


def sample_person(db: Session, message: dict, people: list[dict] | None = None) -> dict:
    """Someone from the real audience for the preview, so placeholders show
    realistic values. Falls back to a made-up person when the group is empty.
    Pass `people` when the audience was already loaded, to avoid loading it twice."""
    if people is None:
        people = preview_people(db, message)
    if people:
        return people[0]
    return _person(
        "sample@example.com", "Ama Mensah", store_name="Ama's Store", job_title="Electrician",
        unsubscribe_url=f"{SITE_URL}/api/newsletter/unsubscribe?token=preview"
        if message["audience"] == "subscribers" else None,
    )


# --------------------------------------------------------------------------
# Sending
# --------------------------------------------------------------------------

def _require_email_ready() -> None:
    if not email_utils.email_configured():
        raise BroadcastError(
            "Email is not set up on the server: RESEND_API_KEY is missing. "
            "Add it (and FROM_EMAIL) in the Render Environment tab and redeploy.",
            503,
        )


def send_test(db: Session, message: dict, to_email: str) -> dict:
    """One copy, to the admin only, with a [TEST] subject. Never recorded as a campaign."""
    _require_email_ready()
    check_message(message)
    person = sample_person(db, message)
    person = {**person, "email": to_email}
    rendered = render_message(message, person)
    try:
        results = send_email_batch([{
            "to": to_email, "subject": f"[TEST] {rendered['subject']}", "body": rendered["body"],
            "html": rendered["html"], "headers": rendered["headers"] or None,
        }])
    except EmailDeliveryError as exc:
        raise BroadcastError(f"The email provider refused the test: {exc}", 502)
    if not results or not results[0]:
        raise BroadcastError("The test email could not be sent. Check the server logs.", 502)
    return {"sent_to": to_email}


def _expire_stale(db: Session) -> None:
    cutoff = datetime.utcnow() - STALE_SENDING_AFTER
    stale = (
        db.query(models.EmailCampaign)
        .filter(models.EmailCampaign.status == "sending", models.EmailCampaign.created_at < cutoff)
        .all()
    )
    for campaign in stale:  # its worker died with the server
        campaign.status = "interrupted"
        campaign.finished_at = datetime.utcnow()
        campaign.error = campaign.error or "The server restarted before this send finished."
    if stale:
        db.commit()


def campaign_dict(c: models.EmailCampaign, with_body: bool = False) -> dict:
    out = {
        "id": c.id,
        "audience": c.audience,
        "audience_label": (
            f"One user: {c.target_email}" if c.audience == "user" and c.target_email
            else AUDIENCES.get(c.audience, {}).get("label", c.audience)
        ),
        "target_email": c.target_email,
        "include_pending": c.include_pending,
        "subject": c.subject,
        "status": c.status,
        "recipient_count": c.recipient_count,
        "sent_count": c.sent_count,
        "failed_count": c.failed_count,
        "error": c.error,
        "created_at": c.created_at.isoformat() if c.created_at else None,
        "finished_at": c.finished_at.isoformat() if c.finished_at else None,
    }
    if with_body:
        out.update(body=c.body, button_label=c.button_label, button_url=c.button_url)
    return out


def start_campaign(db: Session, message: dict, admin_id: str) -> dict:
    """Validates, claims the send slot and starts delivering in the background."""
    _require_email_ready()
    check_message(message)
    _expire_stale(db)

    running = db.query(models.EmailCampaign).filter(models.EmailCampaign.status == "sending").first()
    if running:
        raise BroadcastError(
            "Another email is still being sent. Wait for it to finish (see Recent sends below), then try again.", 409
        )

    # For a single-user send, "the same audience" means the same person, so the
    # duplicate guard below must not stop one message going to two people.
    target_email = None
    if message["audience"] == "user":
        target_email = _single_user(db, message.get("user_id"))["email"].lower()

    twin_query = db.query(models.EmailCampaign).filter(
        models.EmailCampaign.audience == message["audience"],
        models.EmailCampaign.subject == message["subject"],
        models.EmailCampaign.body == message["body"],
        models.EmailCampaign.created_at >= datetime.utcnow() - DUPLICATE_WINDOW,
    )
    if target_email:
        twin_query = twin_query.filter(func.lower(models.EmailCampaign.target_email) == target_email)
    twin = twin_query.first()
    if twin:
        raise BroadcastError(
            "This exact message was already sent to this " + ("person" if target_email else "audience")
            + " in the last 10 minutes, so it was not sent again. "
            "Change the message if you really want to send another.", 409
        )

    recipients = resolve_recipients(
        db, message["audience"], message.get("include_pending", False), message.get("user_id")
    )
    if not recipients:
        raise BroadcastError("There is nobody in this audience yet, so there is nothing to send.")
    if len(recipients) > MAX_RECIPIENTS:
        raise BroadcastError(
            f"This audience has {len(recipients):,} people, above the {MAX_RECIPIENTS:,} limit for one send.", 400
        )

    campaign = models.EmailCampaign(
        audience=message["audience"],
        include_pending=bool(message.get("include_pending")),
        subject=message["subject"],
        body=message["body"],
        button_label=message.get("button_label"),
        button_url=message.get("button_url"),
        status="sending",
        recipient_count=len(recipients),
        target_email=target_email,
        sent_by=admin_id,
    )
    db.add(campaign)
    db.commit()
    db.refresh(campaign)

    threading.Thread(
        target=_deliver, args=(campaign.id, dict(message), recipients),
        daemon=True, name=f"broadcast-{campaign.id[:8]}",
    ).start()
    return campaign_dict(campaign)


def _deliver(campaign_id: str, message: dict, recipients: list[dict]) -> None:
    db = SessionLocal()
    try:
        campaign = db.query(models.EmailCampaign).filter(models.EmailCampaign.id == campaign_id).first()
        if not campaign:
            return
        sent = failed = 0
        error = None
        for start in range(0, len(recipients), BATCH_MAX):
            chunk = recipients[start:start + BATCH_MAX]
            messages = []
            for person in chunk:
                rendered = render_message(message, person)
                item = {"to": person["email"], "subject": rendered["subject"], "body": rendered["body"], "html": rendered["html"]}
                if rendered["headers"]:
                    item["headers"] = rendered["headers"]
                messages.append(item)
            try:
                results = send_email_batch(messages)
            except EmailConfigError as exc:
                error = f"The email provider refused the send: {exc}"
                failed += len(recipients) - start
                break
            except EmailDeliveryError as exc:
                error = f"Sending stopped: {exc}"
                failed += len(recipients) - start
                break
            sent += sum(1 for ok in results if ok)
            failed += sum(1 for ok in results if not ok)
            campaign.sent_count, campaign.failed_count = sent, failed
            db.commit()
            if start + BATCH_MAX < len(recipients):
                time.sleep(BATCH_PAUSE_SECONDS)

        campaign.sent_count, campaign.failed_count = sent, failed
        campaign.error = error[:500] if error else None
        campaign.status = "failed" if (error or (sent == 0 and failed > 0)) else "completed"
        campaign.finished_at = datetime.utcnow()
        db.commit()
        logger.info("Broadcast %s (%s): sent=%s failed=%s", campaign_id, message["audience"], sent, failed)
    except Exception as exc:
        logger.exception("Broadcast %s crashed", campaign_id)
        try:
            db.rollback()
            campaign = db.query(models.EmailCampaign).filter(models.EmailCampaign.id == campaign_id).first()
            if campaign:
                campaign.status = "failed"
                campaign.error = f"Unexpected error: {exc}"[:500]
                campaign.finished_at = datetime.utcnow()
                db.commit()
        except Exception:
            logger.exception("Could not record the failure of broadcast %s", campaign_id)
    finally:
        db.close()

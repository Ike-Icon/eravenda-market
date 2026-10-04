import hmac
import logging
import os
from html import escape
from urllib.parse import quote

from fastapi import APIRouter, Depends, Header, HTTPException, status  # type: ignore[reportMissingImports]
from fastapi.responses import HTMLResponse, JSONResponse  # type: ignore[reportMissingImports]
from sqlalchemy import func  # type: ignore[reportMissingImports]
from sqlalchemy.exc import IntegrityError  # type: ignore[reportMissingImports]
from sqlalchemy.orm import Session  # type: ignore[reportMissingImports]

from .. import models, schemas, auth, email_utils
from ..database import get_db
from ..newsletter_service import NewsletterSendError, send_weekly_digest

router = APIRouter(prefix="/newsletter", tags=["newsletter"])
logger = logging.getLogger("eravenda.newsletter")

# Shared secret for the scheduled weekly send, since a cron job has no user
# to log in as. Set NEWSLETTER_CRON_SECRET in .env / Render and put the same
# value in whatever calls /cron/send-weekly (see docs/newsletter-cron.md).
CRON_SECRET = os.getenv("NEWSLETTER_CRON_SECRET")


@router.post("/subscribe", status_code=status.HTTP_201_CREATED)
def subscribe(payload: schemas.NewsletterSubscribeCreate, db: Session = Depends(get_db)):
    email = payload.email.strip().lower()
    existing = db.query(models.NewsletterSubscriber).filter(models.NewsletterSubscriber.email == email).first()

    if existing:
        if existing.is_active:
            return {"message": "You're already subscribed."}
        existing.is_active = True
        db.commit()
        return {"message": "Welcome back, you're subscribed again."}

    db.add(models.NewsletterSubscriber(email=email))
    try:
        db.commit()
    except IntegrityError:
        # Two clicks at once: the other request won the race. Same outcome.
        db.rollback()
        return {"message": "You're already subscribed."}
    return {"message": "Subscribed! Look out for new arrivals every week."}


def _unsubscribe_page(message: str, confirm_token: str | None = None) -> HTMLResponse:
    button = ""
    if confirm_token:
        button = (
            f'<form method="post" action="/api/newsletter/unsubscribe?token={quote(confirm_token, safe="")}">'
            '<button type="submit" style="background:#1c6b4f;color:#fff;border:0;border-radius:8px;'
            'padding:12px 24px;font-weight:700;font-size:15px;cursor:pointer;margin:8px 0 16px;">'
            "Yes, unsubscribe me</button></form>"
        )
    return HTMLResponse(f"""<!doctype html>
<html lang="en">
  <head><meta name="viewport" content="width=device-width, initial-scale=1"><meta name="robots" content="noindex"></head>
  <body style="font-family:Arial,Helvetica,sans-serif;background:#f5f6f2;color:#14201b;padding:48px 16px;text-align:center;">
    <div style="max-width:420px;margin:0 auto;background:#ffffff;border:1px solid #e3e1d8;border-radius:10px;padding:32px;">
      <h2 style="color:#0b2d20;margin-top:0;">Eravenda Market</h2>
      <p style="line-height:1.6;">{escape(message)}</p>
      {button}
      <a href="/" style="color:#1c6b4f;font-weight:600;text-decoration:none;">Back to Eravenda Market</a>
    </div>
  </body>
</html>""")


@router.get("/unsubscribe", response_class=HTMLResponse)
def unsubscribe_confirm(token: str, db: Session = Depends(get_db)):
    """Opening the link only asks for confirmation. Unsubscribing happens on
    POST, because mail scanners (Outlook, Gmail link protection, antivirus)
    open every link in an email, and a link that unsubscribes on GET would
    silently remove people who never clicked it."""
    subscriber = (
        db.query(models.NewsletterSubscriber)
        .filter(models.NewsletterSubscriber.unsubscribe_token == token)
        .first()
    )
    if not subscriber:
        return _unsubscribe_page("This unsubscribe link isn't valid, or you're already unsubscribed.")
    if not subscriber.is_active:
        return _unsubscribe_page("You're already unsubscribed. You won't get any more new-arrival emails from us.")
    return _unsubscribe_page("Stop receiving new-arrival emails from Eravenda Market?", confirm_token=token)


@router.post("/unsubscribe", response_class=HTMLResponse)
def unsubscribe(token: str, db: Session = Depends(get_db)):
    """Used by the confirmation button above and by the one-click unsubscribe
    button in Gmail, Apple Mail and Yahoo (the List-Unsubscribe-Post header
    on every digest)."""
    subscriber = (
        db.query(models.NewsletterSubscriber)
        .filter(models.NewsletterSubscriber.unsubscribe_token == token)
        .first()
    )
    if subscriber:
        subscriber.is_active = False
        db.commit()
        return _unsubscribe_page("You've been unsubscribed. You won't get any more new-arrival emails from us.")
    return _unsubscribe_page("This unsubscribe link isn't valid, or you're already unsubscribed.")


@router.get("/admin/subscribers")
def list_subscribers(
    current_admin: models.User = Depends(auth.require_role(models.UserRole.admin)),
    db: Session = Depends(get_db),
):
    subscribers = (
        db.query(models.NewsletterSubscriber)
        .order_by(models.NewsletterSubscriber.subscribed_at.desc())
        .all()
    )
    active = [s for s in subscribers if s.is_active]
    last_digest_at = db.query(func.max(models.NewsletterSubscriber.last_sent_at)).scalar()
    return {
        "total": len(subscribers),
        "active": len(active),
        "last_digest_at": last_digest_at,
        "email_configured": email_utils.email_configured(),
        "from_email": email_utils.FROM_EMAIL,
        "subscribers": [
            {
                "email": s.email,
                "subscribed_at": s.subscribed_at,
                "is_active": s.is_active,
                "last_sent_at": s.last_sent_at,
            }
            for s in subscribers
        ],
    }


def _run_send(db: Session, **kwargs) -> dict:
    try:
        return send_weekly_digest(db, **kwargs)
    except NewsletterSendError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message)


@router.post("/admin/send-weekly")
def admin_send_weekly(
    force: bool = False,
    current_admin: models.User = Depends(auth.require_role(models.UserRole.admin)),
    db: Session = Depends(get_db),
):
    """Manual "send now" button on the admin dashboard. force=true also
    emails people who already got a digest in the last 6 days."""
    return _run_send(db, force=force)


@router.post("/admin/send-test")
def admin_send_test(
    current_admin: models.User = Depends(auth.require_role(models.UserRole.admin)),
    db: Session = Depends(get_db),
):
    """Sends one copy of the digest to the signed-in admin only. Nobody else
    is emailed and nobody is marked as sent."""
    return _run_send(db, test_email=current_admin.email)


@router.post("/cron/send-weekly")
def cron_send_weekly(
    x_newsletter_secret: str | None = Header(default=None),
    db: Session = Depends(get_db),
):
    """Called by a scheduled job (GitHub Actions cron or a Render Cron Job),
    not by a logged-in admin, so it checks a shared secret instead of a JWT.

    Answers with an error status whenever nothing could be delivered (email
    not configured, Resend refusing the key or domain, every send failing),
    so the scheduled job shows up red instead of silently "succeeding"."""
    if not CRON_SECRET or not x_newsletter_secret or not hmac.compare_digest(x_newsletter_secret.encode(), CRON_SECRET.encode()):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or missing cron secret.")
    result = _run_send(db)
    if result.get("error") or (result["sent"] == 0 and result["failed"] > 0):
        return JSONResponse(status_code=status.HTTP_502_BAD_GATEWAY, content=result)
    return result

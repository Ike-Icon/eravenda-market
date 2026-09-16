import logging
import os

from fastapi import APIRouter, Depends, Header, HTTPException, status  # type: ignore[reportMissingImports]
from fastapi.responses import HTMLResponse  # type: ignore[reportMissingImports]
from sqlalchemy.orm import Session  # type: ignore[reportMissingImports]

from .. import models, schemas, auth
from ..database import get_db
from ..newsletter_service import send_weekly_digest

router = APIRouter(prefix="/newsletter", tags=["newsletter"])
logger = logging.getLogger("eravenda.newsletter")

# Shared secret for the scheduled weekly send, since a cron job has no user
# to log in as. Set NEWSLETTER_CRON_SECRET in .env / Render and put the same
# value in whatever calls /cron/send-weekly (see docs/newsletter-cron.md).
CRON_SECRET = os.getenv("NEWSLETTER_CRON_SECRET")


@router.post("/subscribe", status_code=status.HTTP_201_CREATED)
def subscribe(payload: schemas.NewsletterSubscribeCreate, db: Session = Depends(get_db)):
    email = payload.email.lower()
    existing = db.query(models.NewsletterSubscriber).filter(models.NewsletterSubscriber.email == email).first()

    if existing:
        if existing.is_active:
            return {"message": "You're already subscribed."}
        existing.is_active = True
        db.commit()
        return {"message": "Welcome back, you're subscribed again."}

    subscriber = models.NewsletterSubscriber(email=email)
    db.add(subscriber)
    db.commit()
    return {"message": "Subscribed! Look out for new arrivals every week."}


@router.get("/unsubscribe", response_class=HTMLResponse)
def unsubscribe(token: str, db: Session = Depends(get_db)):
    subscriber = (
        db.query(models.NewsletterSubscriber)
        .filter(models.NewsletterSubscriber.unsubscribe_token == token)
        .first()
    )
    if subscriber:
        subscriber.is_active = False
        db.commit()
        message = "You've been unsubscribed. You won't get any more new-arrival emails from us."
    else:
        message = "This unsubscribe link isn't valid, or you're already unsubscribed."

    return f"""<!doctype html>
<html lang="en">
  <body style="font-family:Arial,Helvetica,sans-serif;background:#f5f6f2;color:#14201b;padding:48px 16px;text-align:center;">
    <div style="max-width:420px;margin:0 auto;background:#ffffff;border:1px solid #e3e1d8;border-radius:10px;padding:32px;">
      <h2 style="color:#0b2d20;margin-top:0;">Eravenda Market</h2>
      <p style="line-height:1.6;">{message}</p>
      <a href="/" style="color:#1c6b4f;font-weight:600;text-decoration:none;">Back to Eravenda Market</a>
    </div>
  </body>
</html>"""


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
    return {
        "total": len(subscribers),
        "active": len(active),
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


@router.post("/admin/send-weekly")
def admin_send_weekly(
    current_admin: models.User = Depends(auth.require_role(models.UserRole.admin)),
    db: Session = Depends(get_db),
):
    """Manual "send now" button for the admin dashboard, useful for testing
    the digest before trusting the scheduled job with it."""
    return send_weekly_digest(db)


@router.post("/cron/send-weekly")
def cron_send_weekly(
    x_newsletter_secret: str | None = Header(default=None),
    db: Session = Depends(get_db),
):
    """Called by a scheduled job (GitHub Actions cron or a Render Cron Job),
    not by a logged-in admin, so it checks a shared secret instead of a JWT."""
    if not CRON_SECRET or x_newsletter_secret != CRON_SECRET:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or missing cron secret.")
    return send_weekly_digest(db)

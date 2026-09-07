import logging

from fastapi import APIRouter, Depends, status  # type: ignore[reportMissingImports]
from sqlalchemy.orm import Session  # type: ignore[reportMissingImports]

from .. import models, schemas
from ..database import get_db
from ..email_utils import SUPPORT_EMAIL, send_email

router = APIRouter(prefix="/contact", tags=["contact"])
logger = logging.getLogger("eravenda.contact")


@router.post("", status_code=status.HTTP_201_CREATED)
def submit_contact_message(payload: schemas.ContactMessageCreate, db: Session = Depends(get_db)):
    message = models.ContactMessage(**payload.model_dump())
    db.add(message)
    db.commit()
    # Keep the database record even when a mail provider is temporarily down.
    # Reply-To lets support answer the customer directly from their inbox.
    try:
        send_email(
            to=SUPPORT_EMAIL,
            subject=f"[Eravenda Support] {payload.subject or 'New customer message'}",
            body=(f"From: {payload.name} <{payload.email}>\n\n{payload.message}"),
            reply_to=str(payload.email),
        )
    except Exception:
        # Email delivery should not discard an already-saved support request.
        logger.exception("Could not send support notification for contact message %s", message.id)
    return {"message": "Thanks for reaching out — we'll get back to you soon."}

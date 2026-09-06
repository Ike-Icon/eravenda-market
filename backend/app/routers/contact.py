from fastapi import APIRouter, Depends, status  # type: ignore[reportMissingImports]
from sqlalchemy.orm import Session  # type: ignore[reportMissingImports]

from .. import models, schemas
from ..database import get_db

router = APIRouter(prefix="/contact", tags=["contact"])


@router.post("", status_code=status.HTTP_201_CREATED)
def submit_contact_message(payload: schemas.ContactMessageCreate, db: Session = Depends(get_db)):
    message = models.ContactMessage(**payload.model_dump())
    db.add(message)
    db.commit()
    return {"message": "Thanks for reaching out — we'll get back to you soon."}

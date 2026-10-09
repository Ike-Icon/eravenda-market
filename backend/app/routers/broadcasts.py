"""Admin Email center API: write, preview, test and send a message to one
audience (users, sellers, professionals, newsletter subscribers), plus saved
templates and the send history. Logic lives in broadcast_service.py."""

import logging

from fastapi import APIRouter, Depends, HTTPException  # type: ignore[reportMissingImports]
from sqlalchemy import or_  # type: ignore[reportMissingImports]
from sqlalchemy.orm import Session  # type: ignore[reportMissingImports]

from .. import models, schemas, auth
from ..broadcast_service import (
    AUDIENCES,
    BroadcastError,
    audience_summary,
    campaign_dict,
    check_message,
    preview_people,
    render_message,
    sample_person,
    send_test,
    start_campaign,
    _expire_stale,
)
from ..database import get_db
from .. import email_utils

router = APIRouter(
    prefix="/admin/broadcasts",
    tags=["admin-broadcasts"],
    dependencies=[Depends(auth.require_role(models.UserRole.admin))],
)
logger = logging.getLogger("eravenda.broadcast")


def _fail(exc: BroadcastError):
    raise HTTPException(status_code=exc.status_code, detail=exc.message)


def _template_dict(t: models.EmailTemplate) -> dict:
    return {
        "id": t.id, "name": t.name, "audience": t.audience, "subject": t.subject, "body": t.body,
        "button_label": t.button_label, "button_url": t.button_url,
        "updated_at": t.updated_at.isoformat() if t.updated_at else None,
    }


@router.get("/audiences")
def list_audiences(db: Session = Depends(get_db)):
    return {
        "audiences": audience_summary(db),
        "email_configured": email_utils.email_configured(),
        "from_email": email_utils.FROM_EMAIL,
    }


@router.get("/users")
def search_users(q: str = "", db: Session = Depends(get_db)):
    """Find one account to email by name or email. Active accounts only, any
    role. Needs at least 2 characters so it never dumps the whole user table."""
    term = (q or "").strip()
    if len(term) < 2:
        return []
    like = "%" + term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
    rows = (
        db.query(models.User)
        .filter(
            models.User.is_active.is_(True),
            or_(models.User.full_name.ilike(like, escape="\\"), models.User.email.ilike(like, escape="\\")),
        )
        .order_by(models.User.full_name)
        .limit(10)
        .all()
    )
    store_names = {}
    if rows:
        store_names = dict(
            db.query(models.Store.owner_id, models.Store.store_name)
            .filter(models.Store.owner_id.in_([u.id for u in rows]))
            .all()
        )
    return [
        {
            "id": u.id,
            "full_name": u.full_name,
            "email": u.email,
            "role": u.role.value if hasattr(u.role, "value") else str(u.role),
            "store_name": store_names.get(u.id),
        }
        for u in rows
    ]


@router.post("/preview")
def preview(payload: schemas.BroadcastMessage, db: Session = Depends(get_db)):
    """Renders the message exactly as a recipient would get it."""
    message = payload.model_dump()
    try:
        check_message(message)
    except BroadcastError as exc:
        _fail(exc)
    try:
        people = preview_people(db, message)
    except BroadcastError as exc:
        _fail(exc)
    person = sample_person(db, message, people)
    rendered = render_message(message, person)
    return {
        "subject": rendered["subject"],
        "html": rendered["html"],
        "text": rendered["body"],
        "preview_for": person["full_name"] if person["email"] != "sample@example.com" else "a sample person",
        "recipient_count": len(people),
    }


@router.post("/send-test")
def send_test_to_me(
    payload: schemas.BroadcastMessage,
    admin: models.User = Depends(auth.get_current_user),
    db: Session = Depends(get_db),
):
    try:
        return send_test(db, payload.model_dump(), admin.email)
    except BroadcastError as exc:
        _fail(exc)


@router.post("/send", status_code=202)
def send_to_audience(
    payload: schemas.BroadcastMessage,
    admin: models.User = Depends(auth.get_current_user),
    db: Session = Depends(get_db),
):
    """Starts delivering in the background and returns the campaign at once.
    Poll GET /campaigns/{id} for progress."""
    try:
        return start_campaign(db, payload.model_dump(), admin.id)
    except BroadcastError as exc:
        _fail(exc)


@router.get("/campaigns")
def list_campaigns(db: Session = Depends(get_db)):
    _expire_stale(db)
    rows = db.query(models.EmailCampaign).order_by(models.EmailCampaign.created_at.desc()).limit(25).all()
    return [campaign_dict(c) for c in rows]


@router.get("/campaigns/{campaign_id}")
def get_campaign(campaign_id: str, db: Session = Depends(get_db)):
    _expire_stale(db)
    c = db.query(models.EmailCampaign).filter(models.EmailCampaign.id == campaign_id).first()
    if not c:
        raise HTTPException(status_code=404, detail="Campaign not found")
    return campaign_dict(c, with_body=True)


@router.get("/templates")
def list_templates(db: Session = Depends(get_db)):
    rows = db.query(models.EmailTemplate).order_by(models.EmailTemplate.updated_at.desc()).all()
    return [_template_dict(t) for t in rows]


@router.post("/templates", status_code=201)
def create_template(
    payload: schemas.EmailTemplateSave,
    admin: models.User = Depends(auth.get_current_user),
    db: Session = Depends(get_db),
):
    t = models.EmailTemplate(**payload.model_dump(), created_by=admin.id)
    db.add(t)
    db.commit()
    db.refresh(t)
    return _template_dict(t)


@router.put("/templates/{template_id}")
def update_template(template_id: str, payload: schemas.EmailTemplateSave, db: Session = Depends(get_db)):
    t = db.query(models.EmailTemplate).filter(models.EmailTemplate.id == template_id).first()
    if not t:
        raise HTTPException(status_code=404, detail="Template not found")
    for key, value in payload.model_dump().items():
        setattr(t, key, value)
    db.commit()
    db.refresh(t)
    return _template_dict(t)


@router.delete("/templates/{template_id}", status_code=204)
def delete_template(template_id: str, db: Session = Depends(get_db)):
    t = db.query(models.EmailTemplate).filter(models.EmailTemplate.id == template_id).first()
    if not t:
        raise HTTPException(status_code=404, detail="Template not found")
    db.delete(t)
    db.commit()

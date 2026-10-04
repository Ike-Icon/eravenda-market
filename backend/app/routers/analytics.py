"""Anonymous page-view beacon. The admin dashboard reads the totals from
/api/admin/traffic (routers/admin.py)."""

import logging
import re
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, Request, Response, status  # type: ignore[reportMissingImports]
from pydantic import BaseModel, Field  # type: ignore[reportMissingImports]
from sqlalchemy.orm import Session  # type: ignore[reportMissingImports]

from .. import models
from ..database import get_db

router = APIRouter(prefix="/analytics", tags=["analytics"])
logger = logging.getLogger("eravenda.analytics")

_VISITOR_ID = re.compile(r"^[A-Za-z0-9_-]{8,64}$")
_BOT_UA = re.compile(r"bot|crawl|spider|slurp|headless|lighthouse|preview|monitor|uptime|curl|python-requests", re.I)
_SKIP_PREFIXES = ("/admin", "/api", "/static", "/css", "/js")
# A refresh or double-fire of the same page by the same browser inside this
# window counts once.
DEDUPE_SECONDS = 30


class VisitIn(BaseModel):
    visitor_id: str = Field(max_length=64)
    path: str = Field(max_length=300)


@router.post("/visit", status_code=status.HTTP_204_NO_CONTENT)
def record_visit(payload: VisitIn, request: Request, db: Session = Depends(get_db)):
    """Always answers 204. Counting a visit must never break or slow a page,
    so anything odd (bad ID, bot, admin page, database hiccup) is dropped
    silently."""
    try:
        path = payload.path.split("?", 1)[0].split("#", 1)[0] or "/"
        if (
            not _VISITOR_ID.match(payload.visitor_id)
            or not path.startswith("/")
            or path.startswith(_SKIP_PREFIXES)
            or _BOT_UA.search(request.headers.get("user-agent", ""))
        ):
            return Response(status_code=status.HTTP_204_NO_CONTENT)

        recent = (
            db.query(models.SiteVisit.id)
            .filter(
                models.SiteVisit.visitor_id == payload.visitor_id,
                models.SiteVisit.path == path,
                models.SiteVisit.created_at >= datetime.utcnow() - timedelta(seconds=DEDUPE_SECONDS),
            )
            .first()
        )
        if not recent:
            db.add(models.SiteVisit(visitor_id=payload.visitor_id, path=path))
            db.commit()
    except Exception:
        db.rollback()
        logger.exception("Could not record page view")
    return Response(status_code=status.HTTP_204_NO_CONTENT)

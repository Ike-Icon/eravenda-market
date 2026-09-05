from fastapi import APIRouter, Depends, HTTPException  # type: ignore[reportMissingImports]
from sqlalchemy.orm import Session  # type: ignore[reportMissingImports]

from .. import models, schemas, auth
from ..database import get_db
from ..utils import slugify

router = APIRouter(prefix="/categories", tags=["categories"])


@router.get("", response_model=list[schemas.CategoryOut])
def list_categories(db: Session = Depends(get_db)):
    return db.query(models.Category).order_by(models.Category.name).all()


@router.post("", response_model=schemas.CategoryOut, status_code=201)
def create_category(
    payload: schemas.CategoryCreate,
    db: Session = Depends(get_db),
    _admin: models.User = Depends(auth.require_role(models.UserRole.admin)),
):
    slug = slugify(payload.name)
    if db.query(models.Category).filter(models.Category.slug == slug).first():
        raise HTTPException(status_code=400, detail="A category with this name already exists")

    category = models.Category(
        name=payload.name, slug=slug, parent_id=payload.parent_id, icon_url=payload.icon_url
    )
    db.add(category)
    db.commit()
    db.refresh(category)
    return category

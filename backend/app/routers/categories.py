from fastapi import APIRouter, Depends, HTTPException  # type: ignore[reportMissingImports]
from sqlalchemy.orm import Session  # type: ignore[reportMissingImports]
from sqlalchemy.exc import IntegrityError  # type: ignore[reportMissingImports]

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


@router.put("/{category_id}", response_model=schemas.CategoryOut)
def update_category(
    category_id: str,
    payload: schemas.CategoryCreate,
    db: Session = Depends(get_db),
    _admin: models.User = Depends(auth.require_role(models.UserRole.admin)),
):
    category = db.query(models.Category).filter(models.Category.id == category_id).first()
    if not category:
        raise HTTPException(status_code=404, detail="Category not found")
    new_slug = slugify(payload.name)
    if new_slug != category.slug and db.query(models.Category).filter(models.Category.slug == new_slug).first():
        raise HTTPException(status_code=400, detail="A category with this name already exists")
    category.name = payload.name
    category.slug = new_slug
    category.parent_id = payload.parent_id
    category.icon_url = payload.icon_url
    db.commit()
    db.refresh(category)
    return category


@router.delete("/{category_id}", status_code=204)
def delete_category(
    category_id: str,
    db: Session = Depends(get_db),
    _admin: models.User = Depends(auth.require_role(models.UserRole.admin)),
):
    """Admin-only removal. Blocked by the DB when products or child
    categories still reference this one, so the admin gets a clear
    message instead of a raw integrity error."""
    category = db.query(models.Category).filter(models.Category.id == category_id).first()
    if not category:
        raise HTTPException(status_code=404, detail="Category not found")
    try:
        db.delete(category)
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=400,
            detail="Can't delete this category — it still has products or sub-categories. Move or remove those first.",
        )

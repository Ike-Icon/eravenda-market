from fastapi import APIRouter, Depends, HTTPException  # pyright: ignore[reportMissingImports]
from sqlalchemy.orm import Session  # pyright: ignore[reportMissingImports]

from .. import models, schemas, auth
from ..database import get_db
from ..utils import slugify, random_suffix

router = APIRouter(prefix="/stores", tags=["stores"])


@router.post("", response_model=schemas.StoreOut, status_code=201)
def create_store(
    payload: schemas.StoreCreate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_user),
):
    if current_user.store is not None:
        raise HTTPException(status_code=400, detail="You already have a store")

    base_slug = slugify(payload.store_name)
    slug = base_slug
    while db.query(models.Store).filter(models.Store.slug == slug).first():
        slug = f"{base_slug}-{random_suffix(4)}"

    store = models.Store(owner_id=current_user.id, slug=slug, **payload.model_dump())
    db.add(store)

    db.commit()
    db.refresh(store)
    return store


@router.get("/me", response_model=schemas.StoreOut)
def get_my_store(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_user),
):
    if not current_user.store:
        raise HTTPException(status_code=404, detail="You don't have a store yet")
    return current_user.store


@router.get("/{store_id}", response_model=schemas.StoreOut)
def get_store(store_id: str, db: Session = Depends(get_db)):
    store = db.query(models.Store).filter(models.Store.id == store_id).first()
    if not store:
        raise HTTPException(status_code=404, detail="Store not found")
    return store

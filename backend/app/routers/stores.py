from fastapi import APIRouter, Depends, HTTPException  # pyright: ignore[reportMissingImports]
from sqlalchemy.orm import Session  # pyright: ignore[reportMissingImports]
import logging

from .. import models, schemas, auth
from ..database import get_db
from ..utils import slugify, random_suffix
from ..email_utils import send_role_welcome_email

router = APIRouter(prefix="/stores", tags=["stores"])
logger = logging.getLogger("eravenda.stores")


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

    try:
        send_role_welcome_email(
            current_user.email, current_user.full_name, "seller",
            [
                "Our team reviews your store details, usually within 1-2 business days.",
                "Once approved, add your products and they'll go live after a quick review.",
                "You'll get an email as soon as your store is approved.",
            ],
            "/seller/dashboard.html",
        )
    except Exception:
        logger.exception("Could not send seller welcome email to %s", current_user.email)

    return store


@router.get("/me", response_model=schemas.StoreOut)
def get_my_store(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_user),
):
    if not current_user.store:
        raise HTTPException(status_code=404, detail="You don't have a store yet")
    return current_user.store


@router.put("/me", response_model=schemas.StoreOut)
def update_my_store(
    payload: schemas.StoreUpdate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_user),
):
    store = current_user.store
    if not store:
        raise HTTPException(status_code=404, detail="You don't have a store yet")

    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(store, field, value)

    db.commit()
    db.refresh(store)
    return store


# Registered ahead of GET /{store_id} below, same reason /me is: FastAPI
# matches routes in declaration order, and "following"/"me" would otherwise
# be swallowed by the single-segment {store_id} pattern.
@router.get("/following", response_model=list[schemas.StoreFollowOut])
def list_followed_stores(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_user),
):
    return (
        db.query(models.StoreFollow)
        .filter(models.StoreFollow.user_id == current_user.id)
        .order_by(models.StoreFollow.created_at.desc())
        .all()
    )


@router.get("/me/followers", response_model=list[schemas.StoreFollowerOut])
def list_my_store_followers(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_user),
):
    if not current_user.store:
        raise HTTPException(status_code=404, detail="You don't have a store yet")
    follows = (
        db.query(models.StoreFollow)
        .filter(models.StoreFollow.store_id == current_user.store.id)
        .order_by(models.StoreFollow.created_at.desc())
        .all()
    )
    return [
        schemas.StoreFollowerOut(
            id=f.user.id, full_name=f.user.full_name, avatar_key=f.user.avatar_key, followed_at=f.created_at
        )
        for f in follows
    ]


@router.get("/{store_id}", response_model=schemas.StoreOut)
def get_store(store_id: str, db: Session = Depends(get_db)):
    store = db.query(models.Store).filter(models.Store.id == store_id).first()
    if not store:
        raise HTTPException(status_code=404, detail="Store not found")
    return store


@router.get("/{store_id}/follow-status")
def get_follow_status(
    store_id: str,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_user),
):
    is_following = (
        db.query(models.StoreFollow)
        .filter(models.StoreFollow.user_id == current_user.id, models.StoreFollow.store_id == store_id)
        .first()
        is not None
    )
    return {"is_following": is_following}


def _sync_follower_count(db: Session, store: models.Store) -> None:
    store.follower_count = db.query(models.StoreFollow).filter(models.StoreFollow.store_id == store.id).count()


@router.post("/{store_id}/follow", response_model=schemas.StoreFollowOut, status_code=201)
def follow_store(
    store_id: str,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_user),
):
    store = db.query(models.Store).filter(models.Store.id == store_id, models.Store.status == models.StoreStatus.approved).first()
    if not store:
        raise HTTPException(status_code=404, detail="Store not found")
    if store.owner_id == current_user.id:
        raise HTTPException(status_code=400, detail="You can't follow your own store")

    existing = (
        db.query(models.StoreFollow)
        .filter(models.StoreFollow.user_id == current_user.id, models.StoreFollow.store_id == store_id)
        .first()
    )
    if existing:
        return existing

    follow = models.StoreFollow(user_id=current_user.id, store_id=store_id)
    db.add(follow)
    db.flush()
    _sync_follower_count(db, store)
    db.commit()
    db.refresh(follow)
    return follow


@router.delete("/{store_id}/follow", status_code=204)
def unfollow_store(
    store_id: str,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_user),
):
    follow = (
        db.query(models.StoreFollow)
        .filter(models.StoreFollow.user_id == current_user.id, models.StoreFollow.store_id == store_id)
        .first()
    )
    if not follow:
        raise HTTPException(status_code=404, detail="You're not following this store")
    store = follow.store
    db.delete(follow)
    db.flush()
    _sync_follower_count(db, store)
    db.commit()

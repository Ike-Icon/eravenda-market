# pyright: reportMissingImports=false

from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import or_

from .. import models, schemas, auth
from ..database import get_db
from ..utils import slugify, random_suffix

router = APIRouter(prefix="/products", tags=["products"])


@router.get("", response_model=schemas.ProductListOut)
def list_products(
    db: Session = Depends(get_db),
    q: Optional[str] = Query(None, description="Search text"),
    category_id: Optional[str] = None,
    min_price: Optional[float] = None,
    max_price: Optional[float] = None,
    brand: Optional[str] = None,
    sort: str = Query("newest", pattern="^(newest|price_asc|price_desc|rating)$"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
):
    query = db.query(models.Product).filter(models.Product.status == models.ProductStatus.approved)

    if q:
        like = f"%{q}%"
        query = query.filter(or_(models.Product.name.ilike(like), models.Product.brand.ilike(like)))
    if category_id:
        child_ids = [
            row[0] for row in db.query(models.Category.id).filter(models.Category.parent_id == category_id).all()
        ]
        query = query.filter(models.Product.category_id.in_([category_id] + child_ids))
    if min_price is not None:
        query = query.filter(models.Product.price >= min_price)
    if max_price is not None:
        query = query.filter(models.Product.price <= max_price)
    if brand:
        query = query.filter(models.Product.brand.ilike(brand))

    if sort == "price_asc":
        query = query.order_by(models.Product.price.asc())
    elif sort == "price_desc":
        query = query.order_by(models.Product.price.desc())
    elif sort == "rating":
        query = query.order_by(models.Product.average_rating.desc())
    else:
        query = query.order_by(models.Product.created_at.desc())

    total = query.count()
    items = query.offset((page - 1) * page_size).limit(page_size).all()

    return schemas.ProductListOut(total=total, page=page, page_size=page_size, items=items)


# ---------- SELLER ENDPOINTS ----------

def _get_owned_store(current_user: models.User) -> models.Store:
    if not current_user.store:
        raise HTTPException(status_code=400, detail="You need a store before you can manage products")
    return current_user.store


@router.get("/store/mine", response_model=list[schemas.ProductOut])
def list_my_products(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.require_role(models.UserRole.seller)),
):
    store = _get_owned_store(current_user)
    return db.query(models.Product).filter(models.Product.store_id == store.id).order_by(
        models.Product.created_at.desc()
    ).all()


@router.get("/{product_id}", response_model=schemas.ProductOut)
def get_product(product_id: str, db: Session = Depends(get_db)):
    product = db.query(models.Product).filter(models.Product.id == product_id).first()
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")
    return product


@router.post("", response_model=schemas.ProductOut, status_code=201)
def create_product(
    payload: schemas.ProductCreate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.require_role(models.UserRole.seller)),
):
    store = _get_owned_store(current_user)
    if store.status != models.StoreStatus.approved:
        raise HTTPException(status_code=403, detail="Your store must be approved before you can list products")

    category = db.query(models.Category).filter(models.Category.id == payload.category_id).first()
    if not category:
        raise HTTPException(status_code=404, detail="Category not found")

    base_slug = slugify(payload.name)
    slug = base_slug
    while db.query(models.Product).filter(
        models.Product.store_id == store.id, models.Product.slug == slug
    ).first():
        slug = f"{base_slug}-{random_suffix(4)}"

    product = models.Product(store_id=store.id, slug=slug, **payload.model_dump())
    db.add(product)
    db.commit()
    db.refresh(product)
    return product


@router.put("/{product_id}", response_model=schemas.ProductOut)
def update_product(
    product_id: str,
    payload: schemas.ProductUpdate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.require_role(models.UserRole.seller)),
):
    store = _get_owned_store(current_user)
    product = db.query(models.Product).filter(
        models.Product.id == product_id, models.Product.store_id == store.id
    ).first()
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")

    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(product, field, value)

    db.commit()
    db.refresh(product)
    return product


@router.delete("/{product_id}", status_code=204)
def delete_product(
    product_id: str,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.require_role(models.UserRole.seller)),
):
    store = _get_owned_store(current_user)
    product = db.query(models.Product).filter(
        models.Product.id == product_id, models.Product.store_id == store.id
    ).first()
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")
    db.delete(product)
    db.commit()


@router.post("/{product_id}/images", response_model=schemas.ProductImageOut, status_code=201)
def add_product_image(
    product_id: str,
    image_url: str,
    is_primary: bool = False,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.require_role(models.UserRole.seller)),
):
    store = _get_owned_store(current_user)
    product = db.query(models.Product).filter(
        models.Product.id == product_id, models.Product.store_id == store.id
    ).first()
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")

    if is_primary:
        db.query(models.ProductImage).filter(models.ProductImage.product_id == product_id).update(
            {"is_primary": False}
        )

    image = models.ProductImage(product_id=product_id, image_url=image_url, is_primary=is_primary)
    db.add(image)
    db.commit()
    db.refresh(image)
    return image

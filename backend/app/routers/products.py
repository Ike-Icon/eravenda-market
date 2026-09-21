# pyright: reportMissingImports=false

from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import or_, func

from .. import models, schemas, auth
from ..database import get_db
from ..utils import slugify, random_suffix
from ..product_pricing import launch_policy_summary

router = APIRouter(prefix="/products", tags=["products"])


def _variant_stock_sum(entries) -> int:
    total = 0
    for entry in entries or []:
        if isinstance(entry, dict):
            try:
                total += max(0, int(entry.get("stock", 0)))
            except (TypeError, ValueError):
                pass
    return total


def _sync_stock_from_variants(product: models.Product) -> None:
    """Keep product.stock_quantity truthful whenever variant stock is used,
    instead of trusting a separately-typed number that can drift from the
    color/size stock the seller actually configured. Sizes take priority
    (most specific to fit), then colors, then priced options — matching the
    same priority orders.py already uses when decrementing stock on sale."""
    if product.sizes:
        product.stock_quantity = _variant_stock_sum(product.sizes)
    elif product.colors:
        product.stock_quantity = _variant_stock_sum(product.colors)
    elif product.options:
        product.stock_quantity = _variant_stock_sum(product.options)


@router.get("/commission-policy", response_model=schemas.ProductCommissionPolicyOut)
def commission_policy():
    return launch_policy_summary()


@router.get("", response_model=schemas.ProductListOut)
def list_products(
    db: Session = Depends(get_db),
    q: Optional[str] = Query(None, description="Search text"),
    category_id: Optional[str] = None,
    min_price: Optional[float] = None,
    max_price: Optional[float] = None,
    brand: Optional[str] = None,
    cod_eligible: Optional[bool] = Query(None, description="Filter to products that accept Pay on Delivery"),
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
        query = query.filter(models.Product.brand.ilike(f"%{brand}%"))
    if cod_eligible is not None:
        query = query.filter(models.Product.cod_eligible == cod_eligible)

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
    _sync_stock_from_variants(product)
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

    _sync_stock_from_variants(product)
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

    next_order = (db.query(func.max(models.ProductImage.sort_order))
                  .filter(models.ProductImage.product_id == product_id).scalar() or 0) + 1
    image = models.ProductImage(product_id=product_id, image_url=image_url, is_primary=is_primary, sort_order=next_order)
    db.add(image)
    db.commit()
    db.refresh(image)
    return image


@router.delete("/{product_id}/images/{image_id}", status_code=204)
def delete_product_image(
    product_id: str,
    image_id: str,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.require_role(models.UserRole.seller)),
):
    store = _get_owned_store(current_user)
    product = db.query(models.Product).filter(
        models.Product.id == product_id, models.Product.store_id == store.id
    ).first()
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")

    image = db.query(models.ProductImage).filter(
        models.ProductImage.id == image_id, models.ProductImage.product_id == product_id
    ).first()
    if not image:
        raise HTTPException(status_code=404, detail="Image not found")
    was_primary = image.is_primary
    db.delete(image)
    db.flush()

    # Deleting the cover photo shouldn't leave the product with no primary
    # image — promote whichever image is now first in display order.
    if was_primary:
        next_image = (db.query(models.ProductImage)
                      .filter(models.ProductImage.product_id == product_id)
                      .order_by(models.ProductImage.sort_order).first())
        if next_image:
            next_image.is_primary = True
    db.commit()


@router.put("/{product_id}/images/reorder", response_model=list[schemas.ProductImageOut])
def reorder_product_images(
    product_id: str,
    payload: schemas.ProductImageReorder,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.require_role(models.UserRole.seller)),
):
    store = _get_owned_store(current_user)
    product = db.query(models.Product).filter(
        models.Product.id == product_id, models.Product.store_id == store.id
    ).first()
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")

    images = {img.id: img for img in db.query(models.ProductImage).filter(models.ProductImage.product_id == product_id).all()}
    if set(payload.image_ids) != set(images.keys()):
        raise HTTPException(status_code=400, detail="image_ids must include every image on this product, exactly once")

    for position, image_id in enumerate(payload.image_ids):
        images[image_id].sort_order = position
        images[image_id].is_primary = (position == 0)
    db.commit()
    return (db.query(models.ProductImage).filter(models.ProductImage.product_id == product_id)
            .order_by(models.ProductImage.sort_order).all())


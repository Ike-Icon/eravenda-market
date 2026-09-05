from fastapi import APIRouter, Depends, HTTPException  # pyright: ignore[reportMissingImports]
from sqlalchemy.orm import Session  # pyright: ignore[reportMissingImports]
from sqlalchemy import func  # pyright: ignore[reportMissingImports]

from .. import models, schemas, auth
from ..database import get_db

router = APIRouter(prefix="/admin", tags=["admin"], dependencies=[Depends(auth.require_role(models.UserRole.admin))])


@router.get("/stores/pending", response_model=list[schemas.StoreOut])
def pending_stores(db: Session = Depends(get_db)):
    return db.query(models.Store).filter(models.Store.status == models.StoreStatus.pending).all()


@router.put("/stores/{store_id}/approve", response_model=schemas.StoreOut)
def approve_store(store_id: str, db: Session = Depends(get_db)):
    store = db.query(models.Store).filter(models.Store.id == store_id).first()
    if not store:
        raise HTTPException(status_code=404, detail="Store not found")
    store.status = models.StoreStatus.approved
    store.rejection_reason = None
    db.commit()
    db.refresh(store)
    return store


@router.put("/stores/{store_id}/reject", response_model=schemas.StoreOut)
def reject_store(store_id: str, payload: schemas.StoreDecision, db: Session = Depends(get_db)):
    store = db.query(models.Store).filter(models.Store.id == store_id).first()
    if not store:
        raise HTTPException(status_code=404, detail="Store not found")
    store.status = models.StoreStatus.rejected
    store.rejection_reason = payload.rejection_reason
    db.commit()
    db.refresh(store)
    return store


@router.put("/stores/{store_id}/suspend", response_model=schemas.StoreOut)
def suspend_store(store_id: str, db: Session = Depends(get_db)):
    store = db.query(models.Store).filter(models.Store.id == store_id).first()
    if not store:
        raise HTTPException(status_code=404, detail="Store not found")
    store.status = models.StoreStatus.suspended
    db.commit()
    db.refresh(store)
    return store


@router.get("/products/pending", response_model=list[schemas.ProductOut])
def pending_products(db: Session = Depends(get_db)):
    return db.query(models.Product).filter(models.Product.status == models.ProductStatus.pending).all()


@router.put("/products/{product_id}/approve", response_model=schemas.ProductOut)
def approve_product(product_id: str, db: Session = Depends(get_db)):
    product = db.query(models.Product).filter(models.Product.id == product_id).first()
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")
    product.status = models.ProductStatus.approved
    product.rejection_reason = None
    db.commit()
    db.refresh(product)
    return product


@router.put("/products/{product_id}/reject", response_model=schemas.ProductOut)
def reject_product(product_id: str, payload: schemas.StoreDecision, db: Session = Depends(get_db)):
    product = db.query(models.Product).filter(models.Product.id == product_id).first()
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")
    product.status = models.ProductStatus.rejected
    product.rejection_reason = payload.rejection_reason
    db.commit()
    db.refresh(product)
    return product


@router.get("/users", response_model=list[schemas.UserOut])
def list_users(db: Session = Depends(get_db)):
    return db.query(models.User).order_by(models.User.created_at.desc()).all()


@router.put("/users/{user_id}/suspend", response_model=schemas.UserOut)
def suspend_user(user_id: str, db: Session = Depends(get_db)):
    user = db.query(models.User).filter(models.User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    user.is_active = False
    db.commit()
    db.refresh(user)
    return user


@router.get("/stats")
def platform_stats(db: Session = Depends(get_db)):
    total_orders = db.query(func.count(models.Order.id)).scalar() or 0
    total_revenue = db.query(func.coalesce(func.sum(models.Order.commission_amount), 0)).filter(
        models.Order.status != models.OrderStatus.cancelled
    ).scalar()
    total_sellers = db.query(func.count(models.Store.id)).filter(
        models.Store.status == models.StoreStatus.approved
    ).scalar() or 0
    total_products = db.query(func.count(models.Product.id)).filter(
        models.Product.status == models.ProductStatus.approved
    ).scalar() or 0
    pending_stores_count = db.query(func.count(models.Store.id)).filter(
        models.Store.status == models.StoreStatus.pending
    ).scalar() or 0

    return {
        "total_orders": total_orders,
        "platform_revenue": float(total_revenue or 0),
        "active_sellers": total_sellers,
        "active_products": total_products,
        "pending_store_approvals": pending_stores_count,
    }

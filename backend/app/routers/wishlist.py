from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from .. import auth, models, schemas
from ..database import get_db

router = APIRouter(prefix="/wishlist", tags=["wishlist"])


@router.get("", response_model=list[schemas.WishlistOut])
def list_wishlist(db: Session = Depends(get_db), current_user: models.User = Depends(auth.get_current_user)):
    return db.query(models.Wishlist).filter(models.Wishlist.user_id == current_user.id).order_by(models.Wishlist.created_at.desc()).all()


@router.post("/{product_id}", response_model=schemas.WishlistOut, status_code=status.HTTP_201_CREATED)
def add_to_wishlist(product_id: str, db: Session = Depends(get_db), current_user: models.User = Depends(auth.get_current_user)):
    product = db.query(models.Product).filter(models.Product.id == product_id, models.Product.status == models.ProductStatus.approved).first()
    if not product:
        raise HTTPException(status_code=404, detail="Product not available")
    item = db.query(models.Wishlist).filter(models.Wishlist.user_id == current_user.id, models.Wishlist.product_id == product_id).first()
    if item:
        return item
    item = models.Wishlist(user_id=current_user.id, product_id=product_id)
    db.add(item); db.commit(); db.refresh(item)
    return item


@router.delete("/{product_id}", status_code=204)
def remove_from_wishlist(product_id: str, db: Session = Depends(get_db), current_user: models.User = Depends(auth.get_current_user)):
    item = db.query(models.Wishlist).filter(models.Wishlist.user_id == current_user.id, models.Wishlist.product_id == product_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Wishlist item not found")
    db.delete(item); db.commit()

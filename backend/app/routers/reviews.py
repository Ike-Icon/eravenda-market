from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import func

from .. import auth, models, schemas
from ..database import get_db

router = APIRouter(prefix="/reviews", tags=["reviews"])


@router.post("", response_model=schemas.ReviewOut, status_code=201)
def rate_purchased_product(payload: schemas.ReviewCreate, db: Session = Depends(get_db), current_user: models.User = Depends(auth.get_current_user)):
    if not payload.order_item_id:
        raise HTTPException(status_code=400, detail="A purchased order item is required to leave a review")
    item = db.query(models.OrderItem).filter(models.OrderItem.id == payload.order_item_id, models.OrderItem.product_id == payload.product_id).first()
    order = item.order if item else None
    if not order or order.buyer_id != current_user.id or order.status != models.OrderStatus.delivered:
        raise HTTPException(status_code=403, detail="You can rate this item only after your order is delivered")
    review = db.query(models.Review).filter(models.Review.buyer_id == current_user.id, models.Review.order_item_id == item.id).first()
    if review:
        review.rating, review.comment = payload.rating, payload.comment
    else:
        review = models.Review(product_id=payload.product_id, buyer_id=current_user.id, order_item_id=item.id, rating=payload.rating, comment=payload.comment)
        db.add(review)
    db.flush()
    product = db.query(models.Product).filter(models.Product.id == payload.product_id).first()
    product.review_count = db.query(models.Review).filter(models.Review.product_id == product.id).count()
    product.average_rating = db.query(func.avg(models.Review.rating)).filter(models.Review.product_id == product.id).scalar() or 0
    db.commit(); db.refresh(review)
    return review

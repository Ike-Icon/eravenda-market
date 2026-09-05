from fastapi import APIRouter, Depends, HTTPException, status  # type: ignore[reportMissingImports]
from fastapi.security import OAuth2PasswordRequestForm  # type: ignore[reportMissingImports]
from sqlalchemy.orm import Session  # type: ignore[reportMissingImports]

from .. import models, schemas, auth
from ..database import get_db

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register", response_model=schemas.Token, status_code=status.HTTP_201_CREATED)
def register(payload: schemas.UserCreate, db: Session = Depends(get_db)):
    existing = db.query(models.User).filter(models.User.email == payload.email).first()
    if existing:
        raise HTTPException(status_code=400, detail="An account with this email already exists")

    # Only buyer/seller can self-register. Admin accounts are created directly in the database.
    role = payload.role if payload.role != models.UserRole.admin else models.UserRole.buyer

    user = models.User(
        full_name=payload.full_name,
        email=payload.email,
        phone=payload.phone,
        password_hash=auth.hash_password(payload.password),
        role=role,
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    # Every buyer gets an empty cart right away
    db.add(models.Cart(user_id=user.id))
    db.commit()

    token = auth.create_access_token({"sub": user.id, "role": user.role.value})
    return schemas.Token(access_token=token, user=schemas.UserOut.model_validate(user))


@router.post("/login", response_model=schemas.Token)
def login(form_data: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    user = db.query(models.User).filter(models.User.email == form_data.username).first()
    if not user or not auth.verify_password(form_data.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Incorrect email or password")
    if not user.is_active:
        raise HTTPException(status_code=403, detail="This account has been deactivated")

    token = auth.create_access_token({"sub": user.id, "role": user.role.value})
    return schemas.Token(access_token=token, user=schemas.UserOut.model_validate(user))


@router.get("/me", response_model=schemas.UserOut)
def get_me(current_user: models.User = Depends(auth.get_current_user)):
    return current_user


@router.post("/addresses", response_model=schemas.AddressOut, status_code=status.HTTP_201_CREATED)
def add_address(
    payload: schemas.AddressCreate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_user),
):
    address = models.Address(user_id=current_user.id, **payload.model_dump())
    db.add(address)
    db.commit()
    db.refresh(address)
    return address


@router.get("/addresses", response_model=list[schemas.AddressOut])
def list_addresses(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_user),
):
    return db.query(models.Address).filter(models.Address.user_id == current_user.id).all()

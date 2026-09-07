import os

from fastapi import APIRouter, Depends, HTTPException, status  # type: ignore[reportMissingImports]
from fastapi.security import OAuth2PasswordRequestForm  # type: ignore[reportMissingImports]
from sqlalchemy.orm import Session  # type: ignore[reportMissingImports]

from .. import models, schemas, auth
from ..database import get_db
from ..email_utils import send_email

router = APIRouter(prefix="/auth", tags=["auth"])
SITE_URL = os.getenv("SITE_URL", "http://localhost:8000")


@router.post("/register", response_model=schemas.Token, status_code=status.HTTP_201_CREATED)
def register(payload: schemas.UserCreate, db: Session = Depends(get_db)):
    existing = db.query(models.User).filter(models.User.email == payload.email).first()
    if existing:
        raise HTTPException(status_code=400, detail="An account with this email already exists")

    # Accounts always begin as buyers. A store application is reviewed by an
    # admin, who promotes its owner once the store has been approved.
    role = models.UserRole.buyer

    user = models.User(
        full_name=payload.full_name,
        email=payload.email,
        phone=payload.phone,
        avatar_key=payload.avatar_key,
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


@router.post("/forgot-password", status_code=status.HTTP_200_OK)
def forgot_password(payload: schemas.ForgotPasswordRequest, db: Session = Depends(get_db)):
    # Always return the same generic message whether or not the email
    # exists — confirming which emails are registered is its own leak.
    generic_response = {"message": "If an account exists for that email, a reset link has been sent."}

    user = db.query(models.User).filter(models.User.email == payload.email).first()
    if not user:
        return generic_response

    token = auth.create_password_reset_token(user.id)
    reset_link = f"{SITE_URL}/reset-password?token={token}"

    send_email(
        to=user.email,
        subject="Reset your Eravenda Market password",
        body=(
            f"Hi {user.full_name},\n\n"
            f"Click the link below to reset your password. It expires in "
            f"{auth.PASSWORD_RESET_EXPIRE_MINUTES} minutes:\n\n{reset_link}\n\n"
            "If you didn't request this, you can safely ignore this email."
        ),
    )
    return generic_response


@router.post("/reset-password", status_code=status.HTTP_200_OK)
def reset_password(payload: schemas.ResetPasswordRequest, db: Session = Depends(get_db)):
    user_id = auth.verify_password_reset_token(payload.token)

    user = db.query(models.User).filter(models.User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=400, detail="This reset link is invalid or has expired.")

    user.password_hash = auth.hash_password(payload.new_password)
    db.commit()
    return {"message": "Your password has been reset. You can log in now."}

import os
import logging
import time
from collections import defaultdict, deque
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, status  # type: ignore[reportMissingImports]
from fastapi.security import OAuth2PasswordRequestForm  # type: ignore[reportMissingImports]
from sqlalchemy.orm import Session  # type: ignore[reportMissingImports]

from .. import models, schemas, auth, social_auth
from ..database import get_db
from ..email_utils import send_email, SITE_URL

router = APIRouter(prefix="/auth", tags=["auth"])
logger = logging.getLogger("eravenda.auth")
_attempts: dict[str, deque[float]] = defaultdict(deque)


def _check_rate_limit(key: str, limit: int, window_seconds: int) -> None:
    now = time.monotonic()
    attempts = _attempts[key]
    while attempts and now - attempts[0] > window_seconds:
        attempts.popleft()
    if len(attempts) >= limit:
        raise HTTPException(status_code=429, detail="Too many attempts. Please try again later.")
    attempts.append(now)


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
    db.flush()
    # Keep account creation atomic: a user should never exist without its cart.
    db.add(models.Cart(user_id=user.id))
    db.commit()
    db.refresh(user)

    token = auth.create_access_token({"sub": user.id, "role": user.role.value})
    return schemas.Token(access_token=token, user=schemas.UserOut.model_validate(user))


@router.post("/login", response_model=schemas.Token)
def login(request: Request, form_data: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    _check_rate_limit(f"login:{request.client.host if request.client else 'unknown'}", 10, 300)
    user = db.query(models.User).filter(models.User.email == form_data.username).first()
    if user and not user.password_hash:
        raise HTTPException(
            status_code=401,
            detail=f"This account signs in with {user.oauth_provider.title()}. Use that button instead, or reset your password to add one.",
        )
    if not user or not auth.verify_password(form_data.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Incorrect email or password")
    if not user.is_active:
        raise HTTPException(status_code=403, detail="This account has been deactivated")

    token = auth.create_access_token({"sub": user.id, "role": user.role.value})
    return schemas.Token(access_token=token, user=schemas.UserOut.model_validate(user))


def _oauth_login_or_register(db: Session, provider: str, claims: dict, fallback_name: Optional[str] = None) -> models.User:
    """Shared by /google and /apple below. Three cases, checked in order:
    1) this provider account has signed in before — just log them in
    2) a password account already exists with the same email — link the
       provider to it, so one person doesn't end up with two accounts
    3) neither exists — create a fresh account
    """
    sub = claims["sub"]

    user = (
        db.query(models.User)
        .filter(models.User.oauth_provider == provider, models.User.oauth_sub == sub)
        .first()
    )
    if user:
        return user

    email = claims.get("email")
    if email:
        user = db.query(models.User).filter(models.User.email == email).first()
        if user:
            user.oauth_provider = provider
            user.oauth_sub = sub
            db.commit()
            db.refresh(user)
            return user
    else:
        raise HTTPException(
            status_code=400,
            detail=f"Your {provider.title()} account didn't share an email address, so we can't sign you in.",
        )

    full_name = fallback_name or claims.get("full_name") or email.split("@")[0]
    user = models.User(
        full_name=full_name,
        email=email,
        password_hash=None,
        oauth_provider=provider,
        oauth_sub=sub,
        is_verified=claims.get("email_verified", False),
        role=models.UserRole.buyer,
    )
    db.add(user)
    db.flush()
    db.add(models.Cart(user_id=user.id))
    db.commit()
    db.refresh(user)
    return user


@router.post("/google", response_model=schemas.Token)
def google_login(payload: schemas.GoogleAuthRequest, db: Session = Depends(get_db)):
    try:
        claims = social_auth.verify_google_token(payload.id_token)
    except social_auth.TokenVerificationError:
        logger.warning("Google sign-in token failed verification")
        raise HTTPException(status_code=401, detail="Could not verify Google sign-in. Please try again.")

    user = _oauth_login_or_register(db, "google", claims)
    if not user.is_active:
        raise HTTPException(status_code=403, detail="This account has been deactivated")

    token = auth.create_access_token({"sub": user.id, "role": user.role.value})
    return schemas.Token(access_token=token, user=schemas.UserOut.model_validate(user))


@router.post("/apple", response_model=schemas.Token)
def apple_login(payload: schemas.AppleAuthRequest, db: Session = Depends(get_db)):
    try:
        claims = social_auth.verify_apple_token(payload.identity_token)
    except social_auth.TokenVerificationError:
        logger.warning("Apple sign-in token failed verification")
        raise HTTPException(status_code=401, detail="Could not verify Apple sign-in. Please try again.")

    user = _oauth_login_or_register(db, "apple", claims, fallback_name=payload.full_name)
    if not user.is_active:
        raise HTTPException(status_code=403, detail="This account has been deactivated")

    token = auth.create_access_token({"sub": user.id, "role": user.role.value})
    return schemas.Token(access_token=token, user=schemas.UserOut.model_validate(user))


@router.get("/me", response_model=schemas.UserOut)
def get_me(current_user: models.User = Depends(auth.get_current_user)):
    return current_user


def _clear_other_default_addresses(db: Session, user_id: str, exclude_id: Optional[str]) -> None:
    """Only one saved address should be flagged default at a time."""
    query = db.query(models.Address).filter(
        models.Address.user_id == user_id,
        models.Address.is_default.is_(True),
    )
    if exclude_id:
        query = query.filter(models.Address.id != exclude_id)
    query.update({"is_default": False}, synchronize_session=False)


@router.post("/addresses", response_model=schemas.AddressOut, status_code=status.HTTP_201_CREATED)
def add_address(
    payload: schemas.AddressCreate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_user),
):
    address = models.Address(user_id=current_user.id, **payload.model_dump())
    db.add(address)
    db.flush()  # assign address.id before we exclude it from the default-clearing update

    if address.is_default:
        _clear_other_default_addresses(db, current_user.id, exclude_id=address.id)

    db.commit()
    db.refresh(address)
    return address


@router.get("/addresses", response_model=list[schemas.AddressOut])
def list_addresses(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_user),
):
    return db.query(models.Address).filter(models.Address.user_id == current_user.id).all()


@router.put("/addresses/{address_id}", response_model=schemas.AddressOut)
def update_address(
    address_id: str,
    payload: schemas.AddressUpdate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_user),
):
    address = (
        db.query(models.Address)
        .filter(models.Address.id == address_id, models.Address.user_id == current_user.id)
        .first()
    )
    if not address:
        raise HTTPException(status_code=404, detail="Address not found")

    updates = payload.model_dump(exclude_unset=True)
    for field, value in updates.items():
        setattr(address, field, value)

    if updates.get("is_default"):
        _clear_other_default_addresses(db, current_user.id, exclude_id=address.id)

    db.commit()
    db.refresh(address)
    return address


@router.delete("/addresses/{address_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_address(
    address_id: str,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_user),
):
    address = (
        db.query(models.Address)
        .filter(models.Address.id == address_id, models.Address.user_id == current_user.id)
        .first()
    )
    if not address:
        raise HTTPException(status_code=404, detail="Address not found")

    db.delete(address)
    db.commit()
    return None


@router.post("/forgot-password", status_code=status.HTTP_200_OK)
def forgot_password(payload: schemas.ForgotPasswordRequest, request: Request, db: Session = Depends(get_db)):
    _check_rate_limit(f"reset:{request.client.host if request.client else 'unknown'}", 5, 3600)
    # Always return the same generic message whether or not the email
    # exists — confirming which emails are registered is its own leak.
    generic_response = {"message": "If an account exists for that email, a reset link has been sent."}

    user = db.query(models.User).filter(models.User.email == payload.email).first()
    if not user:
        return generic_response

    token = auth.create_password_reset_token(user.id)
    reset_link = f"{SITE_URL}/reset-password?token={token}"

    try:
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
    except Exception:
        # Do not expose SMTP/provider details or turn a password recovery
        # request into a 500; the generic response is intentional.
        logger.exception("Could not send password reset email for user %s", user.id)
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

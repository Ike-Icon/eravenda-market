import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status  # type: ignore[reportMissingImports]
from fastapi.security import OAuth2PasswordRequestForm  # type: ignore[reportMissingImports]
from sqlalchemy import func  # type: ignore[reportMissingImports]
from sqlalchemy.orm import Session  # type: ignore[reportMissingImports]

from .. import models, schemas, auth, security, social_auth
from ..database import get_db
from ..email_utils import send_email, SITE_URL

router = APIRouter(prefix="/auth", tags=["auth"])
logger = logging.getLogger("eravenda.auth")


def _find_user_by_email(db: Session, email: str) -> Optional[models.User]:
    """Case-insensitive lookup, so Ama@x.com and ama@x.com are one account."""
    return db.query(models.User).filter(func.lower(models.User.email) == auth.normalize_email(email)).first()


def _send_verification_email(user: models.User) -> None:
    token = auth.create_email_verification_token(user)
    # The token sits after '#', which browsers never send to the server, so it
    # stays out of access logs and Referer headers.
    link = f"{SITE_URL}/verify-email#token={token}"
    try:
        send_email(
            to=user.email,
            subject="Confirm your email for Eravenda Market",
            body=(
                f"Hi {user.full_name},\n\n"
                f"Confirm your email address by opening this link. It expires in {auth.EMAIL_VERIFY_EXPIRE_HOURS} hours:\n\n"
                f"{link}\n\n"
                "If you didn't create an account, you can ignore this email."
            ),
        )
    except Exception:
        # A mail outage must not block sign-up. The person can request a new
        # link from their account page.
        logger.exception("Could not send verification email for user %s", user.id)


def _token_response(user: models.User, response: Response) -> schemas.Token:
    token = auth.issue_session_token(user)
    auth.set_session_cookie(response, token)
    return schemas.Token(access_token=token, user=schemas.UserOut.model_validate(user))


@router.post("/register", response_model=schemas.Token, status_code=status.HTTP_201_CREATED)
def register(payload: schemas.UserCreate, request: Request, response: Response, db: Session = Depends(get_db)):
    security.enforce_rate_limit(request, "register", 10, 3600)
    email = auth.normalize_email(payload.email)
    if _find_user_by_email(db, email):
        raise HTTPException(status_code=400, detail="An account with this email already exists")

    # Accounts always begin as buyers. A store application is reviewed by an
    # admin, who promotes its owner once the store has been approved.
    role = models.UserRole.buyer

    user = models.User(
        full_name=payload.full_name,
        email=email,
        phone=payload.phone,
        avatar_key=payload.avatar_key,
        password_hash=auth.hash_password(payload.password),
        role=role,
        is_verified=False,
    )
    db.add(user)
    db.flush()
    # Keep account creation atomic: a user should never exist without its cart.
    db.add(models.Cart(user_id=user.id))
    db.commit()
    db.refresh(user)

    _send_verification_email(user)
    return _token_response(user, response)


@router.post("/login", response_model=schemas.Token)
def login(request: Request, response: Response, form_data: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    email = auth.normalize_email(form_data.username)
    security.enforce_rate_limit(request, "login", 30, 300)
    security.enforce_rate_limit(request, "login-email", 8, 900, key=email)
    user = _find_user_by_email(db, email)
    if user and not user.password_hash:
        raise HTTPException(
            status_code=401,
            detail=f"This account signs in with {user.oauth_provider.title()}. Use that button instead, or reset your password to add one.",
        )
    if not auth.verify_password_or_burn_time(form_data.password, user.password_hash if user else None):
        raise HTTPException(status_code=401, detail="Incorrect email or password")
    if not user.is_active:
        raise HTTPException(status_code=403, detail="This account has been deactivated")

    if auth.password_needs_rehash(user.password_hash):
        user.password_hash = auth.hash_password(form_data.password)
        db.commit()
        db.refresh(user)

    return _token_response(user, response)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(response: Response):
    """Clears the session cookie. The cookie is HttpOnly, so only the server can."""
    auth.clear_session_cookie(response)
    response.status_code = status.HTTP_204_NO_CONTENT
    return response


def _oauth_login_or_register(db: Session, provider: str, claims: dict, fallback_name: Optional[str] = None) -> models.User:
    """Shared by /google and /apple below. Three cases, checked in order:
    1) this provider account has signed in before: log them in
    2) a password account already exists with the same email: link the
       provider to it, so one person doesn't end up with two accounts
    3) neither exists: create a fresh account

    The provider must say it verified the email address. Without that, anyone
    could claim someone else's address and be merged into their account.
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
    if not email:
        raise HTTPException(
            status_code=400,
            detail=f"Your {provider.title()} account didn't share an email address, so we can't sign you in.",
        )
    if claims.get("email_verified") is not True:
        raise HTTPException(
            status_code=400,
            detail=f"{provider.title()} hasn't verified that email address, so we can't sign you in with it.",
        )
    email = auth.normalize_email(email)

    user = _find_user_by_email(db, email)
    if user:
        if not user.is_verified:
            # This account's email was never confirmed. Someone may have
            # registered it with a password before the real owner showed up.
            # The provider has now proven who owns the address, so drop the
            # old password. The owner can set a new one with "Forgot password".
            user.password_hash = None
        user.oauth_provider = provider
        user.oauth_sub = sub
        user.is_verified = True
        db.commit()
        db.refresh(user)
        return user

    full_name = fallback_name or claims.get("full_name") or email.split("@")[0]
    user = models.User(
        full_name=full_name[:120],
        email=email,
        password_hash=None,
        oauth_provider=provider,
        oauth_sub=sub,
        is_verified=True,
        role=models.UserRole.buyer,
    )
    db.add(user)
    db.flush()
    db.add(models.Cart(user_id=user.id))
    db.commit()
    db.refresh(user)
    return user


@router.post("/google", response_model=schemas.Token)
def google_login(payload: schemas.GoogleAuthRequest, request: Request, response: Response, db: Session = Depends(get_db)):
    security.enforce_rate_limit(request, "social-login", 20, 300)
    try:
        claims = social_auth.verify_google_token(payload.id_token)
    except social_auth.TokenVerificationError:
        logger.warning("Google sign-in token failed verification")
        raise HTTPException(status_code=401, detail="Could not verify Google sign-in. Please try again.")

    user = _oauth_login_or_register(db, "google", claims)
    if not user.is_active:
        raise HTTPException(status_code=403, detail="This account has been deactivated")
    return _token_response(user, response)


@router.post("/apple", response_model=schemas.Token)
def apple_login(payload: schemas.AppleAuthRequest, request: Request, response: Response, db: Session = Depends(get_db)):
    security.enforce_rate_limit(request, "social-login", 20, 300)
    try:
        claims = social_auth.verify_apple_token(payload.identity_token)
    except social_auth.TokenVerificationError:
        logger.warning("Apple sign-in token failed verification")
        raise HTTPException(status_code=401, detail="Could not verify Apple sign-in. Please try again.")

    user = _oauth_login_or_register(db, "apple", claims, fallback_name=payload.full_name)
    if not user.is_active:
        raise HTTPException(status_code=403, detail="This account has been deactivated")
    return _token_response(user, response)


@router.post("/verify-email", status_code=status.HTTP_200_OK)
def verify_email(payload: schemas.VerifyEmailRequest, request: Request, db: Session = Depends(get_db)):
    security.enforce_rate_limit(request, "verify-email", 20, 3600)
    user = auth.verify_email_verification_token(payload.token, db)
    if not user.is_verified:
        user.is_verified = True
        db.commit()
    return {"message": "Your email address is confirmed."}


@router.post("/resend-verification", status_code=status.HTTP_200_OK)
def resend_verification(request: Request, current_user: models.User = Depends(auth.get_current_user)):
    security.enforce_rate_limit(request, "resend-verification", 5, 3600, key=current_user.id)
    if current_user.is_verified:
        return {"message": "Your email address is already confirmed."}
    _send_verification_email(current_user)
    return {"message": "We sent a new confirmation link to your email."}


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
    email = auth.normalize_email(payload.email)
    security.enforce_rate_limit(request, "reset", 5, 3600)
    security.enforce_rate_limit(request, "reset-email", 3, 3600, key=email)
    # Always return the same generic message whether or not the email
    # exists. Confirming which emails are registered is its own leak.
    generic_response = {"message": "If an account exists for that email, a reset link has been sent."}

    user = _find_user_by_email(db, email)
    if not user or not user.is_active:
        return generic_response

    token = auth.create_password_reset_token(user)
    # '#token=' keeps the token out of server logs and Referer headers.
    reset_link = f"{SITE_URL}/reset-password#token={token}"

    try:
        send_email(
            to=user.email,
            subject="Reset your Eravenda Market password",
            body=(
                f"Hi {user.full_name},\n\n"
                f"Click the link below to reset your password. It expires in "
                f"{auth.PASSWORD_RESET_EXPIRE_MINUTES} minutes and works once:\n\n{reset_link}\n\n"
                "If you didn't request this, you can safely ignore this email."
            ),
        )
    except Exception:
        # Do not expose SMTP/provider details or turn a password recovery
        # request into a 500; the generic response is intentional.
        logger.exception("Could not send password reset email for user %s", user.id)
    return generic_response


@router.post("/reset-password", status_code=status.HTTP_200_OK)
def reset_password(payload: schemas.ResetPasswordRequest, request: Request, response: Response, db: Session = Depends(get_db)):
    security.enforce_rate_limit(request, "reset-password", 10, 3600)
    user = auth.verify_password_reset_token(payload.token, db)

    user.password_hash = auth.hash_password(payload.new_password)
    # Opening the emailed link proves the person controls this address.
    user.is_verified = True
    db.commit()
    # Changing the hash also ends every older session for this account.
    auth.clear_session_cookie(response)
    return {"message": "Your password has been reset. You can log in now."}

import hashlib
import hmac
import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Optional

import jwt  # PyJWT
from fastapi import Depends, HTTPException, Request, Response, status  # type: ignore
from fastapi.security import OAuth2PasswordBearer  # type: ignore
from passlib.context import CryptContext  # type: ignore
from sqlalchemy.orm import Session  # type: ignore

from .database import get_db
from . import models, security

logger = logging.getLogger("eravenda.auth")

SECRET_KEY = os.getenv("SECRET_KEY")
if not SECRET_KEY:
    raise RuntimeError(
        "SECRET_KEY is not set. Generate one with "
        "`python -c \"import secrets; print(secrets.token_hex(32))\"` "
        "and put it in backend/.env — never hardcode a fallback here."
    )
if len(SECRET_KEY) < 32:
    # A warning, not a crash: refusing to boot would take the live site down.
    # Replace the key with a 64-character random value when you can. Doing so
    # signs everyone out once.
    logger.warning("SECRET_KEY is shorter than 32 characters. Use a long random value.")

# Only HMAC algorithms are accepted. A value such as "none" in the environment
# must never turn token verification off.
ALGORITHM = os.getenv("ALGORITHM", "HS256")
if ALGORITHM not in {"HS256", "HS384", "HS512"}:
    raise RuntimeError("ALGORITHM must be HS256, HS384 or HS512.")
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "1440"))
PASSWORD_RESET_EXPIRE_MINUTES = 30
EMAIL_VERIFY_EXPIRE_HOURS = 72

# bcrypt, cost factor 12 (passlib's default). Hashes made with an older cost
# are upgraded automatically the next time that person logs in.
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto", bcrypt__default_rounds=12, bcrypt__min_rounds=12)
# auto_error=False so the session cookie can be used when there is no
# Authorization header.
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="api/auth/login", auto_error=False)

# bcrypt only reads the first 72 bytes of a password.
MAX_PASSWORD_BYTES = 72

# A real bcrypt hash of a random string. Verifying against it when the email
# is unknown makes "no such account" take as long as "wrong password", so
# response time does not reveal which emails are registered.
_DUMMY_HASH = pwd_context.hash("not-a-real-password-" + os.urandom(8).hex())


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(plain: str, hashed: Optional[str]) -> bool:
    if not hashed:
        return False
    try:
        return pwd_context.verify(plain, hashed)
    except (ValueError, TypeError):
        return False


def verify_password_or_burn_time(plain: str, hashed: Optional[str]) -> bool:
    """Like verify_password, but spends the same time when there is no hash."""
    if not hashed:
        pwd_context.verify(plain, _DUMMY_HASH)
        return False
    return verify_password(plain, hashed)


def password_needs_rehash(hashed: Optional[str]) -> bool:
    return bool(hashed) and pwd_context.needs_update(hashed)


def normalize_email(email: str) -> str:
    return (email or "").strip().lower()


def password_fingerprint(user: models.User) -> str:
    """Short keyed digest of the current password hash. It goes into every
    token. Changing or resetting the password changes the fingerprint, which
    ends all older sessions and makes a reset link usable only once."""
    return hmac.new(SECRET_KEY.encode(), (user.password_hash or "").encode(), hashlib.sha256).hexdigest()[:24]


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    to_encode = data.copy()
    now = datetime.now(timezone.utc)
    to_encode.update({"exp": now + (expires_delta or timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)), "iat": now})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)


def issue_session_token(user: models.User) -> str:
    return create_access_token({"sub": user.id, "role": user.role.value, "pwv": password_fingerprint(user)})


def set_session_cookie(response: Response, token: str) -> None:
    """Keeps the login token out of JavaScript. HttpOnly means page scripts
    (and therefore any injected script) cannot read it."""
    response.set_cookie(
        security.SESSION_COOKIE_NAME,
        token,
        max_age=ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        httponly=True,
        secure=security.COOKIE_SECURE,
        samesite="lax",
        path="/",
    )


def clear_session_cookie(response: Response) -> None:
    response.delete_cookie(
        security.SESSION_COOKIE_NAME,
        path="/",
        secure=security.COOKIE_SECURE,
        httponly=True,
        samesite="lax",
    )


def _credentials_exception() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )


def _decode(token: str) -> dict:
    return jwt.decode(
        token,
        SECRET_KEY,
        algorithms=[ALGORITHM],
        options={"require": ["exp", "sub"]},
    )


def _user_from_token(token: str, db: Session) -> Optional[models.User]:
    """The user a login token belongs to, or None for anything not valid."""
    try:
        payload = _decode(token)
    except jwt.PyJWTError:
        return None
    # Reset and verification tokens carry a "purpose". They are only good for
    # their own endpoint and must never work as a login.
    if payload.get("purpose"):
        return None
    user_id = payload.get("sub")
    if not isinstance(user_id, str):
        return None
    try:
        user = db.query(models.User).filter(models.User.id == user_id).first()
    except Exception:
        db.rollback()
        return None
    if user is None or not user.is_active:
        return None
    # Tokens issued before this check existed have no "pwv" and stay valid
    # until they expire (at most ACCESS_TOKEN_EXPIRE_MINUTES).
    pwv = payload.get("pwv")
    if pwv is not None and not hmac.compare_digest(str(pwv), password_fingerprint(user)):
        return None
    return user


def _token_from_request(request: Request, bearer: Optional[str]) -> tuple[Optional[str], str]:
    if bearer:
        return bearer, "header"
    cookie = request.cookies.get(security.SESSION_COOKIE_NAME)
    if cookie:
        return cookie, "cookie"
    return None, "none"


def get_current_user(
    request: Request,
    bearer: Optional[str] = Depends(oauth2_scheme),
    db: Session = Depends(get_db),
) -> models.User:
    token, source = _token_from_request(request, bearer)
    if not token:
        raise _credentials_exception()
    if source == "cookie":
        # A browser attaches cookies on its own, so a cookie login needs the
        # cross-site check. A bearer header is attached only by our own
        # script, so it does not.
        security.enforce_same_origin(request)
    user = _user_from_token(token, db)
    if user is None:
        raise _credentials_exception()
    return user


def get_optional_user(
    request: Request,
    bearer: Optional[str] = Depends(oauth2_scheme),
    db: Session = Depends(get_db),
) -> Optional[models.User]:
    """The signed-in user, or None. Never raises. For page routes that
    redirect instead of returning 401."""
    token, _source = _token_from_request(request, bearer)
    if not token:
        return None
    return _user_from_token(token, db)


def require_role(*roles: models.UserRole):
    def checker(user: models.User = Depends(get_current_user)) -> models.User:
        if user.role not in roles:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not permitted for this role")
        return user
    return checker


# ---------------------------------------------------------------------------
# Single-purpose tokens: password reset and email verification
# ---------------------------------------------------------------------------
def create_password_reset_token(user: models.User) -> str:
    """Stateless reset token. The 'pwv' claim ties it to the current password,
    so it stops working the moment the password changes: one use only."""
    return create_access_token(
        {"sub": user.id, "purpose": "password_reset", "pwv": password_fingerprint(user)},
        expires_delta=timedelta(minutes=PASSWORD_RESET_EXPIRE_MINUTES),
    )


def verify_password_reset_token(token: str, db: Session) -> models.User:
    """The user a valid, unused reset token belongs to, or a 400."""
    invalid = HTTPException(status_code=400, detail="This reset link is invalid or has expired.")
    try:
        payload = _decode(token)
    except jwt.PyJWTError:
        raise invalid
    if payload.get("purpose") != "password_reset" or not isinstance(payload.get("sub"), str):
        raise invalid
    try:
        user = db.query(models.User).filter(models.User.id == payload["sub"]).first()
    except Exception:
        db.rollback()
        raise invalid
    if not user or not user.is_active:
        raise invalid
    if not hmac.compare_digest(str(payload.get("pwv", "")), password_fingerprint(user)):
        raise invalid  # already used, or the password changed since
    return user


def create_email_verification_token(user: models.User) -> str:
    return create_access_token(
        {"sub": user.id, "purpose": "email_verify", "email": normalize_email(user.email)},
        expires_delta=timedelta(hours=EMAIL_VERIFY_EXPIRE_HOURS),
    )


def verify_email_verification_token(token: str, db: Session) -> models.User:
    invalid = HTTPException(status_code=400, detail="This verification link is invalid or has expired.")
    try:
        payload = _decode(token)
    except jwt.PyJWTError:
        raise invalid
    if payload.get("purpose") != "email_verify" or not isinstance(payload.get("sub"), str):
        raise invalid
    try:
        user = db.query(models.User).filter(models.User.id == payload["sub"]).first()
    except Exception:
        db.rollback()
        raise invalid
    # The link is for one specific address. If the account's email changed
    # since it was sent, the link no longer proves anything.
    if not user or normalize_email(user.email) != payload.get("email"):
        raise invalid
    return user


def require_verified_email_enabled() -> bool:
    """REQUIRE_VERIFIED_EMAIL=true makes checkout, store creation and partner
    registration wait for a verified email address."""
    return (os.getenv("REQUIRE_VERIFIED_EMAIL", "false").strip().lower() in {"1", "true", "yes", "on"})


def require_verified_email(user: models.User) -> None:
    if require_verified_email_enabled() and not user.is_verified:
        raise HTTPException(
            status_code=403,
            detail="Please verify your email address first. Check your inbox, or request a new link from your account page.",
        )

# pyright: reportMissingImports=false
"""
Verifies the ID token a browser gets back from Google Identity Services or
Sign In with Apple JS, and returns the claims we actually care about
(sub, email, name). Nothing here touches the database — routers/auth.py
takes the returned claims and decides whether to log in or create a user.

Both providers sign their tokens with RS256 and rotate keys, so instead of
hardcoding a public key we fetch their published JWKS (JSON Web Key Set)
and cache it for an hour. python-jose can verify a token directly against
a raw JWK dict, so no extra dependency is needed beyond what's already in
requirements.txt.
"""

import os
import time
import logging

import httpx  # type: ignore[reportMissingImports]
from jose import jwt, JWTError  # type: ignore[reportMissingImports]

logger = logging.getLogger("eravenda.social_auth")

GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID")
APPLE_CLIENT_ID = os.getenv("APPLE_CLIENT_ID")  # Apple's "Services ID", e.g. com.eravenda.web

GOOGLE_JWKS_URL = "https://www.googleapis.com/oauth2/v3/certs"
GOOGLE_ISSUERS = {"accounts.google.com", "https://accounts.google.com"}
APPLE_JWKS_URL = "https://appleid.apple.com/auth/keys"
APPLE_ISSUER = "https://appleid.apple.com"

JWKS_CACHE_SECONDS = 3600
_jwks_cache: dict[str, tuple[float, list]] = {}


class TokenVerificationError(Exception):
    """Covers a missing config value, an unreachable JWKS endpoint, an
    unknown key id, or a token that fails signature/issuer/audience checks.
    Routers only need to know verification failed, not why, so they can
    catch this one type and return a generic 401."""


def _get_jwks(url: str) -> list:
    cached = _jwks_cache.get(url)
    if cached and time.time() - cached[0] < JWKS_CACHE_SECONDS:
        return cached[1]
    try:
        response = httpx.get(url, timeout=10)
        response.raise_for_status()
        keys = response.json()["keys"]
    except Exception as exc:
        raise TokenVerificationError(f"Could not fetch signing keys from {url}") from exc
    _jwks_cache[url] = (time.time(), keys)
    return keys


def _verify(token: str, jwks_url: str, valid_issuers: set, audience: str, provider: str) -> dict:
    if not audience:
        raise TokenVerificationError(
            f"{provider.upper()}_CLIENT_ID is not configured on the server. "
            "See docs/social-login-setup.md."
        )

    try:
        header = jwt.get_unverified_header(token)
        kid = header.get("kid")
        keys = _get_jwks(jwks_url)
        key = next((k for k in keys if k.get("kid") == kid), None)
        if key is None:
            raise TokenVerificationError(f"No matching {provider} signing key for this token")

        claims = jwt.decode(token, key, algorithms=[header.get("alg", "RS256")], audience=audience)
    except TokenVerificationError:
        raise
    except JWTError as exc:
        raise TokenVerificationError(f"{provider} token failed verification") from exc

    if claims.get("iss") not in valid_issuers:
        raise TokenVerificationError(f"Unexpected issuer on {provider} token")

    return claims


def verify_google_token(id_token: str) -> dict:
    claims = _verify(id_token, GOOGLE_JWKS_URL, GOOGLE_ISSUERS, GOOGLE_CLIENT_ID, "google")
    return {
        "sub": claims["sub"],
        "email": claims.get("email"),
        "email_verified": bool(claims.get("email_verified", False)),
        "full_name": claims.get("name"),
    }


def verify_apple_token(identity_token: str) -> dict:
    claims = _verify(identity_token, APPLE_JWKS_URL, {APPLE_ISSUER}, APPLE_CLIENT_ID, "apple")
    return {
        "sub": claims["sub"],
        "email": claims.get("email"),
        "email_verified": str(claims.get("email_verified", "false")).lower() == "true",
        # Apple never puts the name in the token itself, only in a separate
        # object sent to the frontend on the very first authorization.
        "full_name": None,
    }

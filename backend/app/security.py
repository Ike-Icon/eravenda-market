"""Shared security helpers: rate limiting, client IP, CSRF origin checks,
log redaction and the Content-Security-Policy.

Nothing here touches the database. Every other module imports from here so the
rules live in one place and can be reviewed together.
"""

import ipaddress
import logging
import os
import re
import threading
import time
from collections import deque
from typing import Optional
from urllib.parse import urlparse

from fastapi import HTTPException, Request  # type: ignore[reportMissingImports]

logger = logging.getLogger("eravenda.security")


# ---------------------------------------------------------------------------
# Environment
# ---------------------------------------------------------------------------
def _truthy(value: Optional[str]) -> bool:
    return (value or "").strip().lower() in {"1", "true", "yes", "on"}


# Render sets RENDER=true on every service. APP_ENV lets you force the mode
# anywhere else (APP_ENV=production).
IS_PRODUCTION = _truthy(os.getenv("RENDER")) or os.getenv("APP_ENV", "").strip().lower() in {"production", "prod"}

SITE_URL = (os.getenv("SITE_URL") or "http://localhost:8000").rstrip("/")

# The session cookie is only marked Secure when the site is served over HTTPS,
# so plain-http local development keeps working.
COOKIE_SECURE = IS_PRODUCTION or SITE_URL.startswith("https://")
# The __Host- prefix makes browsers refuse a cookie that a sibling subdomain
# tries to plant or overwrite. It requires Secure + Path=/ + no Domain.
SESSION_COOKIE_NAME = "__Host-erv_session" if COOKIE_SECURE else "erv_session"


# ---------------------------------------------------------------------------
# Client IP
# ---------------------------------------------------------------------------
def _valid_ip(value: str) -> Optional[str]:
    value = (value or "").strip()
    try:
        ipaddress.ip_address(value)
        return value
    except ValueError:
        return None


def client_ip(request: Request) -> str:
    """Best-effort real client address, used only as a rate-limit key.

    Resolution order:
      1. CLIENT_IP_HEADER, if you set it (for example "cf-connecting-ip").
      2. In production, Cloudflare's CF-Connecting-IP. Render's edge sets it
         and overwrites any value a visitor sends.
      3. The right-most X-Forwarded-For entry. That entry is appended by the
         proxy nearest to us, so a visitor cannot forge it.
      4. The socket peer.
    """
    configured = os.getenv("CLIENT_IP_HEADER", "").strip().lower()
    if configured:
        found = _valid_ip((request.headers.get(configured) or "").split(",")[0])
        if found:
            return found

    if IS_PRODUCTION:
        found = _valid_ip(request.headers.get("cf-connecting-ip", ""))
        if found:
            return found

    forwarded = request.headers.get("x-forwarded-for", "")
    if forwarded and (IS_PRODUCTION or _truthy(os.getenv("TRUST_X_FORWARDED_FOR"))):
        found = _valid_ip(forwarded.split(",")[-1])
        if found:
            return found

    return request.client.host if request.client else "unknown"


# ---------------------------------------------------------------------------
# Rate limiting (in memory, per process)
# ---------------------------------------------------------------------------
class SlidingWindowLimiter:
    """Counts hits per key inside a moving window.

    State lives in this process, which is right for one Render instance. If you
    ever run several instances, each keeps its own counters, so the effective
    limit is multiplied by the instance count. Move to Redis at that point.
    """

    def __init__(self) -> None:
        self._hits: dict[str, deque] = {}
        self._lock = threading.Lock()
        self._calls = 0

    def hit(self, key: str, limit: int, window_seconds: int) -> Optional[int]:
        """Record a hit. Returns None when allowed, or seconds to wait when blocked."""
        now = time.monotonic()
        with self._lock:
            self._calls += 1
            if self._calls % 500 == 0:
                self._purge(now)
            bucket = self._hits.setdefault(key, deque())
            while bucket and now - bucket[0] > window_seconds:
                bucket.popleft()
            if len(bucket) >= limit:
                return max(1, int(window_seconds - (now - bucket[0])) + 1)
            bucket.append(now)
            return None

    def _purge(self, now: float) -> None:
        # Drop keys whose newest hit is older than the longest window we use.
        stale = [k for k, b in self._hits.items() if not b or now - b[-1] > 7200]
        for k in stale:
            del self._hits[k]

    def reset(self) -> None:
        with self._lock:
            self._hits.clear()


limiter = SlidingWindowLimiter()


def rate_limiting_enabled() -> bool:
    # The switch exists so automated tests can create many accounts quickly.
    # It is ignored in production, so it can never weaken the live site.
    if IS_PRODUCTION:
        return True
    return not _truthy(os.getenv("RATE_LIMIT_DISABLED"))


def enforce_rate_limit(request: Request, scope: str, limit: int, window_seconds: int, key: Optional[str] = None) -> None:
    """Raise 429 when `scope` has been hit more than `limit` times in the window.

    `key` defaults to the client IP. Pass an email or user id to limit per account.
    """
    if not rate_limiting_enabled():
        return
    identity = key if key is not None else client_ip(request)
    retry_after = limiter.hit(f"{scope}:{identity}", limit, window_seconds)
    if retry_after is not None:
        raise HTTPException(
            status_code=429,
            detail="Too many attempts. Please try again later.",
            headers={"Retry-After": str(retry_after)},
        )


def rate_limit(scope: str, limit: int, window_seconds: int):
    """FastAPI dependency: `dependencies=[Depends(rate_limit("contact", 5, 3600))]`."""

    def dependency(request: Request) -> None:
        enforce_rate_limit(request, scope, limit, window_seconds)

    return dependency


# ---------------------------------------------------------------------------
# CSRF protection for cookie-authenticated requests
# ---------------------------------------------------------------------------
SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}


def _origin_of(url: str) -> Optional[str]:
    parsed = urlparse(url or "")
    if parsed.scheme in {"http", "https"} and parsed.netloc:
        return f"{parsed.scheme}://{parsed.netloc}".lower()
    return None


def trusted_origins(request: Request) -> set[str]:
    """Origins allowed to make state-changing calls with the session cookie."""
    origins: set[str] = set()
    site = _origin_of(SITE_URL)
    if site:
        origins.add(site)
        parsed = urlparse(site)
        host = parsed.netloc
        # eravenda.com and www.eravenda.com are the same site.
        other = host[4:] if host.startswith("www.") else f"www.{host}"
        origins.add(f"{parsed.scheme}://{other}")
    for item in os.getenv("ALLOWED_ORIGINS", "").split(","):
        origin = _origin_of(item.strip())
        if origin:
            origins.add(origin)
    # The origin the browser is actually talking to. A cross-site attacker
    # cannot make a victim's browser send an Origin header equal to ours.
    host = request.headers.get("host")
    if host:
        scheme = request.headers.get("x-forwarded-proto", request.url.scheme).split(",")[0].strip()
        origins.add(f"{scheme}://{host}".lower())
    return origins


def enforce_same_origin(request: Request) -> None:
    """Block a state-changing request that carries the session cookie but did
    not come from our own pages. SameSite=Lax on the cookie is the first
    layer. This check is the second."""
    if request.method.upper() in SAFE_METHODS:
        return
    allowed = trusted_origins(request)
    origin = request.headers.get("origin")
    if origin and origin != "null":
        if origin.lower().rstrip("/") in allowed:
            return
        raise HTTPException(status_code=403, detail="Cross-site request blocked.")
    referer = _origin_of(request.headers.get("referer", ""))
    if referer:
        if referer in allowed:
            return
        raise HTTPException(status_code=403, detail="Cross-site request blocked.")
    # No Origin and no Referer. Browsers always send one on form posts and
    # fetch() writes, so this is a script or an unusual client. Accept it only
    # when the browser itself says the request is same-origin.
    if request.headers.get("sec-fetch-site", "") in {"same-origin", "none"}:
        return
    raise HTTPException(status_code=403, detail="Cross-site request blocked.")


# ---------------------------------------------------------------------------
# Keeping secrets out of logs
# ---------------------------------------------------------------------------
_SECRET_QUERY = re.compile(r"(?i)((?:[?&#]|\b)(?:token|access_token|id_token|identity_token|secret|password|api[_-]?key)=)[^&\s\"']+")
_JWT_LIKE = re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\b")


def redact(text: str) -> str:
    """Mask tokens and passwords inside a string headed for the logs."""
    if not text:
        return text
    return _JWT_LIKE.sub("[redacted-jwt]", _SECRET_QUERY.sub(r"\1[redacted]", text))


class RedactSecretsFilter(logging.Filter):
    """Masks token=... in URLs and anything shaped like a JWT in log lines,
    including uvicorn's access log, which prints full request paths."""

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            if isinstance(record.msg, str):
                record.msg = redact(record.msg)
            if isinstance(record.args, tuple):
                record.args = tuple(redact(a) if isinstance(a, str) else a for a in record.args)
            elif isinstance(record.args, dict):
                record.args = {k: redact(v) if isinstance(v, str) else v for k, v in record.args.items()}
        except Exception:  # never let log redaction break a request
            pass
        return True


def install_log_redaction() -> None:
    # Production only. On a developer's machine the console fallback should
    # still print reset links so password reset can be tested without email.
    if not (IS_PRODUCTION or _truthy(os.getenv("LOG_REDACTION"))):
        return
    redactor = RedactSecretsFilter()
    for name in ("uvicorn.access", "uvicorn.error", "eravenda", ""):
        target = logging.getLogger(name)
        if not any(isinstance(f, RedactSecretsFilter) for f in target.filters):
            target.addFilter(redactor)
    # Handlers see records from child loggers that never pass through the
    # parent logger's filters, so attach to the root handlers as well.
    for handler in logging.getLogger().handlers:
        if not any(isinstance(f, RedactSecretsFilter) for f in handler.filters):
            handler.addFilter(redactor)


# ---------------------------------------------------------------------------
# Content-Security-Policy
# ---------------------------------------------------------------------------
def build_csp() -> str:
    """Policy for the server-rendered pages.

    The pages use inline <script> blocks, so script-src must allow
    'unsafe-inline'. The directives that do the most work here are
    frame-ancestors, base-uri, object-src, form-action and the connect-src /
    script-src host lists, which stop injected markup from loading code or
    sending data to an attacker's server.
    """
    directives = {
        "default-src": ["'self'"],
        "script-src": [
            "'self'", "'unsafe-inline'",
            "https://cdn.tailwindcss.com", "https://unpkg.com",
            "https://accounts.google.com", "https://appleid.cdn-apple.com",
        ],
        "style-src": [
            "'self'", "'unsafe-inline'",
            "https://fonts.googleapis.com", "https://cdnjs.cloudflare.com",
            "https://accounts.google.com",
        ],
        "font-src": ["'self'", "data:", "https://fonts.gstatic.com", "https://cdnjs.cloudflare.com"],
        # Product photos come from Cloudinary, but the bulk importer accepts
        # any https image link, so images may load from any https host.
        "img-src": ["'self'", "data:", "blob:", "https:"],
        "connect-src": [
            "'self'", "https://api.cloudinary.com",
            "https://accounts.google.com", "https://appleid.apple.com",
        ],
        "frame-src": ["https://accounts.google.com", "https://appleid.apple.com"],
        "object-src": ["'none'"],
        "base-uri": ["'self'"],
        "form-action": ["'self'"],
        "frame-ancestors": ["'none'"],
    }
    if IS_PRODUCTION:
        directives["upgrade-insecure-requests"] = []
    return "; ".join(f"{name} {' '.join(values)}".strip() for name, values in directives.items())


def csp_header() -> Optional[tuple[str, str]]:
    """(header name, value) for the configured CSP mode, or None when off.

    CSP_MODE=report-only (default): the browser logs violations in the console
    but blocks nothing, so you can browse the whole site and check it first.
    CSP_MODE=enforce: the browser blocks anything the policy does not allow.
    CSP_MODE=off: no header.
    """
    mode = os.getenv("CSP_MODE", "report-only").strip().lower()
    if mode == "off":
        return None
    name = "Content-Security-Policy" if mode == "enforce" else "Content-Security-Policy-Report-Only"
    return name, build_csp()

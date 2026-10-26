"""Security regression tests. Each test is an attack or a mistake that used to
work (or could have), written so it fails if the protection is ever removed.

Run against a real PostgreSQL, like the other test files:

    DATABASE_URL=postgresql://localhost:5432/eravenda_test \\
    SECRET_KEY=a-long-random-test-secret-of-32-chars-or-more \\
    RATE_LIMIT_DISABLED=1 python -m pytest tests/test_security.py -q
"""
import io
import os
import subprocess
import sys
import uuid
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

os.environ.setdefault("SECRET_KEY", "test-secret-key-for-security-tests-0123456789")

import jwt  # noqa: E402

from app import auth, models, security  # noqa: E402
from app.database import SessionLocal, engine  # noqa: E402
from app.main import app  # noqa: E402

PWD = "Passw0rd!123"
BACKEND_DIR = Path(__file__).resolve().parent.parent


def _sql(query, **params):
    with engine.begin() as conn:
        return conn.execute(text(query), params)


@pytest.fixture()
def client():
    with TestClient(app, base_url="http://testserver/api") as c:
        yield c


@pytest.fixture()
def limiter_on(monkeypatch):
    monkeypatch.delenv("RATE_LIMIT_DISABLED", raising=False)
    security.limiter.reset()
    yield
    security.limiter.reset()


def _register(client, name="Sec Tester", password=PWD, email=None):
    email = (email or f"sec-{uuid.uuid4().hex[:10]}@example.com").lower()
    r = client.post("/auth/register", json={"full_name": name, "email": email, "password": password})
    assert r.status_code == 201, r.text
    return r.json(), email


def _bearer(token):
    return {"Authorization": f"Bearer {token}"}


def _make_role(client, email, role):
    _sql("UPDATE users SET role = :r WHERE email = :e", r=role, e=email)
    r = client.post("/auth/login", data={"username": email, "password": PWD})
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


def _db_user(email):
    with SessionLocal() as db:
        return db.query(models.User).filter(models.User.email == email).first()


# ---------------------------------------------------------------------------
# Sessions and tokens
# ---------------------------------------------------------------------------
def test_login_sets_http_only_cookie_and_cookie_alone_is_enough(client):
    data, email = _register(client)
    client.cookies.clear()
    r = client.post("/auth/login", data={"username": email, "password": PWD})
    assert r.status_code == 200
    set_cookie = r.headers["set-cookie"].lower()
    assert security.SESSION_COOKIE_NAME.lower() in set_cookie
    assert "httponly" in set_cookie and "samesite=lax" in set_cookie
    # No Authorization header: the cookie authenticates.
    assert client.get("/auth/me").json()["email"] == email


def test_logout_clears_cookie(client):
    _register(client)
    assert client.get("/auth/me").status_code == 200
    assert client.post("/auth/logout", headers={"Origin": "http://testserver"}).status_code == 204
    client.cookies.clear()
    assert client.get("/auth/me").status_code == 401


def test_password_reset_token_cannot_be_used_as_login(client):
    data, email = _register(client)
    user = _db_user(email)
    reset_token = auth.create_password_reset_token(user)
    client.cookies.clear()
    assert client.get("/auth/me", headers=_bearer(reset_token)).status_code == 401
    client.cookies.set(security.SESSION_COOKIE_NAME, reset_token)
    assert client.get("/auth/me").status_code == 401


def test_email_verification_token_cannot_be_used_as_login(client):
    data, email = _register(client)
    token = auth.create_email_verification_token(_db_user(email))
    client.cookies.clear()
    assert client.get("/auth/me", headers=_bearer(token)).status_code == 401


def test_reset_link_works_once_and_ends_old_sessions(client):
    data, email = _register(client)
    old_session = data["access_token"]
    assert client.get("/auth/me", headers=_bearer(old_session)).status_code == 200

    reset_token = auth.create_password_reset_token(_db_user(email))
    r = client.post("/auth/reset-password", json={"token": reset_token, "new_password": "BrandNew#Pass9"})
    assert r.status_code == 200, r.text
    # Same link a second time: refused.
    again = client.post("/auth/reset-password", json={"token": reset_token, "new_password": "Another#Pass99"})
    assert again.status_code == 400
    # The session issued before the reset no longer works.
    client.cookies.clear()
    assert client.get("/auth/me", headers=_bearer(old_session)).status_code == 401
    # New password logs in, old one does not.
    assert client.post("/auth/login", data={"username": email, "password": PWD}).status_code == 401
    assert client.post("/auth/login", data={"username": email, "password": "BrandNew#Pass9"}).status_code == 200


def test_changing_password_ends_other_sessions_but_keeps_this_one(client):
    data, email = _register(client)
    other_device = data["access_token"]
    r = client.put("/users/me/password", headers=_bearer(other_device),
                   json={"current_password": PWD, "new_password": "Changed#Pass77"})
    assert r.status_code == 200, r.text
    new_token = r.json()["access_token"]
    assert client.get("/auth/me", headers=_bearer(new_token)).status_code == 200
    assert client.get("/auth/me", headers=_bearer(other_device)).status_code == 401


def test_tokens_signed_with_a_different_algorithm_or_key_are_rejected(client):
    data, email = _register(client)
    user_id = data["user"]["id"]
    forged_wrong_key = jwt.encode({"sub": user_id}, "not-the-real-secret-key-not-the-real-key", algorithm="HS256")
    assert client.get("/auth/me", headers=_bearer(forged_wrong_key)).status_code == 401
    # An unsigned ("alg": "none") token must never be accepted.
    import base64, json
    b64 = lambda d: base64.urlsafe_b64encode(json.dumps(d).encode()).rstrip(b"=").decode()
    unsigned = f"{b64({'alg': 'none', 'typ': 'JWT'})}.{b64({'sub': user_id, 'exp': 4102444800})}."
    assert client.get("/auth/me", headers=_bearer(unsigned)).status_code == 401


def test_cookie_requests_from_other_sites_are_blocked(client):
    _register(client)  # leaves the session cookie in the client
    url = "/auth/resend-verification"
    assert client.post(url, headers={"Origin": "https://evil.example"}).status_code == 403
    assert client.post(url, headers={"Referer": "https://evil.example/page"}).status_code == 403
    assert client.post(url, headers={"Sec-Fetch-Site": "cross-site"}).status_code == 403
    assert client.post(url).status_code == 403  # no Origin, no Referer, no browser hint
    assert client.post(url, headers={"Origin": "http://testserver"}).status_code == 200
    assert client.post(url, headers={"Sec-Fetch-Site": "same-origin"}).status_code == 200


def test_bearer_header_requests_do_not_need_an_origin(client):
    data, _ = _register(client)
    client.cookies.clear()
    r = client.post("/auth/resend-verification", headers=_bearer(data["access_token"]))
    assert r.status_code == 200


# ---------------------------------------------------------------------------
# Email addresses
# ---------------------------------------------------------------------------
def test_email_is_case_insensitive(client):
    data, email = _register(client, email=f"MiXeD-{uuid.uuid4().hex[:8]}@Example.com")
    assert data["user"]["email"] == email.lower()
    client.cookies.clear()
    dup = client.post("/auth/register", json={"full_name": "Dup", "email": email.upper(), "password": PWD})
    assert dup.status_code == 400
    login = client.post("/auth/login", data={"username": email.upper(), "password": PWD})
    assert login.status_code == 200


def test_new_accounts_start_unverified_and_verify_link_works(client):
    data, email = _register(client)
    assert data["user"]["is_verified"] is False
    token = auth.create_email_verification_token(_db_user(email))
    r = client.post("/auth/verify-email", json={"token": token})
    assert r.status_code == 200, r.text
    assert client.get("/auth/me").json()["is_verified"] is True


def test_verification_link_dies_if_the_email_changes(client):
    data, email = _register(client)
    token = auth.create_email_verification_token(_db_user(email))
    _sql("UPDATE users SET email = :n WHERE email = :o", n=f"moved-{uuid.uuid4().hex[:8]}@example.com", o=email)
    assert client.post("/auth/verify-email", json={"token": token}).status_code == 400


def test_unverified_users_are_held_back_only_when_enforcement_is_on(client, monkeypatch):
    data, email = _register(client)
    headers = _bearer(data["access_token"])
    store = {"store_name": f"Held Store {uuid.uuid4().hex[:4]}", "region": "Bono", "city": "Sunyani"}

    monkeypatch.setenv("REQUIRE_VERIFIED_EMAIL", "true")
    blocked = client.post("/stores", headers=headers, json=store)
    assert blocked.status_code == 403 and "verify your email" in blocked.json()["detail"].lower()

    monkeypatch.setenv("REQUIRE_VERIFIED_EMAIL", "false")
    assert client.post("/stores", headers=headers, json=store).status_code == 201


def test_google_sign_in_requires_a_verified_email(client):
    from fastapi import HTTPException
    from app.routers.auth import _oauth_login_or_register
    email = f"g-{uuid.uuid4().hex[:8]}@example.com"
    with SessionLocal() as db:
        with pytest.raises(HTTPException) as exc:
            _oauth_login_or_register(db, "google", {"sub": uuid.uuid4().hex, "email": email, "email_verified": False})
        assert exc.value.status_code == 400
        assert db.query(models.User).filter(models.User.email == email).count() == 0


def test_signing_in_with_google_wipes_a_password_set_by_an_unverified_pre_registration(client):
    """Someone registers victim@... with their own password before the real
    owner shows up. When the owner later signs in with Google, the attacker's
    password must stop working."""
    from app.routers.auth import _oauth_login_or_register
    data, email = _register(client, password="AttackerChose#1")
    with SessionLocal() as db:
        user = _oauth_login_or_register(db, "google", {"sub": uuid.uuid4().hex, "email": email, "email_verified": True})
        assert user.is_verified is True and user.password_hash is None
    client.cookies.clear()
    assert client.post("/auth/login", data={"username": email, "password": "AttackerChose#1"}).status_code == 401


def test_signing_in_with_google_keeps_the_password_of_a_verified_account(client):
    from app.routers.auth import _oauth_login_or_register
    data, email = _register(client)
    _sql("UPDATE users SET is_verified = true WHERE email = :e", e=email)
    with SessionLocal() as db:
        user = _oauth_login_or_register(db, "google", {"sub": uuid.uuid4().hex, "email": email, "email_verified": True})
        assert user.password_hash is not None
    client.cookies.clear()
    assert client.post("/auth/login", data={"username": email, "password": PWD}).status_code == 200


# ---------------------------------------------------------------------------
# Passwords
# ---------------------------------------------------------------------------
def test_passwords_are_stored_as_bcrypt_and_limits_are_enforced(client):
    data, email = _register(client)
    assert _db_user(email).password_hash.startswith("$2")
    too_long = "a" * 73
    r = client.post("/auth/register", json={"full_name": "Long", "email": f"l-{uuid.uuid4().hex[:6]}@example.com", "password": too_long})
    assert r.status_code == 422
    short = client.post("/auth/register", json={"full_name": "Short", "email": f"s-{uuid.uuid4().hex[:6]}@example.com", "password": "short"})
    assert short.status_code == 422


def test_unknown_email_and_wrong_password_look_the_same(client):
    _, email = _register(client)
    client.cookies.clear()
    wrong = client.post("/auth/login", data={"username": email, "password": "Wrong#Pass123"})
    unknown = client.post("/auth/login", data={"username": f"nobody-{uuid.uuid4().hex[:6]}@example.com", "password": "Wrong#Pass123"})
    assert wrong.status_code == unknown.status_code == 401
    assert wrong.json() == unknown.json()


def test_old_cost_factor_hashes_are_upgraded_on_login(client):
    from passlib.hash import bcrypt
    _, email = _register(client)
    weak = bcrypt.using(rounds=6).hash(PWD)
    _sql("UPDATE users SET password_hash = :h WHERE email = :e", h=weak, e=email)
    client.cookies.clear()
    assert client.post("/auth/login", data={"username": email, "password": PWD}).status_code == 200
    assert _db_user(email).password_hash != weak


# ---------------------------------------------------------------------------
# Rate limiting
# ---------------------------------------------------------------------------
def test_login_is_limited_per_email(client, limiter_on):
    _, email = _register(client)
    client.cookies.clear()
    codes = [client.post("/auth/login", data={"username": email, "password": "Wrong#Pass123"}).status_code for _ in range(10)]
    assert codes[:8] == [401] * 8
    assert codes[8] == 429 and "Retry-After" in client.post("/auth/login", data={"username": email, "password": "x"}).headers


def test_register_forgot_password_contact_and_subscribe_are_limited(client, limiter_on):
    for i in range(10):
        client.post("/auth/register", json={"full_name": "R", "email": f"rl{i}-{uuid.uuid4().hex[:6]}@example.com", "password": PWD})
    assert client.post("/auth/register", json={"full_name": "R", "email": f"rl-x-{uuid.uuid4().hex[:6]}@example.com", "password": PWD}).status_code == 429

    for _ in range(3):
        assert client.post("/auth/forgot-password", json={"email": "same@example.com"}).status_code == 200
    assert client.post("/auth/forgot-password", json={"email": "same@example.com"}).status_code == 429

    for _ in range(5):
        client.post("/contact", json={"name": "A", "email": "a@example.com", "message": "hello there"})
    assert client.post("/contact", json={"name": "A", "email": "a@example.com", "message": "hello there"}).status_code == 429


def test_rate_limiter_cannot_be_switched_off_in_production(monkeypatch):
    monkeypatch.setenv("RATE_LIMIT_DISABLED", "1")
    monkeypatch.setattr(security, "IS_PRODUCTION", True)
    assert security.rate_limiting_enabled() is True


def test_client_ip_ignores_spoofed_forwarded_headers(monkeypatch):
    from starlette.requests import Request

    def make(headers, peer="10.0.0.9"):
        scope = {"type": "http", "headers": [(k.lower().encode(), v.encode()) for k, v in headers.items()],
                 "client": (peer, 1234), "method": "GET", "path": "/", "query_string": b"", "scheme": "http", "server": ("x", 80)}
        return Request(scope)

    monkeypatch.setattr(security, "IS_PRODUCTION", False)
    assert security.client_ip(make({"X-Forwarded-For": "6.6.6.6"})) == "10.0.0.9"  # not trusted in development
    monkeypatch.setattr(security, "IS_PRODUCTION", True)
    # A visitor can add entries to the left; the proxy's entry is on the right.
    assert security.client_ip(make({"X-Forwarded-For": "6.6.6.6, 203.0.113.7"})) == "203.0.113.7"
    assert security.client_ip(make({"CF-Connecting-IP": "198.51.100.4", "X-Forwarded-For": "6.6.6.6"})) == "198.51.100.4"
    assert security.client_ip(make({"CF-Connecting-IP": "not-an-ip"})) == "10.0.0.9"


# ---------------------------------------------------------------------------
# Headers, CORS, docs, admin pages
# ---------------------------------------------------------------------------
def test_html_pages_carry_a_csp_and_other_security_headers(client):
    r = TestClient(app).get("/")
    assert r.status_code == 200
    csp = r.headers.get("content-security-policy-report-only") or r.headers.get("content-security-policy")
    assert csp and "frame-ancestors 'none'" in csp and "object-src 'none'" in csp
    assert r.headers["x-content-type-options"] == "nosniff"
    assert r.headers["x-frame-options"] == "DENY"


def test_cors_does_not_open_the_api_to_other_sites(client):
    evil = client.get("/categories", headers={"Origin": "https://evil.example"})
    assert "access-control-allow-origin" not in evil.headers
    pre = client.options("/auth/login", headers={"Origin": "https://evil.example", "Access-Control-Request-Method": "POST"})
    assert "access-control-allow-origin" not in pre.headers


def test_wildcard_cors_setting_is_ignored(monkeypatch):
    from app import main
    monkeypatch.setenv("ALLOWED_ORIGINS", "*")
    assert "*" not in main._resolve_cors_origins()


def test_api_docs_are_off_in_production():
    code = (
        "from app.main import app; "
        "print(app.docs_url, app.redoc_url, app.openapi_url)"
    )
    env = {**os.environ, "RENDER": "true", "SITE_URL": "https://example.com", "CSP_MODE": "off"}
    out = subprocess.run([sys.executable, "-c", code], cwd=BACKEND_DIR, env=env, capture_output=True, text=True, timeout=120)
    assert out.returncode == 0, out.stderr[-2000:]
    assert out.stdout.strip().splitlines()[-1] == "None None None"


def test_api_docs_still_available_locally(client):
    assert TestClient(app).get("/docs").status_code == 200


def test_admin_pages_need_an_admin(client):
    anon = TestClient(app)  # page routes live at the site root, not under /api
    r = anon.get("/admin/dashboard.html", follow_redirects=False)
    assert r.status_code == 302 and r.headers["location"].startswith("/login?next=")

    data, email = _register(client)
    pages = TestClient(app)
    pages.cookies.update(client.cookies)
    assert pages.get("/admin/dashboard.html").status_code == 404  # signed in, but a buyer

    _make_role(client, email, "admin")
    pages.cookies.update(client.cookies)
    assert pages.get("/admin/dashboard.html").status_code == 200
    assert pages.get("/admin/stats.html").status_code == 200


def test_admin_api_rejects_non_admins(client):
    data, _ = _register(client)
    client.cookies.clear()
    assert client.get("/admin/users", headers=_bearer(data["access_token"])).status_code == 403
    assert client.get("/admin/users").status_code == 401


# ---------------------------------------------------------------------------
# Permissions and input validation
# ---------------------------------------------------------------------------
def _seller_with_product(client):
    data, email = _register(client, name="Seller")
    store = client.post("/stores", headers=_bearer(data["access_token"]),
                        json={"store_name": f"Sec Store {uuid.uuid4().hex[:4]}", "region": "Bono", "city": "Sunyani"}).json()
    _sql("UPDATE stores SET status = 'approved' WHERE id = :i", i=store["id"])
    token = _make_role(client, email, "seller")
    admin_data, admin_email = _register(client, name="Admin")
    admin_token = _make_role(client, admin_email, "admin")
    cat = client.post("/categories", headers=_bearer(admin_token), json={"name": f"Cat {uuid.uuid4().hex[:5]}"}).json()
    return token, admin_token, cat["id"], store


def test_product_input_limits(client):
    token, _, cat_id, _ = _seller_with_product(client)
    h = _bearer(token)
    base = {"name": "Good Product", "category_id": cat_id, "price": 10, "stock_quantity": 3}
    assert client.post("/products", headers=h, json=base).status_code == 201
    assert client.post("/products", headers=h, json={**base, "price": -5}).status_code == 422
    assert client.post("/products", headers=h, json={**base, "price": 0}).status_code == 422
    assert client.post("/products", headers=h, json={**base, "stock_quantity": -1}).status_code == 422
    assert client.post("/products", headers=h, json={**base, "name": "x" * 201}).status_code == 422
    assert client.post("/products", headers=h, json={**base, "specifications": ["s"] * 51}).status_code == 422


def test_product_color_hex_cannot_carry_markup(client):
    token, _, cat_id, _ = _seller_with_product(client)
    r = client.post("/products", headers=_bearer(token), json={
        "name": "Colour Test", "category_id": cat_id, "price": 10, "stock_quantity": 3,
        "colors": [{"name": "Red", "hex": "red;background:url(javascript:alert(1))"}, {"name": "Blue", "hex": "#0000ff"}]})
    assert r.status_code == 201, r.text
    colors = {c["name"]: c["hex"] for c in r.json()["colors"]}
    assert colors["Red"] == "" and colors["Blue"] == "#0000FF"


def test_product_description_scripts_are_stripped(client):
    token, _, cat_id, _ = _seller_with_product(client)
    r = client.post("/products", headers=_bearer(token), json={
        "name": "Desc Test", "category_id": cat_id, "price": 10, "stock_quantity": 3,
        "description": "<b>ok</b><script>alert(1)</script><img src=x onerror=alert(1)>"})
    assert r.status_code == 201
    desc = r.json()["description"]
    assert "<script" not in desc and "onerror" not in desc and "<img" not in desc and "<b>ok</b>" in desc


@pytest.mark.parametrize("bad", ["javascript:alert(1)", "data:text/html;base64,AAAA", "http://example.com/a.jpg",
                                  "//example.com/a.jpg", 'https://example.com/a.jpg" onerror="alert(1)', "https://exa mple.com/a.jpg"])
def test_image_urls_must_be_plain_https(client, bad):
    token, admin_token, cat_id, store = _seller_with_product(client)
    created = client.post("/products", headers=_bearer(token), json={"name": "Img Test", "category_id": cat_id, "price": 10, "stock_quantity": 1}).json()
    r = client.post(f"/products/{created['id']}/images", headers=_bearer(token), params={"image_url": bad})
    assert r.status_code == 400, (bad, r.status_code, r.text)
    portfolio = client.put("/stores/me", headers=_bearer(token), json={"logo_url": bad})
    assert portfolio.status_code == 422


def test_good_https_image_url_is_accepted(client):
    token, _, cat_id, _ = _seller_with_product(client)
    created = client.post("/products", headers=_bearer(token), json={"name": "Img OK", "category_id": cat_id, "price": 10, "stock_quantity": 1}).json()
    r = client.post(f"/products/{created['id']}/images", headers=_bearer(token),
                    params={"image_url": "https://res.cloudinary.com/demo/image/upload/sample.jpg"})
    assert r.status_code in (200, 201), r.text


def test_seller_cannot_mark_orders_paid_or_refunded(client):
    from app.routers.orders import SELLER_SETTABLE_STATUSES
    assert models.OrderStatus.paid not in SELLER_SETTABLE_STATUSES
    assert models.OrderStatus.refunded not in SELLER_SETTABLE_STATUSES
    assert models.OrderStatus.pending not in SELLER_SETTABLE_STATUSES
    assert {models.OrderStatus.processing, models.OrderStatus.shipped,
            models.OrderStatus.delivered, models.OrderStatus.cancelled} == SELLER_SETTABLE_STATUSES


def test_seller_order_status_endpoint_blocks_paid(client):
    token, admin_token, cat_id, store = _seller_with_product(client)
    h = _bearer(token)
    product = client.post("/products", headers=h, json={"name": "Order Test", "category_id": cat_id, "price": 10, "stock_quantity": 5}).json()
    _sql("UPDATE products SET status = 'approved' WHERE id = :i", i=product["id"])
    buyer, buyer_email = _register(client, name="Buyer")
    bh = _bearer(buyer["access_token"])
    addr = client.post("/auth/addresses", headers=bh, json={"recipient_name": "B", "phone": "0240000000", "region": "Bono", "city": "Sunyani"}).json()
    assert client.post("/cart/items", headers=bh, json={"product_id": product["id"], "quantity": 1}).status_code in (200, 201)
    orders = client.post("/orders/checkout", headers=bh, json={"address_id": addr["id"], "payment_method": "cash_on_delivery"})
    assert orders.status_code == 201, orders.text
    order_id = orders.json()[0]["id"]
    assert client.put(f"/orders/{order_id}/status", headers=h, json={"status": "paid"}).status_code == 403
    assert client.put(f"/orders/{order_id}/status", headers=h, json={"status": "refunded"}).status_code == 403
    assert client.put(f"/orders/{order_id}/status", headers=h, json={"status": "processing"}).status_code == 200
    # Saving a note without changing the status still works.
    assert client.put(f"/orders/{order_id}/status", headers=h, json={"status": "processing", "seller_note": "packed"}).status_code == 200


def test_search_wildcards_are_literal(client):
    token, _, cat_id, _ = _seller_with_product(client)
    p = client.post("/products", headers=_bearer(token), json={"name": f"Plain Name {uuid.uuid4().hex[:6]}", "category_id": cat_id, "price": 10, "stock_quantity": 1}).json()
    _sql("UPDATE products SET status = 'approved' WHERE id = :i", i=p["id"])
    results = client.get("/products", params={"q": "%"}).json()
    names = [r["name"] for r in (results if isinstance(results, list) else results.get("items", []))]
    assert p["name"] not in names


def test_request_body_size_cap(client):
    r = client.post("/contact", content=b"x", headers={"Content-Length": str(50 * 1024 * 1024), "Content-Type": "application/json"})
    assert r.status_code == 413


# ---------------------------------------------------------------------------
# File uploads
# ---------------------------------------------------------------------------
def test_resume_must_match_its_extension():
    from app.routers.services import _looks_like
    import zipfile
    assert _looks_like(".pdf", b"%PDF-1.7 rest")
    assert not _looks_like(".pdf", b"<html><script>alert(1)</script>")
    assert not _looks_like(".doc", b"MZ\x90\x00 an exe")
    assert _looks_like(".doc", b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1 rest")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("[Content_Types].xml", "<x/>")
        z.writestr("word/document.xml", "<x/>")
    assert _looks_like(".docx", buf.getvalue())
    plain_zip = io.BytesIO()
    with zipfile.ZipFile(plain_zip, "w") as z:
        z.writestr("evil.exe", "MZ")
    assert not _looks_like(".docx", plain_zip.getvalue())
    assert not _looks_like(".docx", b"not a zip")
    assert not _looks_like(".txt", b"%PDF-")


def test_resume_upload_endpoint_rejects_fake_pdf(client):
    data, email = _register(client)
    r = client.post("/services/register", headers=_bearer(data["access_token"]),
                    data={"job_title": "Electrician", "professional_name": "Fake Pro", "work_experience": "10 years",
                          "terms_accepted": "true", "payments_on_platform_accepted": "true"},
                    files={"resume": ("cv.pdf", b"<script>alert(1)</script>", "application/pdf")})
    assert r.status_code == 400 and "doesn't look like" in r.json()["detail"]


def _xlsx(rows):
    import openpyxl
    wb = openpyxl.Workbook()
    ws = wb.active
    for row in rows:
        ws.append(row)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


HEADERS = ["name", "category_id", "price", "stock_quantity", "description", "image_url_1"]


def test_import_cleans_descriptions_and_refuses_bad_image_links(client):
    token, _, cat_id, _ = _seller_with_product(client)
    content = _xlsx([
        HEADERS,
        ["Imported Good", cat_id, 12, 4, "<b>nice</b><script>alert(1)</script>", "https://example.com/a.jpg"],
        ["Imported Bad Image", cat_id, 12, 4, "fine", "javascript:alert(1)"],
        ["Imported Free", cat_id, 0, 4, "fine", ""],
    ])
    r = client.post("/products/import", headers=_bearer(token),
                    files={"file": ("p.xlsx", content, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")})
    assert r.status_code == 200, r.text
    report = r.json()
    assert report["imported"] == 1 and report["skipped"] == 2
    with SessionLocal() as db:
        product = db.query(models.Product).filter(models.Product.name == "Imported Good").first()
        assert "<script" not in (product.description or "") and "<b>nice</b>" in product.description


def test_import_refuses_oversized_and_overlong_files(client):
    token, _, cat_id, _ = _seller_with_product(client)
    many = _xlsx([HEADERS] + [[f"P{i}", cat_id, 5, 1, "", ""] for i in range(520)])
    r = client.post("/products/import", headers=_bearer(token), files={"file": ("p.xlsx", many, "application/octet-stream")})
    assert r.status_code == 422 and "at most" in r.json()["detail"]
    huge = b"PK\x03\x04" + b"0" * (5 * 1024 * 1024 + 10)
    r = client.post("/products/import", headers=_bearer(token), files={"file": ("p.xlsx", huge, "application/octet-stream")})
    assert r.status_code == 413
    r = client.post("/products/import", headers=_bearer(token), files={"file": ("p.xlsx", b"not a zip at all", "application/octet-stream")})
    assert r.status_code == 422


# ---------------------------------------------------------------------------
# Logs and secrets
# ---------------------------------------------------------------------------
def test_redaction_masks_tokens_and_jwts():
    line = 'GET /reset-password?token=abc123SECRET&x=1 HTTP/1.1'
    assert "abc123SECRET" not in security.redact(line) and "x=1" in security.redact(line)
    jwt_like = "Authorization: eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTYifQ.c2lnbmF0dXJlc2lnbmF0dXJl"
    assert "eyJ" not in security.redact(jwt_like)
    assert security.redact("#token=zzzzzzzzzz") == "#token=[redacted]"


def test_access_log_filter_is_installed_in_production(monkeypatch):
    import logging

    def strip_filters():
        targets = [logging.getLogger(n) for n in ("uvicorn.access", "uvicorn.error", "eravenda", "")]
        targets += list(logging.getLogger().handlers)
        for target in targets:
            for f in [f for f in target.filters if isinstance(f, security.RedactSecretsFilter)]:
                target.removeFilter(f)

    monkeypatch.setattr(security, "IS_PRODUCTION", True)
    strip_filters()
    try:
        security.install_log_redaction()
        assert any(isinstance(f, security.RedactSecretsFilter) for f in logging.getLogger("uvicorn.access").filters)
    finally:
        strip_filters()  # leave other tests' log handlers untouched


def test_access_log_filter_redacts_tokens():
    import logging
    record = logging.LogRecord("uvicorn.access", logging.INFO, __file__, 1, '%s - "%s %s HTTP/%s" %d',
                               ("1.2.3.4", "GET", "/reset-password?token=TOPSECRETVALUE", "1.1", 200), None)
    assert security.RedactSecretsFilter().filter(record) is True
    assert "TOPSECRETVALUE" not in record.getMessage()


def test_email_bodies_are_not_logged_in_production(monkeypatch, caplog):
    from app import email_utils
    monkeypatch.setattr(email_utils, "RESEND_API_KEY", None)
    monkeypatch.setattr(security, "IS_PRODUCTION", True)
    with caplog.at_level("INFO", logger="eravenda.email"):
        email_utils.send_email(to="a@example.com", subject="Reset", body="open https://x/reset#token=SECRETRESETLINK")
    assert "SECRETRESETLINK" not in caplog.text
    monkeypatch.setattr(security, "IS_PRODUCTION", False)
    with caplog.at_level("INFO", logger="eravenda.email"):
        email_utils.send_email(to="a@example.com", subject="Reset", body="open https://x/reset#token=SECRETRESETLINK")
    assert "SECRETRESETLINK" in caplog.text  # local development still shows it


def test_weak_algorithm_setting_is_refused():
    env = {**os.environ, "ALGORITHM": "none"}
    out = subprocess.run([sys.executable, "-c", "import app.auth"], cwd=BACKEND_DIR, env=env, capture_output=True, text=True, timeout=120)
    assert out.returncode != 0 and "ALGORITHM" in out.stderr


# ---------------------------------------------------------------------------
# Row level security
# ---------------------------------------------------------------------------
def test_row_level_security_is_on_for_every_table_and_the_app_still_works(client):
    with engine.connect() as conn:
        rows = conn.execute(text(
            "SELECT c.relname FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
            "WHERE n.nspname = 'public' AND c.relkind = 'r' AND NOT c.relrowsecurity"
        )).fetchall()
    assert rows == [], f"RLS missing on: {[r[0] for r in rows]}"
    _register(client)  # the owner role keeps full access


def test_a_second_database_role_sees_nothing(client):
    _register(client)
    role = f"reader_{uuid.uuid4().hex[:6]}"
    with engine.begin() as conn:
        try:
            conn.execute(text(f"CREATE ROLE {role} LOGIN PASSWORD 'x'"))
            conn.execute(text(f"GRANT SELECT ON users TO {role}"))
        except Exception:
            pytest.skip("test database user cannot create roles")
    try:
        with engine.begin() as conn:
            conn.execute(text(f"SET LOCAL ROLE {role}"))
            assert conn.execute(text("SELECT count(*) FROM users")).scalar() == 0
    finally:
        with engine.begin() as conn:
            conn.execute(text(f"REVOKE ALL ON users FROM {role}"))
            conn.execute(text(f"DROP ROLE {role}"))


def test_malformed_ids_return_404_not_500(client):
    root = TestClient(app)
    assert root.get("/product/not-a-uuid").status_code == 404
    assert root.get("/store/%20" + "x" * 5000).status_code in (404, 414)
    assert client.get("/products/not-a-uuid").status_code in (404, 422)
    assert client.get("/orders/not-a-uuid", headers=_bearer(_register(client)[0]["access_token"])).status_code in (404, 422)

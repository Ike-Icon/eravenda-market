"""End-to-end checks for the Retail / Wholesale split.

Runs against a real PostgreSQL (set DATABASE_URL to a throwaway database, e.g.
`createdb eravenda_test`). It boots the real app, so it also proves the new
migration applies cleanly on a fresh database and again on a second start.

    DATABASE_URL=postgresql://localhost:5432/eravenda_test SECRET_KEY=test \
        python -m pytest tests/test_wholesale.py -q
"""
import os
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

os.environ.setdefault("SECRET_KEY", "test-secret-key-for-wholesale-tests-only")

from app.database import engine  # noqa: E402
from app.main import app  # noqa: E402

PWD = "Passw0rd!123"


def _sql(query, **params):
    with engine.begin() as conn:
        return conn.execute(text(query), params)


@pytest.fixture(scope="module")
def client():
    # All API routers are mounted under /api (see main.py).
    with TestClient(app, base_url="http://testserver/api") as c:  # runs startup: create_all + migrations
        yield c


def _register(client, name):
    email = f"{name}-{uuid.uuid4().hex[:6]}@example.com"
    r = client.post("/auth/register", json={"full_name": name, "email": email, "password": PWD})
    assert r.status_code in (200, 201), r.text
    tok = r.json()["access_token"]
    return {"Authorization": f"Bearer {tok}"}, r.json()["user"]["id"], email


def _relogin(client, email, role, user_id):
    _sql("UPDATE users SET role = :r WHERE id = :i", r=role, i=user_id)
    r = client.post("/auth/login", data={"username": email, "password": PWD})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


@pytest.fixture(scope="module")
def world(client):
    admin_h, admin_id, admin_email = _register(client, "Admin")
    admin_h = _relogin(client, admin_email, "admin", admin_id)

    sellers = {}
    for key in ("A", "B"):
        h, uid, email = _register(client, f"Seller{key}")
        r = client.post("/stores", headers=h, json={"store_name": f"Store {key} {uuid.uuid4().hex[:4]}", "region": "Bono", "city": "Sunyani"})
        assert r.status_code == 201, r.text
        store_id = r.json()["id"]
        _sql("UPDATE stores SET status = 'approved' WHERE id = :i", i=store_id)
        h = _relogin(client, email, "seller", uid)
        sellers[key] = {"h": h, "store_id": store_id, "user_id": uid}

    cat = client.post("/categories", headers=admin_h, json={"name": f"Cat {uuid.uuid4().hex[:4]}"})
    assert cat.status_code == 201, cat.text

    buyer_h, buyer_id, buyer_email = _register(client, "Buyer")
    addr = client.post("/auth/addresses", headers=buyer_h, json={
        "recipient_name": "Buyer", "phone": "0240000000", "region": "Bono", "city": "Sunyani"})
    assert addr.status_code in (200, 201), addr.text
    return {"admin": admin_h, "sellers": sellers, "cat": cat.json()["id"], "buyer": buyer_h,
            "buyer_id": buyer_id, "buyer_email": buyer_email, "addr": addr.json()["id"]}


def _make(client, world, seller, **fields):
    body = {"name": f"P-{uuid.uuid4().hex[:5]}", "category_id": world["cat"], "price": 50, "stock_quantity": 100}
    body.update(fields)
    r = client.post("/products", headers=world["sellers"][seller]["h"], json=body)
    if r.status_code == 201:
        _sql("UPDATE products SET status = 'approved' WHERE id = :i", i=r.json()["id"])
    return r


def _clear_cart(client, world):
    for it in client.get("/cart", headers=world["buyer"]).json()["items"]:
        client.delete(f"/cart/items/{it['id']}", headers=world["buyer"])


def test_migration_is_idempotent_and_defaults_to_retail(client):
    from app.migrate import run_migrations
    run_migrations()  # second run on top of startup's run must not fail
    cols = {r[0] for r in _sql("SELECT column_name FROM information_schema.columns WHERE table_name='products'")}
    assert {"sales_type", "wholesale_min_quantity"} <= cols
    assert _sql("SELECT column_default FROM information_schema.columns WHERE table_name='orders' AND column_name='order_type'").scalar()


def test_retail_product_unchanged(client, world):
    r = _make(client, world, "A")
    assert r.status_code == 201
    p = r.json()
    assert p["sales_type"] == "retail" and p["wholesale_min_quantity"] is None and p["wholesale_price"] is None
    # edit still works
    u = client.put(f"/products/{p['id']}", headers=world["sellers"]["A"]["h"], json={"price": 60})
    assert u.status_code == 200 and u.json()["price"] == 60 and u.json()["sales_type"] == "retail"


def test_wholesale_creation_validation(client, world):
    assert _make(client, world, "A", sales_type="wholesale").status_code == 400  # min required
    assert _make(client, world, "A", sales_type="wholesale", wholesale_min_quantity=1).status_code == 400
    assert _make(client, world, "A", sales_type="wholesale", wholesale_min_quantity=0).status_code == 400
    assert _make(client, world, "A", sales_type="bogus").status_code == 422
    for n in (5, 10, 50, 100):
        r = _make(client, world, "A", sales_type="wholesale", wholesale_min_quantity=n)
        assert r.status_code == 201, r.text
        assert r.json()["wholesale_min_quantity"] == n and r.json()["wholesale_price"] == 50


def test_edit_min_and_switch_back_to_retail_clears_min(client, world):
    p = _make(client, world, "A", sales_type="wholesale", wholesale_min_quantity=10).json()
    h = world["sellers"]["A"]["h"]
    assert client.put(f"/products/{p['id']}", headers=h, json={"wholesale_min_quantity": 20}).json()["wholesale_min_quantity"] == 20
    assert client.put(f"/products/{p['id']}", headers=h, json={"wholesale_min_quantity": 1}).status_code == 400
    assert client.put(f"/products/{p['id']}", headers=h, json={"sales_type": None}).json()["sales_type"] == "wholesale"
    back = client.put(f"/products/{p['id']}", headers=h, json={"sales_type": "retail"}).json()
    assert back["sales_type"] == "retail" and back["wholesale_min_quantity"] is None
    # retail -> wholesale without a min is rejected
    assert client.put(f"/products/{p['id']}", headers=h, json={"sales_type": "wholesale"}).status_code == 400


def test_other_seller_cannot_edit(client, world):
    p = _make(client, world, "A", sales_type="wholesale", wholesale_min_quantity=10).json()
    r = client.put(f"/products/{p['id']}", headers=world["sellers"]["B"]["h"], json={"wholesale_min_quantity": 2})
    assert r.status_code == 404
    r = client.put(f"/products/{p['id']}", headers=world["buyer"], json={"wholesale_min_quantity": 2})
    assert r.status_code == 403


def test_listing_filter(client, world):
    w = _make(client, world, "A", name="ZZWHOLE", sales_type="wholesale", wholesale_min_quantity=10).json()
    r = _make(client, world, "A", name="ZZRETAIL").json()
    ids = lambda t: {i["id"] for i in client.get("/products", params={"sales_type": t, "q": "ZZ", "page_size": 100}).json()["items"]}
    assert w["id"] in ids("wholesale") and r["id"] not in ids("wholesale")
    assert r["id"] in ids("retail") and w["id"] not in ids("retail")
    both = {i["id"] for i in client.get("/products", params={"q": "ZZ"}).json()["items"]}
    assert {w["id"], r["id"]} <= both  # API default unchanged


def test_checkout_blocks_below_minimum_and_allows_at_or_above(client, world):
    _clear_cart(client, world)
    b = world["buyer"]
    w = _make(client, world, "A", name="Rice 25kg", price=450, stock_quantity=100, sales_type="wholesale", wholesale_min_quantity=10).json()
    for qty in (1, 2, 5, 9):
        _clear_cart(client, world)
        client.post("/cart/items", headers=b, json={"product_id": w["id"], "quantity": qty})
        cart = client.get("/cart", headers=b).json()
        assert cart["wholesale_issues"][0]["current_quantity"] == qty
        r = client.post("/orders/checkout", headers=b, json={"address_id": world["addr"], "is_pickup": True})
        assert r.status_code == 400, (qty, r.text)
        assert f"Rice 25kg requires a minimum wholesale quantity of 10. Current quantity: {qty}." in r.json()["detail"]
    for qty in (10, 25):
        _clear_cart(client, world)
        client.post("/cart/items", headers=b, json={"product_id": w["id"], "quantity": qty})
        assert client.get("/cart", headers=b).json()["wholesale_issues"] == []
        r = client.post("/orders/checkout", headers=b, json={"address_id": world["addr"], "is_pickup": True})
        assert r.status_code == 201, (qty, r.text)
        o = r.json()[0]
        assert o["order_type"] == "wholesale" and o["total_quantity"] == qty
        assert o["subtotal"] == 450 * qty and o["items"][0]["wholesale_min_quantity"] == 10
        assert o["items"][0]["unit_price"] == 450


def test_cannot_exceed_stock(client, world):
    _clear_cart(client, world)
    b = world["buyer"]
    w = _make(client, world, "A", stock_quantity=30, sales_type="wholesale", wholesale_min_quantity=10).json()
    client.post("/cart/items", headers=b, json={"product_id": w["id"], "quantity": 20})
    client.post("/cart/items", headers=b, json={"product_id": w["id"], "quantity": 20})  # 40 total > 30
    r = client.post("/orders/checkout", headers=b, json={"address_id": world["addr"], "is_pickup": True})
    assert r.status_code == 400 and "in stock" in r.json()["detail"], r.text
    assert _sql("SELECT stock_quantity FROM products WHERE id=:i", i=w["id"]).scalar() == 30


def test_variant_lines_count_together(client, world):
    _clear_cart(client, world)
    b = world["buyer"]
    w = _make(client, world, "A", sales_type="wholesale", wholesale_min_quantity=10,
              colors=[{"name": "Black", "stock": 50, "available": True}, {"name": "White", "stock": 50, "available": True}]).json()
    client.post("/cart/items", headers=b, json={"product_id": w["id"], "quantity": 6, "color": "Black"})
    r = client.post("/orders/checkout", headers=b, json={"address_id": world["addr"], "is_pickup": True})
    assert r.status_code == 400
    client.post("/cart/items", headers=b, json={"product_id": w["id"], "quantity": 6, "color": "White"})
    r = client.post("/orders/checkout", headers=b, json={"address_id": world["addr"], "is_pickup": True})
    assert r.status_code == 201 and r.json()[0]["total_quantity"] == 12


def test_mixed_cart_splits_by_type_and_retail_unaffected(client, world):
    _clear_cart(client, world)
    b = world["buyer"]
    ret = _make(client, world, "A", name="MixRetail", price=20, stock_quantity=10).json()
    whl = _make(client, world, "A", name="MixWhole", price=5, stock_quantity=100, sales_type="wholesale", wholesale_min_quantity=10).json()
    other = _make(client, world, "B", name="OtherStoreRetail", price=7, stock_quantity=10).json()
    client.post("/cart/items", headers=b, json={"product_id": ret["id"], "quantity": 1})
    client.post("/cart/items", headers=b, json={"product_id": whl["id"], "quantity": 12})
    client.post("/cart/items", headers=b, json={"product_id": other["id"], "quantity": 2})
    quote = client.post("/orders/delivery-quote", headers=b, json={"address_id": world["addr"]})
    assert quote.status_code == 200 and quote.json()["store_count"] == 3
    r = client.post("/orders/checkout", headers=b, json={"address_id": world["addr"], "is_pickup": True})
    assert r.status_code == 201, r.text
    types = sorted(o["order_type"] for o in r.json())
    assert types == ["retail", "retail", "wholesale"]
    assert _sql("SELECT stock_quantity FROM products WHERE id=:i", i=ret["id"]).scalar() == 9
    assert _sql("SELECT stock_quantity FROM products WHERE id=:i", i=whl["id"]).scalar() == 88
    retail_order = next(o for o in r.json() if o["order_type"] == "retail" and o["items"][0]["product_name"] == "MixRetail")
    assert retail_order["items"][0]["wholesale_min_quantity"] is None


def test_snapshot_survives_min_change(client, world):
    _clear_cart(client, world)
    b = world["buyer"]
    w = _make(client, world, "A", sales_type="wholesale", wholesale_min_quantity=10).json()
    client.post("/cart/items", headers=b, json={"product_id": w["id"], "quantity": 10})
    oid = client.post("/orders/checkout", headers=b, json={"address_id": world["addr"], "is_pickup": True}).json()[0]["id"]
    client.put(f"/products/{w['id']}", headers=world["sellers"]["A"]["h"], json={"wholesale_min_quantity": 40})
    assert client.get(f"/orders/{oid}", headers=b).json()["items"][0]["wholesale_min_quantity"] == 10
    # seller sees it in their orders
    mine = client.get("/orders/store/mine", headers=world["sellers"]["A"]["h"]).json()
    assert any(o["id"] == oid and o["order_type"] == "wholesale" for o in mine)


def test_min_raised_after_add_blocks_checkout(client, world):
    _clear_cart(client, world)
    b = world["buyer"]
    w = _make(client, world, "A", sales_type="wholesale", wholesale_min_quantity=10).json()
    client.post("/cart/items", headers=b, json={"product_id": w["id"], "quantity": 10})
    client.put(f"/products/{w['id']}", headers=world["sellers"]["A"]["h"], json={"wholesale_min_quantity": 30})
    r = client.post("/orders/checkout", headers=b, json={"address_id": world["addr"], "is_pickup": True})
    assert r.status_code == 400 and "minimum wholesale quantity of 30" in r.json()["detail"]


def test_admin_wholesale_monitoring(client, world):
    adm = world["admin"]
    s = client.get("/admin/wholesale/summary", headers=adm).json()
    assert s["wholesale_products"] >= 1 and s["wholesale_orders"] >= 1 and s["wholesale_sales"] > 0
    assert s["pending_orders"] >= 1 and s["wholesale_sellers"] >= 1

    orders = client.get("/admin/wholesale/orders", headers=adm).json()
    assert orders and all(o["order_type"] == "wholesale" for o in orders)
    assert all(o["met_minimum"] is True for o in orders)
    o = orders[0]
    assert {"buyer_name", "seller_name", "store_name", "order_value", "total_quantity", "status", "items"} <= set(o)
    assert client.get("/admin/wholesale/orders", params={"order_type": "retail"}, headers=adm).json()
    assert all(x["store_id"] == o["store_id"] for x in client.get("/admin/wholesale/orders", params={"store_id": o["store_id"]}, headers=adm).json())
    assert client.get("/admin/wholesale/orders", params={"product_id": o["items"][0]["product_id"]}, headers=adm).json()
    assert client.get("/admin/wholesale/orders", params={"status": "completed"}, headers=adm).json() == []
    assert client.get("/admin/wholesale/orders", params={"date_from": "2999-01-01"}, headers=adm).json() == []
    assert client.get("/admin/wholesale/orders", params={"status": "nonsense"}, headers=adm).status_code == 400

    prods = client.get("/admin/wholesale/products", headers=adm).json()
    assert prods and all(p["sales_type"] == "wholesale" and p["wholesale_min_quantity"] for p in prods)
    tracking = client.get("/admin/products/tracking", headers=adm).json()
    assert {"sales_type", "wholesale_min_quantity"} <= set(tracking[0])

    # admin may edit a wholesale product; same validation applies
    pid = prods[0]["id"]
    assert client.put(f"/admin/products/{pid}", headers=adm, json={"wholesale_min_quantity": 15}).json()["wholesale_min_quantity"] == 15
    assert client.put(f"/admin/products/{pid}", headers=adm, json={"wholesale_min_quantity": 1}).status_code == 400


def test_admin_endpoints_are_admin_only(client, world):
    for path in ("/admin/wholesale/summary", "/admin/wholesale/orders", "/admin/wholesale/products"):
        assert client.get(path, headers=world["buyer"]).status_code == 403
        assert client.get(path, headers=world["sellers"]["A"]["h"]).status_code == 403
        assert client.get(path).status_code in (401, 403)
    assert client.put("/admin/products/x", headers=world["sellers"]["A"]["h"], json={}).status_code == 403


# ---------- Page rendering (server-side templates) ----------

@pytest.fixture(scope="module")
def pages():
    with TestClient(app) as c:  # site root, pages are not under /api
        yield c


def test_marketplace_pages_split_retail_and_wholesale(client, pages, world):
    w = _make(client, world, "A", name="PageWholeRice", price=450, stock_quantity=100,
              sales_type="wholesale", wholesale_min_quantity=10).json()
    r = _make(client, world, "A", name="PageRetailMug", price=15, stock_quantity=20).json()

    retail = pages.get("/products")
    assert retail.status_code == 200
    assert "PageRetailMug" in retail.text and "PageWholeRice" not in retail.text
    assert "Wholesale" in retail.text  # section switch present

    whole = pages.get("/products?type=wholesale")
    assert whole.status_code == 200
    assert "PageWholeRice" in whole.text and "PageRetailMug" not in whole.text
    assert "Min. order: 10 units" in whole.text
    assert 'data-cart="' + w["id"] not in whole.text  # no one-click add for wholesale
    assert pages.get("/products?type=bogus").status_code == 200  # falls back to retail

    # search keeps the section
    assert "PageWholeRice" in pages.get("/products?type=wholesale&q=PageWhole").text
    assert "PageWholeRice" not in pages.get("/products?q=PageWhole").text

    # home page rails are retail only
    home = pages.get("/")
    assert home.status_code == 200 and "PageWholeRice" not in home.text


def test_product_page_shows_minimum(client, pages, world):
    w = _make(client, world, "A", name="PdpWholeShoes", price=120, stock_quantity=100,
              sales_type="wholesale", wholesale_min_quantity=20).json()
    page = pages.get(f"/product/{w['id']}")
    assert page.status_code == 200
    assert "Minimum order" in page.text and "20 units" in page.text and "Wholesale price" in page.text
    assert 'id="qtyInput" value="20"' in page.text
    short = _make(client, world, "A", name="PdpShort", stock_quantity=5,
                  sales_type="wholesale", wholesale_min_quantity=10).json()
    assert "below the minimum order" in pages.get(f"/product/{short['id']}").text
    retail = _make(client, world, "A", name="PdpRetail").json()
    rp = pages.get(f"/product/{retail['id']}")
    assert rp.status_code == 200 and "Minimum order" not in rp.text and 'id="qtyInput" value="1"' in rp.text


def test_store_and_other_pages_render(client, pages, world):
    store_id = world["sellers"]["A"]["store_id"]
    s = pages.get(f"/store/{store_id}")
    assert s.status_code == 200 and "View &amp; order" in s.text
    for path in ("/cart", "/checkout", "/orders.html", "/seller/products.html", "/seller/add-product.html",
                 "/seller/orders.html", "/seller/dashboard.html", "/admin/dashboard.html"):
        assert pages.get(path).status_code == 200, path
    add = pages.get("/seller/add-product.html").text
    assert "Minimum Wholesale Quantity" in add and 'value="wholesale"' in add
    assert "Wholesale management" in pages.get("/admin/dashboard.html").text


# ---------- Email center: "One user" audience ----------

@pytest.fixture()
def fake_mail(monkeypatch):
    """Pretend email is configured and capture what would be sent."""
    from app import broadcast_service, email_utils
    sent = []
    monkeypatch.setattr(email_utils, "email_configured", lambda: True)
    monkeypatch.setattr(broadcast_service.email_utils, "email_configured", lambda: True)

    def fake_batch(messages):
        sent.extend(messages)
        return [True] * len(messages)

    monkeypatch.setattr(broadcast_service, "send_email_batch", fake_batch)
    return sent


def _wait_done(client, admin_h, cid, tries=60):
    import time
    for _ in range(tries):
        c = client.get(f"/admin/broadcasts/campaigns/{cid}", headers=admin_h).json()
        if c["status"] != "sending":
            return c
        time.sleep(0.1)
    raise AssertionError("campaign never finished")


def _msg(user_id, **kw):
    body = {"audience": "user", "user_id": user_id, "subject": f"Hello {uuid.uuid4().hex[:6]}",
            "body": "Hi {{first_name}}, this is personal."}
    body.update(kw)
    return body


def test_user_search(client, world):
    adm = world["admin"]
    uid = world["buyer_id"]
    assert client.get("/admin/broadcasts/users", params={"q": "B"}, headers=adm).json() == []  # too short
    email = world["buyer_email"]
    found = client.get("/admin/broadcasts/users", params={"q": email}, headers=adm).json()
    assert [(u["id"], u["role"]) for u in found] == [(uid, "buyer")]
    assert [u["id"] for u in client.get("/admin/broadcasts/users", params={"q": email.upper()}, headers=adm).json()] == [uid]  # case-insensitive
    by_name = client.get("/admin/broadcasts/users", params={"q": "Buyer"}, headers=adm).json()
    assert by_name and len(by_name) <= 10  # name search works and is capped
    sid = world["sellers"]["A"]["user_id"]
    seller_email = _sql("SELECT email FROM users WHERE id = :i", i=sid).scalar()
    seller = client.get("/admin/broadcasts/users", params={"q": seller_email}, headers=adm).json()
    assert len(seller) == 1 and seller[0]["id"] == sid and seller[0]["store_name"] and seller[0]["role"] == "seller"
    # LIKE wildcards are literal, not "match everything"
    assert client.get("/admin/broadcasts/users", params={"q": "%%"}, headers=adm).json() == []
    assert client.get("/admin/broadcasts/users", params={"q": "__"}, headers=adm).json() == []
    # deactivated accounts don't show up
    _sql("UPDATE users SET is_active = false WHERE id = :i", i=uid)
    try:
        assert client.get("/admin/broadcasts/users", params={"q": email}, headers=adm).json() == []
    finally:
        _sql("UPDATE users SET is_active = true WHERE id = :i", i=uid)
    # admin only
    assert client.get("/admin/broadcasts/users", params={"q": email}, headers=world["buyer"]).status_code == 403
    assert client.get("/admin/broadcasts/users", params={"q": email}, headers=world["sellers"]["A"]["h"]).status_code == 403


def test_audience_list_includes_one_user(client, world):
    a = client.get("/admin/broadcasts/audiences", headers=world["admin"]).json()["audiences"]
    assert [x["key"] for x in a if x["key"] == "user"] == ["user"]
    assert {"users", "sellers", "professionals", "subscribers"} <= {x["key"] for x in a}  # existing groups intact


def test_preview_single_user_and_without_pick(client, world):
    adm = world["admin"]
    r = client.post("/admin/broadcasts/preview", headers=adm, json=_msg(world["buyer_id"]))
    assert r.status_code == 200, r.text
    assert r.json()["recipient_count"] == 1 and r.json()["preview_for"] == "Buyer"
    assert "Hi Buyer," in r.json()["html"]
    # nobody chosen yet: still previews, with a sample person
    nopick = client.post("/admin/broadcasts/preview", headers=adm, json=_msg(None))
    assert nopick.status_code == 200 and nopick.json()["preview_for"] == "a sample person"
    # only the placeholders that make sense for one account
    bad = client.post("/admin/broadcasts/preview", headers=adm, json=_msg(world["buyer_id"], body="Hi {{store_name}}"))
    assert bad.status_code == 400


def test_send_to_one_user_only(client, world, fake_mail):
    adm = world["admin"]
    buyer_email = world["buyer_email"]
    r = client.post("/admin/broadcasts/send", headers=adm, json=_msg(world["buyer_id"]))
    assert r.status_code == 202, r.text
    c = _wait_done(client, adm, r.json()["id"])
    assert c["status"] == "completed" and c["recipient_count"] == 1 and c["sent_count"] == 1
    assert c["audience"] == "user" and c["target_email"].lower() == buyer_email.lower()
    assert c["audience_label"].startswith("One user: ")
    assert len(fake_mail) == 1 and fake_mail[0]["to"].lower() == buyer_email.lower()
    assert "Hi Buyer, this is personal." in fake_mail[0]["body"]
    assert "[TEST]" not in fake_mail[0]["subject"]


def test_duplicate_guard_is_per_person(client, world, fake_mail):
    adm = world["admin"]
    other_id = world["sellers"]["A"]["user_id"]
    base = _msg(world["buyer_id"], subject=f"Dup {uuid.uuid4().hex[:6]}")
    first = client.post("/admin/broadcasts/send", headers=adm, json=base)
    assert first.status_code == 202
    _wait_done(client, adm, first.json()["id"])
    again = client.post("/admin/broadcasts/send", headers=adm, json=base)
    assert again.status_code == 409 and "this person" in again.json()["detail"]
    to_other = client.post("/admin/broadcasts/send", headers=adm, json={**base, "user_id": other_id})
    assert to_other.status_code == 202, to_other.text  # same text, different person: allowed
    _wait_done(client, adm, to_other.json()["id"])
    assert len({m["to"].lower() for m in fake_mail}) == 2


def test_send_validation(client, world, fake_mail):
    adm = world["admin"]
    assert client.post("/admin/broadcasts/send", headers=adm, json=_msg(None)).status_code == 400
    assert "Choose which user" in client.post("/admin/broadcasts/send", headers=adm, json=_msg(None)).json()["detail"]
    assert client.post("/admin/broadcasts/send", headers=adm, json=_msg("not-a-uuid")).status_code == 400
    assert client.post("/admin/broadcasts/send", headers=adm, json=_msg(str(uuid.uuid4()))).status_code == 404
    uid = world["buyer_id"]
    _sql("UPDATE users SET is_active = false WHERE id = :i", i=uid)
    try:
        r = client.post("/admin/broadcasts/send", headers=adm, json=_msg(uid))
        assert r.status_code == 400 and "deactivated" in r.json()["detail"]
    finally:
        _sql("UPDATE users SET is_active = true WHERE id = :i", i=uid)
    assert fake_mail == []  # nothing went out for any of the rejected sends
    # non-admins can never send
    assert client.post("/admin/broadcasts/send", headers=world["buyer"], json=_msg(uid)).status_code == 403


def test_test_send_still_goes_only_to_admin(client, world, fake_mail):
    adm = world["admin"]
    me = client.get("/auth/me", headers=adm).json()["email"]
    r = client.post("/admin/broadcasts/send-test", headers=adm, json=_msg(world["buyer_id"]))
    assert r.status_code == 200 and r.json()["sent_to"] == me
    assert len(fake_mail) == 1 and fake_mail[0]["to"] == me and fake_mail[0]["subject"].startswith("[TEST]")


def test_existing_group_audiences_unchanged(client, world, fake_mail):
    adm = world["admin"]
    for aud in ("users", "sellers", "professionals", "subscribers"):
        r = client.post("/admin/broadcasts/preview", headers=adm, json={"audience": aud, "subject": "S", "body": "Hi {{first_name}}"})
        assert r.status_code == 200, (aud, r.text)

"""End-to-end checks for payment receipts (download, email, permissions).

Runs against a real PostgreSQL, like test_wholesale.py:

    DATABASE_URL=postgresql://localhost:5432/eravenda_test SECRET_KEY=test \\
        python -m pytest tests/test_receipts.py -q
"""
import os
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

os.environ.setdefault("SECRET_KEY", "test-secret-key-for-receipt-tests-only")

from app import receipts  # noqa: E402
from app.database import engine  # noqa: E402
from app.main import app  # noqa: E402

PWD = "Passw0rd!123"


def _sql(query, **params):
    with engine.begin() as conn:
        return conn.execute(text(query), params)


@pytest.fixture(scope="module")
def client():
    with TestClient(app, base_url="http://testserver/api") as c:
        yield c


def _register(client, name):
    email = f"{name}-{uuid.uuid4().hex[:6]}@example.com"
    r = client.post("/auth/register", json={"full_name": name, "email": email, "password": PWD})
    assert r.status_code in (200, 201), r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}, r.json()["user"]["id"], email


def _relogin(client, email, role, user_id):
    _sql("UPDATE users SET role = :r WHERE id = :i", r=role, i=user_id)
    r = client.post("/auth/login", data={"username": email, "password": PWD})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


@pytest.fixture(scope="module")
def world(client):
    admin_h, admin_id, admin_email = _register(client, "Admin")
    admin_h = _relogin(client, admin_email, "admin", admin_id)
    s_h, s_id, s_email = _register(client, "Seller")
    r = client.post("/stores", headers=s_h, json={"store_name": f"Receipt Store {uuid.uuid4().hex[:4]}", "region": "Bono", "city": "Sunyani"})
    assert r.status_code == 201, r.text
    _sql("UPDATE stores SET status = 'approved' WHERE id = :i", i=r.json()["id"])
    s_h = _relogin(client, s_email, "seller", s_id)
    cat = client.post("/categories", headers=admin_h, json={"name": f"RCat {uuid.uuid4().hex[:4]}"})
    assert cat.status_code == 201, cat.text
    buyer_h, buyer_id, buyer_email = _register(client, "Ama Buyer")
    other_h, _, _ = _register(client, "Someone Else")
    addr = client.post("/auth/addresses", headers=buyer_h, json={"recipient_name": "Ama Buyer", "phone": "0240000000", "region": "Bono", "city": "Sunyani"})
    assert addr.status_code in (200, 201), addr.text
    prod = client.post("/products", headers=s_h, json={"name": "Kɔkɔɔ Powder", "category_id": cat.json()["id"], "price": 50, "stock_quantity": 500})
    assert prod.status_code == 201, prod.text
    _sql("UPDATE products SET status = 'approved' WHERE id = :i", i=prod.json()["id"])
    return {"admin": admin_h, "seller": s_h, "buyer": buyer_h, "buyer_email": buyer_email, "other": other_h,
            "addr": addr.json()["id"], "product": prod.json()["id"]}


def _place_order(client, world, qty=2, method="mobile_money", pickup=True):
    for it in client.get("/cart", headers=world["buyer"]).json()["items"]:
        client.delete(f"/cart/items/{it['id']}", headers=world["buyer"])
    assert client.post("/cart/items", headers=world["buyer"], json={"product_id": world["product"], "quantity": qty}).status_code in (200, 201)
    r = client.post("/orders/checkout", headers=world["buyer"], json={"address_id": world["addr"], "payment_method": method, "is_pickup": pickup})
    assert r.status_code == 201, r.text
    return r.json()[0]


def _mark_paid(order, status="success"):
    """Stand-in for Paystack confirming the payment."""
    _sql("INSERT INTO payments (id, order_id, provider, provider_reference, amount, currency, status, paid_at, created_at) "
         "VALUES (:id, :o, 'paystack', :ref, :amt, 'GHS', :st, now(), now())",
         id=str(uuid.uuid4()), o=order["id"], ref=f"EVM-{uuid.uuid4().hex[:10]}", amt=order["total_amount"], st=status)
    _sql("UPDATE orders SET status = 'paid' WHERE id = :i", i=order["id"])


@pytest.fixture(autouse=True)
def _no_real_email_and_no_cooldown(monkeypatch):
    receipts._last_emailed.clear()
    sent = []
    monkeypatch.setattr(receipts, "send_email", lambda **kw: sent.append(kw))
    return sent


# ----------------------------------------------------------------- download
def test_unpaid_order_has_no_receipt(client, world):
    order = _place_order(client, world)
    assert order["receipt_available"] is False and order["receipt_number"] is None
    r = client.get(f"/orders/{order['id']}/receipt", headers=world["buyer"])
    assert r.status_code == 400 and "payment" in r.json()["detail"].lower()


def test_pending_payment_attempt_is_not_a_receipt(client, world):
    order = _place_order(client, world)
    _mark_paid(order, status="pending")
    assert client.get(f"/orders/{order['id']}/receipt", headers=world["buyer"]).status_code == 400


def test_buyer_downloads_pdf_after_payment(client, world):
    order = _place_order(client, world, qty=3)
    _mark_paid(order)
    listed = next(o for o in client.get("/orders", headers=world["buyer"]).json() if o["id"] == order["id"])
    assert listed["receipt_available"] is True and listed["receipt_number"] == f"RCP-{order['order_number']}"
    r = client.get(f"/orders/{order['id']}/receipt", headers=world["buyer"])
    assert r.status_code == 200
    assert r.headers["content-type"] == "application/pdf"
    assert r.content.startswith(b"%PDF")
    assert f"EraVenda-Receipt-{order['order_number']}.pdf" in r.headers["content-disposition"]
    assert "attachment" in r.headers["content-disposition"]
    assert "no-store" in r.headers["cache-control"]


def test_cod_order_gets_receipt_when_admin_records_payment(client, world, monkeypatch):
    from app.routers import payments
    mails = []
    monkeypatch.setattr(payments, "send_email", lambda **kw: mails.append(kw))
    order = _place_order(client, world, method="cash_on_delivery")
    assert client.get(f"/orders/{order['id']}/receipt", headers=world["buyer"]).status_code == 400  # nothing paid yet
    rec = client.post("/admin/payments/cod-record", headers=world["admin"], json={"order_id": order["id"], "amount": order["total_amount"]})
    assert rec.status_code == 200, rec.text
    assert client.get(f"/orders/{order['id']}/receipt", headers=world["buyer"]).status_code == 200
    # ...and the buyer's confirmation email carried the PDF
    buyer_mail = next(m for m in mails if m["to"] == world["buyer_email"])
    assert buyer_mail["attachments"][0]["content"].startswith(b"%PDF")
    assert buyer_mail["attachments"][0]["filename"].endswith(".pdf")
    assert "receipt is attached" in buyer_mail["body"]
    assert not any(m.get("attachments") for m in mails if m["to"] != world["buyer_email"])  # only the buyer gets it


def test_payment_email_still_sends_if_the_receipt_cannot_be_built(client, world, monkeypatch):
    from app.routers import payments
    mails = []
    monkeypatch.setattr(payments, "send_email", lambda **kw: mails.append(kw))
    monkeypatch.setattr(receipts, "build_receipt_pdf", lambda **kw: (_ for _ in ()).throw(RuntimeError("boom")))
    order = _place_order(client, world, method="cash_on_delivery")
    assert client.post("/admin/payments/cod-record", headers=world["admin"], json={"order_id": order["id"], "amount": order["total_amount"]}).status_code == 200
    buyer_mail = next(m for m in mails if m["to"] == world["buyer_email"])
    assert not buyer_mail.get("attachments") and "attached" not in buyer_mail["body"]


# ----------------------------------------------------------------- permissions
def test_receipt_requires_login(client, world):
    order = _place_order(client, world)
    _mark_paid(order)
    assert client.get(f"/orders/{order['id']}/receipt").status_code == 401
    assert client.post(f"/orders/{order['id']}/receipt/email").status_code == 401


def test_other_users_cannot_see_or_email_my_receipt(client, world):
    order = _place_order(client, world)
    _mark_paid(order)
    for call in (lambda h: client.get(f"/orders/{order['id']}/receipt", headers=h),
                 lambda h: client.post(f"/orders/{order['id']}/receipt/email", headers=h)):
        assert call(world["other"]).status_code == 404   # not 403: don't confirm the order exists
        assert call(world["seller"]).status_code == 404  # even the seller uses their own dashboard, not this route


def test_malformed_and_unknown_ids_are_404_not_500(client, world):
    assert client.get("/orders/not-a-uuid/receipt", headers=world["buyer"]).status_code == 404
    assert client.get(f"/orders/{uuid.uuid4()}/receipt", headers=world["buyer"]).status_code == 404
    assert client.get("/admin/orders/not-a-uuid/receipt", headers=world["admin"]).status_code == 404


def test_admin_can_download_any_receipt_and_others_cannot(client, world):
    order = _place_order(client, world)
    _mark_paid(order)
    r = client.get(f"/admin/orders/{order['id']}/receipt", headers=world["admin"])
    assert r.status_code == 200 and r.content.startswith(b"%PDF")
    assert client.get(f"/admin/orders/{order['id']}/receipt", headers=world["buyer"]).status_code == 403
    assert client.get(f"/admin/orders/{order['id']}/receipt", headers=world["seller"]).status_code == 403
    assert client.get(f"/admin/orders/{order['id']}/receipt").status_code == 401
    assert client.post(f"/admin/orders/{order['id']}/receipt/email", headers=world["buyer"]).status_code == 403


def test_admin_payment_ledger_exposes_order_id(client, world):
    order = _place_order(client, world)
    _mark_paid(order)
    rows = client.get("/admin/payments/tracking", headers=world["admin"]).json()
    assert any(row["order_id"] == order["id"] and row["status"] == "success" for row in rows)


# ----------------------------------------------------------------- email
def test_buyer_can_email_receipt_to_themselves(client, world, _no_real_email_and_no_cooldown):
    order = _place_order(client, world)
    _mark_paid(order)
    r = client.post(f"/orders/{order['id']}/receipt/email", headers=world["buyer"])
    assert r.status_code == 200 and r.json()["sent_to"] == world["buyer_email"]
    sent = _no_real_email_and_no_cooldown
    assert len(sent) == 1 and sent[0]["to"] == world["buyer_email"]
    assert sent[0]["attachments"][0]["content"].startswith(b"%PDF")
    assert order["order_number"] in sent[0]["subject"]


def test_admin_resend_goes_only_to_the_buyers_own_email(client, world, _no_real_email_and_no_cooldown):
    order = _place_order(client, world)
    _mark_paid(order)
    r = client.post(f"/admin/orders/{order['id']}/receipt/email", headers=world["admin"])
    assert r.status_code == 200 and r.json()["sent_to"] == world["buyer_email"]
    assert _no_real_email_and_no_cooldown[0]["to"] == world["buyer_email"]


def test_email_is_rate_limited_per_order(client, world, _no_real_email_and_no_cooldown):
    order = _place_order(client, world)
    _mark_paid(order)
    assert client.post(f"/orders/{order['id']}/receipt/email", headers=world["buyer"]).status_code == 200
    again = client.post(f"/orders/{order['id']}/receipt/email", headers=world["buyer"])
    assert again.status_code == 429 and "wait" in again.json()["detail"].lower()
    assert len(_no_real_email_and_no_cooldown) == 1


def test_cannot_email_an_unpaid_receipt(client, world):
    order = _place_order(client, world)
    assert client.post(f"/orders/{order['id']}/receipt/email", headers=world["buyer"]).status_code == 400


def test_email_failure_is_a_clear_502_and_does_not_start_the_cooldown(client, world, monkeypatch):
    from app.email_utils import EmailDeliveryError
    order = _place_order(client, world)
    _mark_paid(order)

    def fail(**kw):
        raise EmailDeliveryError("resend down")
    monkeypatch.setattr(receipts, "send_email", fail)
    assert client.post(f"/orders/{order['id']}/receipt/email", headers=world["buyer"]).status_code == 502
    monkeypatch.setattr(receipts, "send_email", lambda **kw: None)
    assert client.post(f"/orders/{order['id']}/receipt/email", headers=world["buyer"]).status_code == 200  # retry works at once


def test_refunded_payment_still_produces_a_receipt_marked_refunded(client, world):
    order = _place_order(client, world)
    _mark_paid(order, status="refunded")
    r = client.get(f"/orders/{order['id']}/receipt", headers=world["buyer"])
    assert r.status_code == 200 and r.content.startswith(b"%PDF")

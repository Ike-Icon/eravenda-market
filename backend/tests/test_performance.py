"""Performance regression tests. Each one protects a speed-up so it cannot be
undone by accident (a missing index, a new N+1 query, a lost cache header).

    DATABASE_URL=postgresql://localhost:5432/eravenda_test \\
    SECRET_KEY=a-long-random-test-secret-of-32-chars-or-more \\
    RATE_LIMIT_DISABLED=1 python -m pytest tests/test_performance.py -q
"""
import gzip
import os
import pathlib
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event, text

os.environ.setdefault("SECRET_KEY", "test-secret-key-for-performance-tests-0123456789")

from app import cache, models  # noqa: E402
from app.database import SessionLocal, engine  # noqa: E402
from app.main import app  # noqa: E402

PWD = "Passw0rd!123"


def _sql(query, **params):
    with engine.begin() as conn:
        return conn.execute(text(query), params)


@pytest.fixture()
def api():
    with TestClient(app, base_url="http://testserver/api") as c:
        yield c


@pytest.fixture()
def site():
    with TestClient(app) as c:
        yield c


def _user(api, role):
    email = f"perf-{uuid.uuid4().hex[:10]}@example.com"
    api.post("/auth/register", json={"full_name": role, "email": email, "password": PWD})
    _sql("UPDATE users SET role = :r WHERE email = :e", r=role, e=email)
    token = api.post("/auth/login", data={"username": email, "password": PWD}).json()["access_token"]
    return email, {"Authorization": f"Bearer {token}"}


def _catalogue(api, product_count):
    """An approved store with `product_count` approved products, each with 3 images."""
    _, admin = _user(api, "admin")
    category = api.post("/categories", headers=admin, json={"name": f"Perf {uuid.uuid4().hex[:6]}"}).json()
    seller_email, seller = _user(api, "buyer")
    store = api.post("/stores", headers=seller, json={"store_name": f"Perf Store {uuid.uuid4().hex[:5]}", "region": "Bono", "city": "Sunyani"}).json()
    _sql("UPDATE stores SET status = 'approved' WHERE id = :i", i=store["id"])
    _sql("UPDATE users SET role = 'seller' WHERE email = :e", e=seller_email)
    token = api.post("/auth/login", data={"username": seller_email, "password": PWD}).json()["access_token"]
    seller = {"Authorization": f"Bearer {token}"}
    ids = []
    for i in range(product_count):
        p = api.post("/products", headers=seller, json={"name": f"Perf Item {uuid.uuid4().hex[:6]}", "category_id": category["id"], "price": 10 + i, "stock_quantity": 5}).json()
        for k in range(3):
            _sql("INSERT INTO product_images (id, product_id, image_url, is_primary, sort_order) VALUES (:id, :p, :u, :pr, :s)",
                 id=str(uuid.uuid4()), p=p["id"], u=f"https://res.cloudinary.com/demo/image/upload/{p['id']}_{k}.jpg", pr=(k == 0), s=k)
        ids.append(p["id"])
    _sql("UPDATE products SET status = 'approved' WHERE store_id = :s", s=store["id"])
    return admin, seller, category, store, ids


class QueryCounter:
    def __enter__(self):
        self.count = 0
        event.listen(engine, "before_cursor_execute", self._hit)
        return self

    def _hit(self, *args, **kwargs):
        self.count += 1

    def __exit__(self, *exc):
        event.remove(engine, "before_cursor_execute", self._hit)


# ---------------------------------------------------------------------------
# N+1 queries
# ---------------------------------------------------------------------------
def test_product_list_query_count_does_not_grow_with_the_number_of_products(api):
    _catalogue(api, 3)
    with QueryCounter() as few:
        assert api.get("/products", params={"page_size": 100}).status_code == 200
    _catalogue(api, 25)
    with QueryCounter() as many:
        r = api.get("/products", params={"page_size": 100})
        assert r.status_code == 200 and len(r.json()["items"]) >= 25
    # Before the fix every extra product cost about 2 more queries (its images and its store).
    assert many.count <= few.count + 2, (few.count, many.count)
    assert many.count <= 12


def test_products_page_query_count_stays_flat(site, api):
    _catalogue(api, 30)
    with QueryCounter() as counter:
        assert site.get("/products").status_code == 200
    assert counter.count <= 25, counter.count  # was one query per product on top of the base


def test_buyer_orders_list_does_not_query_per_order(api):
    _, _, category, store, ids = _catalogue(api, 6)
    email, buyer = _user(api, "buyer")
    address = api.post("/auth/addresses", headers=buyer, json={"recipient_name": "B", "phone": "0240000000", "region": "Bono", "city": "Sunyani"}).json()

    def place(count):
        for pid in ids[:count]:
            api.post("/cart/items", headers=buyer, json={"product_id": pid, "quantity": 1})
            r = api.post("/orders/checkout", headers=buyer, json={"address_id": address["id"], "payment_method": "cash_on_delivery"})
            assert r.status_code == 201, r.text

    place(2)
    with QueryCounter() as few:
        assert len(api.get("/orders", headers=buyer).json()) == 2
    place(4)
    with QueryCounter() as many:
        assert len(api.get("/orders", headers=buyer).json()) == 6
    # Before the fix each order cost about 9 more queries (items, products, images, stores).
    assert many.count <= few.count + 1, (few.count, many.count)


# ---------------------------------------------------------------------------
# Indexes
# ---------------------------------------------------------------------------
def test_every_foreign_key_column_is_indexed():
    """PostgreSQL does not index foreign keys on its own. Add the index to the
    newest file in backend/migrations when a model gains a new ForeignKey."""
    rows = _sql("""
        SELECT c.conrelid::regclass::text || '.' || a.attname
        FROM pg_constraint c
        JOIN pg_attribute a ON a.attrelid = c.conrelid AND a.attnum = ANY (c.conkey)
        WHERE c.contype = 'f' AND array_length(c.conkey, 1) = 1
          AND NOT EXISTS (SELECT 1 FROM pg_index i WHERE i.indrelid = c.conrelid AND i.indkey[0] = a.attnum)
    """).fetchall()
    assert rows == [], f"Foreign keys without an index: {[r[0] for r in rows]}"


def test_listing_queries_use_indexes_not_table_scans():
    with engine.begin() as conn:
        conn.execute(text("SET LOCAL enable_seqscan = off"))  # force the planner to show whether an index exists
        plan = "\n".join(r[0] for r in conn.execute(text(
            "EXPLAIN SELECT * FROM orders WHERE buyer_id = '00000000-0000-0000-0000-000000000000' ORDER BY created_at DESC")))
        assert "Seq Scan" not in plan and "ix_orders_buyer_created" in plan
        plan = "\n".join(r[0] for r in conn.execute(text(
            "EXPLAIN SELECT * FROM product_images WHERE product_id = '00000000-0000-0000-0000-000000000000'")))
        assert "Seq Scan" not in plan
        plan = "\n".join(r[0] for r in conn.execute(text(
            "EXPLAIN SELECT * FROM order_items WHERE order_id = '00000000-0000-0000-0000-000000000000'")))
        assert "Seq Scan" not in plan


# ---------------------------------------------------------------------------
# Compression and browser caching
# ---------------------------------------------------------------------------
def test_pages_and_json_are_gzipped_when_the_browser_accepts_it(site, api):
    _catalogue(api, 6)
    # /faq is a fixed page; the home page rearranges its products on every visit.
    plain = site.get("/faq", headers={"Accept-Encoding": "identity"})
    packed = site.get("/faq", headers={"Accept-Encoding": "gzip"})
    assert packed.headers.get("content-encoding") == "gzip"
    assert plain.headers.get("content-encoding") is None
    raw = gzip.compress(plain.content)
    assert len(raw) < len(plain.content) / 2  # HTML compresses to well under half
    assert packed.content == plain.content  # httpx decodes it; the page is unchanged

    json_resp = api.get("/products", params={"page_size": 100}, headers={"Accept-Encoding": "gzip"})
    assert json_resp.headers.get("content-encoding") == "gzip"
    assert json_resp.json()["items"]  # and it still decodes to valid JSON


def test_images_and_pdfs_are_not_compressed_again(site):
    png = site.get("/static/img/og-default.png", headers={"Accept-Encoding": "gzip"})
    assert png.status_code == 200 and png.headers.get("content-encoding") is None


def test_static_files_carry_cache_headers(site):
    versioned = site.get("/static/js/main.js?v=123")
    assert versioned.status_code == 200
    assert "max-age=31536000" in versioned.headers["cache-control"] and "immutable" in versioned.headers["cache-control"]

    unversioned = site.get("/static/js/main.js")
    assert "must-revalidate" in unversioned.headers["cache-control"] and "immutable" not in unversioned.headers["cache-control"]

    image = site.get("/static/img/og-default.png")
    assert "max-age=604800" in image.headers["cache-control"]
    # Every file the page head points at must exist, or each page view makes a wasted request.
    for icon in ("/static/img/favicon.svg", "/static/img/favicon.png", "/static/img/apple-touch-icon.png"):
        assert site.get(icon).status_code == 200, icon


def test_pages_that_must_stay_fresh_are_still_never_cached(site, api):
    # The home page shows a new random order on every visit by design.
    assert "no-store" in site.get("/").headers["cache-control"]


def test_public_api_reads_are_briefly_cacheable_but_never_personal(api):
    _, _, category, store, ids = _catalogue(api, 2)
    api.cookies.clear()
    cats = api.get("/categories")
    assert cats.headers["cache-control"] == "public, max-age=60, stale-while-revalidate=300"
    assert api.get("/products").headers["cache-control"] == "public, max-age=30, stale-while-revalidate=120"
    assert api.get(f"/products/{ids[0]}").headers["cache-control"].startswith("public, max-age=30")

    # A request carrying a login is never marked public, so it cannot be shared with others.
    email, buyer = _user(api, "buyer")
    api.cookies.clear()
    assert "no-store" in api.get("/categories", headers=buyer).headers["cache-control"]
    assert "no-store" in api.get("/products", headers=buyer).headers["cache-control"]
    api.post("/auth/login", data={"username": email, "password": PWD})  # sets the session cookie
    assert "no-store" in api.get("/categories").headers["cache-control"]

    # Private and role-specific endpoints are never cacheable.
    api.cookies.clear()
    for path in ("/cart", "/orders", "/wishlist", "/products/store/mine", "/auth/me"):
        r = api.get(path, headers=buyer)
        assert "public" not in r.headers.get("cache-control", ""), path
    assert "no-store" in api.get("/products/store/mine", headers=buyer).headers["cache-control"]
    # An error is never cached as if it were content.
    missing = api.get(f"/products/{uuid.uuid4()}")
    assert missing.status_code == 404 and "public" not in missing.headers["cache-control"]


def test_pages_load_the_minified_assets_while_they_are_fresh(site):
    html = site.get("/").text
    for name in ("js/main.js", "js/shell.js", "js/config.js", "css/custom.css"):
        stem, ext = name.rsplit(".", 1)
        assert f"/static/dist/{stem}.min.{ext}?v=" in html, name
        assert f"/static/{name}?v=" not in html, name
    # minified copies are about half the size
    root = pathlib.Path(__file__).resolve().parents[2] / "frontend" / "static"
    assert (root / "dist/js/main.min.js").stat().st_size < (root / "js/main.js").stat().st_size * 0.6


def test_stale_minified_copy_is_never_served(monkeypatch, tmp_path):
    """Edit main.js without rebuilding: visitors must get the edited file."""
    from app import main as app_main
    static = tmp_path / "static"
    (static / "js").mkdir(parents=True)
    (static / "dist" / "js").mkdir(parents=True)
    (static / "js" / "main.js").write_text("console.log('edited version');")
    (static / "dist" / "js" / "main.min.js").write_text("console.log('old')")
    import hashlib, json
    old_hash = hashlib.sha256(b"console.log('the version that was minified');").hexdigest()[:16]
    (static / "dist" / "manifest.json").write_text(json.dumps({"files": {"js/main.js": {
        "source_sha": old_hash, "dist": "dist/js/main.min.js", "dist_sha": "abc123"}}}))
    monkeypatch.setattr(app_main, "FRONTEND_DIR", tmp_path)
    (tmp_path / "static").mkdir(exist_ok=True)
    stale = app_main._compute_asset_urls()
    assert stale["js/main.js"].startswith("/static/js/main.js?v="), stale  # the source, not dist

    # Rebuild: the manifest now matches the source, so the minified copy is used.
    fresh_hash = hashlib.sha256((static / "js" / "main.js").read_bytes()).hexdigest()[:16]
    (static / "dist" / "manifest.json").write_text(json.dumps({"files": {"js/main.js": {
        "source_sha": fresh_hash, "dist": "dist/js/main.min.js", "dist_sha": "abc123"}}}))
    assert app_main._compute_asset_urls()["js/main.js"] == "/static/dist/js/main.min.js?v=abc123"

    # A missing minified file, a broken manifest, or the off switch all fall back to the source.
    (static / "dist" / "js" / "main.min.js").unlink()
    assert app_main._compute_asset_urls()["js/main.js"].startswith("/static/js/main.js?v=")
    (static / "dist" / "js" / "main.min.js").write_text("x")
    (static / "dist" / "manifest.json").write_text("{not json")
    assert app_main._compute_asset_urls()["js/main.js"].startswith("/static/js/main.js?v=")
    (static / "dist" / "manifest.json").write_text(json.dumps({"files": {"js/main.js": {
        "source_sha": fresh_hash, "dist": "dist/js/main.min.js", "dist_sha": "abc123"}}}))
    monkeypatch.setenv("MINIFIED_ASSETS", "false")
    assert app_main._compute_asset_urls()["js/main.js"].startswith("/static/js/main.js?v=")


def test_committed_minified_assets_match_their_sources():
    """If this fails the site still works (it serves the source instead), but it
    is slower. Fix: tools/build-assets.sh"""
    from app import main as app_main
    urls = app_main._compute_asset_urls()
    stale = [name for name, url in urls.items() if "/static/dist/" not in url]
    assert not stale, f"Minified copies out of date for {stale}. Run tools/build-assets.sh"


# ---------------------------------------------------------------------------
# Category menu cache
# ---------------------------------------------------------------------------
def test_category_menu_is_cached_and_updates_when_an_admin_changes_it(api, site):
    _, admin = _user(api, "admin")
    name = f"Cache Test {uuid.uuid4().hex[:6]}"
    assert name not in site.get("/").text

    cache.invalidate("categories")
    with QueryCounter() as first:
        site.get("/products")
    with QueryCounter() as second:
        site.get("/products")
    assert second.count < first.count  # the menu came from memory the second time

    created = api.post("/categories", headers=admin, json={"name": name})
    assert created.status_code == 201
    assert name in site.get("/").text  # visible immediately, no waiting for the timeout

    renamed = f"{name} Renamed"
    api.put(f"/categories/{created.json()['id']}", headers=admin, json={"name": renamed})
    page = site.get("/").text
    assert renamed in page

    assert api.delete(f"/categories/{created.json()['id']}", headers=admin).status_code == 204
    assert renamed not in site.get("/").text


def test_cache_helper_expires_and_invalidates():
    cache.invalidate("unit:")
    calls = []

    def load():
        calls.append(1)
        return len(calls)

    assert cache.cached("unit:a", 60, load) == 1
    assert cache.cached("unit:a", 60, load) == 1  # served from memory
    assert len(calls) == 1
    cache.invalidate("unit:")
    assert cache.cached("unit:a", 60, load) == 2  # reloaded after invalidation
    assert cache.cached("unit:b", 0, load) == 3
    assert cache.cached("unit:b", 0, load) == 4  # a zero-second limit never reuses


# ---------------------------------------------------------------------------
# Pre-built Tailwind stylesheet
# ---------------------------------------------------------------------------
def _tailwind_tools():
    import importlib.util
    path = pathlib.Path(__file__).resolve().parents[2] / "tools" / "tailwind" / "tokens.py"
    spec = importlib.util.spec_from_file_location("tailwind_tokens", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_tailwind_css_covers_every_class_in_use():
    """The site no longer compiles Tailwind in the browser, so a class added to a
    template after the last build would have no style. Fix: tools/build-assets.sh"""
    tools = _tailwind_tools()
    root = tools.ROOT
    built = tools.class_names_in_css((root / "frontend/static/css/tailwind.css").read_text())
    custom = tools.class_names_in_css((root / "frontend/static/css/custom.css").read_text())
    new = {t for t in tools.collect_tokens() if tools.looks_like_utility(t)} - tools.read_manifest()
    missing = sorted(t for t in new if t not in built and t not in custom and t.lstrip("!") not in built)
    assert not missing, f"Classes added since the last Tailwind build: {missing[:15]}. Run tools/build-assets.sh"


def test_tailwind_checker_notices_a_new_class(tmp_path):
    tools = _tailwind_tools()
    template = tmp_path / "frontend" / "templates"
    template.mkdir(parents=True)
    (template / "x.html").write_text('<div class="p-4 totally-new-utility-class mt-[37px] hover:bg-brand-500">')
    for sub in ("frontend/static/js", "backend/app"):
        (tmp_path / sub).mkdir(parents=True)
    tokens = {t for t in tools.collect_tokens(tmp_path) if tools.looks_like_utility(t)}
    assert "mt-[37px]" in tokens and "hover:bg-brand-500" in tokens and "p-4" in tokens
    assert "totally-new-utility-class" not in tokens  # not shaped like a utility: ignored
    built = tools.class_names_in_css((tools.ROOT / "frontend/static/css/tailwind.css").read_text())
    assert "mt-[37px]" not in built  # so the real check would flag it


def test_built_stylesheet_is_small_and_links_last(site):
    root = pathlib.Path(__file__).resolve().parents[2]
    size = (root / "frontend/static/css/tailwind.css").stat().st_size
    assert 10_000 < size < 200_000, size  # a 4 KB file means the build matched no files
    html = site.get("/faq").text
    head = html[: html.index("</head>")]
    assert head.rfind("/static/css/tailwind.css") > head.rfind("/static/css/custom.css")
    assert "cdn.tailwindcss.com" not in head


# ---------------------------------------------------------------------------
# Paged admin accounts list
# ---------------------------------------------------------------------------
def test_admin_users_page_pages_searches_and_filters(api):
    _, admin = _user(api, "admin")
    tag = uuid.uuid4().hex[:8]
    for i in range(5):
        api.post("/auth/register", json={"full_name": f"Pagetest {tag} {i}", "email": f"pt-{tag}-{i}@example.com", "password": PWD})
    _sql("UPDATE users SET role = 'seller' WHERE email = :e", e=f"pt-{tag}-0@example.com")

    first = api.get("/admin/users/page", headers=admin, params={"q": tag, "limit": 2, "offset": 0}).json()
    second = api.get("/admin/users/page", headers=admin, params={"q": tag, "limit": 2, "offset": 2}).json()
    last = api.get("/admin/users/page", headers=admin, params={"q": tag, "limit": 2, "offset": 4}).json()
    assert first["total"] == 5 and len(first["items"]) == 2 and len(second["items"]) == 2 and len(last["items"]) == 1
    ids = [u["id"] for page in (first, second, last) for u in page["items"]]
    assert len(set(ids)) == 5  # no account repeats or goes missing across pages

    sellers = api.get("/admin/users/page", headers=admin, params={"q": tag, "role": "seller"}).json()
    assert sellers["total"] == 1 and sellers["items"][0]["role"] == "seller"
    assert api.get("/admin/users/page", headers=admin, params={"q": f"pt-{tag}-3@"}).json()["total"] == 1  # search by email
    assert api.get("/admin/users/page", headers=admin, params={"q": "%"}).json()["total"] == 0  # wildcard is literal
    assert api.get("/admin/users/page", headers=admin, params={"limit": 1000}).status_code == 422  # page size is capped


def test_admin_users_page_flags_professionals_and_is_admin_only(api):
    _, admin = _user(api, "admin")
    email, buyer = _user(api, "buyer")
    api.cookies.clear()  # the test client keeps session cookies from earlier logins, like a browser
    assert api.get("/admin/users/page", headers=buyer).status_code == 403
    assert api.get("/admin/users/page").status_code == 401
    uid = api.get("/auth/me", headers=buyer).json()["id"]
    _sql("""INSERT INTO handyman_profiles (id, user_id, professional_name, job_title, qualifications, status,
                verified_pro, background_checked, average_rating, review_count, safety_rating, terms_accepted_at)
            VALUES (:id, :u, 'Pro Name', 'Electrician', 'Certified', 'approved', false, false, 0, 0, 0, now())""",
         id=str(uuid.uuid4()), u=uid)
    pros = api.get("/admin/users/page", headers=admin, params={"role": "professional", "q": email}).json()
    assert pros["total"] == 1 and pros["items"][0]["is_professional"] is True


def test_admin_users_page_payload_is_one_page_not_everyone(api):
    _, admin = _user(api, "admin")
    everyone = api.get("/admin/users", headers=admin)
    page = api.get("/admin/users/page", headers=admin, params={"limit": 20})
    assert len(page.json()["items"]) <= 20
    if len(everyone.json()) > 40:
        assert len(page.content) < len(everyone.content) / 2


# ---------------------------------------------------------------------------
# Home page product pool cache
# ---------------------------------------------------------------------------
def _ids_of(items):
    return [p.id for p in items]


def test_home_rails_stay_random_fair_and_cheap(api):
    from app.home_feed import fair_random_products
    big = _catalogue(api, 30)[3]    # store with 30 products
    small = _catalogue(api, 3)[3]   # store with 3 products
    only_these = models.Product.store_id.in_([big["id"], small["id"]])
    cache.invalidate("home-pool:")
    with SessionLocal() as db:
        with QueryCounter() as cold:
            first = fair_random_products(db, 6, only_these)
        with QueryCounter() as warm:
            second = fair_random_products(db, 6, only_these)
        orders = {tuple(_ids_of(fair_random_products(db, 12, only_these))) for _ in range(8)}
        # sellers take turns: the 3-product store gets 3 of the 6 slots even though the other has 30
        for _ in range(5):
            picked = fair_random_products(db, 6, only_these)
            assert sum(1 for p in picked if p.store_id == small["id"]) == 3
    assert len(first) == 6 and len(second) == 6
    assert warm.count < cold.count          # the candidate query is skipped the second time
    assert len(orders) > 1                  # a fresh random order on every visit, not a frozen one


def test_home_rails_never_show_a_product_that_was_just_hidden(api):
    from app.home_feed import fair_random_products
    _, _, _, store, ids = _catalogue(api, 4)
    only_this_store = models.Product.store_id == store["id"]
    cache.invalidate("home-pool:")
    with SessionLocal() as db:
        assert set(_ids_of(fair_random_products(db, 10, only_this_store))) == set(ids)  # pool is now cached
        _sql("UPDATE products SET status = 'rejected' WHERE id = :i", i=ids[0])
        shown = set(_ids_of(fair_random_products(db, 10, only_this_store)))
        assert ids[0] not in shown and shown == set(ids[1:])
        _sql("UPDATE stores SET status = 'suspended' WHERE id = :i", i=store["id"])
        assert fair_random_products(db, 10, only_this_store) == []  # a suspended store vanishes at once


def test_home_rails_respect_the_exclusion_list(api):
    from app.home_feed import fair_random_products
    _, _, _, store, ids = _catalogue(api, 5)
    only_this_store = models.Product.store_id == store["id"]
    cache.invalidate("home-pool:")
    with SessionLocal() as db:
        picked = _ids_of(fair_random_products(db, 10, only_this_store, exclude_ids=ids[:2]))
        assert set(picked) == set(ids[2:])

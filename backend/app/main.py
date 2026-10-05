# pyright: reportMissingImports=false

import os
import logging
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

from fastapi import FastAPI, Depends, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response, FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import text
from sqlalchemy.orm import Session, selectinload

from .database import Base, engine, get_db
from .migrate import run_migrations
from . import models  # noqa: F401 - registers models on Base before create_all
from .routers import auth, products, categories, cart, orders, stores, admin, users, payments, contact, wishlist, services, reviews, delivery, newsletter, import_products, monetization, analytics, broadcasts
from .platform_settings import get_settings, pinned_product_ids
from .home_feed import fair_random_products, live_promoted_products
from .database import SessionLocal
from . import email_utils
from .email_utils import SITE_URL

logger = logging.getLogger("eravenda.main")

app = FastAPI(title="Eravenda API", version="1.0.0")

allowed_origins = [origin.strip() for origin in os.getenv("ALLOWED_ORIGINS", "*").split(",") if origin.strip()]
if not allowed_origins:
    allowed_origins = ["*"]

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    # The frontend uses bearer tokens, not cookies. Keeping credentials off
    # makes wildcard origins valid and avoids accidental credential leakage.
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    response.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
    path = request.url.path
    if path.startswith("/api"):
        response.headers.setdefault("Cache-Control", "no-store")
    elif path in ("/", "/promoted", "/products"):
        # These pages rotate their content on every visit (fair-share random
        # home rails, promoted placements). Without an explicit header a
        # browser, proxy or CDN may keep serving one stale copy, which looks
        # like "the order never changes" and "the new section never appears".
        response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
        response.headers["CDN-Cache-Control"] = "no-store"
        response.headers["Pragma"] = "no-cache"
    return response


@app.on_event("startup")
def on_startup():
    # Create any missing tables first, then run the migrations. The order
    # matters on a brand-new database: most migrations ALTER core tables
    # (users, products, orders...) and fail with 'relation "users" does not
    # exist' if those tables haven't been created yet. On an existing
    # database create_all() only adds tables that are missing and leaves the
    # rest alone, so the migrations below still bring older tables up to date
    # (they are all idempotent), which keeps pages such as /services and
    # /services/register matching the ORM schema.
    Base.metadata.create_all(bind=engine)
    run_migrations()

    # Seed the single platform_settings row (standard product commission 7%,
    # subscriptions and promotions off) so the admin Monetization tab has
    # something to edit on a fresh database.
    with SessionLocal() as seed_db:
        get_settings(seed_db)

    # RESEND_API_KEY is declared with `sync: false` in render.yaml, which
    # means Render does NOT fill it in for you — it starts blank until
    # someone enters a real value in the dashboard's Environment tab. With
    # RESEND_API_KEY unset, send_email() quietly logs the email instead of
    # sending it (so local dev works with zero setup), which makes "why
    # isn't the reset email arriving?" very hard to debug in production
    # unless it's called out loudly at boot.
    if not email_utils.RESEND_API_KEY:
        logger.warning(
            "RESEND_API_KEY is not set — password reset, welcome, and contact "
            "emails will be logged to this console instead of actually sent. "
            "Set RESEND_API_KEY and FROM_EMAIL in the Render dashboard's "
            "Environment tab to fix this (see docs/resend-email-setup.md)."
        )


# ============================================================
# JSON API — everything the browser's fetch() calls talk to.
# Namespaced under /api so it never collides with the page
# routes below (GET /products the page vs GET /api/products the
# JSON endpoint used to be the same path before this refactor).
# ============================================================
app.include_router(auth.router, prefix="/api")
app.include_router(categories.router, prefix="/api")
app.include_router(stores.router, prefix="/api")
app.include_router(products.router, prefix="/api")
app.include_router(cart.router, prefix="/api")
app.include_router(orders.router, prefix="/api")
app.include_router(admin.router, prefix="/api")
app.include_router(users.router, prefix="/api")
app.include_router(payments.router, prefix="/api")
app.include_router(contact.router, prefix="/api")
app.include_router(wishlist.router, prefix="/api")
app.include_router(services.router, prefix="/api")
app.include_router(reviews.router, prefix="/api")
app.include_router(delivery.router, prefix="/api")
app.include_router(newsletter.router, prefix="/api")
app.include_router(broadcasts.router, prefix="/api")
app.include_router(analytics.router, prefix="/api")
app.include_router(import_products.template_router, prefix="/api")
app.include_router(import_products.seller_import_router, prefix="/api")
app.include_router(import_products.admin_import_router, prefix="/api")
app.include_router(monetization.router, prefix="/api")
app.include_router(monetization.admin_router, prefix="/api")


@app.get("/api/health")
def health_check(db: Session = Depends(get_db)):
    db.execute(text("SELECT 1"))
    return {"status": "ok", "service": "eravenda-api", "database": "ok"}


# ============================================================
# Server-rendered pages (Jinja2)
# ============================================================
FRONTEND_DIR = Path(__file__).resolve().parent.parent.parent / "frontend"

# Cards per page on the browse (/products) and store (/store/{id}) pages.
# Passed to the templates as `page_size` so the server-rendered markup and the
# browser-side pager can never disagree about it.
PRODUCTS_PAGE_SIZE = 24
# Upper bound on how many products /products sends to the browser to page
# through (the pager works client-side so the sidebar filters span everything).
PRODUCTS_PAGE_MAX = 500

templates = Jinja2Templates(directory=str(FRONTEND_DIR / "templates"))
# Used when building JSON-LD in templates: {"a": 1, "b": None} | compact -> {"a": 1}.
# Keeps optional structured-data fields (aggregateRating, brand, ...) out of the
# JSON entirely when there's nothing to say, instead of shipping "field": null,
# which trips validators like Google's Rich Results Test.
templates.env.filters["compact"] = lambda d: {k: v for k, v in d.items() if v is not None}

# New Tailwind-based assets (main.js, config.js, custom.css) for the
# templated pages below.
app.mount("/static", StaticFiles(directory=str(FRONTEND_DIR / "static")), name="static")

# Legacy assets, still used by the order-history page, which hasn't
# been migrated to Jinja2 yet.
app.mount("/css", StaticFiles(directory=str(FRONTEND_DIR / "css")), name="legacy_css")
app.mount("/js", StaticFiles(directory=str(FRONTEND_DIR / "js")), name="legacy_js")


def _category_and_child_ids(db: Session, category_id: str) -> list:
    """
    A category filter should include its children — a buyer who clicks
    the parent "Electronics & Gadgets" expects to see everything under
    it, including products tagged with the more specific "Mobile &
    Accessories" child, not just products tagged to the parent itself.
    """
    child_ids = [
        row[0] for row in db.query(models.Category.id).filter(models.Category.parent_id == category_id).all()
    ]
    return [category_id] + child_ids


def page_context(request: Request, db: Session, **extra) -> dict:
    """
    Shared context every page template needs.

    `categories` stays a flat list of every category (parent and child) —
    used where a flat pick-list makes sense, like the seller's "choose a
    category" dropdown when listing a product.

    `category_tree` is top-level categories only, each with `.children`
    preloaded — used for navigation displays (header, homepage grid) where
    only parents show by default and children reveal on hover/click.
    """
    categories = db.query(models.Category).order_by(models.Category.name).all()
    category_tree = (
        db.query(models.Category)
        .filter(models.Category.parent_id.is_(None))
        .options(selectinload(models.Category.children))
        .order_by(models.Category.name)
        .all()
    )
    context = {
        "request": request,
        "categories": categories,
        "category_tree": category_tree,
        "current_year": datetime.utcnow().year,
        "site_url": SITE_URL,
        # Self-referencing canonical for every page. `page` is dropped because
        # our list pages paginate client-side (history.replaceState, no
        # server reload) — every ?page=N is the same document as far as a
        # crawler should be concerned, so they'd otherwise look like
        # duplicate content competing against each other in search results.
        "canonical_url": _canonical_url(request),
    }
    context.update(extra)
    return context


def _canonical_url(request: Request) -> str:
    query = "&".join(
        f"{k}={v}" for k, v in request.query_params.multi_items() if k != "page"
    )
    path = request.url.path.rstrip("/") or "/"
    return f"{SITE_URL}{path}" + (f"?{query}" if query else "")


@app.get("/", response_class=HTMLResponse)
def home_page(request: Request, db: Session = Depends(get_db)):
    # Paid promotions get their own section; the rails below are fair-share
    # random (every seller takes turns, new order on each visit) instead of
    # newest-first, so no seller owns the home page just by uploading last.
    promoted_products = live_promoted_products(db, limit=12)
    promoted_ids = [p.id for p in promoted_products]
    products_list = fair_random_products(db, 30, exclude_ids=promoted_ids)
    if not products_list:  # tiny catalogue: everything is already in the promoted rail
        products_list = fair_random_products(db, 30)
    flash_deals = fair_random_products(
        db, 8,
        models.Product.discount_price.isnot(None),
        models.Product.discount_price < models.Product.price,
    )
    featured_stores = (
        db.query(models.Store)
        .order_by(models.Store.created_at.desc())
        .limit(6)
        .all()
    )
    featured_handymen = (
        db.query(models.HandymanProfile)
        .options(selectinload(models.HandymanProfile.portfolio))
        .filter(models.HandymanProfile.status == models.ServiceStatus.approved)
        .order_by(models.HandymanProfile.average_rating.desc(), models.HandymanProfile.review_count.desc())
        .limit(6)
        .all()
    )
    # Distinct from flash_deals (which is recency-ordered for the countdown
    # banner): this is the biggest absolute cedi savings across the catalog,
    # feeding the horizontal-scroll "Top Deals" rail further down the page.
    top_deals = (
        db.query(models.Product)
        .filter(
            models.Product.status == models.ProductStatus.approved,
            models.Product.discount_price.isnot(None),
            models.Product.discount_price < models.Product.price,
        )
        .order_by((models.Product.price - models.Product.discount_price).desc())
        .limit(14)
        .all()
    )
    top_rated = (
        db.query(models.Product)
        .filter(
            models.Product.status == models.ProductStatus.approved,
            models.Product.average_rating >= 4,
            models.Product.review_count > 0,
        )
        .order_by(models.Product.average_rating.desc(), models.Product.review_count.desc())
        .limit(14)
        .all()
    )
    # Feeds the "Pay on Delivery" rail — sellers opt individual products in or
    # out of COD (Product.cod_eligible), so this only shows ones they've kept eligible.
    pay_on_delivery = fair_random_products(db, 14, models.Product.cod_eligible.is_(True))
    return templates.TemplateResponse(
        "index.html",
        page_context(
            request,
            db,
            products=products_list,
            flash_deals=flash_deals,
            featured_stores=featured_stores,
            featured_handymen=featured_handymen,
            top_deals=top_deals,
            top_rated=top_rated,
            pay_on_delivery=pay_on_delivery,
            promoted_products=promoted_products,
        ),
    )


@app.get("/products", response_class=HTMLResponse)
def products_page(
    request: Request,
    q: str = "",
    category_id: str = "",
    sort: str = "newest",
    cod: str = "",
    db: Session = Depends(get_db),
):
    query = db.query(models.Product).filter(models.Product.status == models.ProductStatus.approved)

    if q:
        like = f"%{q}%"
        query = query.filter(models.Product.name.ilike(like))
    if category_id:
        query = query.filter(models.Product.category_id.in_(_category_and_child_ids(db, category_id)))
    cod_only = cod in ("1", "true", "yes")
    if cod_only:
        query = query.filter(models.Product.cod_eligible.is_(True))

    if sort == "price_asc":
        query = query.order_by(models.Product.price.asc())
    elif sort == "price_desc":
        query = query.order_by(models.Product.price.desc())
    else:
        query = query.order_by(models.Product.created_at.desc())

    # The page paginates in the browser (products.html), so that its category,
    # stock and Pay-on-Delivery filters can work across every product rather
    # than just the current page. Previously this was capped at 60 with no
    # way to reach the rest. PRODUCTS_PAGE_MAX keeps the page size sane; when
    # more products match than that, the template shows a "narrow your search"
    # notice (products_not_shown). If the catalogue outgrows this, move to
    # server-side pagination.
    total_matching = query.count()
    products_list = query.limit(PRODUCTS_PAGE_MAX).all()

    # Promoted listings: when browsing a category, live paid pins go first
    # (oldest promotion first) and are marked so the card can say "Sponsored".
    # Only products already in this result set move, so search text, the
    # Pay-on-Delivery filter and approval status still apply to them.
    if category_id:
        pinned_ids = pinned_product_ids(db, _category_and_child_ids(db, category_id))
        if pinned_ids:
            by_id = {p.id: p for p in products_list}
            pinned = [by_id[pid] for pid in pinned_ids if pid in by_id]
            for p in pinned:
                p.is_sponsored = True
            pinned_set = {p.id for p in pinned}
            products_list = pinned + [p for p in products_list if p.id not in pinned_set]

    # Paid-promotion strip above the grid (hidden by the template while the
    # shopper is searching by text, so it never hijacks a specific search).
    promoted_strip = live_promoted_products(
        db, limit=8,
        category_ids=_category_and_child_ids(db, category_id) if category_id else None,
    )

    return templates.TemplateResponse(
        "products.html",
        page_context(
            request, db,
            promoted_strip=promoted_strip,
            products=products_list,
            search_query=q,
            selected_category_id=category_id,
            sort=sort,
            cod_only=cod_only,
            page_size=PRODUCTS_PAGE_SIZE,
            # Non-zero only when more products match than the page can hold, so
            # the template can say so instead of silently dropping the rest.
            products_not_shown=max(0, total_matching - len(products_list)),
        ),
    )


@app.get("/promoted", response_class=HTMLResponse)
def promoted_page(request: Request, category_id: str = "", db: Session = Depends(get_db)):
    """Only products sellers have paid to promote right now."""
    all_promoted = live_promoted_products(db)
    # Category chips: only categories that actually have a promoted product,
    # so every chip leads somewhere.
    chip_ids = {p.category_id for p in all_promoted}
    chip_categories = (
        db.query(models.Category).filter(models.Category.id.in_(chip_ids)).order_by(models.Category.name).all()
        if chip_ids else []
    )
    if category_id:
        wanted = set(_category_and_child_ids(db, category_id))
        promoted = [p for p in all_promoted if p.category_id in wanted]
    else:
        promoted = all_promoted
    return templates.TemplateResponse(
        "promoted.html",
        page_context(
            request, db,
            promoted_products=promoted,
            chip_categories=chip_categories,
            selected_category_id=category_id,
        ),
    )


@app.get("/product/{product_id}", response_class=HTMLResponse)
def product_page(product_id: str, request: Request, db: Session = Depends(get_db)):
    product = db.query(models.Product).filter(models.Product.id == product_id).first()
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")

    store = db.query(models.Store).filter(models.Store.id == product.store_id).first()

    more_from_store = (
        db.query(models.Product)
        .filter(
            models.Product.store_id == product.store_id,
            models.Product.id != product.id,
            models.Product.status == models.ProductStatus.approved,
        )
        .order_by(models.Product.created_at.desc())
        .limit(6)
        .all()
    )
    reviews = (
        db.query(models.Review)
        .filter(models.Review.product_id == product.id)
        .order_by(models.Review.created_at.desc())
        .limit(20)
        .all()
    )
    related_products = (
        db.query(models.Product)
        .filter(models.Product.category_id == product.category_id, models.Product.id != product.id, models.Product.status == models.ProductStatus.approved)
        .order_by(models.Product.average_rating.desc(), models.Product.created_at.desc())
        .limit(6).all()
    )

    return templates.TemplateResponse(
        "product.html",
        page_context(
            request, db, product=product, store=store, more_from_store=more_from_store,
            related_products=related_products, reviews=reviews,
            sponsored_picks=live_promoted_products(
                db, limit=6, category_ids=[product.category_id], exclude_ids=[product.id],
            ),
        ),
    )


@app.get("/store/{store_id}", response_class=HTMLResponse)
def store_page(store_id: str, request: Request, db: Session = Depends(get_db)):
    store = db.query(models.Store).filter(models.Store.id == store_id).first()
    if not store:
        raise HTTPException(status_code=404, detail="Store not found")

    products_list = (
        db.query(models.Product)
        .filter(models.Product.store_id == store_id, models.Product.status == models.ProductStatus.approved)
        .order_by(models.Product.created_at.desc())
        .all()
    )

    return templates.TemplateResponse(
        "store.html",
        page_context(request, db, store=store, products=products_list, page_size=PRODUCTS_PAGE_SIZE),
    )


@app.get("/cart", response_class=HTMLResponse)
def cart_page(request: Request, db: Session = Depends(get_db)):
    # Cart contents are fetched client-side (see cart.html's script block),
    # since the cart is tied to the JWT sitting in localStorage, not a
    # server-side session this route could read.
    return templates.TemplateResponse("cart.html", page_context(request, db))


@app.get("/checkout", response_class=HTMLResponse)
def checkout_page(request: Request, db: Session = Depends(get_db)):
    return templates.TemplateResponse("checkout.html", page_context(request, db))


@app.get("/login", response_class=HTMLResponse)
def login_page(request: Request, db: Session = Depends(get_db)):
    return templates.TemplateResponse("login.html", page_context(request, db))


@app.get("/register", response_class=HTMLResponse)
def register_page(request: Request, db: Session = Depends(get_db)):
    return templates.TemplateResponse("register.html", page_context(request, db))


@app.get("/wishlist", response_class=HTMLResponse)
def wishlist_page(request: Request, db: Session = Depends(get_db)):
    return templates.TemplateResponse("wishlist.html", page_context(request, db))


@app.get("/services", response_class=HTMLResponse)
def services_page(request: Request, db: Session = Depends(get_db)):
    return templates.TemplateResponse("services.html", page_context(request, db))


@app.get("/services/register", response_class=HTMLResponse)
def services_register_page(request: Request, db: Session = Depends(get_db)):
    return templates.TemplateResponse("services-register.html", page_context(request, db))


@app.get("/delivery/register", response_class=HTMLResponse)
def delivery_register_page(request: Request, db: Session = Depends(get_db)):
    return templates.TemplateResponse("delivery-register.html", page_context(request, db))


@app.get("/delivery/dashboard", response_class=HTMLResponse)
def delivery_dashboard_page(request: Request, db: Session = Depends(get_db)):
    return templates.TemplateResponse("delivery-dashboard.html", page_context(request, db))


@app.get("/professional/dashboard.html", response_class=HTMLResponse)
def professional_dashboard_page(request: Request, db: Session = Depends(get_db)):
    return templates.TemplateResponse("professional/dashboard.html", page_context(request, db))


@app.get("/services/professional/{handyman_id}", response_class=HTMLResponse)
def service_professional_page(handyman_id: str, request: Request, db: Session = Depends(get_db)):
    worker = db.query(models.HandymanProfile).options(selectinload(models.HandymanProfile.portfolio)).filter(models.HandymanProfile.id == handyman_id, models.HandymanProfile.status == models.ServiceStatus.approved).first()
    if not worker:
        raise HTTPException(status_code=404, detail="Service professional not found")
    return templates.TemplateResponse("services-professional.html", page_context(request, db, worker=worker))


@app.get("/services/request/{handyman_id}", response_class=HTMLResponse)
def service_request_page(handyman_id: str, request: Request, db: Session = Depends(get_db)):
    worker = db.query(models.HandymanProfile).filter(
        models.HandymanProfile.id == handyman_id,
        models.HandymanProfile.status == models.ServiceStatus.approved,
    ).first()
    if not worker:
        raise HTTPException(status_code=404, detail="Service professional not found")
    return templates.TemplateResponse("service-request.html", page_context(request, db, worker=worker))


# ============================================================
# Seeker-facing booking pages. Both are auth-gated client-side
# (see each template's script block) since bookings belong to
# whoever's JWT is in localStorage — the same pattern as
# orders.html and the seller/admin dashboards.
# ============================================================
@app.get("/services/bookings", response_class=HTMLResponse)
def my_bookings_page(request: Request, db: Session = Depends(get_db)):
    return templates.TemplateResponse("my-bookings.html", page_context(request, db))


@app.get("/services/bookings/{booking_id}", response_class=HTMLResponse)
def booking_tracker_page(booking_id: str, request: Request, db: Session = Depends(get_db)):
    # The booking itself is fetched client-side (with the viewer's JWT) so
    # the API can enforce who's allowed to see it. This route just needs a
    # valid-looking id to hand off to the template.
    return templates.TemplateResponse("booking-tracker.html", page_context(request, db, booking_id=booking_id))


@app.get("/forgot-password", response_class=HTMLResponse)
def forgot_password_page(request: Request, db: Session = Depends(get_db)):
    return templates.TemplateResponse("forgot-password.html", page_context(request, db))


@app.get("/reset-password", response_class=HTMLResponse)
def reset_password_page(request: Request, db: Session = Depends(get_db)):
    return templates.TemplateResponse("reset-password.html", page_context(request, db))


@app.get("/account", response_class=HTMLResponse)
def account_page(request: Request, db: Session = Depends(get_db)):
    return templates.TemplateResponse("account.html", page_context(request, db))


@app.get("/settings", response_class=HTMLResponse)
def settings_page(request: Request, db: Session = Depends(get_db)):
    return templates.TemplateResponse("settings.html", page_context(request, db))


# ============================================================
# Static info pages
# ============================================================
@app.get("/about", response_class=HTMLResponse)
def about_page(request: Request, db: Session = Depends(get_db)):
    return templates.TemplateResponse("about.html", page_context(request, db))


@app.get("/contact", response_class=HTMLResponse)
def contact_page(request: Request, db: Session = Depends(get_db)):
    return templates.TemplateResponse("contact.html", page_context(request, db))


@app.get("/terms", response_class=HTMLResponse)
def terms_page(request: Request, db: Session = Depends(get_db)):
    return templates.TemplateResponse("terms.html", page_context(request, db))


@app.get("/delivery/terms", response_class=HTMLResponse)
def delivery_terms_page(request: Request, db: Session = Depends(get_db)):
    return templates.TemplateResponse("delivery-terms.html", page_context(request, db))


@app.get("/privacy", response_class=HTMLResponse)
def privacy_page(request: Request, db: Session = Depends(get_db)):
    return templates.TemplateResponse("privacy.html", page_context(request, db))


@app.get("/faq", response_class=HTMLResponse)
def faq_page(request: Request, db: Session = Depends(get_db)):
    return templates.TemplateResponse("faq.html", page_context(request, db))


# ============================================================
# Paystack redirect lands here after payment. The page itself
# calls /api/payments/verify/{reference} client-side to confirm
# the transaction and show success/failure.
# ============================================================
@app.get("/payments/callback", response_class=HTMLResponse)
def payment_callback_page(request: Request, db: Session = Depends(get_db)):
    return templates.TemplateResponse("payments/callback.html", page_context(request, db))


# ============================================================
# Seller dashboard — auth-gated client-side (see each template's
# script block), since these pages read the JWT from localStorage.
# ============================================================
@app.get("/seller/dashboard.html", response_class=HTMLResponse)
def seller_dashboard_page(request: Request, db: Session = Depends(get_db)):
    return templates.TemplateResponse("seller/dashboard.html", page_context(request, db))


@app.get("/seller/products.html", response_class=HTMLResponse)
def seller_products_page(request: Request, db: Session = Depends(get_db)):
    return templates.TemplateResponse("seller/products.html", page_context(request, db))


@app.get("/seller/add-product.html", response_class=HTMLResponse)
def seller_add_product_page(request: Request, db: Session = Depends(get_db)):
    return templates.TemplateResponse("seller/add-product.html", page_context(request, db))


@app.get("/seller/edit-product.html", response_class=HTMLResponse)
def seller_edit_product_page(request: Request, db: Session = Depends(get_db)):
    # product_id comes from a ?id= query param, read client-side (see the
    # template's script block) — same reasoning as add-product: this page
    # needs the seller's own JWT to fetch and authorize the edit.
    return templates.TemplateResponse("seller/edit-product.html", page_context(request, db))


@app.get("/seller/growth.html", response_class=HTMLResponse)
def seller_growth_page(request: Request, db: Session = Depends(get_db)):
    # Subscription plan + promoted listings; data is fetched client-side with
    # the seller's JWT, same as the other seller pages.
    return templates.TemplateResponse("seller/growth.html", page_context(request, db))


@app.get("/seller/orders.html", response_class=HTMLResponse)
def seller_orders_page(request: Request, db: Session = Depends(get_db)):
    return templates.TemplateResponse("seller/orders.html", page_context(request, db))


# ============================================================
# Admin dashboard — same client-side auth-gating approach as the
# seller pages above, plus a role check in the template's script.
# ============================================================
@app.get("/admin/dashboard.html", response_class=HTMLResponse)
def admin_dashboard_page(request: Request, db: Session = Depends(get_db)):
    return templates.TemplateResponse("admin/dashboard.html", page_context(request, db))


@app.get("/admin/stats.html", response_class=HTMLResponse)
def admin_stats_page(request: Request, db: Session = Depends(get_db)):
    return templates.TemplateResponse("admin/stats.html", page_context(request, db))


@app.get("/admin/edit-product.html", response_class=HTMLResponse)
def admin_edit_product_page(request: Request, db: Session = Depends(get_db)):
    # Same client-side auth-gating as the seller edit page: product_id comes
    # from a ?id= query param, read in the template's script, using the
    # signed-in admin's own JWT so /admin/products/{id} authorizes correctly.
    return templates.TemplateResponse("admin/edit-product.html", page_context(request, db))


# ============================================================
# A couple of standalone legacy files that aren't part of the
# Jinja2 migration yet, served as-is.
# ============================================================
@app.get("/pay-order", response_class=HTMLResponse)
def pay_order_page(request: Request, db: Session = Depends(get_db)):
    return templates.TemplateResponse("pay-order.html", page_context(request, db))


@app.get("/orders.html", response_class=HTMLResponse)
def orders_page(request: Request, db: Session = Depends(get_db)):
    # Order contents are fetched client-side (see orders.html's script
    # block), since orders belong to whoever's JWT is in localStorage,
    # not a server-side session this route could read directly.
    return templates.TemplateResponse("orders.html", page_context(request, db))


@app.get("/orders/review", response_class=HTMLResponse)
def order_review_page(request: Request, db: Session = Depends(get_db)):
    return templates.TemplateResponse("order-review.html", page_context(request, db))


@app.get("/orders/track", response_class=HTMLResponse)
def order_tracking_page(request: Request, db: Session = Depends(get_db)):
    return templates.TemplateResponse("order-tracking.html", page_context(request, db))


@app.get("/healthz")
def healthz():
    # Deliberately does not touch the database: Render's paid plans use this
    # (see healthCheckPath in render.yaml) to confirm a new instance is ready
    # before routing traffic to it and retiring the old one (zero-downtime
    # deploys). It needs to answer fast regardless of DB load, so it can't
    # depend on the DB being reachable.
    return {"status": "ok"}


@app.get("/robots.txt")
def robots_txt():
    return FileResponse(FRONTEND_DIR / "robots.txt", media_type="text/plain")


@app.get("/favicon.ico")
def favicon():
    # Browsers and crawlers request this by convention, regardless of the
    # <link rel="icon"> tags in base.html — this covers that fallback.
    return FileResponse(FRONTEND_DIR / "static" / "img" / "favicon.ico")


@app.get("/sitemap.xml")
def sitemap(db: Session = Depends(get_db)):
    """
    Regenerates the sitemap from live data on every request. Fine for a
    catalog this size; if you grow past a few thousand products, cache
    this behind a short TTL instead of hitting the database every time.
    """
    # Static pages worth indexing. Account, checkout, dashboard and other
    # private/transactional pages are marked noindex in their own template
    # (robots_meta block) and left out of here entirely.
    static_urls = [
        SITE_URL, f"{SITE_URL}/products", f"{SITE_URL}/promoted", f"{SITE_URL}/services",
        f"{SITE_URL}/services/register", f"{SITE_URL}/delivery/register",
        f"{SITE_URL}/about", f"{SITE_URL}/contact", f"{SITE_URL}/faq",
        f"{SITE_URL}/terms", f"{SITE_URL}/privacy", f"{SITE_URL}/delivery/terms",
    ]

    approved_products = db.query(models.Product.id, models.Product.updated_at).filter(
        models.Product.status == models.ProductStatus.approved
    ).all()

    approved_stores = db.query(models.Store.id).filter(
        models.Store.status == models.StoreStatus.approved
    ).all()

    approved_handymen = db.query(models.HandymanProfile.id).filter(
        models.HandymanProfile.status == models.ServiceStatus.approved
    ).all()

    xml_parts = ['<?xml version="1.0" encoding="UTF-8"?>', '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">']

    for url in static_urls:
        xml_parts.append(f"<url><loc>{url}</loc><changefreq>weekly</changefreq></url>")

    for product_id, updated_at in approved_products:
        loc = f"{SITE_URL}/product/{product_id}"
        lastmod = updated_at.strftime("%Y-%m-%d") if updated_at else ""
        xml_parts.append(f"<url><loc>{loc}</loc><lastmod>{lastmod}</lastmod><changefreq>weekly</changefreq></url>")

    for (store_id,) in approved_stores:
        loc = f"{SITE_URL}/store/{store_id}"
        xml_parts.append(f"<url><loc>{loc}</loc><changefreq>weekly</changefreq></url>")

    for (handyman_id,) in approved_handymen:
        loc = f"{SITE_URL}/services/professional/{handyman_id}"
        xml_parts.append(f"<url><loc>{loc}</loc><changefreq>weekly</changefreq></url>")

    xml_parts.append("</urlset>")
    xml = "".join(xml_parts)

    return Response(content=xml, media_type="application/xml")

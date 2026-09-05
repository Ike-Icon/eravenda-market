# pyright: reportMissingImports=false

import os
from datetime import datetime
from pathlib import Path

from fastapi import FastAPI, Depends, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response, FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from dotenv import load_dotenv
from sqlalchemy.orm import Session

from .database import Base, engine, get_db
from . import models  # noqa: F401 - registers models on Base before create_all
from .routers import auth, products, categories, cart, orders, stores, admin

load_dotenv()

app = FastAPI(title="Eravenda API", version="1.0.0")

allowed_origins = os.getenv("ALLOWED_ORIGINS", "*").split(",")

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def on_startup():
    # For local development. In production, use Alembic migrations instead.
    Base.metadata.create_all(bind=engine)


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


@app.get("/api/health")
def health_check():
    return {"status": "ok", "service": "eravenda-api"}


# ============================================================
# Server-rendered pages (Jinja2)
# ============================================================
FRONTEND_DIR = Path(__file__).resolve().parent.parent.parent / "frontend"

templates = Jinja2Templates(directory=str(FRONTEND_DIR / "templates"))

# New Tailwind-based assets (main.js, config.js, custom.css) for the
# templated pages below.
app.mount("/static", StaticFiles(directory=str(FRONTEND_DIR / "static")), name="static")

# Legacy assets, still used by the order-history page, which hasn't
# been migrated to Jinja2 yet.
app.mount("/css", StaticFiles(directory=str(FRONTEND_DIR / "css")), name="legacy_css")
app.mount("/js", StaticFiles(directory=str(FRONTEND_DIR / "js")), name="legacy_js")


def page_context(request: Request, db: Session, **extra) -> dict:
    """
    Shared context every page template needs — the category list for the
    header/footer, plus the current year for the copyright line. Individual
    routes layer their own data (products, a single product, etc.) on top.
    """
    categories = db.query(models.Category).order_by(models.Category.name).all()
    context = {
        "request": request,
        "categories": categories,
        "current_year": datetime.utcnow().year,
    }
    context.update(extra)
    return context


@app.get("/", response_class=HTMLResponse)
def home_page(request: Request, db: Session = Depends(get_db)):
    products_list = (
        db.query(models.Product)
        .filter(models.Product.status == models.ProductStatus.approved)
        .order_by(models.Product.created_at.desc())
        .limit(15)
        .all()
    )
    return templates.TemplateResponse(
        "index.html", page_context(request, db, products=products_list)
    )


@app.get("/products", response_class=HTMLResponse)
def products_page(
    request: Request,
    q: str = "",
    category_id: str = "",
    sort: str = "newest",
    db: Session = Depends(get_db),
):
    query = db.query(models.Product).filter(models.Product.status == models.ProductStatus.approved)

    if q:
        like = f"%{q}%"
        query = query.filter(models.Product.name.ilike(like))
    if category_id:
        query = query.filter(models.Product.category_id == category_id)

    if sort == "price_asc":
        query = query.order_by(models.Product.price.asc())
    elif sort == "price_desc":
        query = query.order_by(models.Product.price.desc())
    else:
        query = query.order_by(models.Product.created_at.desc())

    products_list = query.limit(60).all()

    return templates.TemplateResponse(
        "products.html",
        page_context(
            request, db,
            products=products_list,
            search_query=q,
            selected_category_id=category_id,
            sort=sort,
        ),
    )


@app.get("/product/{product_id}", response_class=HTMLResponse)
def product_page(product_id: str, request: Request, db: Session = Depends(get_db)):
    product = db.query(models.Product).filter(models.Product.id == product_id).first()
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")
    return templates.TemplateResponse("product.html", page_context(request, db, product=product))


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


# ============================================================
# A couple of standalone legacy files that aren't part of the
# Jinja2 migration yet, served as-is.
# ============================================================
@app.get("/orders.html", response_class=HTMLResponse)
def orders_page(request: Request, db: Session = Depends(get_db)):
    # Order contents are fetched client-side (see orders.html's script
    # block), since orders belong to whoever's JWT is in localStorage,
    # not a server-side session this route could read directly.
    return templates.TemplateResponse("orders.html", page_context(request, db))


@app.get("/robots.txt")
def robots_txt():
    return FileResponse(FRONTEND_DIR / "robots.txt", media_type="text/plain")


@app.get("/favicon.ico")
def favicon():
    # Browsers and crawlers request this by convention, regardless of the
    # <link rel="icon"> tags in base.html — this covers that fallback.
    return FileResponse(FRONTEND_DIR / "static" / "img" / "favicon.ico")


# Set this in your .env once you have a real domain, e.g. https://www.eravenda.com
SITE_URL = os.getenv("SITE_URL", "https://www.eravenda.com")


@app.get("/sitemap.xml")
def sitemap(db: Session = Depends(get_db)):
    """
    Regenerates the sitemap from live data on every request. Fine for a
    catalog this size; if you grow past a few thousand products, cache
    this behind a short TTL instead of hitting the database every time.
    """
    urls = [SITE_URL, f"{SITE_URL}/products"]

    approved_products = db.query(models.Product.id, models.Product.updated_at).filter(
        models.Product.status == models.ProductStatus.approved
    ).all()

    xml_parts = ['<?xml version="1.0" encoding="UTF-8"?>', '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">']

    for url in urls:
        xml_parts.append(f"<url><loc>{url}</loc><changefreq>daily</changefreq></url>")

    for product_id, updated_at in approved_products:
        loc = f"{SITE_URL}/product/{product_id}"
        lastmod = updated_at.strftime("%Y-%m-%d") if updated_at else ""
        xml_parts.append(f"<url><loc>{loc}</loc><lastmod>{lastmod}</lastmod><changefreq>weekly</changefreq></url>")

    xml_parts.append("</urlset>")
    xml = "".join(xml_parts)

    return Response(content=xml, media_type="application/xml")

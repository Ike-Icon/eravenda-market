# pyright: reportMissingImports=false
"""
Bulk Excel product import.

Endpoints
---------
GET  /api/import/template
    Returns a pre-filled .xlsx template sellers can fill in.

POST /api/products/import               (seller — uses own store)
POST /api/admin/import/products         (admin  — requires ?store_id=<uuid>)

Both POST endpoints accept a multipart file upload (.xlsx or .xls) and
return a structured report:

  {
    "total_rows": 50,
    "imported":   48,
    "skipped":     2,
    "errors": [
      {"row": 5,  "reason": "Missing required field: price"},
      {"row": 23, "reason": "Category not found"}
    ]
  }

Products are always created with status=pending so they go through
the normal admin review flow.
"""

import io
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from .. import models, auth
from ..database import get_db
from ..utils import slugify, random_suffix

# ---------------------------------------------------------------------------
# Column definitions
# ---------------------------------------------------------------------------

TEMPLATE_COLUMNS = [
    "name",
    "category_id",
    "price",
    "stock_quantity",
    "description",
    "brand",
    "condition",
    "sku",
    "discount_price",
    "specifications",
    "colors",
    "image_url_1",
    "image_url_2",
    "image_url_3",
]

COLUMN_NOTES = {
    "name":           "REQUIRED — Product name (max 200 chars)",
    "category_id":    "REQUIRED — UUID of the category (copy from admin panel)",
    "price":          "REQUIRED — Selling price, e.g. 49.99",
    "stock_quantity": "REQUIRED — Integer quantity in stock",
    "description":    "Optional — Full product description",
    "brand":          "Optional — Brand / manufacturer",
    "condition":      "Optional — new | refurbished | used  (default: new)",
    "sku":            "Optional — Stock-keeping unit / model number",
    "discount_price": "Optional — Sale price (must be less than price)",
    "specifications": "Optional — Pipe-separated, e.g. Color: Red|Size: XL",
    "colors":         "Optional — Pipe-separated color names, e.g. Red|Blue|Green",
    "image_url_1":    "Optional — Primary image URL",
    "image_url_2":    "Optional — Additional image URL",
    "image_url_3":    "Optional — Additional image URL",
}

VALID_CONDITIONS = {"new", "refurbished", "used"}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _build_template_xlsx() -> bytes:
    """Return the bytes of a template .xlsx file."""
    try:
        import openpyxl
        from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
        from openpyxl.utils import get_column_letter
    except ImportError:
        raise HTTPException(
            status_code=500,
            detail="openpyxl is not installed on the server. Run: pip install openpyxl",
        )

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Products"

    header_font = Font(bold=True, color="FFFFFF", size=11)
    header_fill = PatternFill("solid", fgColor="2563EB")
    note_fill   = PatternFill("solid", fgColor="EFF6FF")
    note_font   = Font(italic=True, color="6B7280", size=9)
    thin_side   = Side(style="thin", color="CBD5E1")
    thin_border = Border(left=thin_side, right=thin_side, bottom=thin_side, top=thin_side)

    # Row 1 — headers
    for col_idx, col_name in enumerate(TEMPLATE_COLUMNS, start=1):
        cell = ws.cell(row=1, column=col_idx, value=col_name)
        cell.font      = header_font
        cell.fill      = header_fill
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        cell.border    = thin_border

    # Row 2 — human-readable notes
    for col_idx, col_name in enumerate(TEMPLATE_COLUMNS, start=1):
        cell = ws.cell(row=2, column=col_idx, value=COLUMN_NOTES.get(col_name, ""))
        cell.font      = note_font
        cell.fill      = note_fill
        cell.alignment = Alignment(wrap_text=True)
        cell.border    = thin_border

    # Row 3 — example row
    example = {
        "name":           "Sample Product Name",
        "category_id":    "paste-category-uuid-here",
        "price":          "29.99",
        "stock_quantity": "100",
        "description":    "A short product description goes here.",
        "brand":          "BrandName",
        "condition":      "new",
        "sku":            "SKU-001",
        "discount_price": "24.99",
        "specifications": "Material: Cotton|Size: M|Weight: 250g",
        "colors":         "Red|Blue|Green",
        "image_url_1":    "https://example.com/image1.jpg",
        "image_url_2":    "https://example.com/image2.jpg",
        "image_url_3":    "",
    }
    for col_idx, col_name in enumerate(TEMPLATE_COLUMNS, start=1):
        cell = ws.cell(row=3, column=col_idx, value=example.get(col_name, ""))
        cell.alignment = Alignment(wrap_text=True)
        cell.border    = thin_border

    widths = {
        "name": 30, "category_id": 38, "price": 12, "stock_quantity": 14,
        "description": 40, "brand": 18, "condition": 14, "sku": 16,
        "discount_price": 14, "specifications": 35, "colors": 22,
        "image_url_1": 40, "image_url_2": 40, "image_url_3": 40,
    }
    for col_idx, col_name in enumerate(TEMPLATE_COLUMNS, start=1):
        ws.column_dimensions[get_column_letter(col_idx)].width = widths.get(col_name, 20)

    ws.row_dimensions[1].height = 22
    ws.row_dimensions[2].height = 40
    ws.freeze_panes = "A3"

    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return buf.read()


def _load_workbook_rows(file_bytes: bytes, filename: str) -> list:
    """
    Parse an .xlsx or .xls file and return a list of dicts (one per data row).
    Row 1 = header; Row 2 = notes (skipped if it looks like our template notes row).
    """
    fname_lower = filename.lower()

    if fname_lower.endswith(".xlsx"):
        try:
            import openpyxl
        except ImportError:
            raise HTTPException(status_code=500, detail="openpyxl not installed")
        wb = openpyxl.load_workbook(io.BytesIO(file_bytes), data_only=True)
        ws = wb.active
        all_rows = list(ws.iter_rows(values_only=True))

    elif fname_lower.endswith(".xls"):
        try:
            import xlrd
        except ImportError:
            raise HTTPException(status_code=500, detail="xlrd not installed")
        book = xlrd.open_workbook(file_contents=file_bytes)
        sheet = book.sheet_by_index(0)
        all_rows = [
            tuple(sheet.cell_value(r, c) for c in range(sheet.ncols))
            for r in range(sheet.nrows)
        ]
    else:
        raise HTTPException(
            status_code=422,
            detail="Only .xlsx and .xls files are accepted.",
        )

    if not all_rows:
        raise HTTPException(status_code=422, detail="The uploaded file is empty.")

    headers = [str(h).strip().lower() if h is not None else "" for h in all_rows[0]]

    data_rows = []
    for raw in all_rows[1:]:
        row_dict = {
            headers[i]: (str(v).strip() if v is not None else "")
            for i, v in enumerate(raw)
            if i < len(headers)
        }
        # Skip entirely empty rows or the notes row from our template
        if all(v == "" for v in row_dict.values()):
            continue
        first_val = row_dict.get("name", "")
        if "REQUIRED" in first_val or "Optional" in first_val:
            continue
        data_rows.append(row_dict)

    return data_rows


def _unique_slug(base_slug: str, store_id: str, db: Session) -> str:
    slug = base_slug
    while db.query(models.Product).filter(
        models.Product.store_id == store_id,
        models.Product.slug == slug,
    ).first():
        slug = f"{base_slug}-{random_suffix(4)}"
    return slug


def _parse_and_import(rows: list, store: models.Store, db: Session) -> dict:
    """Validate and import rows; returns the import report."""
    imported = 0
    errors   = []
    category_cache: dict = {}

    for idx, row in enumerate(rows, start=2):  # row 2 in Excel = first data row
        row_num = idx

        # --- Required fields ---
        name = row.get("name", "").strip()
        if not name:
            errors.append({"row": row_num, "reason": "Missing required field: name"})
            continue

        category_id = row.get("category_id", "").strip()
        if not category_id:
            errors.append({"row": row_num, "reason": "Missing required field: category_id"})
            continue

        price_raw = row.get("price", "").strip()
        if not price_raw:
            errors.append({"row": row_num, "reason": "Missing required field: price"})
            continue
        try:
            price = float(price_raw)
            if price < 0:
                raise ValueError
        except ValueError:
            errors.append({"row": row_num, "reason": f"Invalid price value: '{price_raw}'"})
            continue

        stock_raw = row.get("stock_quantity", "").strip()
        if not stock_raw:
            errors.append({"row": row_num, "reason": "Missing required field: stock_quantity"})
            continue
        try:
            stock_quantity = int(float(stock_raw))
            if stock_quantity < 0:
                raise ValueError
        except ValueError:
            errors.append({"row": row_num, "reason": f"Invalid stock_quantity value: '{stock_raw}'"})
            continue

        # --- Validate category ---
        if category_id not in category_cache:
            cat = db.query(models.Category).filter(models.Category.id == category_id).first()
            if not cat:
                errors.append({"row": row_num, "reason": f"Category not found: {category_id}"})
                continue
            category_cache[category_id] = cat

        # --- Optional fields ---
        description = row.get("description", "").strip() or None
        brand       = row.get("brand", "").strip() or None
        sku         = row.get("sku", "").strip() or None

        condition_raw = row.get("condition", "new").strip().lower() or "new"
        if condition_raw not in VALID_CONDITIONS:
            errors.append({"row": row_num, "reason": f"Invalid condition '{condition_raw}'. Must be: new, refurbished, or used"})
            continue
        condition = models.ProductCondition(condition_raw)

        discount_price = None
        discount_raw = row.get("discount_price", "").strip()
        if discount_raw:
            try:
                discount_price = float(discount_raw)
                if discount_price <= 0 or discount_price >= price:
                    errors.append({"row": row_num, "reason": "discount_price must be positive and less than price"})
                    continue
            except ValueError:
                errors.append({"row": row_num, "reason": f"Invalid discount_price value: '{discount_raw}'"})
                continue

        # specifications — pipe-separated → list of strings
        specifications = None
        specs_raw = row.get("specifications", "").strip()
        if specs_raw:
            specifications = [s.strip() for s in specs_raw.split("|") if s.strip()]

        # colors — pipe-separated → list of {"name": ..., "hex": ""}
        colors = None
        colors_raw = row.get("colors", "").strip()
        if colors_raw:
            colors = [{"name": c.strip(), "hex": ""} for c in colors_raw.split("|") if c.strip()]

        # Image URLs — optional; up to 3
        image_urls = []
        for key in ("image_url_1", "image_url_2", "image_url_3"):
            url = row.get(key, "").strip()
            if url:
                image_urls.append(url)

        # --- Slug ---
        slug = _unique_slug(slugify(name), store.id, db)

        # --- Insert product ---
        product = models.Product(
            store_id       = store.id,
            category_id    = category_id,
            name           = name,
            slug           = slug,
            description    = description,
            brand          = brand,
            condition      = condition,
            sku            = sku,
            price          = price,
            discount_price = discount_price,
            stock_quantity = stock_quantity,
            specifications = specifications,
            colors         = colors,
            status         = models.ProductStatus.pending,
        )
        db.add(product)
        db.flush()  # get product.id without full commit

        for i, url in enumerate(image_urls):
            db.add(models.ProductImage(
                product_id = product.id,
                image_url  = url,
                is_primary = (i == 0),
                sort_order = i,
            ))

        imported += 1

    if imported:
        db.commit()

    return {
        "total_rows": len(rows),
        "imported":   imported,
        "skipped":    len(rows) - imported,
        "errors":     errors,
    }


# ---------------------------------------------------------------------------
# Routers
# ---------------------------------------------------------------------------

# Template download — no auth required
template_router = APIRouter(prefix="/import", tags=["import"])

# Seller self-import — must be a seller with an approved store
seller_import_router = APIRouter(prefix="/products", tags=["import"])

# Admin import on behalf of any store
admin_import_router = APIRouter(prefix="/admin/import", tags=["import"])


@template_router.get(
    "/template",
    summary="Download the product import Excel template",
    response_class=StreamingResponse,
)
def download_template():
    """Returns a formatted .xlsx template that sellers fill in and upload."""
    xlsx_bytes = _build_template_xlsx()
    return StreamingResponse(
        io.BytesIO(xlsx_bytes),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": "attachment; filename=eravenda_product_import_template.xlsx"},
    )


@seller_import_router.post(
    "/import",
    summary="Bulk-import products from an Excel file (seller)",
)
def seller_import_products(
    file: UploadFile = File(..., description="Excel file (.xlsx or .xls)"),
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.require_role(models.UserRole.seller)),
):
    """
    Upload an Excel file to bulk-create products in the seller's own store.
    Products are created with **pending** status and go through normal approval.
    """
    if not current_user.store:
        raise HTTPException(status_code=400, detail="You need a store before you can import products")
    store = current_user.store
    if store.status != models.StoreStatus.approved:
        raise HTTPException(status_code=403, detail="Your store must be approved before you can import products")

    file_bytes = file.file.read()
    rows = _load_workbook_rows(file_bytes, file.filename or "upload.xlsx")
    return _parse_and_import(rows, store, db)


@admin_import_router.post(
    "/products",
    summary="Bulk-import products from an Excel file (admin)",
)
def admin_import_products(
    store_id: str = Query(..., description="UUID of the target store"),
    file: UploadFile = File(..., description="Excel file (.xlsx or .xls)"),
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.require_role(models.UserRole.admin)),
):
    """
    Admin-only. Upload an Excel file to bulk-create products for any approved store.
    Products start with **pending** status.
    """
    store = db.query(models.Store).filter(models.Store.id == store_id).first()
    if not store:
        raise HTTPException(status_code=404, detail="Store not found")
    if store.status != models.StoreStatus.approved:
        raise HTTPException(status_code=403, detail="Target store is not approved")

    file_bytes = file.file.read()
    rows = _load_workbook_rows(file_bytes, file.filename or "upload.xlsx")
    return _parse_and_import(rows, store, db)

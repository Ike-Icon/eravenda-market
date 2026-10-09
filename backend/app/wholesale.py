"""Wholesale rules in one place.

A product is either "retail" (the original behaviour) or "wholesale". A
wholesale product has a seller-chosen minimum quantity (wholesale_min_quantity)
that a buyer's order must reach before checkout can proceed. The minimum is
counted per product across all of its cart lines (colour/size/option variants),
so 6 black + 6 white shoes meets a minimum of 10.

Everything here reads the values from the database product, never from the
request, so a manipulated request can't change the price or the minimum.
"""

from collections import OrderedDict

from fastapi import HTTPException  # type: ignore[reportMissingImports]

RETAIL = "retail"
WHOLESALE = "wholesale"
SALES_TYPES = (RETAIL, WHOLESALE)

# A minimum of 1 would make "wholesale" meaningless, and the ceiling only
# guards against typos like 1000000.
MIN_QUANTITY_FLOOR = 2
MIN_QUANTITY_CEILING = 100000


def normalize_sales_type(value) -> str:
    text = str(value or RETAIL).strip().lower()
    if text not in SALES_TYPES:
        raise HTTPException(status_code=400, detail="Sales type must be either retail or wholesale.")
    return text


def apply_sales_type_rules(product) -> None:
    """Call after a create/update has been applied to `product`, before commit.

    Wholesale needs a valid minimum quantity; retail never keeps one, so
    switching a product back to retail can't leave a stale requirement behind.
    """
    product.sales_type = normalize_sales_type(product.sales_type)
    if product.sales_type == WHOLESALE:
        minimum = product.wholesale_min_quantity
        if minimum is None:
            raise HTTPException(status_code=400, detail="Minimum wholesale quantity is required for wholesale products.")
        try:
            minimum = int(minimum)
        except (TypeError, ValueError):
            raise HTTPException(status_code=400, detail="Minimum wholesale quantity must be a whole number.")
        if minimum < MIN_QUANTITY_FLOOR or minimum > MIN_QUANTITY_CEILING:
            raise HTTPException(
                status_code=400,
                detail=f"Minimum wholesale quantity must be between {MIN_QUANTITY_FLOOR} and {MIN_QUANTITY_CEILING:,}.",
            )
        product.wholesale_min_quantity = minimum
    else:
        product.wholesale_min_quantity = None


def minimum_message(product_name: str, minimum: int, current: int) -> str:
    return (
        f"{product_name} requires a minimum wholesale quantity of {minimum}. "
        f"Current quantity: {current}."
    )


def cart_issues(items) -> list[dict]:
    """Problems that must block checkout for a list of cart items.

    One entry per wholesale product (quantities summed across its lines):
    kind "minimum" when below the seller's minimum, "stock" when above the
    stock that is available. Retail items never appear here.
    """
    by_product: "OrderedDict[str, dict]" = OrderedDict()
    for item in items:
        product = item.product
        if not product or not product.is_wholesale:
            continue
        row = by_product.setdefault(product.id, {"product": product, "quantity": 0})
        row["quantity"] += int(item.quantity or 0)

    issues: list[dict] = []
    for product_id, row in by_product.items():
        product = row["product"]
        quantity = row["quantity"]
        minimum = int(product.wholesale_min_quantity or MIN_QUANTITY_FLOOR)
        stock = max(0, int(product.stock_quantity or 0))
        if quantity < minimum:
            issues.append({
                "product_id": product_id,
                "product_name": product.name,
                "kind": "minimum",
                "minimum_quantity": minimum,
                "current_quantity": quantity,
                "available_stock": stock,
                "message": minimum_message(product.name, minimum, quantity),
            })
        elif quantity > stock:
            issues.append({
                "product_id": product_id,
                "product_name": product.name,
                "kind": "stock",
                "minimum_quantity": minimum,
                "current_quantity": quantity,
                "available_stock": stock,
                "message": f"{product.name} has only {stock} in stock. Current quantity: {quantity}.",
            })
    return issues


def assert_cart_ok(items) -> None:
    """Raise a 400 listing every wholesale problem in the cart."""
    issues = cart_issues(items)
    if not issues:
        return
    detail = " ".join(issue["message"] for issue in issues)
    if any(issue["kind"] == "minimum" for issue in issues):
        detail += " Please increase your quantity before continuing."
    raise HTTPException(status_code=400, detail=detail)

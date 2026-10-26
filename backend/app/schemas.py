from datetime import datetime
from typing import Optional, List, Any, Literal
import re
from pydantic import BaseModel, EmailStr, Field, ConfigDict, field_validator  # pyright: ignore[reportMissingImports]
import os
from urllib.parse import urlparse

import bleach  # type: ignore[reportMissingImports]

from .models import UserRole, StoreStatus, ProductStatus, OrderStatus, PayoutStatus, ProductCondition, PaymentStatus, PaymentMethod, ServiceStatus, ServiceBookingStatus, DeliveryStatus

# bcrypt only reads the first 72 bytes of a password and (in older versions)
# ignores the rest silently, so longer passwords are refused up front.
MAX_PASSWORD_BYTES = 72
_HEX_COLOR = re.compile(r"^#?[0-9A-F]{3,8}$")


def _check_password(value: str) -> str:
    if len(value.encode("utf-8")) > MAX_PASSWORD_BYTES:
        raise ValueError("Password is too long (72 bytes at most)")
    if not value.strip():
        raise ValueError("Password can't be blank")
    return value


def clean_public_url(value: Optional[str], max_len: int = 2000) -> Optional[str]:
    """Image or link URLs must be plain https. This rejects javascript:, data:,
    http:, protocol-relative links, and anything with spaces, quotes or angle
    brackets that could break out of an HTML attribute."""
    if value is None:
        return None
    value = value.strip()
    if not value:
        return None
    parsed = urlparse(value)
    if (
        len(value) > max_len
        or parsed.scheme != "https"
        or not parsed.netloc
        or re.search(r"[\s\"'<>`\\]", value)
    ):
        raise ValueError("Use a full https:// link")
    return value


def clean_site_asset(value: Optional[str], max_len: int = 2000) -> Optional[str]:
    """Like clean_public_url, but a path under /static/ is also fine (category icons)."""
    if value is None:
        return None
    stripped = value.strip()
    if stripped.startswith("/static/") and not re.search(r"[\s\"'<>`\\]|\.\.", stripped) and len(stripped) <= max_len:
        return stripped
    return clean_public_url(value, max_len)


AVATAR_KEYS = {"Avery", "Bailey", "Charlie", "Dakota", "Emery", "Finley", "Harper", "Jordan"}


def clean_avatar_url(value: Optional[str]) -> Optional[str]:
    """Accept only an image from OUR Cloudinary account (the browser uploads the
    cropped photo there, then sends the URL). Anything else - another host, a
    plain http link, a javascript: URL, an oversized string - is rejected, so a
    profile can never point at an arbitrary third-party URL. None / empty clears
    the photo and falls back to the preset avatar."""
    if value is None:
        return None
    value = value.strip()
    if not value:
        return None
    cloud = os.getenv("CLOUDINARY_CLOUD_NAME") or "ni2pcrua"
    parsed = urlparse(value)
    if (
        len(value) > 500
        or parsed.scheme != "https"
        or parsed.netloc != "res.cloudinary.com"
        or not parsed.path.startswith(f"/{cloud}/image/upload/")
    ):
        raise ValueError("That profile photo could not be used. Please upload it again.")
    return value


# ---------- USERS ----------

class UserCreate(BaseModel):
    full_name: str = Field(min_length=1, max_length=120)
    email: EmailStr
    phone: Optional[str] = Field(default=None, max_length=30)
    password: str = Field(min_length=8, max_length=128)
    avatar_key: str = "Avery"
    region: Optional[str] = Field(default=None, max_length=100)
    city: Optional[str] = Field(default=None, max_length=100)
    sub_town: Optional[str] = Field(default=None, max_length=100)

    @field_validator("full_name")
    @classmethod
    def _name_not_blank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Name can't be blank")
        return value

    @field_validator("password")
    @classmethod
    def _password_ok(cls, value: str) -> str:
        return _check_password(value)

    @field_validator("avatar_key")
    @classmethod
    def avatar_must_be_curated(cls, value: str) -> str:
        if value not in AVATAR_KEYS:
            raise ValueError("Choose an avatar from the available options")
        return value


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    full_name: str
    email: EmailStr
    phone: Optional[str]
    role: UserRole
    is_active: bool
    is_verified: bool = False
    avatar_key: str = "Avery"
    avatar_url: Optional[str] = None
    region: Optional[str] = None
    city: Optional[str] = None
    sub_town: Optional[str] = None
    created_at: datetime
    # There's no "professional" UserRole — a handyman keeps whatever base role
    # they had (almost always "buyer") and is distinguished only by having a
    # HandymanProfile row. Set explicitly in list_users(); defaults to False
    # here only so this field is never silently missing from the response.
    is_professional: bool = False


class UserUpdate(BaseModel):
    full_name: Optional[str] = None
    phone: Optional[str] = None
    avatar_key: Optional[str] = None
    avatar_url: Optional[str] = None

    @field_validator("avatar_key")
    @classmethod
    def avatar_must_be_curated(cls, value: Optional[str]) -> Optional[str]:
        if value is not None and value not in AVATAR_KEYS:
            raise ValueError("Choose an avatar from the available options")
        return value

    @field_validator("avatar_url")
    @classmethod
    def avatar_url_must_be_ours(cls, value: Optional[str]) -> Optional[str]:
        return clean_avatar_url(value)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserOut


class GoogleAuthRequest(BaseModel):
    id_token: str


class AppleAuthRequest(BaseModel):
    identity_token: str
    # Apple only includes the person's name in its response the very first
    # time they authorize the app, never inside the token itself, so the
    # frontend passes it along separately and only on that first sign-in.
    full_name: Optional[str] = None


class ForgotPasswordRequest(BaseModel):
    email: EmailStr


class ResetPasswordRequest(BaseModel):
    token: str = Field(min_length=10, max_length=2000)
    new_password: str = Field(min_length=8, max_length=128)

    @field_validator("new_password")
    @classmethod
    def _password_ok(cls, value: str) -> str:
        return _check_password(value)


class ChangePasswordRequest(BaseModel):
    current_password: str = Field(max_length=128)
    new_password: str = Field(min_length=8, max_length=128)

    @field_validator("new_password")
    @classmethod
    def _password_ok(cls, value: str) -> str:
        return _check_password(value)


class VerifyEmailRequest(BaseModel):
    token: str = Field(min_length=10, max_length=2000)


# ---------- ADDRESSES ----------

class AddressCreate(BaseModel):
    label: Optional[str] = Field(default=None, max_length=60)
    recipient_name: str = Field(min_length=1, max_length=120)
    phone: str = Field(min_length=3, max_length=30)
    region: str = Field(min_length=1, max_length=100)
    city: str = Field(min_length=1, max_length=100)
    area: Optional[str] = Field(default=None, max_length=100)
    sub_town: Optional[str] = Field(default=None, max_length=100)
    landmark: Optional[str] = Field(default=None, max_length=200)
    is_default: bool = False


class AddressOut(AddressCreate):
    model_config = ConfigDict(from_attributes=True)
    id: str


class AddressUpdate(BaseModel):
    label: Optional[str] = Field(default=None, max_length=60)
    recipient_name: Optional[str] = Field(default=None, min_length=1, max_length=120)
    phone: Optional[str] = Field(default=None, min_length=3, max_length=30)
    region: Optional[str] = Field(default=None, min_length=1, max_length=100)
    city: Optional[str] = Field(default=None, min_length=1, max_length=100)
    area: Optional[str] = Field(default=None, max_length=100)
    sub_town: Optional[str] = Field(default=None, max_length=100)
    landmark: Optional[str] = Field(default=None, max_length=200)
    is_default: Optional[bool] = None


# ---------- STORES ----------

class StoreCreate(BaseModel):
    store_name: str = Field(min_length=2, max_length=120)
    description: Optional[str] = Field(default=None, max_length=3000)
    region: Optional[str] = Field(default=None, max_length=100)
    city: Optional[str] = Field(default=None, max_length=100)
    sub_town: Optional[str] = Field(default=None, max_length=100)
    business_registration_number: Optional[str] = Field(default=None, max_length=60)


class StoreUpdate(BaseModel):
    store_name: Optional[str] = Field(default=None, min_length=2, max_length=120)
    description: Optional[str] = Field(default=None, max_length=3000)
    logo_url: Optional[str] = None
    banner_url: Optional[str] = None
    region: Optional[str] = Field(default=None, max_length=100)
    city: Optional[str] = Field(default=None, max_length=100)
    sub_town: Optional[str] = Field(default=None, max_length=100)
    business_registration_number: Optional[str] = Field(default=None, max_length=60)

    @field_validator("logo_url", "banner_url")
    @classmethod
    def _https_only(cls, value):
        return clean_public_url(value)


class StoreOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    store_name: str
    slug: str
    description: Optional[str]
    logo_url: Optional[str]
    banner_url: Optional[str]
    region: Optional[str]
    city: Optional[str]
    sub_town: Optional[str] = None
    status: StoreStatus
    commission_rate: float
    rejection_reason: Optional[str] = None
    created_at: datetime
    follower_count: int = 0
    badge_keys: Optional[List[str]] = None


# A store's followers, as seen by that store's own seller — deliberately not
# the full UserOut (name + email + phone + role + ...): a follower didn't
# hand their contact details to this seller, so only what's needed to show
# "who follows you" (name, avatar, since when) is exposed here.
class StoreFollowerOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    full_name: str
    avatar_key: str = "Avery"
    followed_at: datetime


class StoreFollowOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    store: StoreOut
    created_at: datetime


# ---------- CATEGORIES ----------

class CategoryCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    parent_id: Optional[str] = Field(default=None, max_length=64)
    icon_url: Optional[str] = None

    @field_validator("icon_url")
    @classmethod
    def _safe_icon(cls, value):
        return clean_site_asset(value)


class CategoryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    name: str
    slug: str
    parent_id: Optional[str]
    icon_url: Optional[str]


# ---------- PRODUCTS ----------

class ProductImageOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    image_url: str
    is_primary: bool
    sort_order: int = 0


class ProductImageReorder(BaseModel):
    image_ids: List[str]  # full ordered list of this product's image IDs; position 0 becomes primary


def _normalize_product_colors(value):
    if value is None:
        return None
    normalized = []
    for item in value:
        if isinstance(item, str):
            name = item.strip()[:60]
            if name:
                normalized.append({"name": name, "hex": ""})
        elif isinstance(item, dict):
            name = str(item.get("name", "")).strip()[:60]
            hex_value = str(item.get("hex", "")).strip().upper()[:9]
            if hex_value and not _HEX_COLOR.match(hex_value):
                hex_value = ""
            try:
                stock = max(0, int(item.get("stock", 0)))
            except (TypeError, ValueError):
                stock = 0
            available = bool(item.get("available", stock > 0)) and stock > 0
            if name:
                normalized.append({"name": name, "hex": hex_value, "available": available, "stock": stock})
    return normalized


def _normalize_product_options(value):
    if value is None:
        return None
    normalized = []
    for item in value:
        if not isinstance(item, dict):
            continue
        label = str(item.get("label", "")).strip()[:80]
        if not label:
            continue
        try:
            price = round(float(item.get("price", 0)), 2)
        except (TypeError, ValueError):
            price = 0.0
        discount_price = None
        raw_discount = item.get("discount_price")
        if raw_discount not in (None, ""):
            try:
                candidate = round(float(raw_discount), 2)
                if 0 < candidate < price:
                    discount_price = candidate
            except (TypeError, ValueError):
                discount_price = None
        try:
            stock = max(0, int(item.get("stock", 0)))
        except (TypeError, ValueError):
            stock = 0
        available = bool(item.get("available", stock > 0)) and stock > 0
        normalized.append({
            "label": label, "price": price, "discount_price": discount_price,
            "stock": stock, "available": available,
        })
    return normalized


def _normalize_product_sizes(value):
    """Sizes are a stock-only variant — no own price, unlike options — used
    for shoes, clothing, etc. where every size sells at the product's base
    (or discount) price."""
    if value is None:
        return None
    normalized = []
    for item in value:
        if not isinstance(item, dict):
            continue
        label = str(item.get("label", "")).strip()[:80]
        if not label:
            continue
        try:
            stock = max(0, int(item.get("stock", 0)))
        except (TypeError, ValueError):
            stock = 0
        available = bool(item.get("available", stock > 0)) and stock > 0
        normalized.append({"label": label, "stock": stock, "available": available})
    return normalized


# Sellers can now format the product description with a small toolbar
# (bold/italic/underline/bulleted list) on the add/edit product pages. The
# browser sends that back as HTML, so it's sanitized here — server-side,
# not just in the editor's own JS — to a short allowlist before it's ever
# stored or shown to a buyer. This is the one place every client (the web
# UI today, anything else that calls this API later) has to pass through,
# so it's the only place this really needs enforcing. Deliberately no
# links/images/headings: this is for emphasis within a paragraph, not for
# a seller to embed a link to somewhere off-platform.
_DESCRIPTION_ALLOWED_TAGS = ["b", "strong", "i", "em", "u", "ul", "ol", "li", "br", "p"]


def _sanitize_description_html(value):
    if value is None:
        return None
    cleaned = bleach.clean(value, tags=_DESCRIPTION_ALLOWED_TAGS, attributes={}, strip=True).strip()
    # bleach.clean() only strips disallowed tags — an empty result still
    # collapses to "" here so "no description" stays None, not "<p></p>".
    text_only = bleach.clean(cleaned, tags=[], strip=True).strip()
    return cleaned if text_only else None


class ProductCreate(BaseModel):
    name: str = Field(min_length=2, max_length=200)
    category_id: str = Field(max_length=64)
    description: Optional[str] = Field(default=None, max_length=20000)
    brand: Optional[str] = Field(default=None, max_length=100)
    condition: ProductCondition = ProductCondition.new
    sku: Optional[str] = Field(default=None, max_length=100)
    specifications: Optional[List[str]] = Field(default=None, max_length=50)
    price: float = Field(gt=0, le=100_000_000)
    discount_price: Optional[float] = Field(default=None, ge=0, le=100_000_000)
    stock_quantity: int = Field(default=0, ge=0, le=10_000_000)
    colors: Optional[List[Any]] = Field(default=None, max_length=50)
    options: Optional[List[Any]] = Field(default=None, max_length=50)
    sizes: Optional[List[Any]] = Field(default=None, max_length=100)
    cod_eligible: bool = True
    weight_kg: Optional[float] = Field(default=None, gt=0, le=1000)
    # Wholesale: price above is the per-unit wholesale price. The minimum is
    # required when sales_type is "wholesale" (enforced in wholesale.py).
    sales_type: Literal["retail", "wholesale"] = "retail"
    wholesale_min_quantity: Optional[int] = None

    @field_validator("description")
    @classmethod
    def sanitize_description(cls, value):
        return _sanitize_description_html(value)

    @field_validator("colors")
    @classmethod
    def normalize_colors(cls, value):
        return _normalize_product_colors(value)

    @field_validator("options")
    @classmethod
    def normalize_options(cls, value):
        return _normalize_product_options(value)

    @field_validator("sizes")
    @classmethod
    def normalize_sizes(cls, value):
        return _normalize_product_sizes(value)


class ProductUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=2, max_length=200)
    category_id: Optional[str] = Field(default=None, max_length=64)
    description: Optional[str] = Field(default=None, max_length=20000)
    brand: Optional[str] = Field(default=None, max_length=100)
    condition: Optional[ProductCondition] = None
    sku: Optional[str] = Field(default=None, max_length=100)
    specifications: Optional[List[str]] = Field(default=None, max_length=50)
    price: Optional[float] = Field(default=None, gt=0, le=100_000_000)
    discount_price: Optional[float] = Field(default=None, ge=0, le=100_000_000)
    stock_quantity: Optional[int] = Field(default=None, ge=0, le=10_000_000)
    colors: Optional[List[Any]] = Field(default=None, max_length=50)
    options: Optional[List[Any]] = Field(default=None, max_length=50)
    sizes: Optional[List[Any]] = Field(default=None, max_length=100)
    cod_eligible: Optional[bool] = None
    weight_kg: Optional[float] = Field(default=None, gt=0, le=1000)
    sales_type: Optional[Literal["retail", "wholesale"]] = None
    wholesale_min_quantity: Optional[int] = None

    @field_validator("description")
    @classmethod
    def sanitize_description(cls, value):
        return _sanitize_description_html(value)

    @field_validator("colors")
    @classmethod
    def normalize_colors(cls, value):
        return _normalize_product_colors(value)

    @field_validator("options")
    @classmethod
    def normalize_options(cls, value):
        return _normalize_product_options(value)

    @field_validator("sizes")
    @classmethod
    def normalize_sizes(cls, value):
        return _normalize_product_sizes(value)


class ProductOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    store_id: str
    category_id: str
    name: str
    slug: str
    description: Optional[str]
    brand: Optional[str]
    condition: ProductCondition
    sku: Optional[str] = None
    specifications: Optional[List[str]] = None
    price: float
    discount_price: Optional[float]
    stock_quantity: int
    status: ProductStatus
    rejection_reason: Optional[str] = None
    average_rating: float
    review_count: int
    colors: Optional[List[Any]] = None
    options: Optional[List[Any]] = None
    sizes: Optional[List[Any]] = None
    badge_keys: Optional[List[str]] = None
    cod_eligible: bool = True
    weight_kg: Optional[float] = None
    sales_type: str = "retail"
    wholesale_min_quantity: Optional[int] = None
    wholesale_price: Optional[float] = None
    images: List[ProductImageOut] = []
    created_at: datetime


class ProductListOut(BaseModel):
    total: int
    page: int
    page_size: int
    items: List[ProductOut]


# ---------- CART ----------

class CartItemIn(BaseModel):
    product_id: str = Field(max_length=64)
    quantity: int = Field(gt=0, le=100_000)
    color: Optional[str] = Field(default=None, max_length=80)
    option: Optional[str] = Field(default=None, max_length=80)
    size: Optional[str] = Field(default=None, max_length=80)


class CartItemOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    product: ProductOut
    quantity: int
    color: Optional[str] = None
    option: Optional[str] = None
    size: Optional[str] = None


class WholesaleIssueOut(BaseModel):
    product_id: str
    product_name: str
    kind: str  # "minimum" or "stock"
    minimum_quantity: int
    current_quantity: int
    available_stock: int
    message: str


class CartOut(BaseModel):
    id: str
    items: List[CartItemOut]
    subtotal: float
    # Wholesale products that currently block checkout (below the seller's
    # minimum, or above stock). Empty for a retail-only cart.
    wholesale_issues: List[WholesaleIssueOut] = []


class WishlistOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    product: ProductOut
    created_at: datetime


# ---------- ORDERS ----------

class CheckoutRequest(BaseModel):
    address_id: str
    payment_method: PaymentMethod = PaymentMethod.mobile_money
    is_pickup: bool = False


class OrderItemOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    product_id: str
    product_name: str
    unit_price: float
    quantity: int
    line_total: float
    commission_rate: float = 0
    commission_amount: float = 0
    color: Optional[str] = None
    option: Optional[str] = None
    size: Optional[str] = None
    wholesale_min_quantity: Optional[int] = None
    # Read from OrderItem.image_url — a property, not a column; see its
    # docstring in models.py for why this isn't snapshotted at order time.
    image_url: Optional[str] = None


class OrderOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    order_number: str
    store_id: str
    status: OrderStatus
    subtotal: float
    delivery_fee: float
    is_pickup: bool = False
    order_type: str = "retail"
    total_quantity: int = 0
    # True once a payment has been confirmed; the buyer's order page and the admin ledger use this to show the
    # receipt button. The receipt itself is served by GET /orders/{id}/receipt (and /admin/orders/{id}/receipt).
    receipt_available: bool = False
    receipt_number: Optional[str] = None
    commission_amount: float
    total_amount: float
    payment_method: PaymentMethod
    seller_note: Optional[str] = None
    shipping_carrier: Optional[str] = None
    tracking_number: Optional[str] = None
    estimated_delivery: Optional[datetime] = None
    shipped_at: Optional[datetime] = None
    delivered_at: Optional[datetime] = None
    items: List[OrderItemOut] = []
    delivery_person: Optional["DeliveryPersonOut"] = None
    created_at: datetime


class OrderStatusUpdate(BaseModel):
    status: OrderStatus
    seller_note: Optional[str] = Field(default=None, max_length=2000)
    shipping_carrier: Optional[str] = Field(default=None, max_length=100)
    tracking_number: Optional[str] = Field(default=None, max_length=150)
    estimated_delivery: Optional[datetime] = None


class DeliveryQuoteRequest(BaseModel):
    address_id: str


class DeliveryQuoteOut(BaseModel):
    delivery_fee: float
    store_count: int
    breakdown: List[dict]


class ProductCommissionPolicyOut(BaseModel):
    standard_rate: float
    category_rates: dict[str, float]
    category_rate_cap: float
    subscription: Optional[dict] = None
    promotions: Optional[dict] = None


class DeliveryRegistration(BaseModel):
    company_name: Optional[str] = Field(default=None, max_length=150)
    location: str = Field(min_length=1, max_length=255)
    vehicle_type: str = Field(min_length=1, max_length=80)
    license_number: Optional[str] = Field(default=None, max_length=100)
    availability: str = Field(default="available", max_length=50)
    terms_accepted: bool = False


class DeliveryPersonOut(BaseModel):
    name: str
    company_name: Optional[str] = None
    location: str
    phone: Optional[str] = None
    email: EmailStr
    vehicle_type: str
    license_number: Optional[str] = None
    availability: str
    status: DeliveryStatus
    rejection_reason: Optional[str] = None


class DeliveryProfileOut(DeliveryPersonOut):
    model_config = ConfigDict(from_attributes=True)
    id: str
    user_id: str
    created_at: datetime


class DeliveryAssignmentRequest(BaseModel):
    delivery_person_id: str
    assignment_note: Optional[str] = Field(default=None, max_length=1000)


class DeliveryOrderStatusUpdate(BaseModel):
    status: OrderStatus


class DeliveryOrderOut(BaseModel):
    id: str
    order_number: str
    status: OrderStatus
    buyer_name: str
    buyer_phone: Optional[str] = None
    buyer_email: EmailStr
    delivery_location: Optional[str] = None
    store_name: str
    total_amount: float
    delivery_fee: float
    assignment_note: Optional[str] = None
    assigned_at: datetime
    created_at: datetime
    shipped_at: Optional[datetime] = None
    delivered_at: Optional[datetime] = None


class DeliveryDashboardOut(BaseModel):
    profile: DeliveryProfileOut
    active_orders: List[DeliveryOrderOut]
    completed_orders: List[DeliveryOrderOut]
    total_deliveries: int
    active_delivery_count: int
    amount_received: float


# ---------- SERVICES ----------
class ServicePortfolioCreate(BaseModel):
    image_url: str = Field(min_length=1, max_length=2000)
    caption: Optional[str] = Field(default=None, max_length=200)

    @field_validator("image_url")
    @classmethod
    def _https_image(cls, value):
        cleaned = clean_public_url(value)
        if not cleaned:
            raise ValueError("Image link is required")
        return cleaned


class ServicePortfolioOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    image_url: str
    caption: Optional[str]


class HandymanOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    job_title: str
    custom_job_title: Optional[str]
    professional_name: Optional[str]
    company_name: Optional[str]
    work_experience: Optional[str]
    education: Optional[str]
    qualifications: str
    resume_path: Optional[str] = None
    status: ServiceStatus
    verified_pro: bool
    background_checked: bool
    average_rating: float
    review_count: int
    badge_keys: Optional[List[str]] = None
    safety_rating: float = 0
    portfolio: List[ServicePortfolioOut] = []
    created_at: datetime


class ServiceBookingCreate(BaseModel):
    handyman_id: str
    details: str = Field(min_length=10)
    location: Optional[str] = Field(default=None, max_length=255)
    preferred_contact: Optional[str] = Field(default=None, max_length=20)
    contact_details: Optional[str] = Field(default=None, max_length=150)


class ServiceJobPhotoOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    booking_id: str
    uploaded_by: str
    uploader_role: str
    image_url: str
    caption: Optional[str] = None
    created_at: datetime


class ServiceJobPhotoCreate(BaseModel):
    image_url: str = Field(min_length=1, max_length=2000)
    caption: Optional[str] = Field(default=None, max_length=200)

    @field_validator("image_url")
    @classmethod
    def _https_image(cls, value):
        cleaned = clean_public_url(value)
        if not cleaned:
            raise ValueError("Image link is required")
        return cleaned


class ServiceReviewOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    rating: int
    comment: Optional[str]
    created_at: datetime


class ServiceBookingOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    handyman_id: str
    details: str
    location: Optional[str] = None
    preferred_contact: Optional[str] = None
    contact_details: Optional[str] = None
    quoted_amount: Optional[float]
    escrow_amount: float
    commission_amount: float
    payout_amount: float = 0
    payout_status: PayoutStatus = PayoutStatus.pending
    payout_held: bool = False
    completion_requested_at: Optional[datetime] = None
    paid_at: Optional[datetime] = None
    payout_released_at: Optional[datetime] = None
    status: ServiceBookingStatus
    created_at: datetime
    photos: List[ServiceJobPhotoOut] = []
    review: Optional[ServiceReviewOut] = None


class HandymanBookingOut(BaseModel):
    """A booking as seen from the handyman's own dashboard: client contact
    info plus the dual-sided payment ledger and any review received."""
    model_config = ConfigDict(from_attributes=True)
    id: str
    client_name: str
    client_phone: Optional[str] = None
    details: str
    location: Optional[str] = None
    status: ServiceBookingStatus
    quoted_amount: Optional[float] = None
    escrow_amount: float
    commission_amount: float
    payout_amount: float
    payout_status: PayoutStatus
    payout_held: bool
    paid_at: Optional[datetime] = None
    payout_released_at: Optional[datetime] = None
    created_at: datetime
    photos: List[ServiceJobPhotoOut] = []
    review: Optional[ServiceReviewOut] = None


class AdminServiceBookingOut(BaseModel):
    id: str
    handyman_id: str
    professional_name: Optional[str]
    company_name: Optional[str]
    professional_email: Optional[EmailStr]
    professional_phone: Optional[str]
    client_name: str
    client_email: EmailStr
    client_phone: Optional[str]
    details: str
    location: Optional[str]
    preferred_contact: Optional[str]
    contact_details: Optional[str]
    quoted_amount: Optional[float]
    escrow_amount: float = 0
    commission_amount: float = 0
    payout_amount: float = 0
    payout_status: PayoutStatus = PayoutStatus.pending
    payout_held: bool = False
    payout_note: Optional[str] = None
    paid_at: Optional[datetime] = None
    payout_released_at: Optional[datetime] = None
    photo_count: int = 0
    rating: Optional[int] = None
    review_comment: Optional[str] = None
    status: ServiceBookingStatus
    created_at: datetime


class AdminServiceReviewOut(BaseModel):
    id: str
    booking_id: str
    handyman_id: str
    professional_name: Optional[str]
    client_name: str
    rating: int
    comment: Optional[str]
    created_at: datetime


class ServiceBookingUpdate(BaseModel):
    status: ServiceBookingStatus
    quoted_amount: Optional[float] = Field(default=None, gt=0)
    escrow_amount: Optional[float] = Field(default=None, ge=0)


class ServiceBookingAccept(BaseModel):
    quoted_amount: Optional[float] = Field(default=None, gt=0)


class ServiceCompletionRequest(BaseModel):
    escrow_amount: Optional[float] = Field(default=None, gt=0)
    note: Optional[str] = Field(default=None, max_length=1000)


class ServicePayoutAction(BaseModel):
    action: Literal["release", "hold"]
    note: Optional[str] = Field(default=None, max_length=1000)


class ServiceReviewCreate(BaseModel):
    rating: int = Field(ge=1, le=5)
    comment: Optional[str] = Field(default=None, max_length=1000)


class ServicePaymentInitRequest(BaseModel):
    booking_id: str


class ServicePaymentVerifyOut(BaseModel):
    status: PaymentStatus
    booking_id: str
    booking_status: ServiceBookingStatus
    amount: float
    reference: str


# ---------- REVIEWS ----------

class ReviewCreate(BaseModel):
    product_id: str
    order_item_id: Optional[str] = None
    rating: int = Field(ge=1, le=5)
    comment: Optional[str] = Field(default=None, max_length=3000)


class ReviewOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    product_id: str
    buyer_id: str
    rating: int
    comment: Optional[str]
    created_at: datetime


# ---------- ADMIN / PAYOUTS ----------

class StoreDecision(BaseModel):
    rejection_reason: Optional[str] = None


class PayoutRequest(BaseModel):
    amount: float = Field(gt=0)
    payout_method: str


class PayoutOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    amount: float
    status: PayoutStatus
    payout_method: Optional[str]
    requested_at: datetime


class UserStatusUpdate(BaseModel):
    is_active: bool


class ProductStatusUpdate(BaseModel):
    status: ProductStatus
    rejection_reason: Optional[str] = None


# ---------- PAYMENTS (Paystack) ----------

class PaymentInitRequest(BaseModel):
    order_id: str


class PaymentInitOut(BaseModel):
    authorization_url: str
    access_code: str
    reference: str


class PaymentVerifyOut(BaseModel):
    status: PaymentStatus
    order_id: str
    order_status: OrderStatus
    amount: float
    reference: str


class CODPaymentRecord(BaseModel):
    order_id: str
    amount: float = Field(gt=0)
    reference: Optional[str] = Field(default=None, max_length=150)


# ---------- CONTACT FORM ----------

class NewsletterSubscribeCreate(BaseModel):
    email: EmailStr


# ---------- ADMIN EMAIL CENTER ----------

class BroadcastMessage(BaseModel):
    """The message body shared by preview, test, send and saved templates."""
    audience: Literal["users", "sellers", "professionals", "subscribers", "user"]
    subject: str = Field(min_length=1, max_length=200)
    body: str = Field(min_length=1, max_length=20000)
    button_label: Optional[str] = Field(default=None, max_length=60)
    button_url: Optional[str] = Field(default=None, max_length=500)
    include_pending: bool = False
    # Required when audience is "user": the one account to email.
    user_id: Optional[str] = Field(default=None, max_length=64)

    @field_validator("subject", "body")
    @classmethod
    def _not_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("This can't be empty")
        return v.strip()

    @field_validator("button_label", "button_url")
    @classmethod
    def _blank_to_none(cls, v):
        v = (v or "").strip()
        return v or None


class EmailTemplateSave(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    audience: Literal["users", "sellers", "professionals", "subscribers", "user"]
    subject: str = Field(min_length=1, max_length=200)
    body: str = Field(min_length=1, max_length=20000)
    button_label: Optional[str] = Field(default=None, max_length=60)
    button_url: Optional[str] = Field(default=None, max_length=500)


class ContactMessageCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    email: EmailStr
    subject: Optional[str] = Field(default=None, max_length=200)
    message: str = Field(min_length=5, max_length=5000)

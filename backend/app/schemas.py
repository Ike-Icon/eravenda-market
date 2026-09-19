from datetime import datetime
from typing import Optional, List, Any, Literal
from pydantic import BaseModel, EmailStr, Field, ConfigDict, field_validator  # pyright: ignore[reportMissingImports]

from .models import UserRole, StoreStatus, ProductStatus, OrderStatus, PayoutStatus, ProductCondition, PaymentStatus, PaymentMethod, ServiceStatus, ServiceBookingStatus, DeliveryStatus

AVATAR_KEYS = {"Avery", "Bailey", "Charlie", "Dakota", "Emery", "Finley", "Harper", "Jordan"}


# ---------- USERS ----------

class UserCreate(BaseModel):
    full_name: str
    email: EmailStr
    phone: Optional[str] = None
    password: str = Field(min_length=8)
    avatar_key: str = "Avery"
    region: Optional[str] = None
    city: Optional[str] = None
    sub_town: Optional[str] = None

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
    avatar_key: str = "Avery"
    region: Optional[str] = None
    city: Optional[str] = None
    sub_town: Optional[str] = None
    created_at: datetime


class UserUpdate(BaseModel):
    full_name: Optional[str] = None
    phone: Optional[str] = None
    avatar_key: Optional[str] = None

    @field_validator("avatar_key")
    @classmethod
    def avatar_must_be_curated(cls, value: Optional[str]) -> Optional[str]:
        if value is not None and value not in AVATAR_KEYS:
            raise ValueError("Choose an avatar from the available options")
        return value


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
    token: str
    new_password: str = Field(min_length=8)


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str = Field(min_length=8)


# ---------- ADDRESSES ----------

class AddressCreate(BaseModel):
    label: Optional[str] = None
    recipient_name: str
    phone: str
    region: str
    city: str
    area: Optional[str] = None
    sub_town: Optional[str] = None
    landmark: Optional[str] = None
    is_default: bool = False


class AddressOut(AddressCreate):
    model_config = ConfigDict(from_attributes=True)
    id: str


# ---------- STORES ----------

class StoreCreate(BaseModel):
    store_name: str
    description: Optional[str] = None
    region: Optional[str] = None
    city: Optional[str] = None
    sub_town: Optional[str] = None
    business_registration_number: Optional[str] = None


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


# ---------- CATEGORIES ----------

class CategoryCreate(BaseModel):
    name: str
    parent_id: Optional[str] = None
    icon_url: Optional[str] = None


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


def _normalize_product_colors(value):
    if value is None:
        return None
    normalized = []
    for item in value:
        if isinstance(item, str):
            name = item.strip()
            if name:
                normalized.append({"name": name, "hex": ""})
        elif isinstance(item, dict):
            name = str(item.get("name", "")).strip()
            hex_value = str(item.get("hex", "")).strip().upper()
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
        label = str(item.get("label", "")).strip()
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
        label = str(item.get("label", "")).strip()
        if not label:
            continue
        try:
            stock = max(0, int(item.get("stock", 0)))
        except (TypeError, ValueError):
            stock = 0
        available = bool(item.get("available", stock > 0)) and stock > 0
        normalized.append({"label": label, "stock": stock, "available": available})
    return normalized


class ProductCreate(BaseModel):
    name: str
    category_id: str
    description: Optional[str] = None
    brand: Optional[str] = None
    condition: ProductCondition = ProductCondition.new
    sku: Optional[str] = None
    specifications: Optional[List[str]] = None
    price: float
    discount_price: Optional[float] = None
    stock_quantity: int = 0
    colors: Optional[List[Any]] = None
    options: Optional[List[Any]] = None
    sizes: Optional[List[Any]] = None

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
    name: Optional[str] = None
    category_id: Optional[str] = None
    description: Optional[str] = None
    brand: Optional[str] = None
    condition: Optional[ProductCondition] = None
    sku: Optional[str] = None
    specifications: Optional[List[str]] = None
    price: Optional[float] = None
    discount_price: Optional[float] = None
    stock_quantity: Optional[int] = None
    colors: Optional[List[Any]] = None
    options: Optional[List[Any]] = None
    sizes: Optional[List[Any]] = None

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
    images: List[ProductImageOut] = []
    created_at: datetime


class ProductListOut(BaseModel):
    total: int
    page: int
    page_size: int
    items: List[ProductOut]


# ---------- CART ----------

class CartItemIn(BaseModel):
    product_id: str
    quantity: int = Field(gt=0)
    color: Optional[str] = None
    option: Optional[str] = None
    size: Optional[str] = None


class CartItemOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    product: ProductOut
    quantity: int
    color: Optional[str] = None
    option: Optional[str] = None
    size: Optional[str] = None


class CartOut(BaseModel):
    id: str
    items: List[CartItemOut]
    subtotal: float


class WishlistOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    product: ProductOut
    created_at: datetime


# ---------- ORDERS ----------

class CheckoutRequest(BaseModel):
    address_id: str
    payment_method: PaymentMethod = PaymentMethod.mobile_money


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


class OrderOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    order_number: str
    store_id: str
    status: OrderStatus
    subtotal: float
    delivery_fee: float
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
    launch_start_date: str
    launch_end_date: str
    launch_vendor_cap: int
    discount: str


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
    comment: Optional[str] = None


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


class ContactMessageCreate(BaseModel):
    name: str
    email: EmailStr
    subject: Optional[str] = None
    message: str = Field(min_length=5)

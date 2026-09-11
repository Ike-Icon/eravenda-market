from datetime import datetime
from typing import Optional, List
from pydantic import BaseModel, EmailStr, Field, ConfigDict, field_validator  # pyright: ignore[reportMissingImports]

from .models import UserRole, StoreStatus, ProductStatus, OrderStatus, PayoutStatus, ProductCondition, PaymentStatus, PaymentMethod, ServiceStatus, ServiceBookingStatus

AVATAR_KEYS = {"Avery", "Bailey", "Charlie", "Dakota", "Emery", "Finley", "Harper", "Jordan"}


# ---------- USERS ----------

class UserCreate(BaseModel):
    full_name: str
    email: EmailStr
    phone: Optional[str] = None
    password: str = Field(min_length=6)
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


class ForgotPasswordRequest(BaseModel):
    email: EmailStr


class ResetPasswordRequest(BaseModel):
    token: str
    new_password: str = Field(min_length=6)


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str = Field(min_length=6)


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


class CartItemOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    product: ProductOut
    quantity: int


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
    items: List[OrderItemOut] = []
    created_at: datetime


class OrderStatusUpdate(BaseModel):
    status: OrderStatus


class DeliveryQuoteRequest(BaseModel):
    address_id: str


class DeliveryQuoteOut(BaseModel):
    delivery_fee: float
    store_count: int
    breakdown: List[dict]


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
    portfolio: List[ServicePortfolioOut] = []
    created_at: datetime


class ServiceBookingCreate(BaseModel):
    handyman_id: str
    details: str = Field(min_length=10)
    location: Optional[str] = Field(default=None, max_length=255)
    preferred_contact: Optional[str] = Field(default=None, max_length=20)
    contact_details: Optional[str] = Field(default=None, max_length=150)


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
    status: ServiceBookingStatus
    created_at: datetime


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


class ServiceReviewCreate(BaseModel):
    rating: int = Field(ge=1, le=5)
    comment: Optional[str] = Field(default=None, max_length=1000)


class ServiceReviewOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    rating: int
    comment: Optional[str]
    created_at: datetime


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

class ContactMessageCreate(BaseModel):
    name: str
    email: EmailStr
    subject: Optional[str] = None
    message: str = Field(min_length=5)

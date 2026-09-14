import uuid
import enum
from datetime import datetime

from sqlalchemy import (  # type: ignore[reportMissingImports]
    Column, String, Text, Boolean, Integer, Numeric, ForeignKey,
    DateTime, Enum, SmallInteger, UniqueConstraint, JSON
)
from sqlalchemy.dialects.postgresql import UUID  # type: ignore[reportMissingImports]
from sqlalchemy.orm import relationship, backref  # type: ignore[reportMissingImports]

from .database import Base


def gen_uuid():
    return str(uuid.uuid4())


class UserRole(str, enum.Enum):
    buyer = "buyer"
    seller = "seller"
    admin = "admin"
    delivery = "delivery"


class StoreStatus(str, enum.Enum):
    pending = "pending"
    approved = "approved"
    rejected = "rejected"
    suspended = "suspended"


class ProductStatus(str, enum.Enum):
    pending = "pending"
    approved = "approved"
    rejected = "rejected"
    out_of_stock = "out_of_stock"


class OrderStatus(str, enum.Enum):
    pending = "pending"
    paid = "paid"
    processing = "processing"
    shipped = "shipped"
    delivered = "delivered"
    cancelled = "cancelled"
    refunded = "refunded"


class PaymentStatus(str, enum.Enum):
    pending = "pending"
    success = "success"
    failed = "failed"
    refunded = "refunded"


class PaymentMethod(str, enum.Enum):
    cash_on_delivery = "cash_on_delivery"
    mobile_money = "mobile_money"


class ServiceStatus(str, enum.Enum):
    pending = "pending"
    approved = "approved"
    rejected = "rejected"
    suspended = "suspended"


class DeliveryStatus(str, enum.Enum):
    pending = "pending"
    approved = "approved"
    rejected = "rejected"
    suspended = "suspended"


class ServiceBookingStatus(str, enum.Enum):
    requested = "requested"
    assigned = "assigned"
    in_progress = "in_progress"
    escrow_funded = "escrow_funded"
    completion_requested = "completion_requested"
    completed = "completed"
    released = "released"
    cancelled = "cancelled"


class PayoutStatus(str, enum.Enum):
    pending = "pending"
    processing = "processing"
    paid = "paid"
    failed = "failed"


class ProductCondition(str, enum.Enum):
    new = "new"
    refurbished = "refurbished"
    used = "used"


class User(Base):
    __tablename__ = "users"

    id = Column(UUID(as_uuid=False), primary_key=True, default=gen_uuid)
    full_name = Column(String(150), nullable=False)
    email = Column(String(150), unique=True, nullable=False, index=True)
    phone = Column(String(20), unique=True, nullable=True)
    password_hash = Column(Text, nullable=False)
    role = Column(Enum(UserRole), nullable=False, default=UserRole.buyer)
    is_active = Column(Boolean, nullable=False, default=True)
    is_verified = Column(Boolean, nullable=False, default=False)
    avatar_key = Column(String(40), nullable=False, default="Avery")
    region = Column(String(100), nullable=True)
    city = Column(String(100), nullable=True)
    sub_town = Column(String(150), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    addresses = relationship("Address", back_populates="user", cascade="all, delete-orphan")
    store = relationship("Store", back_populates="owner", uselist=False, cascade="all, delete-orphan")
    wishlist_items = relationship("Wishlist", back_populates="user", cascade="all, delete-orphan")


class Address(Base):
    __tablename__ = "addresses"

    id = Column(UUID(as_uuid=False), primary_key=True, default=gen_uuid)
    user_id = Column(UUID(as_uuid=False), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    label = Column(String(50))
    recipient_name = Column(String(150), nullable=False)
    phone = Column(String(20), nullable=False)
    region = Column(String(100), nullable=False)
    city = Column(String(100), nullable=False)
    area = Column(String(150))
    sub_town = Column(String(150))
    landmark = Column(String(255))
    is_default = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    user = relationship("User", back_populates="addresses")


class Store(Base):
    __tablename__ = "stores"

    id = Column(UUID(as_uuid=False), primary_key=True, default=gen_uuid)
    owner_id = Column(UUID(as_uuid=False), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    store_name = Column(String(150), nullable=False)
    slug = Column(String(170), unique=True, nullable=False)
    description = Column(Text)
    logo_url = Column(Text)
    banner_url = Column(Text)
    business_registration_number = Column(String(100))
    region = Column(String(100))
    city = Column(String(100))
    sub_town = Column(String(150))
    status = Column(Enum(StoreStatus), nullable=False, default=StoreStatus.pending)
    # Retained for backwards-compatible reads of existing stores. Commission is
    # now calculated from the price tier and snapshotted on each order item.
    commission_rate = Column(Numeric(5, 2), nullable=False, default=0.00)
    rejection_reason = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    owner = relationship("User", back_populates="store")
    products = relationship("Product", back_populates="store", cascade="all, delete-orphan")


class Category(Base):
    __tablename__ = "categories"

    id = Column(UUID(as_uuid=False), primary_key=True, default=gen_uuid)
    name = Column(String(100), nullable=False)
    slug = Column(String(120), unique=True, nullable=False)
    parent_id = Column(UUID(as_uuid=False), ForeignKey("categories.id", ondelete="SET NULL"), nullable=True)
    icon_url = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)

    children = relationship(
        "Category",
        backref=backref("parent", remote_side=[id]),
        order_by="Category.name",
    )


class Product(Base):
    __tablename__ = "products"
    __table_args__ = (UniqueConstraint("store_id", "slug", name="uq_store_slug"),)

    id = Column(UUID(as_uuid=False), primary_key=True, default=gen_uuid)
    store_id = Column(UUID(as_uuid=False), ForeignKey("stores.id", ondelete="CASCADE"), nullable=False)
    category_id = Column(UUID(as_uuid=False), ForeignKey("categories.id"), nullable=False)
    name = Column(String(200), nullable=False)
    slug = Column(String(220), nullable=False)
    description = Column(Text)
    brand = Column(String(100))
    condition = Column(Enum(ProductCondition), nullable=False, default=ProductCondition.new)
    sku = Column(String(80), nullable=True)
    specifications = Column(JSON, nullable=True)  # list of short "spec bullet" strings
    price = Column(Numeric(12, 2), nullable=False)
    discount_price = Column(Numeric(12, 2), nullable=True)
    stock_quantity = Column(Integer, nullable=False, default=0)
    status = Column(Enum(ProductStatus), nullable=False, default=ProductStatus.pending)
    rejection_reason = Column(Text)
    average_rating = Column(Numeric(3, 2), nullable=False, default=0)
    review_count = Column(Integer, nullable=False, default=0)
    colors = Column(JSON, nullable=True)
    badge_keys = Column(JSON, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    store = relationship("Store", back_populates="products")
    category = relationship("Category")
    images = relationship("ProductImage", back_populates="product", cascade="all, delete-orphan")
    wishlisted_by = relationship("Wishlist", back_populates="product", cascade="all, delete-orphan")


class ProductImage(Base):
    __tablename__ = "product_images"

    id = Column(UUID(as_uuid=False), primary_key=True, default=gen_uuid)
    product_id = Column(UUID(as_uuid=False), ForeignKey("products.id", ondelete="CASCADE"), nullable=False)
    image_url = Column(Text, nullable=False)
    is_primary = Column(Boolean, default=False)
    sort_order = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.utcnow)

    product = relationship("Product", back_populates="images")


class Cart(Base):
    __tablename__ = "carts"

    id = Column(UUID(as_uuid=False), primary_key=True, default=gen_uuid)
    user_id = Column(UUID(as_uuid=False), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, unique=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    items = relationship("CartItem", back_populates="cart", cascade="all, delete-orphan")


class CartItem(Base):
    __tablename__ = "cart_items"
    __table_args__ = (UniqueConstraint("cart_id", "product_id", "color", name="uq_cart_product_color"),)

    id = Column(UUID(as_uuid=False), primary_key=True, default=gen_uuid)
    cart_id = Column(UUID(as_uuid=False), ForeignKey("carts.id", ondelete="CASCADE"), nullable=False)
    product_id = Column(UUID(as_uuid=False), ForeignKey("products.id", ondelete="CASCADE"), nullable=False)
    quantity = Column(Integer, nullable=False)
    color = Column(String(60), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    cart = relationship("Cart", back_populates="items")
    product = relationship("Product")


class Wishlist(Base):
    __tablename__ = "wishlists"
    __table_args__ = (UniqueConstraint("user_id", "product_id", name="uq_wishlist_user_product"),)

    id = Column(UUID(as_uuid=False), primary_key=True, default=gen_uuid)
    user_id = Column(UUID(as_uuid=False), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    product_id = Column(UUID(as_uuid=False), ForeignKey("products.id", ondelete="CASCADE"), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    user = relationship("User", back_populates="wishlist_items")
    product = relationship("Product", back_populates="wishlisted_by")


class Order(Base):
    __tablename__ = "orders"

    id = Column(UUID(as_uuid=False), primary_key=True, default=gen_uuid)
    order_number = Column(String(30), unique=True, nullable=False)
    buyer_id = Column(UUID(as_uuid=False), ForeignKey("users.id"), nullable=False)
    store_id = Column(UUID(as_uuid=False), ForeignKey("stores.id"), nullable=False)
    address_id = Column(UUID(as_uuid=False), ForeignKey("addresses.id"), nullable=False)
    status = Column(Enum(OrderStatus), nullable=False, default=OrderStatus.pending)
    subtotal = Column(Numeric(12, 2), nullable=False)
    delivery_fee = Column(Numeric(12, 2), nullable=False, default=0)
    commission_amount = Column(Numeric(12, 2), nullable=False, default=0)
    total_amount = Column(Numeric(12, 2), nullable=False)
    payment_method = Column(Enum(PaymentMethod), nullable=False, default=PaymentMethod.mobile_money)
    seller_note = Column(Text, nullable=True)
    shipping_carrier = Column(String(100), nullable=True)
    tracking_number = Column(String(150), nullable=True)
    estimated_delivery = Column(DateTime, nullable=True)
    shipped_at = Column(DateTime, nullable=True)
    delivered_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    items = relationship("OrderItem", back_populates="order", cascade="all, delete-orphan")
    address = relationship("Address")
    store = relationship("Store")
    delivery_assignment = relationship("OrderDeliveryAssignment", back_populates="order", uselist=False, cascade="all, delete-orphan")

    @property
    def delivery_person(self):
        assignment = self.delivery_assignment
        profile = assignment.delivery_person if assignment else None
        if not profile or not profile.user:
            return None
        return {
            "name": profile.user.full_name,
            "company_name": profile.company_name,
            "location": profile.location,
            "phone": profile.user.phone,
            "email": profile.user.email,
            "vehicle_type": profile.vehicle_type,
            "license_number": profile.license_number,
            "availability": profile.availability,
            "status": profile.status,
        }


class OrderItem(Base):
    __tablename__ = "order_items"

    id = Column(UUID(as_uuid=False), primary_key=True, default=gen_uuid)
    order_id = Column(UUID(as_uuid=False), ForeignKey("orders.id", ondelete="CASCADE"), nullable=False)
    product_id = Column(UUID(as_uuid=False), ForeignKey("products.id"), nullable=False)
    product_name = Column(String(200), nullable=False)
    unit_price = Column(Numeric(12, 2), nullable=False)
    quantity = Column(Integer, nullable=False)
    line_total = Column(Numeric(12, 2), nullable=False)
    commission_rate = Column(Numeric(5, 2), nullable=False, default=0)
    commission_amount = Column(Numeric(12, 2), nullable=False, default=0)
    color = Column(String(60), nullable=True)

    order = relationship("Order", back_populates="items")


class DeliveryProfile(Base):
    __tablename__ = "delivery_profiles"

    id = Column(UUID(as_uuid=False), primary_key=True, default=gen_uuid)
    user_id = Column(UUID(as_uuid=False), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, unique=True)
    company_name = Column(String(150), nullable=True)
    location = Column(String(255), nullable=False)
    vehicle_type = Column(String(80), nullable=False)
    license_number = Column(String(100), nullable=True)
    availability = Column(String(50), nullable=False, default="available")
    status = Column(Enum(DeliveryStatus), nullable=False, default=DeliveryStatus.pending)
    terms_accepted_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    user = relationship("User")
    assignments = relationship("OrderDeliveryAssignment", back_populates="delivery_person")

    @property
    def name(self):
        return self.user.full_name if self.user else ""

    @property
    def email(self):
        return self.user.email if self.user else ""

    @property
    def phone(self):
        return self.user.phone if self.user else None


class OrderDeliveryAssignment(Base):
    __tablename__ = "order_delivery_assignments"

    id = Column(UUID(as_uuid=False), primary_key=True, default=gen_uuid)
    order_id = Column(UUID(as_uuid=False), ForeignKey("orders.id", ondelete="CASCADE"), nullable=False, unique=True)
    delivery_person_id = Column(UUID(as_uuid=False), ForeignKey("delivery_profiles.id"), nullable=False)
    assigned_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    assignment_note = Column(Text, nullable=True)

    order = relationship("Order", back_populates="delivery_assignment")
    delivery_person = relationship("DeliveryProfile", back_populates="assignments")


class Payment(Base):
    __tablename__ = "payments"

    id = Column(UUID(as_uuid=False), primary_key=True, default=gen_uuid)
    order_id = Column(UUID(as_uuid=False), ForeignKey("orders.id", ondelete="CASCADE"), nullable=False)
    provider = Column(String(30), nullable=False)
    provider_reference = Column(String(150), unique=True, nullable=False)
    amount = Column(Numeric(12, 2), nullable=False)
    currency = Column(String(10), nullable=False, default="GHS")
    status = Column(Enum(PaymentStatus), nullable=False, default=PaymentStatus.pending)
    paid_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class Review(Base):
    __tablename__ = "reviews"
    __table_args__ = (UniqueConstraint("buyer_id", "order_item_id", name="uq_buyer_orderitem_review"),)

    id = Column(UUID(as_uuid=False), primary_key=True, default=gen_uuid)
    product_id = Column(UUID(as_uuid=False), ForeignKey("products.id", ondelete="CASCADE"), nullable=False)
    buyer_id = Column(UUID(as_uuid=False), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    order_item_id = Column(UUID(as_uuid=False), ForeignKey("order_items.id"), nullable=True)
    rating = Column(SmallInteger, nullable=False)
    comment = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)


class Payout(Base):
    __tablename__ = "payouts"

    id = Column(UUID(as_uuid=False), primary_key=True, default=gen_uuid)
    store_id = Column(UUID(as_uuid=False), ForeignKey("stores.id", ondelete="CASCADE"), nullable=False)
    amount = Column(Numeric(12, 2), nullable=False)
    status = Column(Enum(PayoutStatus), nullable=False, default=PayoutStatus.pending)
    payout_method = Column(String(30))
    payout_reference = Column(String(150))
    requested_at = Column(DateTime, default=datetime.utcnow)
    processed_at = Column(DateTime, nullable=True)


class ContactMessage(Base):
    """Submissions from the public Contact Us form. No admin UI reads these
    yet — they're stored so the form is genuinely functional rather than a
    dead end. Query them directly (or build a viewer later) as needed."""
    __tablename__ = "contact_messages"

    id = Column(UUID(as_uuid=False), primary_key=True, default=gen_uuid)
    name = Column(String(150), nullable=False)
    email = Column(String(150), nullable=False)
    subject = Column(String(200), nullable=True)
    message = Column(Text, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)


class HandymanProfile(Base):
    __tablename__ = "handyman_profiles"
    id = Column(UUID(as_uuid=False), primary_key=True, default=gen_uuid)
    user_id = Column(UUID(as_uuid=False), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, unique=True)
    job_title = Column(String(100), nullable=False)
    custom_job_title = Column(String(100))
    professional_name = Column(String(150))
    company_name = Column(String(150))
    work_experience = Column(Text)
    education = Column(Text)
    qualifications = Column(Text, nullable=False)
    resume_path = Column(Text)
    status = Column(Enum(ServiceStatus), nullable=False, default=ServiceStatus.pending)
    verified_pro = Column(Boolean, nullable=False, default=False)
    background_checked = Column(Boolean, nullable=False, default=False)
    average_rating = Column(Numeric(3, 2), nullable=False, default=0)
    review_count = Column(Integer, nullable=False, default=0)
    badge_keys = Column(JSON, nullable=True)
    safety_rating = Column(Numeric(3, 2), nullable=False, default=0)
    terms_accepted_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    created_at = Column(DateTime, default=datetime.utcnow)
    user = relationship("User")
    portfolio = relationship("ServicePortfolio", back_populates="profile", cascade="all, delete-orphan")


class ServicePortfolio(Base):
    __tablename__ = "service_portfolio"
    id = Column(UUID(as_uuid=False), primary_key=True, default=gen_uuid)
    handyman_id = Column(UUID(as_uuid=False), ForeignKey("handyman_profiles.id", ondelete="CASCADE"), nullable=False)
    image_url = Column(Text, nullable=False)
    caption = Column(String(200))
    profile = relationship("HandymanProfile", back_populates="portfolio")


class ServiceBooking(Base):
    __tablename__ = "service_bookings"
    id = Column(UUID(as_uuid=False), primary_key=True, default=gen_uuid)
    client_id = Column(UUID(as_uuid=False), ForeignKey("users.id"), nullable=False)
    handyman_id = Column(UUID(as_uuid=False), ForeignKey("handyman_profiles.id"), nullable=False)
    details = Column(Text, nullable=False)
    location = Column(String(255), nullable=True)
    preferred_contact = Column(String(20), nullable=True)
    contact_details = Column(String(150), nullable=True)
    quoted_amount = Column(Numeric(12, 2), nullable=True)
    escrow_amount = Column(Numeric(12, 2), nullable=False, default=0)
    commission_amount = Column(Numeric(12, 2), nullable=False, default=0)
    status = Column(Enum(ServiceBookingStatus), nullable=False, default=ServiceBookingStatus.requested)
    created_at = Column(DateTime, default=datetime.utcnow)

    # --- Dual-sided payment ledger & completion workflow ---
    # payout_amount: net amount owed to the handyman after commission.
    payout_amount = Column(Numeric(12, 2), nullable=False, default=0)
    payout_status = Column(Enum(PayoutStatus), nullable=False, default=PayoutStatus.pending)
    payout_held = Column(Boolean, nullable=False, default=False)
    payout_note = Column(Text, nullable=True)
    completion_requested_at = Column(DateTime, nullable=True)
    paid_at = Column(DateTime, nullable=True)
    payout_released_at = Column(DateTime, nullable=True)

    handyman = relationship("HandymanProfile")
    client = relationship("User")
    photos = relationship("ServiceJobPhoto", back_populates="booking", cascade="all, delete-orphan", order_by="ServiceJobPhoto.created_at")
    review = relationship("ServiceReview", uselist=False, cascade="all, delete-orphan")


class ServiceReview(Base):
    __tablename__ = "service_reviews"
    __table_args__ = (UniqueConstraint("booking_id", name="uq_service_review_booking"),)
    id = Column(UUID(as_uuid=False), primary_key=True, default=gen_uuid)
    booking_id = Column(UUID(as_uuid=False), ForeignKey("service_bookings.id", ondelete="CASCADE"), nullable=False)
    handyman_id = Column(UUID(as_uuid=False), ForeignKey("handyman_profiles.id", ondelete="CASCADE"), nullable=False)
    client_id = Column(UUID(as_uuid=False), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    rating = Column(SmallInteger, nullable=False)
    comment = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)


class ServiceJobPhoto(Base):
    """Work-in-progress / completion-verification photos for a service
    booking. Either the handyman or the seeker can upload; uploader_role
    records which side added it so the tracker/admin can tell them apart."""
    __tablename__ = "service_job_photos"
    id = Column(UUID(as_uuid=False), primary_key=True, default=gen_uuid)
    booking_id = Column(UUID(as_uuid=False), ForeignKey("service_bookings.id", ondelete="CASCADE"), nullable=False)
    uploaded_by = Column(UUID(as_uuid=False), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    uploader_role = Column(String(20), nullable=False, default="handyman")  # "handyman" | "seeker"
    image_url = Column(Text, nullable=False)
    caption = Column(String(200), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    booking = relationship("ServiceBooking", back_populates="photos")
    uploader = relationship("User")


class ServicePayment(Base):
    """Mirrors Payment, but for service bookings paid through Paystack
    (kept separate from Payment since bookings aren't product orders)."""
    __tablename__ = "service_payments"

    id = Column(UUID(as_uuid=False), primary_key=True, default=gen_uuid)
    booking_id = Column(UUID(as_uuid=False), ForeignKey("service_bookings.id", ondelete="CASCADE"), nullable=False)
    provider = Column(String(30), nullable=False)
    provider_reference = Column(String(150), unique=True, nullable=False)
    amount = Column(Numeric(12, 2), nullable=False)
    currency = Column(String(10), nullable=False, default="GHS")
    status = Column(Enum(PaymentStatus), nullable=False, default=PaymentStatus.pending)
    paid_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    booking = relationship("ServiceBooking")

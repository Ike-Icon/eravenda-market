import uuid
import enum
import secrets
from datetime import datetime

from sqlalchemy import (  # type: ignore[reportMissingImports]
    Column, String, Text, Boolean, Integer, Numeric, ForeignKey,
    DateTime, Date, Enum, SmallInteger, UniqueConstraint, JSON
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
    password_hash = Column(Text, nullable=True)
    role = Column(Enum(UserRole), nullable=False, default=UserRole.buyer)
    is_active = Column(Boolean, nullable=False, default=True)
    is_verified = Column(Boolean, nullable=False, default=False)
    oauth_provider = Column(String(20), nullable=True)  # "google" | "apple" | None for password accounts
    oauth_sub = Column(String(255), nullable=True)  # stable id from the provider's token, not their email
    avatar_key = Column(String(40), nullable=False, default="Avery")
    region = Column(String(100), nullable=True)
    city = Column(String(100), nullable=True)
    sub_town = Column(String(150), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    addresses = relationship("Address", back_populates="user", cascade="all, delete-orphan")
    store = relationship("Store", back_populates="owner", uselist=False, cascade="all, delete-orphan")
    wishlist_items = relationship("Wishlist", back_populates="user", cascade="all, delete-orphan")
    store_follows = relationship("StoreFollow", back_populates="user", cascade="all, delete-orphan")


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
    # Denormalized from store_follows — see the migration for why (same
    # pattern as Product.review_count below).
    follower_count = Column(Integer, nullable=False, default=0)
    # Admin-applied trust/publicity badges — same BADGE_CATALOG as Product and
    # HandymanProfile's own badge_keys. Shown on the store page and merged
    # into every one of this store's products on top of their own badges.
    badge_keys = Column(JSON, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    owner = relationship("User", back_populates="store")
    products = relationship("Product", back_populates="store", cascade="all, delete-orphan")
    followers = relationship("StoreFollow", back_populates="store", cascade="all, delete-orphan")


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
    options = Column(JSON, nullable=True)  # e.g. [{"label":"250ml","price":53.0,"stock":10,"available":true}]
    sizes = Column(JSON, nullable=True)  # e.g. [{"label":"42","stock":6,"available":true}] — no own price; shares product.price
    badge_keys = Column(JSON, nullable=True)
    cod_eligible = Column(Boolean, nullable=False, default=True)
    # Item weight in kg, set by the seller. Used by the admin-controlled weight
    # surcharge on delivery (delivery_fees.py). Null means "not set", and the
    # default item weight from the admin's delivery settings is assumed.
    weight_kg = Column(Numeric(8, 2), nullable=True)
    # "retail" (default, the original behaviour) or "wholesale". A wholesale
    # product reuses `price` as its per-unit wholesale price, so every existing
    # pricing path (cart, checkout, commission, delivery) keeps working. The
    # seller sets wholesale_min_quantity per product; it is required (and only
    # kept) while sales_type is "wholesale". See wholesale.py.
    sales_type = Column(String(20), nullable=False, default="retail", server_default="retail")
    wholesale_min_quantity = Column(Integer, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    store = relationship("Store", back_populates="products")
    category = relationship("Category")
    images = relationship("ProductImage", back_populates="product", cascade="all, delete-orphan", order_by="ProductImage.sort_order")
    wishlisted_by = relationship("Wishlist", back_populates="product", cascade="all, delete-orphan")

    @property
    def is_wholesale(self) -> bool:
        return (self.sales_type or "retail") == "wholesale"

    @property
    def wholesale_price(self):
        """Read-only convenience for the API: a wholesale product's per-unit
        wholesale price is its normal `price` (no duplicate column to drift)."""
        return self.price if self.is_wholesale else None


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
    __table_args__ = (
        UniqueConstraint("cart_id", "product_id", "color", "option", "size", name="uq_cart_product_color_option_size"),
    )

    id = Column(UUID(as_uuid=False), primary_key=True, default=gen_uuid)
    cart_id = Column(UUID(as_uuid=False), ForeignKey("carts.id", ondelete="CASCADE"), nullable=False)
    product_id = Column(UUID(as_uuid=False), ForeignKey("products.id", ondelete="CASCADE"), nullable=False)
    quantity = Column(Integer, nullable=False)
    color = Column(String(60), nullable=True)
    option = Column(String(80), nullable=True)  # matches an entry in product.options[].label
    size = Column(String(60), nullable=True)  # matches an entry in product.sizes[].label
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


class StoreFollow(Base):
    __tablename__ = "store_follows"
    __table_args__ = (UniqueConstraint("user_id", "store_id", name="uq_store_follow_user_store"),)

    id = Column(UUID(as_uuid=False), primary_key=True, default=gen_uuid)
    user_id = Column(UUID(as_uuid=False), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    store_id = Column(UUID(as_uuid=False), ForeignKey("stores.id", ondelete="CASCADE"), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    user = relationship("User", back_populates="store_follows")
    store = relationship("Store", back_populates="followers")


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
    is_pickup = Column(Boolean, nullable=False, default=False)
    commission_amount = Column(Numeric(12, 2), nullable=False, default=0)
    total_amount = Column(Numeric(12, 2), nullable=False)
    payment_method = Column(Enum(PaymentMethod), nullable=False, default=PaymentMethod.mobile_money)
    # "retail" or "wholesale". Checkout splits a seller's items by sales type,
    # so every order is wholly one or the other.
    order_type = Column(String(20), nullable=False, default="retail", server_default="retail")
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
    # Read-only view of this order's payment attempts (a buyer can retry, so there may be several; only a
    # successful or refunded one makes a receipt). selectin keeps order lists to one extra query, not one per order.
    payments = relationship("Payment", viewonly=True, order_by="Payment.created_at", lazy="selectin")

    @property
    def receipt_payment(self):
        """The payment a receipt is issued for: the latest successful one, otherwise the latest refunded one,
        otherwise None (pending/failed attempts never produce a receipt)."""
        for wanted in (PaymentStatus.success, PaymentStatus.refunded):
            matches = [p for p in (self.payments or []) if p.status == wanted]
            if matches:
                return matches[-1]
        return None

    @property
    def receipt_available(self) -> bool:
        return self.receipt_payment is not None

    @property
    def receipt_number(self) -> str | None:
        return f"RCP-{self.order_number}" if self.receipt_available else None

    @property
    def total_quantity(self) -> int:
        return sum(int(i.quantity or 0) for i in (self.items or []))

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
    option = Column(String(80), nullable=True)
    size = Column(String(60), nullable=True)
    # Snapshot of the product's minimum wholesale quantity when the order was
    # placed (null for retail lines), so the record of the requirement that
    # applied survives the seller changing it later.
    wholesale_min_quantity = Column(Integer, nullable=True)

    order = relationship("Order", back_populates="items")
    # One-directional on purpose — Product doesn't need a back-reference to
    # every order item that's ever referenced it. Deleting a product with
    # existing orders is already blocked at the database level (no ondelete
    # on product_id's FK; see admin.delete_product's IntegrityError handling),
    # so this relationship is safe to rely on: it can never point at a
    # since-deleted product.
    product = relationship("Product")

    @property
    def image_url(self) -> str | None:
        """The product's current primary photo (or its first photo), used to
        show a thumbnail in order tracking and in order-related emails. Not
        snapshotted at order time like product_name/unit_price are — if a
        seller swaps their product photos later, past orders show the new
        one. Accepted trade-off: the alternative (a stored column, backfilled
        for old orders from whatever's live today anyway) adds a migration
        and checkout-time write for a cosmetic field, with no real accuracy
        gain over just reading it live."""
        images = self.product.images if self.product else None
        if not images:
            return None
        primary = next((img for img in images if img.is_primary), None)
        return (primary or images[0]).image_url


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
    rejection_reason = Column(Text, nullable=True)
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


class NewsletterSubscriber(Base):
    """Footer 'Get new-arrival alerts' signup. is_active lets someone
    unsubscribe without deleting their history; unsubscribe_token is the
    one-click link sent in every digest email so no login is required."""
    __tablename__ = "newsletter_subscribers"

    id = Column(UUID(as_uuid=False), primary_key=True, default=gen_uuid)
    email = Column(String(255), nullable=False, unique=True)
    is_active = Column(Boolean, nullable=False, default=True)
    unsubscribe_token = Column(String(64), nullable=False, unique=True, default=lambda: secrets.token_urlsafe(32))
    subscribed_at = Column(DateTime, default=datetime.utcnow)
    last_sent_at = Column(DateTime, nullable=True)


class SiteVisit(Base):
    """One page view, recorded by a tiny beacon in main.js on every public
    page. visitor_id is a random ID the browser makes up and keeps in
    localStorage: no IP address, name or email is stored, so a "visitor" is
    one browser, not one person. The admin dashboard counts distinct
    visitor_ids for visitors and rows for page views."""
    __tablename__ = "site_visits"

    id = Column(UUID(as_uuid=False), primary_key=True, default=gen_uuid)
    visitor_id = Column(String(64), nullable=False, index=True)
    path = Column(String(300), nullable=False)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow, index=True)


class EmailTemplate(Base):
    """A saved admin message (Email center) that can be reloaded and edited."""
    __tablename__ = "email_templates"

    id = Column(UUID(as_uuid=False), primary_key=True, default=gen_uuid)
    name = Column(String(120), nullable=False)
    audience = Column(String(20), nullable=False, default="users")
    subject = Column(String(200), nullable=False)
    body = Column(Text, nullable=False)
    button_label = Column(String(60), nullable=True)
    button_url = Column(String(500), nullable=True)
    created_by = Column(UUID(as_uuid=False), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)


class EmailCampaign(Base):
    """One admin broadcast: who it went to, what it said, and how it ended.
    status: sending | completed | failed | interrupted."""
    __tablename__ = "email_campaigns"

    id = Column(UUID(as_uuid=False), primary_key=True, default=gen_uuid)
    audience = Column(String(20), nullable=False)
    include_pending = Column(Boolean, nullable=False, default=False)
    subject = Column(String(200), nullable=False)
    body = Column(Text, nullable=False)
    button_label = Column(String(60), nullable=True)
    button_url = Column(String(500), nullable=True)
    status = Column(String(20), nullable=False, default="sending")
    recipient_count = Column(Integer, nullable=False, default=0)
    sent_count = Column(Integer, nullable=False, default=0)
    failed_count = Column(Integer, nullable=False, default=0)
    error = Column(String(500), nullable=True)
    # Only set for the "user" (single recipient) audience.
    target_email = Column(String(255), nullable=True)
    sent_by = Column(UUID(as_uuid=False), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow, index=True)
    finished_at = Column(DateTime, nullable=True)


class PlatformSettings(Base):
    """Single-row table (id is always 1) holding every admin-controlled money
    setting: the standard product commission, the seller subscription plan and
    paid promotions. Read through platform_settings.get_settings(); edited from
    the admin dashboard's Monetization tab. Product commission only: handyman
    commission stays in service_pricing.py."""
    __tablename__ = "platform_settings"

    id = Column(Integer, primary_key=True, default=1)
    product_commission_rate = Column(Numeric(5, 2), nullable=False, default=7.00)

    subscription_enabled = Column(Boolean, nullable=False, default=False)
    subscription_monthly_fee = Column(Numeric(12, 2), nullable=False, default=150.00)
    subscription_commission_rate = Column(Numeric(5, 2), nullable=False, default=4.00)

    promotions_enabled = Column(Boolean, nullable=False, default=False)
    # Promotions can't be bought before this date even when enabled (Month 4
    # of a 14 Oct 2026 launch = 14 Jan 2027). Null means "no date gate".
    promotions_open_from = Column(Date, nullable=True)
    promo_product_weekly_price = Column(Numeric(12, 2), nullable=False, default=20.00)
    promo_store_weekly_price = Column(Numeric(12, 2), nullable=False, default=50.00)
    promo_max_weeks = Column(Integer, nullable=False, default=4)
    promo_slots_per_category = Column(Integer, nullable=False, default=3)

    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class DeliveryFeeSettings(Base):
    """Single-row table (id is always 1) holding the delivery fee rules the
    admin edits in the dashboard's "Delivery fees" tab. Read through
    delivery_fees.get_settings(). Fees are saved on each order when it is
    placed, so changing a rule never alters an existing order."""
    __tablename__ = "delivery_fee_settings"

    id = Column(Integer, primary_key=True, default=1)
    # Distance: there are no GPS coordinates, so distance is the relationship
    # between the buyer's address and the seller's store, in five bands.
    base_city = Column(String(100), nullable=False, default="Sunyani")
    fee_same_neighbourhood = Column(Numeric(12, 2), nullable=False, default=8.00)
    fee_base_city_other_area = Column(Numeric(12, 2), nullable=False, default=10.00)
    fee_same_city = Column(Numeric(12, 2), nullable=False, default=18.00)
    fee_same_region = Column(Numeric(12, 2), nullable=False, default=30.00)
    fee_other_region = Column(Numeric(12, 2), nullable=False, default=45.00)
    # Free delivery: a delivery inside the base city (buyer and store both
    # there) is free when that store's order subtotal is above this amount.
    free_delivery_enabled = Column(Boolean, nullable=False, default=True)
    free_delivery_min_order = Column(Numeric(12, 2), nullable=False, default=200.00)
    # Weight: an extra charge per store order, by total weight band. Off until
    # the admin switches it on, so deploying changes no price.
    weight_pricing_enabled = Column(Boolean, nullable=False, default=False)
    default_item_weight_kg = Column(Numeric(8, 2), nullable=False, default=1.00)
    weight_bands = Column(JSON, nullable=True)  # [{"up_to_kg": 5, "surcharge": 0}, ..., {"up_to_kg": null, ...}]
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    updated_by = Column(String(150), nullable=True)


class SellerSubscription(Base):
    """One row per store. A subscription is live while status == 'active' and
    current_period_end is in the future; there is no cron, expiry is just the
    date passing. commission_rate and monthly_fee are snapshots from the
    moment it was bought or renewed, so an admin editing the plan later never
    changes what a seller already paid for."""
    __tablename__ = "seller_subscriptions"

    id = Column(UUID(as_uuid=False), primary_key=True, default=gen_uuid)
    store_id = Column(UUID(as_uuid=False), ForeignKey("stores.id", ondelete="CASCADE"), nullable=False, unique=True)
    status = Column(String(20), nullable=False, default="active")  # active | ended
    monthly_fee = Column(Numeric(12, 2), nullable=False, default=0)
    commission_rate = Column(Numeric(5, 2), nullable=False, default=0)
    started_at = Column(DateTime, default=datetime.utcnow)
    current_period_end = Column(DateTime, nullable=False)
    granted_by_admin = Column(Boolean, nullable=False, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    store = relationship("Store")


class PromotedListing(Base):
    """A paid pin to the top of a category's results. product_id set = pins that
    one product; product_id null = pins the store's products in that category.
    Live while status == 'active' and now is between starts_at and ends_at."""
    __tablename__ = "promoted_listings"

    id = Column(UUID(as_uuid=False), primary_key=True, default=gen_uuid)
    store_id = Column(UUID(as_uuid=False), ForeignKey("stores.id", ondelete="CASCADE"), nullable=False)
    product_id = Column(UUID(as_uuid=False), ForeignKey("products.id", ondelete="CASCADE"), nullable=True)
    category_id = Column(UUID(as_uuid=False), ForeignKey("categories.id", ondelete="CASCADE"), nullable=False)
    weeks = Column(Integer, nullable=False, default=1)
    weekly_price = Column(Numeric(12, 2), nullable=False, default=0)
    total_amount = Column(Numeric(12, 2), nullable=False, default=0)
    status = Column(String(20), nullable=False, default="pending")  # pending | active | cancelled
    starts_at = Column(DateTime, nullable=True)
    ends_at = Column(DateTime, nullable=True)
    granted_by_admin = Column(Boolean, nullable=False, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    store = relationship("Store")
    product = relationship("Product")
    category = relationship("Category")


class StoreCharge(Base):
    """A Paystack payment from a seller to EraVenda for a subscription or a
    promotion (not an order, so it can't live in payments, which requires an
    order_id). quantity = months for a subscription, weeks for a promotion."""
    __tablename__ = "store_charges"

    id = Column(UUID(as_uuid=False), primary_key=True, default=gen_uuid)
    store_id = Column(UUID(as_uuid=False), ForeignKey("stores.id", ondelete="CASCADE"), nullable=False)
    kind = Column(String(20), nullable=False)  # subscription | promotion
    target_id = Column(UUID(as_uuid=False), nullable=True)  # promoted_listings.id for promotions
    quantity = Column(Integer, nullable=False, default=1)
    provider = Column(String(30), nullable=False, default="paystack")
    provider_reference = Column(String(150), unique=True, nullable=False)
    amount = Column(Numeric(12, 2), nullable=False)
    currency = Column(String(10), nullable=False, default="GHS")
    status = Column(Enum(PaymentStatus), nullable=False, default=PaymentStatus.pending)
    paid_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    store = relationship("Store")

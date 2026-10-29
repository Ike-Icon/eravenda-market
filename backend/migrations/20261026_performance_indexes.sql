-- Speed up the queries the site runs most.
--
-- PostgreSQL does not index a foreign key column by itself. Without these, every
-- "orders for this buyer", "images for this product" or "items in this order"
-- lookup reads the whole table, and deleting a row scans every table that
-- points at it. Every statement is IF NOT EXISTS, so this file is safe to run on
-- every start, like the other migrations.

-- Foreign keys that had no index ----------------------------------------------
CREATE INDEX IF NOT EXISTS ix_addresses_user_id             ON addresses (user_id);
CREATE INDEX IF NOT EXISTS ix_cart_items_product_id         ON cart_items (product_id);
CREATE INDEX IF NOT EXISTS ix_categories_parent_id          ON categories (parent_id);
CREATE INDEX IF NOT EXISTS ix_order_items_order_id          ON order_items (order_id);
CREATE INDEX IF NOT EXISTS ix_order_items_product_id        ON order_items (product_id);
CREATE INDEX IF NOT EXISTS ix_order_delivery_assignments_person ON order_delivery_assignments (delivery_person_id);
CREATE INDEX IF NOT EXISTS ix_orders_address_id             ON orders (address_id);
CREATE INDEX IF NOT EXISTS ix_payments_order_id             ON payments (order_id);
CREATE INDEX IF NOT EXISTS ix_payouts_store_id              ON payouts (store_id);
CREATE INDEX IF NOT EXISTS ix_product_images_product_sort   ON product_images (product_id, sort_order);
CREATE INDEX IF NOT EXISTS ix_products_category_id          ON products (category_id);
CREATE INDEX IF NOT EXISTS ix_promoted_listings_category_id ON promoted_listings (category_id);
CREATE INDEX IF NOT EXISTS ix_promoted_listings_product_id  ON promoted_listings (product_id);
CREATE INDEX IF NOT EXISTS ix_promoted_listings_store_id    ON promoted_listings (store_id);
CREATE INDEX IF NOT EXISTS ix_reviews_order_item_id         ON reviews (order_item_id);
CREATE INDEX IF NOT EXISTS ix_service_bookings_client_id    ON service_bookings (client_id);
CREATE INDEX IF NOT EXISTS ix_service_bookings_handyman_id  ON service_bookings (handyman_id);
CREATE INDEX IF NOT EXISTS ix_service_job_photos_booking_id ON service_job_photos (booking_id);
CREATE INDEX IF NOT EXISTS ix_service_job_photos_uploaded_by ON service_job_photos (uploaded_by);
CREATE INDEX IF NOT EXISTS ix_service_payments_booking_id   ON service_payments (booking_id);
CREATE INDEX IF NOT EXISTS ix_service_portfolio_handyman_id ON service_portfolio (handyman_id);
CREATE INDEX IF NOT EXISTS ix_service_reviews_client_id     ON service_reviews (client_id);
CREATE INDEX IF NOT EXISTS ix_service_reviews_handyman_id   ON service_reviews (handyman_id);
CREATE INDEX IF NOT EXISTS ix_store_charges_store_id        ON store_charges (store_id);
CREATE INDEX IF NOT EXISTS ix_stores_owner_id               ON stores (owner_id);
CREATE INDEX IF NOT EXISTS ix_wishlists_product_id          ON wishlists (product_id);
CREATE INDEX IF NOT EXISTS ix_email_campaigns_sent_by       ON email_campaigns (sent_by);
CREATE INDEX IF NOT EXISTS ix_email_templates_created_by    ON email_templates (created_by);

-- Lists that filter and sort ------------------------------------------------
-- Order lists: "my orders", "this store's orders", "orders in this status", newest first.
CREATE INDEX IF NOT EXISTS ix_orders_buyer_created   ON orders (buyer_id, created_at DESC);
CREATE INDEX IF NOT EXISTS ix_orders_store_created   ON orders (store_id, created_at DESC);
CREATE INDEX IF NOT EXISTS ix_orders_status_created  ON orders (status, created_at DESC);
-- Product lists on the home page, /products and the seller's own list.
CREATE INDEX IF NOT EXISTS ix_products_listing       ON products (status, sales_type, created_at DESC);
CREATE INDEX IF NOT EXISTS ix_products_store_status  ON products (store_id, status);
CREATE INDEX IF NOT EXISTS ix_products_top_rated     ON products (average_rating DESC, review_count DESC)
    WHERE status = 'approved' AND review_count > 0;
-- Reviews on a product page, newest first.
CREATE INDEX IF NOT EXISTS ix_reviews_product_created ON reviews (product_id, created_at DESC);
-- Store lists.
CREATE INDEX IF NOT EXISTS ix_stores_status_created  ON stores (status, created_at DESC);

-- Fast "contains" search on product names (the search box) ----------
-- pg_trgm ships with PostgreSQL. If this database user may not enable it, skip
-- quietly: search still works, it just reads the table as before.
DO $$
BEGIN
    CREATE EXTENSION IF NOT EXISTS pg_trgm;
    CREATE INDEX IF NOT EXISTS ix_products_name_trgm ON products USING gin (name gin_trgm_ops);
EXCEPTION WHEN OTHERS THEN
    RAISE NOTICE 'Skipped the product-name search index (pg_trgm is not available to this user)';
END $$;

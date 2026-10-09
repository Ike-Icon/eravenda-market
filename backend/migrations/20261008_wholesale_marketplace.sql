-- Wholesale / Retail marketplace split.
-- Every existing product and order is retail, so the defaults keep the current
-- marketplace behaving exactly as before. All statements are idempotent because
-- app/migrate.py re-runs every migration file on each deploy.

ALTER TABLE products ADD COLUMN IF NOT EXISTS sales_type VARCHAR(20) NOT NULL DEFAULT 'retail';
ALTER TABLE products ADD COLUMN IF NOT EXISTS wholesale_min_quantity INTEGER;

ALTER TABLE orders ADD COLUMN IF NOT EXISTS order_type VARCHAR(20) NOT NULL DEFAULT 'retail';
ALTER TABLE order_items ADD COLUMN IF NOT EXISTS wholesale_min_quantity INTEGER;

CREATE INDEX IF NOT EXISTS ix_products_sales_type ON products (sales_type);
CREATE INDEX IF NOT EXISTS ix_orders_order_type ON orders (order_type);

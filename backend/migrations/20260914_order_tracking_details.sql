-- Optional seller-provided fulfillment details for customer order tracking.
ALTER TABLE orders ADD COLUMN IF NOT EXISTS seller_note TEXT;
ALTER TABLE orders ADD COLUMN IF NOT EXISTS shipping_carrier VARCHAR(100);
ALTER TABLE orders ADD COLUMN IF NOT EXISTS tracking_number VARCHAR(150);
ALTER TABLE orders ADD COLUMN IF NOT EXISTS estimated_delivery TIMESTAMP;
ALTER TABLE orders ADD COLUMN IF NOT EXISTS shipped_at TIMESTAMP;
ALTER TABLE orders ADD COLUMN IF NOT EXISTS delivered_at TIMESTAMP;
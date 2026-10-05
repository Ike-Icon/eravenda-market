-- Free delivery inside the base city for orders above a minimum subtotal.
ALTER TABLE delivery_fee_settings ADD COLUMN IF NOT EXISTS free_delivery_enabled BOOLEAN NOT NULL DEFAULT TRUE;
ALTER TABLE delivery_fee_settings ADD COLUMN IF NOT EXISTS free_delivery_min_order NUMERIC(12,2) NOT NULL DEFAULT 200.00;

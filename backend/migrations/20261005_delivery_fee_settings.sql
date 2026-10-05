-- Admin-editable delivery fees (distance bands + weight bands) and the
-- per-product weight the weight surcharge reads.
ALTER TABLE products ADD COLUMN IF NOT EXISTS weight_kg NUMERIC(8,2);

CREATE TABLE IF NOT EXISTS delivery_fee_settings (
    id INTEGER PRIMARY KEY,
    base_city VARCHAR(100) NOT NULL DEFAULT 'Sunyani',
    fee_same_neighbourhood NUMERIC(12,2) NOT NULL DEFAULT 8.00,
    fee_base_city_other_area NUMERIC(12,2) NOT NULL DEFAULT 10.00,
    fee_same_city NUMERIC(12,2) NOT NULL DEFAULT 18.00,
    fee_same_region NUMERIC(12,2) NOT NULL DEFAULT 30.00,
    fee_other_region NUMERIC(12,2) NOT NULL DEFAULT 45.00,
    weight_pricing_enabled BOOLEAN NOT NULL DEFAULT FALSE,
    default_item_weight_kg NUMERIC(8,2) NOT NULL DEFAULT 1.00,
    weight_bands JSON,
    updated_at TIMESTAMP,
    updated_by VARCHAR(150)
);

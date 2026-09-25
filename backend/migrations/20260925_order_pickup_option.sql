-- Lets a buyer choose in-person pickup at checkout instead of delivery, so
-- they aren't charged a delivery fee when they don't want one. Existing
-- orders default to FALSE (delivery), which matches how every past order
-- was actually fulfilled.

ALTER TABLE orders ADD COLUMN IF NOT EXISTS is_pickup BOOLEAN NOT NULL DEFAULT FALSE;

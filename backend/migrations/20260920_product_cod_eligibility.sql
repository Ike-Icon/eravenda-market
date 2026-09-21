-- Per-product Cash-on-Delivery control. Previously COD was a single checkout-wide
-- payment option available for every product with no way for a seller to opt out
-- (e.g. high-value or easily-disputed items). Existing products default to TRUE so
-- COD keeps working exactly as before for sellers who don't change anything; sellers
-- can now uncheck it per product going forward.

ALTER TABLE products ADD COLUMN IF NOT EXISTS cod_eligible BOOLEAN NOT NULL DEFAULT TRUE;

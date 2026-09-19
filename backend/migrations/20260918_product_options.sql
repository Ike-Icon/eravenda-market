-- Priced product options (e.g. "100ml / 250ml / 500ml" with a different price
-- each). Each product.options entry is:
-- {"label":"250ml","price":53.00,"stock":10,"available":true}
-- Distinct from product.colors, which never carries its own price.

ALTER TABLE products ADD COLUMN IF NOT EXISTS options JSON;

ALTER TABLE cart_items ADD COLUMN IF NOT EXISTS option VARCHAR(80);
ALTER TABLE order_items ADD COLUMN IF NOT EXISTS option VARCHAR(80);

DO $$
BEGIN
  IF EXISTS (
    SELECT 1 FROM pg_constraint
    WHERE conname = 'uq_cart_product_color'
      AND conrelid = 'cart_items'::regclass
  ) THEN
    ALTER TABLE cart_items DROP CONSTRAINT uq_cart_product_color;
  END IF;

  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint
    WHERE conname = 'uq_cart_product_color_option'
      AND conrelid = 'cart_items'::regclass
  ) THEN
    ALTER TABLE cart_items
      ADD CONSTRAINT uq_cart_product_color_option UNIQUE (cart_id, product_id, color, option);
  END IF;
END $$;

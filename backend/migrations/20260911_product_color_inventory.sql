-- Per-color inventory. Each product.colors entry is:
-- {"name":"Ocean Blue","hex":"#1D4ED8","available":true,"stock":12}
-- Existing color records are normalized by the application; legacy products
-- continue to use product.stock_quantity when no color variants are configured.

-- Older databases do not have the cart-item color column yet. Add it before
-- creating the color-aware uniqueness constraint.
ALTER TABLE cart_items
  ADD COLUMN IF NOT EXISTS color VARCHAR(60);

DO $$
BEGIN
  IF EXISTS (
    SELECT 1 FROM pg_constraint
    WHERE conname = 'uq_cart_product'
      AND conrelid = 'cart_items'::regclass
  ) THEN
    ALTER TABLE cart_items DROP CONSTRAINT uq_cart_product;
  END IF;

  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint
    WHERE conname = 'uq_cart_product_color'
      AND conrelid = 'cart_items'::regclass
  ) THEN
    ALTER TABLE cart_items
      ADD CONSTRAINT uq_cart_product_color UNIQUE (cart_id, product_id, color);
  END IF;
END $$;

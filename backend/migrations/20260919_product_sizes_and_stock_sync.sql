-- Shoe/clothing sizes: a stock-only variant dimension (no own price, unlike
-- product.options), plus the seller-form + product-page fixes that make
-- color/size stock actually correspond to the product's main stock_quantity.

ALTER TABLE products ADD COLUMN IF NOT EXISTS sizes JSON;

ALTER TABLE cart_items ADD COLUMN IF NOT EXISTS size VARCHAR(60);
ALTER TABLE order_items ADD COLUMN IF NOT EXISTS size VARCHAR(60);

DO $$
BEGIN
  IF EXISTS (
    SELECT 1 FROM pg_constraint
    WHERE conname = 'uq_cart_product_color_option'
      AND conrelid = 'cart_items'::regclass
  ) THEN
    ALTER TABLE cart_items DROP CONSTRAINT uq_cart_product_color_option;
  END IF;

  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint
    WHERE conname = 'uq_cart_product_color_option_size'
      AND conrelid = 'cart_items'::regclass
  ) THEN
    ALTER TABLE cart_items
      ADD CONSTRAINT uq_cart_product_color_option_size UNIQUE (cart_id, product_id, color, option, size);
  END IF;
END $$;

-- Data repair: existing products whose colors/sizes stock don't add up to
-- stock_quantity (the root cause of permanently-disabled Buy/Add-to-Cart
-- buttons) get corrected once, the same way create/update product now keeps
-- them in sync going forward. Sizes take priority over colors when a product
-- has both, matching the app's variant-priority rule.
UPDATE products
SET stock_quantity = COALESCE((
  SELECT SUM(GREATEST(0, (elem->>'stock')::int))
  FROM json_array_elements(sizes) AS elem
), 0)
WHERE sizes IS NOT NULL AND json_array_length(sizes) > 0;

UPDATE products
SET stock_quantity = COALESCE((
  SELECT SUM(GREATEST(0, (elem->>'stock')::int))
  FROM json_array_elements(colors) AS elem
), 0)
WHERE (sizes IS NULL OR json_array_length(sizes) = 0)
  AND colors IS NOT NULL AND json_array_length(colors) > 0;

UPDATE products
SET stock_quantity = COALESCE((
  SELECT SUM(GREATEST(0, (elem->>'stock')::int))
  FROM json_array_elements(options) AS elem
), 0)
WHERE (sizes IS NULL OR json_array_length(sizes) = 0)
  AND (colors IS NULL OR json_array_length(colors) = 0)
  AND options IS NOT NULL AND json_array_length(options) > 0;

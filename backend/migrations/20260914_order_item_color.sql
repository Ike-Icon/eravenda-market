-- Preserve the selected product color on order line items.
-- Safe for databases created before color selection was added.
ALTER TABLE order_items ADD COLUMN IF NOT EXISTS color VARCHAR(60);

-- Backfill fields introduced after the initial production schema.
-- `create_all` creates tables but never adds columns to tables that already exist.

DO $$
BEGIN
    CREATE TYPE productcondition AS ENUM ('new', 'refurbished', 'used');
EXCEPTION
    WHEN duplicate_object THEN NULL;
END $$;

ALTER TABLE products
    ADD COLUMN IF NOT EXISTS condition productcondition NOT NULL DEFAULT 'new';
ALTER TABLE products ADD COLUMN IF NOT EXISTS sku VARCHAR(80);
ALTER TABLE products ADD COLUMN IF NOT EXISTS specifications JSON;

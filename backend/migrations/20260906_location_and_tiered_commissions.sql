-- PostgreSQL migration for existing Eravenda installations.
-- New databases receive these columns through SQLAlchemy metadata at startup.

ALTER TABLE users ADD COLUMN IF NOT EXISTS region VARCHAR(100);
ALTER TABLE users ADD COLUMN IF NOT EXISTS city VARCHAR(100);
ALTER TABLE users ADD COLUMN IF NOT EXISTS sub_town VARCHAR(150);
ALTER TABLE users ADD COLUMN IF NOT EXISTS avatar_url TEXT;

ALTER TABLE addresses ADD COLUMN IF NOT EXISTS sub_town VARCHAR(150);
ALTER TABLE stores ADD COLUMN IF NOT EXISTS sub_town VARCHAR(150);

ALTER TABLE order_items ADD COLUMN IF NOT EXISTS commission_rate NUMERIC(5, 2) NOT NULL DEFAULT 0;
ALTER TABLE order_items ADD COLUMN IF NOT EXISTS commission_amount NUMERIC(12, 2) NOT NULL DEFAULT 0;

-- Store-level rates are no longer used for new orders; per-item snapshots are.
ALTER TABLE stores ALTER COLUMN commission_rate SET DEFAULT 0;

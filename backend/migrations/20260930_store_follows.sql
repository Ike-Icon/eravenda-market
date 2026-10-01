-- Lets a buyer follow a seller's store, so they can see the stores they
-- follow from their account page and sellers can see who follows them.
-- One row per (user, store); the unique constraint is what makes following
-- twice a no-op instead of a duplicate row.
CREATE TABLE IF NOT EXISTS store_follows (
    id UUID PRIMARY KEY,
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    store_id UUID NOT NULL REFERENCES stores(id) ON DELETE CASCADE,
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_store_follow_user_store UNIQUE (user_id, store_id)
);
CREATE INDEX IF NOT EXISTS ix_store_follows_store_id ON store_follows(store_id);

-- Denormalized count, recomputed from store_follows after every follow/unfollow
-- (same pattern as products.review_count) so the store page and seller
-- dashboard can show it without a COUNT query on every read.
ALTER TABLE stores ADD COLUMN IF NOT EXISTS follower_count INTEGER NOT NULL DEFAULT 0;

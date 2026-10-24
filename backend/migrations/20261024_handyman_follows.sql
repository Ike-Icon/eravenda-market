-- Lets a signed-in user follow a handyman (service professional), the same way
-- they can follow a seller's store. One row per (user, handyman); the unique
-- constraint makes following twice a no-op instead of a duplicate row.
CREATE TABLE IF NOT EXISTS handyman_follows (
    id UUID PRIMARY KEY,
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    handyman_id UUID NOT NULL REFERENCES handyman_profiles(id) ON DELETE CASCADE,
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_handyman_follow_user_handyman UNIQUE (user_id, handyman_id)
);
CREATE INDEX IF NOT EXISTS ix_handyman_follows_handyman_id ON handyman_follows(handyman_id);
CREATE INDEX IF NOT EXISTS ix_handyman_follows_user_id ON handyman_follows(user_id);

-- Denormalized count, recomputed from handyman_follows after every follow/unfollow.
ALTER TABLE handyman_profiles ADD COLUMN IF NOT EXISTS follower_count INTEGER NOT NULL DEFAULT 0;

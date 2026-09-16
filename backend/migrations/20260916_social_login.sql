-- Google/Apple sign-in. password_hash becomes optional since a social
-- account may never set one; oauth_sub is the provider's stable user id
-- (never their email, which can change). The partial unique index only
-- applies to rows that actually have a provider, so ordinary password
-- accounts (both columns NULL) are unaffected.
ALTER TABLE users ALTER COLUMN password_hash DROP NOT NULL;
ALTER TABLE users ADD COLUMN IF NOT EXISTS oauth_provider VARCHAR(20);
ALTER TABLE users ADD COLUMN IF NOT EXISTS oauth_sub VARCHAR(255);
CREATE UNIQUE INDEX IF NOT EXISTS ix_users_oauth_provider_sub
    ON users (oauth_provider, oauth_sub)
    WHERE oauth_provider IS NOT NULL;

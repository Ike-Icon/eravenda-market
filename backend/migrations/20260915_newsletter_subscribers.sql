-- Footer "Get new-arrival alerts" signup. One row per email, plus a token
-- used for one-click unsubscribe links in the weekly digest email.
CREATE TABLE IF NOT EXISTS newsletter_subscribers (
    id UUID PRIMARY KEY,
    email VARCHAR(255) NOT NULL UNIQUE,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    unsubscribe_token VARCHAR(64) NOT NULL UNIQUE,
    subscribed_at TIMESTAMP NOT NULL DEFAULT NOW(),
    last_sent_at TIMESTAMP
);

-- Page-view beacon behind the admin dashboard's "Traffic & purchases" card.
-- visitor_id is a random per-browser ID (no IP, no personal data).
CREATE TABLE IF NOT EXISTS site_visits (
    id UUID PRIMARY KEY,
    visitor_id VARCHAR(64) NOT NULL,
    path VARCHAR(300) NOT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS ix_site_visits_visitor_id ON site_visits (visitor_id);
CREATE INDEX IF NOT EXISTS ix_site_visits_created_at ON site_visits (created_at);

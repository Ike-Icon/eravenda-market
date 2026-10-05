-- Admin Email center: saved message templates and a log of every broadcast
-- an admin sends to buyers, sellers, professionals or newsletter subscribers.
CREATE TABLE IF NOT EXISTS email_templates (
    id UUID PRIMARY KEY,
    name VARCHAR(120) NOT NULL,
    audience VARCHAR(20) NOT NULL DEFAULT 'users',
    subject VARCHAR(200) NOT NULL,
    body TEXT NOT NULL,
    button_label VARCHAR(60),
    button_url VARCHAR(500),
    created_by UUID REFERENCES users(id) ON DELETE SET NULL,
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS email_campaigns (
    id UUID PRIMARY KEY,
    audience VARCHAR(20) NOT NULL,
    include_pending BOOLEAN NOT NULL DEFAULT FALSE,
    subject VARCHAR(200) NOT NULL,
    body TEXT NOT NULL,
    button_label VARCHAR(60),
    button_url VARCHAR(500),
    status VARCHAR(20) NOT NULL DEFAULT 'sending',  -- sending | completed | failed | interrupted
    recipient_count INTEGER NOT NULL DEFAULT 0,
    sent_count INTEGER NOT NULL DEFAULT 0,
    failed_count INTEGER NOT NULL DEFAULT 0,
    error VARCHAR(500),
    sent_by UUID REFERENCES users(id) ON DELETE SET NULL,
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    finished_at TIMESTAMP
);
CREATE INDEX IF NOT EXISTS ix_email_campaigns_created_at ON email_campaigns(created_at);

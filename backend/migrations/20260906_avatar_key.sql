-- Avatar choices are application-defined keys rather than user-supplied URLs.
ALTER TABLE users ADD COLUMN IF NOT EXISTS avatar_key VARCHAR(40) NOT NULL DEFAULT 'Avery';

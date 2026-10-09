-- Email center: "One user" audience. Records which address a single-user send
-- went to (shown in Recent sends, and keeps the 10-minute duplicate guard from
-- blocking the same message going to two different people). Idempotent.
ALTER TABLE email_campaigns ADD COLUMN IF NOT EXISTS target_email VARCHAR(255);

-- Lets the admin record why a delivery partner application was rejected,
-- so the rejected applicant can be shown the reason on their dashboard
-- (with an option to reapply or contact support), instead of just seeing
-- a blank dashboard with no explanation.

ALTER TABLE delivery_profiles ADD COLUMN IF NOT EXISTS rejection_reason TEXT;

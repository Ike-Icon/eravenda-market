-- Handyman service payment workflow: progress tracking, work-verification
-- photos, dual-sided payout ledger, and admin payout controls.

-- New booking status milestones (in_progress, completion_requested).
ALTER TYPE servicebookingstatus ADD VALUE IF NOT EXISTS 'in_progress';
ALTER TYPE servicebookingstatus ADD VALUE IF NOT EXISTS 'completion_requested';

DO $$ BEGIN CREATE TYPE payoutstatus AS ENUM ('pending', 'processing', 'paid', 'failed'); EXCEPTION WHEN duplicate_object THEN NULL; END $$;

ALTER TABLE service_bookings ADD COLUMN IF NOT EXISTS payout_amount NUMERIC(12,2) NOT NULL DEFAULT 0;
ALTER TABLE service_bookings ADD COLUMN IF NOT EXISTS payout_status payoutstatus NOT NULL DEFAULT 'pending';
ALTER TABLE service_bookings ADD COLUMN IF NOT EXISTS payout_held BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE service_bookings ADD COLUMN IF NOT EXISTS payout_note TEXT;
ALTER TABLE service_bookings ADD COLUMN IF NOT EXISTS completion_requested_at TIMESTAMP;
ALTER TABLE service_bookings ADD COLUMN IF NOT EXISTS paid_at TIMESTAMP;
ALTER TABLE service_bookings ADD COLUMN IF NOT EXISTS payout_released_at TIMESTAMP;

CREATE TABLE IF NOT EXISTS service_job_photos (
  id UUID PRIMARY KEY,
  booking_id UUID NOT NULL REFERENCES service_bookings(id) ON DELETE CASCADE,
  uploaded_by UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  uploader_role VARCHAR(20) NOT NULL DEFAULT 'handyman',
  image_url TEXT NOT NULL,
  caption VARCHAR(200),
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS service_payments (
  id UUID PRIMARY KEY,
  booking_id UUID NOT NULL REFERENCES service_bookings(id) ON DELETE CASCADE,
  provider VARCHAR(30) NOT NULL,
  provider_reference VARCHAR(150) NOT NULL UNIQUE,
  amount NUMERIC(12,2) NOT NULL,
  currency VARCHAR(10) NOT NULL DEFAULT 'GHS',
  status paymentstatus NOT NULL DEFAULT 'pending',
  paid_at TIMESTAMP,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

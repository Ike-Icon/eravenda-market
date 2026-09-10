-- Service profile and request management additions for existing installations.
ALTER TABLE handyman_profiles ADD COLUMN IF NOT EXISTS professional_name VARCHAR(150);
ALTER TABLE handyman_profiles ADD COLUMN IF NOT EXISTS company_name VARCHAR(150);
ALTER TABLE handyman_profiles ADD COLUMN IF NOT EXISTS work_experience TEXT;
ALTER TABLE handyman_profiles ADD COLUMN IF NOT EXISTS education TEXT;
ALTER TABLE service_bookings ADD COLUMN IF NOT EXISTS location VARCHAR(255);
ALTER TABLE service_bookings ADD COLUMN IF NOT EXISTS preferred_contact VARCHAR(20);
ALTER TABLE service_bookings ADD COLUMN IF NOT EXISTS contact_details VARCHAR(150);
CREATE TABLE IF NOT EXISTS service_portfolio (
  id UUID PRIMARY KEY,
  handyman_id UUID NOT NULL REFERENCES handyman_profiles(id) ON DELETE CASCADE,
  image_url TEXT NOT NULL,
  caption VARCHAR(200)
);

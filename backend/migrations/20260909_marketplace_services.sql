DO $$ BEGIN CREATE TYPE paymentmethod AS ENUM ('cash_on_delivery', 'mobile_money'); EXCEPTION WHEN duplicate_object THEN NULL; END $$;
DO $$ BEGIN CREATE TYPE servicestatus AS ENUM ('pending', 'approved', 'rejected'); EXCEPTION WHEN duplicate_object THEN NULL; END $$;
DO $$ BEGIN CREATE TYPE servicebookingstatus AS ENUM ('requested', 'assigned', 'escrow_funded', 'completed', 'released', 'cancelled'); EXCEPTION WHEN duplicate_object THEN NULL; END $$;

ALTER TABLE orders ADD COLUMN IF NOT EXISTS payment_method paymentmethod NOT NULL DEFAULT 'mobile_money';
CREATE TABLE IF NOT EXISTS wishlists (
  id UUID PRIMARY KEY, user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  product_id UUID NOT NULL REFERENCES products(id) ON DELETE CASCADE, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  CONSTRAINT uq_wishlist_user_product UNIQUE (user_id, product_id)
);
CREATE TABLE IF NOT EXISTS handyman_profiles (
  id UUID PRIMARY KEY, user_id UUID NOT NULL UNIQUE REFERENCES users(id) ON DELETE CASCADE,
  job_title VARCHAR(100) NOT NULL, custom_job_title VARCHAR(100), qualifications TEXT NOT NULL, resume_path TEXT,
  status servicestatus NOT NULL DEFAULT 'pending', verified_pro BOOLEAN NOT NULL DEFAULT FALSE, background_checked BOOLEAN NOT NULL DEFAULT FALSE,
  terms_accepted_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS service_portfolio (
  id UUID PRIMARY KEY, handyman_id UUID NOT NULL REFERENCES handyman_profiles(id) ON DELETE CASCADE, image_url TEXT NOT NULL, caption VARCHAR(200)
);
CREATE TABLE IF NOT EXISTS service_bookings (
  id UUID PRIMARY KEY, client_id UUID NOT NULL REFERENCES users(id), handyman_id UUID NOT NULL REFERENCES handyman_profiles(id),
  details TEXT NOT NULL, quoted_amount NUMERIC(12,2), escrow_amount NUMERIC(12,2) NOT NULL DEFAULT 0,
  commission_amount NUMERIC(12,2) NOT NULL DEFAULT 0, status servicebookingstatus NOT NULL DEFAULT 'requested', created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
ALTER TABLE handyman_profiles ADD COLUMN IF NOT EXISTS average_rating NUMERIC(3,2) NOT NULL DEFAULT 0;
ALTER TABLE handyman_profiles ADD COLUMN IF NOT EXISTS review_count INTEGER NOT NULL DEFAULT 0;
CREATE TABLE IF NOT EXISTS service_reviews (
  id UUID PRIMARY KEY, booking_id UUID NOT NULL REFERENCES service_bookings(id) ON DELETE CASCADE,
  handyman_id UUID NOT NULL REFERENCES handyman_profiles(id) ON DELETE CASCADE, client_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  rating SMALLINT NOT NULL CHECK (rating BETWEEN 1 AND 5), comment TEXT, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  CONSTRAINT uq_service_review_booking UNIQUE (booking_id)
);
ALTER TABLE service_bookings ADD COLUMN IF NOT EXISTS location VARCHAR(255);
ALTER TABLE service_bookings ADD COLUMN IF NOT EXISTS preferred_contact VARCHAR(20);
ALTER TABLE service_bookings ADD COLUMN IF NOT EXISTS contact_details VARCHAR(150);
ALTER TABLE handyman_profiles ADD COLUMN IF NOT EXISTS professional_name VARCHAR(150);
ALTER TABLE handyman_profiles ADD COLUMN IF NOT EXISTS company_name VARCHAR(150);
ALTER TABLE handyman_profiles ADD COLUMN IF NOT EXISTS work_experience TEXT;
ALTER TABLE handyman_profiles ADD COLUMN IF NOT EXISTS education TEXT;

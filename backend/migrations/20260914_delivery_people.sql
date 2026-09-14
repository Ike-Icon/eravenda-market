DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_type WHERE typname = 'userrole') THEN
        ALTER TYPE userrole ADD VALUE IF NOT EXISTS 'delivery';
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'deliverystatus') THEN
        CREATE TYPE deliverystatus AS ENUM ('pending', 'approved', 'rejected', 'suspended');
    END IF;
END $$;

CREATE TABLE IF NOT EXISTS delivery_profiles (
    id UUID PRIMARY KEY,
    user_id UUID NOT NULL UNIQUE REFERENCES users(id) ON DELETE CASCADE,
    company_name VARCHAR(150),
    location VARCHAR(255) NOT NULL,
    vehicle_type VARCHAR(80) NOT NULL,
    license_number VARCHAR(100),
    availability VARCHAR(50) NOT NULL DEFAULT 'available',
    status deliverystatus NOT NULL DEFAULT 'pending',
    terms_accepted_at TIMESTAMP NOT NULL DEFAULT NOW(),
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS order_delivery_assignments (
    id UUID PRIMARY KEY,
    order_id UUID NOT NULL UNIQUE REFERENCES orders(id) ON DELETE CASCADE,
    delivery_person_id UUID NOT NULL REFERENCES delivery_profiles(id),
    assigned_at TIMESTAMP NOT NULL DEFAULT NOW(),
    assignment_note TEXT
);
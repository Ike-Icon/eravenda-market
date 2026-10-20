-- Users can upload their own (cropped) profile photo. The preset avatar_key stays as the fallback.
ALTER TABLE users ADD COLUMN IF NOT EXISTS avatar_url TEXT;

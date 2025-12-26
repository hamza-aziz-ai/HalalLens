BEGIN;

ALTER TABLE users
    ADD COLUMN IF NOT EXISTS provider TEXT NOT NULL DEFAULT 'password',
    ADD COLUMN IF NOT EXISTS google_sub TEXT UNIQUE,
    ADD COLUMN IF NOT EXISTS full_name TEXT,
    ADD COLUMN IF NOT EXISTS avatar_url TEXT;

CREATE INDEX IF NOT EXISTS idx_users_google_sub ON users(google_sub);

COMMIT;

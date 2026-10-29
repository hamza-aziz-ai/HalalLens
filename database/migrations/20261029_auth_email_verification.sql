-- Auth hardening (D-020): email verification, password reset, no admin rights
-- or Google linking based on an unproven email.
--
-- Until now an account became admin, and Google sign-in attached to it, just
-- because its email matched, and sign-up never proved the mailbox. No address
-- counts as proven yet, so every account starts unverified (no backfill: not
-- even provider='google', because the old callback accepted a missing
-- email_verified claim), loses its admin flag and its sessions. An account
-- proves its email again with a password-reset link or a fresh Google sign-in;
-- admin is then granted from ADMIN_EMAILS.

BEGIN;

ALTER TABLE users ADD COLUMN IF NOT EXISTS email_verified_at TIMESTAMPTZ;
-- Google-only accounts have no usable password.
ALTER TABLE users ALTER COLUMN password_hash DROP NOT NULL;

UPDATE users SET is_admin = FALSE WHERE email_verified_at IS NULL;
DELETE FROM user_sessions;

-- Single-use emailed proofs. Only the SHA-256 digest of the token is stored.
-- signup tokens have no user yet (email-first sign-up creates the account on
-- confirmation); reset_password tokens belong to an existing user.
CREATE TABLE IF NOT EXISTS auth_tokens (
    id BIGSERIAL PRIMARY KEY,
    purpose TEXT NOT NULL CHECK (purpose IN ('signup', 'reset_password')),
    email TEXT NOT NULL,
    user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
    token_digest TEXT NOT NULL UNIQUE,
    expires_at TIMESTAMPTZ NOT NULL,
    consumed_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_auth_tokens_email_purpose ON auth_tokens (email, purpose);

COMMIT;

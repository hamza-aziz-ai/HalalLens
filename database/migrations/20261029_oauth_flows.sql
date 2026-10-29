-- Browser-bound, single-use Google OAuth flows (D-021).
--
-- Replaces the signed, reusable OAuth state. Each flow is a row created when a
-- browser starts a Google sign-in or link, keyed by the SHA-256 digests of the
-- `state` sent to Google and of a random value set as a short-lived HttpOnly
-- cookie in that same browser. The callback must present both, once, within
-- ten minutes, so a state cannot be replayed or completed in another browser.
--
-- purpose = 'link' flows also record the signed-in user and session that
-- started them. The callback only stores the proven Google identity and a
-- one-time link code; the account changes only when that same session
-- confirms the code.

BEGIN;

CREATE TABLE IF NOT EXISTS oauth_flows (
    id BIGSERIAL PRIMARY KEY,
    purpose TEXT NOT NULL CHECK (purpose IN ('login', 'link')),
    state_digest TEXT NOT NULL UNIQUE,
    browser_digest TEXT NOT NULL,
    redirect TEXT,
    user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
    session_digest TEXT,
    google_sub TEXT,
    google_email TEXT,
    link_code_digest TEXT UNIQUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    expires_at TIMESTAMPTZ NOT NULL,
    callback_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ
);

COMMIT;

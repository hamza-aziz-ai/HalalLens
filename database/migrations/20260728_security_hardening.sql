-- Security hardening for auth sessions and billing idempotency.
--
-- 1. user_sessions.token now stores a SHA-256 digest of the bearer token
--    instead of the token itself, so a database dump cannot be replayed
--    against the API. Existing plaintext rows are unusable under the new
--    lookup and are removed here; users simply sign in again.
-- 2. payment_events gains a uniqueness guarantee on (provider, event_id) so a
--    replayed Razorpay webhook or a double-submitted verification cannot grant
--    a subscription period twice.

BEGIN;

-- 1. Invalidate plaintext session tokens ------------------------------------
DELETE FROM user_sessions;

COMMENT ON COLUMN user_sessions.token IS
    'SHA-256 hex digest of the bearer token issued to the client. Never the raw token.';

-- 2. Payment event idempotency ----------------------------------------------
-- Collapse any pre-existing duplicates before enforcing the constraint.
DELETE FROM payment_events pe
USING payment_events keep
WHERE pe.provider = keep.provider
  AND pe.event_id = keep.event_id
  AND pe.event_id IS NOT NULL
  AND pe.id > keep.id;

-- NULL event_ids stay distinct under Postgres semantics, which is what we want:
-- provider events without an id are still recorded, just not deduplicated.
CREATE UNIQUE INDEX IF NOT EXISTS payment_events_provider_event_key
    ON payment_events (provider, event_id);

-- 3. Faster session expiry sweeps -------------------------------------------
CREATE INDEX IF NOT EXISTS idx_user_sessions_expires_at
    ON user_sessions (expires_at);

COMMIT;

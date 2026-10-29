-- Compliance-flip alerts are emailed to the subscriber who watches the symbol
-- (D-031), no longer to one operator address. The mailbox lives on the watch
-- row: a row is pending while last_is_compliant IS DISTINCT FROM
-- notified_is_compliant (alerts/storage.py, alerts/delivery.py). Idempotent.

BEGIN;

ALTER TABLE watchlist_entries
    -- Verdict the subscriber was last told about (or silently rebaselined to).
    ADD COLUMN IF NOT EXISTS notified_is_compliant BOOLEAN,
    -- SMTP failures since the last acknowledged send; backoff and terminal stop.
    ADD COLUMN IF NOT EXISTS notify_attempts INTEGER NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS notify_next_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS notify_failed_at TIMESTAMPTZ,
    -- Evaluation behind last_is_compliant; an older observation never overwrites it.
    -- Same type as announcements.filing_date, so the staleness comparison is exact.
    ADD COLUMN IF NOT EXISTS observed_filing_date TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS observed_evaluated_at TIMESTAMPTZ;

-- Nothing is pending at deploy: flips seen before this release are not mailed.
UPDATE watchlist_entries
   SET notified_is_compliant = last_is_compliant
 WHERE notified_is_compliant IS DISTINCT FROM last_is_compliant
   AND observed_evaluated_at IS NULL;

-- Opt-out from alert emails (account page); on by default.
ALTER TABLE users ADD COLUMN IF NOT EXISTS alert_emails BOOLEAN NOT NULL DEFAULT TRUE;

COMMIT;

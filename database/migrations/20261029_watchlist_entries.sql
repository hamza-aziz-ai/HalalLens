-- Watchlists move from a JSON file (cache/watchlists.json, rewritten whole
-- without a lock) to PostgreSQL, so concurrent alert checks and watchlist
-- changes can no longer duplicate an alert or undo another user's change.
-- Entries belong to a user and go with the account. The JSON file is no longer
-- read; production's was empty ({}) when this shipped, so nothing is imported.

BEGIN;

CREATE TABLE IF NOT EXISTS watchlist_entries (
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    symbol TEXT NOT NULL,
    trigger TEXT NOT NULL DEFAULT 'compliance_flip',
    -- Last conclusive verdict seen by this user's alert checks; NULL until the
    -- first one (the baseline). alerts/storage.py moves it with conditional
    -- UPDATEs so a flip is reported once.
    last_is_compliant BOOLEAN,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (user_id, symbol, trigger)
);

COMMIT;

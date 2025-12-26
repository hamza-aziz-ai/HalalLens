BEGIN;

CREATE TABLE IF NOT EXISTS feedback_events (
    id              SERIAL PRIMARY KEY,
    feedback_id     INTEGER NOT NULL REFERENCES feedback_reports(id) ON DELETE CASCADE,
    event_type      TEXT NOT NULL,
    status          TEXT,
    reviewer        TEXT,
    details         TEXT,
    source          TEXT DEFAULT 'api',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_feedback_events_feedback_id_created_at
    ON feedback_events(feedback_id, created_at DESC);

COMMIT;

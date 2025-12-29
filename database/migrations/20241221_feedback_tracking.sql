-- Adds tracking tokens and re-evaluation metadata to feedback reports.
-- Run with:
--   psql -h 192.168.1.9 -U hamza -d "Halal-Lens" -f database/migrations/20241221_feedback_tracking.sql

ALTER TABLE feedback_reports
    ADD COLUMN IF NOT EXISTS public_token TEXT UNIQUE,
    ADD COLUMN IF NOT EXISTS status_updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    ADD COLUMN IF NOT EXISTS reevaluated_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS reevaluation_notes TEXT;

UPDATE feedback_reports
   SET public_token = COALESCE(
           public_token,
           md5(random()::text || clock_timestamp()::text)
       )
 WHERE public_token IS NULL;

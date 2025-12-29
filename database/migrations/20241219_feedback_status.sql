-- Adds reviewer workflow columns to feedback_reports.
-- Run with:
--   psql -h 192.168.1.9 -U hamza -d "Halal-Lens" -f database/migrations/20241219_feedback_status.sql

ALTER TABLE feedback_reports
    ADD COLUMN IF NOT EXISTS status TEXT NOT NULL DEFAULT 'open',
    ADD COLUMN IF NOT EXISTS review_notes TEXT,
    ADD COLUMN IF NOT EXISTS resolved_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS resolved_by TEXT;

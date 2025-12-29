-- Adds the AAOIFI-supporting columns expected by the latest code.
-- Run with:
--   psql -h 192.168.1.9 -U hamza -d "Halal-Lens" -f database/migrations/20241218_add_aaoifi_columns.sql

ALTER TABLE financial_snapshots
    ADD COLUMN IF NOT EXISTS accounts_receivable NUMERIC,
    ADD COLUMN IF NOT EXISTS liquid_assets NUMERIC,
    ADD COLUMN IF NOT EXISTS non_halal_income NUMERIC,
    ADD COLUMN IF NOT EXISTS governance_notes TEXT;

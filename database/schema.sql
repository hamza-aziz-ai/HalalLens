-- HalalLens Postgres schema
-- Run: psql "$DATABASE_URL" -f database/schema.sql

BEGIN;

CREATE TABLE IF NOT EXISTS announcements (
    symbol          VARCHAR(32) NOT NULL,
    filing_date     TIMESTAMPTZ NOT NULL,
    company_name    TEXT NOT NULL DEFAULT '',
    category        TEXT NOT NULL DEFAULT '',
    headline        TEXT NOT NULL DEFAULT '',
    confidence      VARCHAR(16) NOT NULL DEFAULT 'LOW',
    raw_json        JSONB NOT NULL,
    minio_path      TEXT,
    pdf_stored      BOOLEAN NOT NULL DEFAULT FALSE,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (symbol, filing_date)
);

CREATE TABLE IF NOT EXISTS financial_snapshots (
    symbol             VARCHAR(32) NOT NULL,
    filing_date        TIMESTAMPTZ NOT NULL,
    fy_end             DATE,
    quarter            VARCHAR(16),
    audit_status       VARCHAR(32),
    total_debt         NUMERIC,
    cash_equiv         NUMERIC,
    revenue            NUMERIC,
    interest_income    NUMERIC,
    dividend_income    NUMERIC,
    parsed_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (symbol, filing_date),
    CONSTRAINT fk_financials_announcement
        FOREIGN KEY (symbol, filing_date)
        REFERENCES announcements(symbol, filing_date)
        ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_announcements_filing_date
    ON announcements (filing_date DESC);

CREATE INDEX IF NOT EXISTS idx_financial_snapshots_filing_date
    ON financial_snapshots (filing_date DESC);

COMMIT;

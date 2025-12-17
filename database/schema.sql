-- HalalLens Postgres schema
-- Run: psql "$DATABASE_URL" -f database/schema.sql

BEGIN;

CREATE TABLE IF NOT EXISTS announcements (
    symbol          VARCHAR(32) NOT NULL,
    symbol_alias    VARCHAR(64) NOT NULL DEFAULT '',
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

CREATE INDEX IF NOT EXISTS idx_announcements_symbol_alias
    ON announcements (symbol_alias);

CREATE INDEX IF NOT EXISTS idx_financial_snapshots_filing_date
    ON financial_snapshots (filing_date DESC);

CREATE TABLE IF NOT EXISTS market_data_snapshots (
    symbol          VARCHAR(32) NOT NULL,
    captured_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    market_cap      NUMERIC,
    share_price     NUMERIC,
    provider        TEXT DEFAULT 'yahoo',
    PRIMARY KEY (symbol, captured_at)
);

CREATE TABLE IF NOT EXISTS filing_evaluations (
    symbol             VARCHAR(32) NOT NULL,
    filing_date        TIMESTAMPTZ NOT NULL,
    is_compliant       BOOLEAN,
    ratios             JSONB,
    summary            TEXT,
    verdict            TEXT,
    narration_source   TEXT,
    market_cap_used    NUMERIC,
    trailing_cap_used  NUMERIC,
    evaluated_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (symbol, filing_date),
    FOREIGN KEY (symbol, filing_date)
        REFERENCES announcements(symbol, filing_date)
        ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS data_quality_issues (
    id              SERIAL PRIMARY KEY,
    symbol          VARCHAR(32) NOT NULL,
    filing_date     TIMESTAMPTZ NOT NULL,
    issue_type      TEXT NOT NULL,
    details         TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    resolved_at     TIMESTAMPTZ,
    UNIQUE (symbol, filing_date, issue_type)
);

CREATE TABLE IF NOT EXISTS feedback_reports (
    id              SERIAL PRIMARY KEY,
    symbol          VARCHAR(32),
    filing_date     TIMESTAMPTZ,
    verdict         TEXT,
    message         TEXT NOT NULL,
    contact         TEXT,
    source          TEXT DEFAULT 'ui',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

COMMIT;

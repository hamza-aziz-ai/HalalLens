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
    accounts_receivable NUMERIC,
    liquid_assets      NUMERIC,
    non_halal_income   NUMERIC,
    governance_notes   TEXT,
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
    market_data_provider TEXT,
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
    status          TEXT NOT NULL DEFAULT 'open',
    review_notes    TEXT,
    resolved_at     TIMESTAMPTZ,
    resolved_by     TEXT,
    public_token    TEXT UNIQUE,
    status_updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    reevaluated_at  TIMESTAMPTZ,
    reevaluation_notes TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

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

CREATE TABLE IF NOT EXISTS governance_overrides (
    symbol              VARCHAR(32) NOT NULL,
    filing_date         TIMESTAMPTZ NOT NULL,
    accounts_receivable NUMERIC,
    liquid_assets       NUMERIC,
    non_halal_income    NUMERIC,
    governance_notes    TEXT,
    source              TEXT,
    reviewer            TEXT,
    reason              TEXT,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (symbol, filing_date)
);

CREATE OR REPLACE FUNCTION update_governance_overrides_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_governance_overrides_updated ON governance_overrides;
CREATE TRIGGER trg_governance_overrides_updated
BEFORE UPDATE ON governance_overrides
FOR EACH ROW
EXECUTE PROCEDURE update_governance_overrides_updated_at();

CREATE TABLE IF NOT EXISTS indianapi_snapshots (
    id              BIGSERIAL PRIMARY KEY,
    symbol          VARCHAR(32) NOT NULL,
    symbol_alias    VARCHAR(64),
    company_name    TEXT,
    snapshot_date   DATE,
    fetched_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    payload         JSONB NOT NULL,
    UNIQUE (symbol, snapshot_date)
);

CREATE INDEX IF NOT EXISTS idx_indianapi_snapshots_fetched_at
    ON indianapi_snapshots (fetched_at DESC);

CREATE TABLE IF NOT EXISTS users (
    id SERIAL PRIMARY KEY,
    email TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    provider TEXT NOT NULL DEFAULT 'password',
    google_sub TEXT UNIQUE,
    full_name TEXT,
    avatar_url TEXT,
    is_admin BOOLEAN NOT NULL DEFAULT FALSE,
    plan TEXT NOT NULL DEFAULT 'free',
    subscription_status TEXT NOT NULL DEFAULT 'inactive',
    subscription_renewal DATE,
    trial_used BOOLEAN NOT NULL DEFAULT FALSE,
    plan_started_at TIMESTAMPTZ,
    last_login TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- token holds a SHA-256 hex digest of the bearer token, never the raw token.
CREATE TABLE IF NOT EXISTS user_sessions (
    token TEXT PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    expires_at TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_users_email ON users(email);
CREATE INDEX IF NOT EXISTS idx_users_google_sub ON users(google_sub);
CREATE INDEX IF NOT EXISTS idx_user_sessions_user ON user_sessions(user_id);
CREATE INDEX IF NOT EXISTS idx_user_sessions_expires_at ON user_sessions(expires_at);

CREATE TABLE IF NOT EXISTS subscription_plans (
    code TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    price_inr INTEGER NOT NULL,
    interval_days INTEGER NOT NULL DEFAULT 30,
    trial_days INTEGER NOT NULL DEFAULT 0,
    features JSONB NOT NULL DEFAULT '{}'::jsonb,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS user_subscriptions (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    plan_code TEXT NOT NULL REFERENCES subscription_plans(code),
    provider TEXT NOT NULL DEFAULT 'razorpay',
    status TEXT NOT NULL DEFAULT 'inactive',
    current_period_start TIMESTAMPTZ,
    current_period_end TIMESTAMPTZ,
    cancel_at_period_end BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_user_subscriptions_user
    ON user_subscriptions (user_id);

CREATE TABLE IF NOT EXISTS razorpay_orders (
    order_id TEXT PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    amount INTEGER NOT NULL,
    currency TEXT NOT NULL DEFAULT 'INR',
    status TEXT NOT NULL DEFAULT 'created',
    payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS payment_events (
    id BIGSERIAL PRIMARY KEY,
    user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
    provider TEXT NOT NULL DEFAULT 'razorpay',
    event_type TEXT NOT NULL,
    event_id TEXT,
    payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Idempotency guard: a replayed webhook or double-submitted verification must
-- not be able to grant the same subscription period twice.
CREATE UNIQUE INDEX IF NOT EXISTS payment_events_provider_event_key
    ON payment_events (provider, event_id);

INSERT INTO subscription_plans (code, name, price_inr, interval_days, trial_days, features)
VALUES (
    'starter',
    'Starter',
    50,
    30,
    30,
    '["instant_lookup","explain_why","governance_overrides","history","alerts"]'::jsonb
)
ON CONFLICT (code) DO NOTHING;

INSERT INTO subscription_plans (code, name, price_inr, interval_days, trial_days, features)
VALUES (
    'annual',
    'Annual',
    500,
    365,
    30,
    '["instant_lookup","explain_why","governance_overrides","history","alerts"]'::jsonb
)
ON CONFLICT (code) DO NOTHING;

INSERT INTO subscription_plans (code, name, price_inr, interval_days, trial_days, features)
VALUES (
    'lifetime',
    'Lifetime',
    2000,
    0,
    0,
    '["instant_lookup","explain_why","governance_overrides","history","alerts"]'::jsonb
)
ON CONFLICT (code) DO NOTHING;

CREATE TABLE IF NOT EXISTS bhavcopy_quotes (
    symbol      VARCHAR(32) NOT NULL,
    trade_date  DATE NOT NULL,
    share_price NUMERIC,
    market_cap  NUMERIC,
    provider    TEXT NOT NULL DEFAULT 'bhavcopy',
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (symbol, trade_date)
);

CREATE INDEX IF NOT EXISTS idx_bhavcopy_quotes_trade_date
    ON bhavcopy_quotes (trade_date);

COMMIT;

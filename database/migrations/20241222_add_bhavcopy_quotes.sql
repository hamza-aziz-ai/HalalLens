BEGIN;

CREATE TABLE IF NOT EXISTS bhavcopy_quotes (
    symbol VARCHAR(32) NOT NULL,
    trade_date DATE NOT NULL,
    share_price NUMERIC,
    market_cap NUMERIC,
    provider TEXT NOT NULL DEFAULT 'bhavcopy',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (symbol, trade_date)
);

CREATE INDEX IF NOT EXISTS idx_bhavcopy_quotes_trade_date
    ON bhavcopy_quotes (trade_date);

COMMIT;

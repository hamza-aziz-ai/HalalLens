BEGIN;

CREATE TABLE IF NOT EXISTS governance_overrides (
    symbol VARCHAR(32) NOT NULL,
    filing_date TIMESTAMPTZ NOT NULL,
    accounts_receivable NUMERIC,
    liquid_assets NUMERIC,
    non_halal_income NUMERIC,
    governance_notes TEXT,
    source TEXT,
    reviewer TEXT,
    reason TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (symbol, filing_date)
);

CREATE OR REPLACE FUNCTION update_governance_overrides_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = now();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_governance_overrides_updated ON governance_overrides;
CREATE TRIGGER trg_governance_overrides_updated
BEFORE UPDATE ON governance_overrides
FOR EACH ROW
EXECUTE PROCEDURE update_governance_overrides_updated_at();

COMMIT;

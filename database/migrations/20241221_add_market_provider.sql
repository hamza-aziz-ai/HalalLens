ALTER TABLE filing_evaluations
    ADD COLUMN IF NOT EXISTS market_data_provider TEXT;

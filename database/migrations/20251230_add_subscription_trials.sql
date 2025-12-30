BEGIN;

ALTER TABLE users
    ADD COLUMN IF NOT EXISTS trial_used BOOLEAN NOT NULL DEFAULT FALSE;

ALTER TABLE subscription_plans
    ADD COLUMN IF NOT EXISTS trial_days INTEGER NOT NULL DEFAULT 0;

UPDATE subscription_plans
SET trial_days = 30
WHERE code = 'starter';

INSERT INTO subscription_plans (code, name, price_inr, interval_days, trial_days, features)
VALUES (
    'annual',
    'Annual',
    500,
    365,
    30,
    '["instant_lookup","explain_why","governance_overrides","history","alerts"]'::jsonb
)
ON CONFLICT (code) DO UPDATE
SET name = EXCLUDED.name,
    price_inr = EXCLUDED.price_inr,
    interval_days = EXCLUDED.interval_days,
    trial_days = EXCLUDED.trial_days,
    features = EXCLUDED.features,
    updated_at = NOW();

INSERT INTO subscription_plans (code, name, price_inr, interval_days, trial_days, features)
VALUES (
    'lifetime',
    'Lifetime',
    2000,
    0,
    0,
    '["instant_lookup","explain_why","governance_overrides","history","alerts"]'::jsonb
)
ON CONFLICT (code) DO UPDATE
SET name = EXCLUDED.name,
    price_inr = EXCLUDED.price_inr,
    interval_days = EXCLUDED.interval_days,
    trial_days = EXCLUDED.trial_days,
    features = EXCLUDED.features,
    updated_at = NOW();

COMMIT;

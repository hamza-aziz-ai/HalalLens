BEGIN;

CREATE TABLE IF NOT EXISTS subscription_plans (
    code TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    price_inr INTEGER NOT NULL,
    interval_days INTEGER NOT NULL DEFAULT 30,
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

INSERT INTO subscription_plans (code, name, price_inr, interval_days, features)
VALUES (
    'starter',
    'Starter',
    50,
    30,
    '["instant_lookup","explain_why","governance_overrides","history","alerts"]'::jsonb
)
ON CONFLICT (code) DO NOTHING;

COMMIT;

-- Billing ledger (D-024): one grant per paid order, trial or pre-ledger
-- period. Access is derived from the grants (api/billing.py); users.plan,
-- subscription_status and subscription_renewal become a projection written in
-- the same transaction as each grant or refund. Idempotent; run once before
-- deploying the release that reads subscription_grants.
BEGIN;

-- Explicit tier order for Upgrade / Switch / Extend labels (not the price).
ALTER TABLE subscription_plans ADD COLUMN IF NOT EXISTS rank INTEGER NOT NULL DEFAULT 0;
UPDATE subscription_plans SET rank = 1 WHERE code = 'starter';
UPDATE subscription_plans SET rank = 2 WHERE code = 'annual';
UPDATE subscription_plans SET rank = 3 WHERE code = 'lifetime';

-- Purchase terms fixed when the order is created, so settlement never reads
-- a plan edited later; payment_id links refunds back to the order.
ALTER TABLE razorpay_orders
    ADD COLUMN IF NOT EXISTS plan_code TEXT REFERENCES subscription_plans(code),
    ADD COLUMN IF NOT EXISTS interval_days INTEGER,
    ADD COLUMN IF NOT EXISTS payment_id TEXT;
UPDATE razorpay_orders o
SET plan_code = o.payload->'notes'->>'plan_code'
WHERE o.plan_code IS NULL
  AND EXISTS (SELECT 1 FROM subscription_plans p WHERE p.code = o.payload->'notes'->>'plan_code');
UPDATE razorpay_orders o
SET interval_days = p.interval_days
FROM subscription_plans p
WHERE o.interval_days IS NULL AND p.code = o.plan_code;
CREATE UNIQUE INDEX IF NOT EXISTS razorpay_orders_payment_id_key
    ON razorpay_orders (payment_id) WHERE payment_id IS NOT NULL;

-- Exact period ends (a DATE cut every renewal to midnight). Existing dates
-- become midnight UTC, the boundary the old code compared against.
DO $$
BEGIN
    IF (SELECT data_type FROM information_schema.columns
        WHERE table_name = 'users' AND column_name = 'subscription_renewal') = 'date' THEN
        ALTER TABLE users ALTER COLUMN subscription_renewal TYPE TIMESTAMPTZ
            USING (subscription_renewal::timestamp AT TIME ZONE 'UTC');
    END IF;
END $$;

CREATE TABLE IF NOT EXISTS subscription_grants (
    id BIGSERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    plan_code TEXT NOT NULL REFERENCES subscription_plans(code),
    source TEXT NOT NULL CHECK (source IN ('razorpay', 'trial', 'legacy')),
    order_id TEXT UNIQUE REFERENCES razorpay_orders(order_id),
    duration INTERVAL,                       -- NULL: Lifetime
    allocated_at TIMESTAMPTZ NOT NULL,       -- set under the per-user lock
    refunded_amount INTEGER NOT NULL DEFAULT 0,
    revoked_at TIMESTAMPTZ,                  -- full refund
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_subscription_grants_user
    ON subscription_grants (user_id, allocated_at, id);

-- Opening grant for every currently entitled user, ending exactly where their
-- access ends today. It is linked to an order only when that is unambiguous
-- (the user's single paid order, for the same plan), so a refund of it can
-- revoke it; otherwise refunds of older orders need manual review.
INSERT INTO subscription_grants (user_id, plan_code, source, order_id, duration, allocated_at)
SELECT u.id,
       u.plan,
       CASE WHEN u.subscription_status = 'trialing' THEN 'trial' ELSE 'legacy' END,
       CASE WHEN u.subscription_status = 'trialing' THEN NULL ELSE o.order_id END,
       CASE WHEN u.plan = 'lifetime' THEN NULL
            ELSE GREATEST(u.subscription_renewal - s.started, INTERVAL '0') END,
       s.started
FROM users u
CROSS JOIN LATERAL (SELECT LEAST(COALESCE(u.plan_started_at, NOW()), NOW()) AS started) s
LEFT JOIN LATERAL (
    SELECT r.order_id
    FROM razorpay_orders r
    WHERE r.user_id = u.id AND r.status = 'paid' AND r.plan_code = u.plan
      AND (SELECT COUNT(*) FROM razorpay_orders r2 WHERE r2.user_id = u.id AND r2.status = 'paid') = 1
) o ON TRUE
WHERE u.plan <> 'free'
  AND u.subscription_status IN ('active', 'trialing')
  AND (u.plan = 'lifetime' OR u.subscription_renewal > NOW())
  AND EXISTS (SELECT 1 FROM subscription_plans p WHERE p.code = u.plan)
  AND NOT EXISTS (SELECT 1 FROM subscription_grants g WHERE g.user_id = u.id);

COMMIT;

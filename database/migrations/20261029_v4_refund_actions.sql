-- Automatic refund requests (D-025, PR C). One per payment; the key, body,
-- amount and currency are fixed when the row is created, so every retry
-- sends the identical request (X-Refund-Idempotency). Idempotent migration.
CREATE TABLE IF NOT EXISTS refund_actions (
    id BIGSERIAL PRIMARY KEY,
    payment_id TEXT NOT NULL UNIQUE,
    order_id TEXT NOT NULL REFERENCES razorpay_orders(order_id),
    reason TEXT NOT NULL CHECK (reason IN ('duplicate', 'refund_due')),
    amount INTEGER NOT NULL CHECK (amount > 0),
    currency TEXT NOT NULL,
    idempotency_key TEXT NOT NULL UNIQUE,
    request_body JSONB NOT NULL,
    -- requested < created < processed; failed / blocked only from requested or created
    state TEXT NOT NULL DEFAULT 'requested'
        CHECK (state IN ('requested', 'created', 'processed', 'failed', 'blocked')),
    provider_refund_id TEXT UNIQUE,
    attempts INTEGER NOT NULL DEFAULT 0,
    next_attempt_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_error TEXT,
    -- the payment's refund obligation was met (by this or any other refund)
    obligation_settled_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_refund_actions_due
    ON refund_actions (next_attempt_at) WHERE state IN ('requested', 'created') AND obligation_settled_at IS NULL;

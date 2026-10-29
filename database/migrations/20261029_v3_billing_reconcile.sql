-- Payment reconciler state (D-025, jobs/reconcile_payments.py). Idempotent.
-- billing_reconcile_state: one row; each stream's checkpoint is the end of
-- its last fully processed window (never moves back).
CREATE TABLE IF NOT EXISTS billing_reconcile_state (
    id SMALLINT PRIMARY KEY DEFAULT 1 CHECK (id = 1),
    payments_checkpoint TIMESTAMPTZ,
    refunds_checkpoint TIMESTAMPTZ,
    audit_before TIMESTAMPTZ,          -- historical audit walks back from here
    last_success_at TIMESTAMPTZ,
    last_error TEXT,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
INSERT INTO billing_reconcile_state (id) VALUES (1) ON CONFLICT (id) DO NOTHING;

-- billing_tracked: everything the reconciler must look at again (pending at
-- Razorpay, or needing a refund or a human). Rows are never resolved by age.
CREATE TABLE IF NOT EXISTS billing_tracked (
    kind TEXT NOT NULL CHECK (kind IN ('payment', 'refund', 'order')),
    provider_id TEXT NOT NULL,
    order_id TEXT,
    reason TEXT NOT NULL,
    last_status TEXT,
    attempts INTEGER NOT NULL DEFAULT 1,
    first_seen TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_checked TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    next_check_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_notified_at TIMESTAMPTZ,
    resolved_at TIMESTAMPTZ,
    PRIMARY KEY (kind, provider_id)
);
CREATE INDEX IF NOT EXISTS idx_billing_tracked_due
    ON billing_tracked (next_check_at) WHERE resolved_at IS NULL;

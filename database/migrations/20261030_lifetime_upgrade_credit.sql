-- Upgrade credit at checkout for Lifetime (D-030). Idempotent.
-- An order's pricing terms are fixed when it is created: list price, credit
-- and the charged amount (amount = list_amount - credit_amount), when it was
-- priced and until when a payment attempt may use that price, and the
-- per-source evidence behind the credit. credit_version is NULL for ordinary
-- and pre-migration orders, which settle exactly as before.
ALTER TABLE razorpay_orders
    ADD COLUMN IF NOT EXISTS list_amount INTEGER,
    ADD COLUMN IF NOT EXISTS credit_amount INTEGER NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS priced_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS price_valid_until TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS credit_version INTEGER,
    ADD COLUMN IF NOT EXISTS credit_detail JSONB,
    -- why an order is refund_due: lifetime_held | price_expired | credit_changed
    ADD COLUMN IF NOT EXISTS refund_due_reason TEXT;

UPDATE razorpay_orders SET list_amount = amount WHERE list_amount IS NULL;

ALTER TABLE razorpay_orders DROP CONSTRAINT IF EXISTS razorpay_orders_credit_terms_check;
ALTER TABLE razorpay_orders ADD CONSTRAINT razorpay_orders_credit_terms_check
    CHECK (list_amount IS NULL OR (credit_amount >= 0 AND amount = list_amount - credit_amount));

-- credit_conflict: a payment that funded a settled credited order's credit
-- was refunded afterwards (alert only; resolved by a human, never by age).
ALTER TABLE billing_tracked DROP CONSTRAINT IF EXISTS billing_tracked_kind_check;
ALTER TABLE billing_tracked ADD CONSTRAINT billing_tracked_kind_check
    CHECK (kind IN ('payment', 'refund', 'order', 'credit_conflict'));

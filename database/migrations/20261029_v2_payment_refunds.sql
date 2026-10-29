-- One row per processed Razorpay refund, scoped to the payment it refunds
-- (D-025). Refund totals are summed from these rows; a refund applies to a
-- grant only when its payment is the one that funded the order. Idempotent.
CREATE TABLE IF NOT EXISTS payment_refunds (
    refund_id TEXT PRIMARY KEY,
    payment_id TEXT NOT NULL,
    order_id TEXT REFERENCES razorpay_orders(order_id),
    amount INTEGER NOT NULL CHECK (amount >= 0),
    recorded_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_payment_refunds_payment ON payment_refunds (payment_id);

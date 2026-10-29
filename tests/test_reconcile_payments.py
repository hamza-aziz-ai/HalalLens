"""The payment reconciler (jobs/reconcile_payments.py, D-025) on fakes.

The SQL, the advisory lock and the checkpoint rules on a real database are
in tests/test_billing_postgres.py (opt-in).
"""

from datetime import timedelta

import pytest

from api.razorpay_client import RazorpayClient, RazorpayError
from jobs.reconcile_payments import Reconciler
from tests.billing_fake import FakeRazorpay, ReconcileFake


@pytest.fixture()
def env():
    db = ReconcileFake()
    rzp = FakeRazorpay(db)
    alerts = []
    rec = Reconciler(db, rzp, lambda severity, message, details=None: alerts.append((severity, message)))
    return db, rzp, rec, alerts


def run(db, rec, minutes=20):
    """Advance past the reconciler's 10-minute lag, then run once."""

    db.advance(minutes / 1440)
    return rec.run(db.now)


def test_a_missed_webhook_is_settled_once_and_alerted(env):
    db, rzp, rec, alerts = env
    order = db.add_order("order_1", "starter")
    rzp.pay("pay_1", order)
    summary = run(db, rec)
    assert db.users[42]["plan"] == "starter" and len(db.grants) == 1
    assert summary["webhook_missed"] == 1 and any("webhook was missed" in m for _, m in alerts)
    run(db, rec, minutes=60)  # the overlap sees it again: nothing more happens
    assert len(db.grants) == 1


def test_the_webhook_winning_after_the_first_read_is_classified_from_the_locked_result(env):
    db, rzp, rec, alerts = env
    order = db.add_order("order_1", "starter")
    payment = rzp.pay("pay_1", order)
    # The webhook settles the order between the job's read and its settle call.
    real_settle = db.settle_razorpay_order

    def webhook_first(**kwargs):
        real_settle(**{**kwargs, "event_type": "payment.captured"})
        return real_settle(**kwargs)

    db.settle_razorpay_order = webhook_first
    rec.handle_payment(payment, db.now)
    assert len(db.grants) == 1 and db.open_items() == {}


def test_a_second_capture_on_a_paid_order_is_tracked_as_duplicate_not_granted(env):
    db, rzp, rec, alerts = env
    order = db.add_order("order_1", "annual")
    rzp.pay("pay_1", order)
    run(db, rec)
    rzp.pay("pay_2", order)
    run(db, rec, minutes=60)
    assert len(db.grants) == 1
    assert db.open_items() == {("payment", "pay_2"): "duplicate"}


def test_duplicates_on_refunded_and_refund_due_orders_are_tracked(env):
    db, rzp, rec, alerts = env
    life = db.add_order("o_life", "lifetime")
    starter = db.add_order("o_s", "starter")
    rzp.pay("pay_life", life)
    rzp.pay("pay_s", starter)
    run(db, rec)
    assert db.orders["o_s"]["status"] == "refund_due"
    assert db.open_items()[("payment", "pay_s")] == "refund_due"
    rzp.pay("pay_s2", starter)
    run(db, rec, minutes=60)
    assert db.open_items()[("payment", "pay_s2")] == "duplicate"


def test_a_mismatched_capture_gets_no_grant_and_an_alert(env):
    db, rzp, rec, alerts = env
    order = db.add_order("order_1", "annual")
    rzp.pay("pay_1", order, amount=100)
    run(db, rec)
    assert db.grants == [] and db.open_items() == {("payment", "pay_1"): "mismatch"}
    assert any("mismatch" in m for _, m in alerts)


def test_alerts_for_an_open_item_repeat_daily_not_every_run(env):
    db, rzp, rec, alerts = env
    order = db.add_order("order_1", "annual")
    rzp.pay("pay_1", order, amount=100)
    run(db, rec)
    run(db, rec, minutes=30)  # the overlap re-reads it 30 minutes later
    assert sum("mismatch" in m for _, m in alerts) == 1
    db.advance(1)
    rec._follow_up(db.due_billing_items(10)[0], db.now)
    assert sum("mismatch" in m for _, m in alerts) == 2


def test_an_authorized_payment_captured_after_the_overlap_is_found_by_follow_up(env):
    db, rzp, rec, alerts = env
    order = db.add_order("order_1", "starter")
    rzp.pay("pay_1", order, status="authorized")
    run(db, rec)
    assert db.open_items() == {("payment", "pay_1"): "pending"}
    db.advance(2)  # far beyond the 30-minute overlap
    rzp.payments["pay_1"]["status"] = "captured"
    run(db, rec)
    assert db.users[42]["plan"] == "starter" and db.open_items() == {}


def test_a_created_payment_is_never_retired_by_age(env):
    db, rzp, rec, alerts = env
    order = db.add_order("order_1", "starter")
    rzp.pay("pay_1", order, status="created")
    run(db, rec)
    db.advance(8)
    run(db, rec)
    row = db.tracked[("payment", "pay_1")]
    assert row["resolved_at"] is None
    assert row["next_check_at"] - db.now >= timedelta(hours=23)  # daily now
    db.advance(1)
    rzp.payments["pay_1"]["status"] = "captured"
    run(db, rec)
    assert db.users[42]["plan"] == "starter"


def test_a_dashboard_refund_processed_days_later_is_applied_without_a_webhook(env):
    db, rzp, rec, alerts = env
    order = db.add_order("order_1", "starter")
    rzp.pay("pay_1", order)
    run(db, rec)
    rzp.refund("rfnd_1", "pay_1", status="pending")
    run(db, rec)
    assert db.open_items() == {("refund", "rfnd_1"): "pending"}
    db.advance(3)
    rzp.refunds["rfnd_1"]["status"] = "processed"
    run(db, rec)
    assert db.users[42]["plan"] == "free" and db.open_items() == {}


def test_a_refunded_payment_is_never_granted(env):
    db, rzp, rec, alerts = env
    order = db.add_order("order_1", "starter")
    rzp.pay("pay_1", order)
    rzp.refund("rfnd_1", "pay_1")  # refunded at Razorpay before we ever saw it
    run(db, rec)
    assert db.grants == [] and db.open_items() == {}


def test_legacy_binding_applies_refunds_recorded_earlier(env):
    db, rzp, rec, alerts = env
    order = db.add_order("order_old", "annual")
    order["status"] = "paid"
    db.grants.append({"id": 1, "user_id": 42, "plan_code": "annual", "source": "legacy", "order_id": "order_old",
                      "duration": timedelta(days=365), "allocated_at": db.now, "refunded_amount": 0,
                      "revoked_at": None})
    db.refresh_entitlement(42, __import__("api.billing", fromlist=["project"]).project)
    rzp.pay("pay_old", order)
    rzp.refund("rfnd_1", "pay_old")
    run(db, rec)
    assert db.orders["order_old"]["payment_id"] == "pay_old"
    assert db.users[42]["plan"] == "free"  # the refund recorded earlier now applies


def test_legacy_binding_refuses_when_more_than_one_attempt_succeeded(env):
    db, rzp, rec, alerts = env
    order = db.add_order("order_old", "annual")
    order["status"] = "paid"
    db.grants.append({"id": 1, "user_id": 42, "plan_code": "annual", "source": "legacy", "order_id": "order_old",
                      "duration": timedelta(days=365), "allocated_at": db.now, "refunded_amount": 0,
                      "revoked_at": None})
    rzp.pay("pay_original", order)
    rzp.refund("rfnd_1", "pay_original")  # the original was refunded...
    rzp.pay("pay_dup", order)             # ...and a later attempt is the only one still captured
    run(db, rec)
    assert db.orders["order_old"]["payment_id"] is None
    assert db.open_items()[("order", "order_old")] == "legacy_review"


def test_payments_on_orders_this_app_did_not_create_are_ignored(env):
    db, rzp, rec, alerts = env
    db.add_order("order_1", "starter")
    rzp.payments["pay_link"] = {"id": "pay_link", "order_id": "order_elsewhere", "amount": 100, "currency": "INR",
                                "status": "captured", "amount_refunded": 0, "created_at": int(db.now.timestamp())}
    run(db, rec)
    assert db.grants == [] and db.open_items() == {}


def test_a_razorpay_failure_stops_the_run_without_moving_the_checkpoint(env):
    db, rzp, rec, alerts = env
    db.add_order("order_1", "starter")
    run(db, rec)
    checkpoint = db.state["payments_checkpoint"]
    rzp.fail_with = RazorpayError("HTTP 503", 503)
    summary = run(db, rec, minutes=60)
    assert summary.get("stopped") == 1 and db.state["payments_checkpoint"] == checkpoint
    assert db.state["last_error"]


def test_an_auth_failure_halts_and_raises(env):
    db, rzp, rec, alerts = env
    db.add_order("order_1", "starter")
    rzp.fail_with = RazorpayError("HTTP 401", 401)
    with pytest.raises(RazorpayError):
        run(db, rec)
    assert alerts and alerts[-1][0] == "error"


def test_an_outage_longer_than_a_week_catches_up_over_several_runs(env):
    db, rzp, rec, alerts = env
    order = db.add_order("order_1", "starter")
    run(db, rec)
    start = db.state["payments_checkpoint"]
    db.advance(20)  # 20 days with the job down
    rzp.pay("pay_1", order)
    checkpoints = []
    for _ in range(4):
        run(db, rec)
        checkpoints.append(db.state["payments_checkpoint"])
    # At most 7 days per run, never backwards, until the window reaches "now".
    assert checkpoints[0] - start <= timedelta(days=7, minutes=1)
    assert all(b >= a for a, b in zip(checkpoints, checkpoints[1:]))
    assert checkpoints[-1] >= db.now - timedelta(minutes=10)
    assert db.users[42]["plan"] == "starter"


def test_no_orders_means_nothing_to_do(env):
    db, rzp, rec, alerts = env
    assert rec.run(db.now) == {"skipped_no_orders": 1} and rzp.list_calls == 0


def test_client_pages_until_a_short_page(monkeypatch):
    calls = []

    def fake_items(self, path, params=None):
        calls.append(params["skip"])
        return [{"id": i} for i in range(100 if params["skip"] < 200 else 1)]

    monkeypatch.setattr(RazorpayClient, "_items", fake_items)
    items = RazorpayClient("k", "s").list_window("payments", 0, 10)
    assert len(items) == 201 and calls == [0, 100, 200]


def test_client_stops_after_exactly_one_full_page_then_an_empty_one(monkeypatch):
    pages = {0: [{"id": i} for i in range(100)], 100: []}
    monkeypatch.setattr(RazorpayClient, "_items", lambda self, path, params=None: pages[params["skip"]])
    assert len(RazorpayClient("k", "s").list_window("refunds", 0, 10)) == 100

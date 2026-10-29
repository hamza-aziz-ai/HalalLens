"""Automatic refunds and the reconciler heartbeat (D-025, PR C) on fakes."""

import asyncio
import importlib
from datetime import timedelta

import pytest
from fastapi import HTTPException

from api.razorpay_client import RazorpayError
from jobs.reconcile_payments import Reconciler
from tests.billing_fake import FakeRazorpay, ReconcileFake

api_module = importlib.import_module("api.app")


@pytest.fixture()
def env():
    db = ReconcileFake()
    rzp = FakeRazorpay(db)
    alerts = []
    rec = Reconciler(db, rzp, lambda severity, message, details=None: alerts.append((severity, message)),
                     auto_refunds=True)
    return db, rzp, rec, alerts


def run(db, rec, minutes=20):
    db.advance(minutes / 1440)
    return rec.run(db.now)


def duplicate(db, rzp, rec):
    """A paid Annual order plus a second captured payment on it."""

    order = db.add_order("order_1", "annual")
    rzp.pay("pay_1", order)
    run(db, rec)
    rzp.pay("pay_2", order)
    return order


def test_a_duplicate_payment_is_refunded_once_and_the_obligation_closes(env):
    db, rzp, rec, alerts = env
    duplicate(db, rzp, rec)
    run(db, rec)
    assert len(rzp.refund_posts) == 1
    payment_id, body, key = rzp.refund_posts[0]
    assert payment_id == "pay_2" and body["amount"] == 50000 and body["notes"]["halallens_refund_key"] == key
    action = db.actions["pay_2"]
    assert action["state"] == "processed" and action["obligation_settled_at"] is not None
    assert db.open_items() == {} and db.users[42]["plan"] == "annual"  # the funding payment's plan is untouched
    run(db, rec, minutes=60)
    assert len(rzp.refund_posts) == 1  # never twice


def test_a_refund_due_payment_is_refunded_and_closed(env):
    db, rzp, rec, alerts = env
    life, starter = db.add_order("o_life", "lifetime"), db.add_order("o_s", "starter")
    rzp.pay("pay_life", life)
    rzp.pay("pay_s", starter)
    run(db, rec)
    run(db, rec)
    assert db.orders["o_s"]["status"] == "refunded" and db.actions["pay_s"]["state"] == "processed"
    assert db.users[42]["plan"] == "lifetime"


def test_the_intent_is_persisted_before_the_post_and_a_lost_response_is_recovered(env):
    db, rzp, rec, alerts = env
    duplicate(db, rzp, rec)
    rzp.post_outcomes = ["lost"]  # Razorpay made the refund, the response never arrived
    run(db, rec)
    action = db.actions["pay_2"]
    assert action["state"] == "requested" and len(rzp.refund_posts) == 1
    db.advance(1 / 96)
    run(db, rec)
    # Found by our key in the refund's notes: adopted, no second POST.
    assert len(rzp.refund_posts) == 1 and db.actions["pay_2"]["state"] == "processed"


def test_a_timeout_before_razorpay_acted_resends_the_identical_request(env):
    db, rzp, rec, alerts = env
    duplicate(db, rzp, rec)
    rzp.post_outcomes = [RazorpayError("timed out")]
    run(db, rec)
    db.advance(1 / 96)
    run(db, rec)
    assert len(rzp.refund_posts) == 2
    assert rzp.refund_posts[0][1:] == rzp.refund_posts[1][1:]  # same body, same key
    assert db.actions["pay_2"]["state"] == "processed"


@pytest.mark.parametrize("error", [RazorpayError("HTTP 429", 429), RazorpayError("HTTP 502", 502),
                                   RazorpayError("HTTP 409", 409, "Request with the same key is in progress")])
def test_retryable_errors_retry_with_the_same_request(env, error):
    db, rzp, rec, alerts = env
    duplicate(db, rzp, rec)
    rzp.post_outcomes = [error]
    run(db, rec)
    assert db.actions["pay_2"]["state"] == "requested"
    db.advance(1 / 96)
    run(db, rec)
    assert db.actions["pay_2"]["state"] == "processed" and len({p[2] for p in rzp.refund_posts}) == 1


@pytest.mark.parametrize("error", [RazorpayError("HTTP 409", 409, "different parameters for the same key"),
                                   RazorpayError("HTTP 400", 400, "refund amount exceeds")])
def test_parameter_mismatch_and_refusals_block_for_a_human_never_count_as_success(env, error):
    db, rzp, rec, alerts = env
    duplicate(db, rzp, rec)
    rzp.post_outcomes = [error]
    run(db, rec)
    assert db.actions["pay_2"]["state"] == "blocked"
    assert any("blocked" in m for _, m in alerts)
    assert db.open_items()[("payment", "pay_2")] == "duplicate"  # obligation still open


def test_a_manual_refund_after_a_blocked_request_settles_the_obligation(env):
    db, rzp, rec, alerts = env
    duplicate(db, rzp, rec)
    rzp.post_outcomes = [RazorpayError("HTTP 400", 400, "refused")]
    run(db, rec)
    rzp.refund("rfnd_manual", "pay_2")  # the maintainer refunds it in the dashboard
    run(db, rec)
    assert db.actions["pay_2"]["state"] == "blocked"            # its own outcome is kept
    assert db.actions["pay_2"]["obligation_settled_at"] is not None
    assert db.open_items() == {}


def test_manual_partial_refunds_close_the_obligation_only_at_the_full_amount(env):
    db, rzp, rec, alerts = env
    duplicate(db, rzp, rec)
    rzp.refund("rfnd_a", "pay_2", amount=20000)  # a human starts refunding before the job runs
    run(db, rec)
    assert len(rzp.refund_posts) == 0  # never resized, never automatic once a refund exists
    assert db.open_items()[("payment", "pay_2")] == "partial_refund_review"
    rzp.refund("rfnd_b", "pay_2", amount=30000)
    run(db, rec)
    db.advance(1)
    run(db, rec)
    assert ("payment", "pay_2") not in db.open_items()


def test_an_external_pending_refund_blocks_a_new_request(env):
    db, rzp, rec, alerts = env
    duplicate(db, rzp, rec)
    rzp.refund("rfnd_pending", "pay_2", status="pending")
    run(db, rec)
    assert rzp.refund_posts == [] and "pay_2" not in db.actions


def test_a_refund_record_arriving_first_still_completes_the_action(env):
    db, rzp, rec, alerts = env
    duplicate(db, rzp, rec)
    rzp.post_outcomes = ["pending"]
    run(db, rec)
    assert db.actions["pay_2"]["state"] == "created"
    refund_id = db.actions["pay_2"]["provider_refund_id"]
    rzp.refunds[refund_id]["status"] = "processed"
    # The webhook records it before the job polls (event replays return "duplicate").
    db.refund_razorpay_payment(order_id="order_1", payment_id="pay_2", refund_id=refund_id, refund_amount=50000,
                               event_type="refund.processed", payload={}, project=None)
    db.sync_refund_action("pay_2")
    assert db.actions["pay_2"]["state"] == "processed" and db.open_items() == {}


def test_a_failed_refund_alerts_and_is_not_retried(env):
    db, rzp, rec, alerts = env
    duplicate(db, rzp, rec)
    rzp.post_outcomes = ["pending"]
    run(db, rec)
    rzp.refunds[db.actions["pay_2"]["provider_refund_id"]]["status"] = "failed"
    db.advance(1 / 96)
    run(db, rec)
    assert db.actions["pay_2"]["state"] == "failed" and len(rzp.refund_posts) == 1
    assert any("failed" in m for _, m in alerts)


def test_state_never_moves_backwards(env):
    db, rzp, rec, alerts = env
    duplicate(db, rzp, rec)
    run(db, rec)
    action = db.actions["pay_2"]
    assert action["state"] == "processed"
    db.update_refund_action(action["id"], state="created")
    assert db.actions["pay_2"]["state"] == "processed"


def test_an_obligation_that_stopped_being_valid_gets_no_refund(env):
    db, rzp, _, alerts = env
    tracker = Reconciler(db, rzp, lambda *a: alerts.append(a), auto_refunds=False)
    order = duplicate(db, rzp, tracker)
    run(db, tracker)  # tracked as duplicate, nothing sent
    assert db.open_items()[("payment", "pay_2")] == "duplicate"
    order["payment_id"] = None  # the funding payment is no longer known: not a proven duplicate
    Reconciler(db, rzp, lambda *a: alerts.append(a), auto_refunds=True)._refund_phase(db.now)
    assert rzp.refund_posts == [] and "pay_2" not in db.actions


def test_live_keys_never_post(env):
    db, rzp, _, alerts = env
    rec = Reconciler(db, rzp, lambda *a: alerts.append(a), auto_refunds=False)
    duplicate(db, rzp, rec)
    run(db, rec)
    run(db, rec)
    assert rzp.refund_posts == [] and db.open_items()[("payment", "pay_2")] == "duplicate"


# --- heartbeat ------------------------------------------------------------------------------


class _Resp:
    def __init__(self):
        self.headers = {}


def _beat(monkeypatch, db, enabled=True):
    monkeypatch.setattr(api_module, "_get_db", lambda: db)
    monkeypatch.setattr(api_module, "_razorpay_enabled", lambda: enabled)
    resp = _Resp()
    body = asyncio.run(api_module.billing_heartbeat(resp))
    assert resp.headers["Cache-Control"] == "no-store"
    return body


def test_heartbeat_reports_age_and_staleness(monkeypatch):
    db = ReconcileFake()
    assert _beat(monkeypatch, db) == {"status": "never", "last_success_age_seconds": None}
    db.state["last_success_at"] = db.now - timedelta(minutes=20)
    assert _beat(monkeypatch, db) == {"status": "ok", "last_success_age_seconds": 1200}
    db.state["last_success_at"] = db.now - timedelta(minutes=61)
    assert _beat(monkeypatch, db)["status"] == "stale"
    db.state["last_success_at"] = db.now + timedelta(hours=1)
    assert _beat(monkeypatch, db)["status"] == "stale"  # a future timestamp is wrong
    assert _beat(monkeypatch, db, enabled=False) == {"status": "disabled"}


def test_heartbeat_fails_when_the_database_does(monkeypatch):
    class Broken:
        def read_reconcile_heartbeat(self):
            raise RuntimeError("db down")

    monkeypatch.setattr(api_module, "_get_db", lambda: Broken())
    monkeypatch.setattr(api_module, "_razorpay_enabled", lambda: True)
    with pytest.raises(HTTPException) as excinfo:
        asyncio.run(api_module.billing_heartbeat(_Resp()))
    assert excinfo.value.status_code == 503

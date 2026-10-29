"""Billing behaviour through the API (D-024), against tests/billing_fake.py.

Replaces the BillingDBStub tests that lived in test_security.py: the same
guarantees (exactly one grant per order, foreign orders refused, the webhook
grants when the browser call is lost, unsigned webhooks rejected, refunds
revoke, expired periods lose access) plus switching, stacking, Lifetime,
partial refunds and capture checks.
"""

import asyncio
import importlib
import json
from datetime import timedelta

import pytest
from fastapi import HTTPException

from tests.billing_fake import BillingFake

api_module = importlib.import_module("api.app")


def _run(coro):
    return asyncio.run(coro)


@pytest.fixture()
def fake(monkeypatch):
    stub = BillingFake()
    monkeypatch.setattr(api_module, "_get_db", lambda: stub)
    monkeypatch.setattr(api_module, "_utcnow", lambda: stub.now)
    monkeypatch.setattr(api_module, "RAZORPAY_KEY_ID", "rzp_test_x")
    monkeypatch.setattr(api_module, "RAZORPAY_KEY_SECRET", "secret")
    monkeypatch.setattr(api_module, "RAZORPAY_WEBHOOK_SECRET", "whsec")
    monkeypatch.setattr(api_module, "_verify_razorpay_webhook", lambda body, sig: True)
    monkeypatch.setattr(api_module, "_verify_razorpay_signature", lambda message, sig: True)
    monkeypatch.setattr(
        api_module,
        "_require_session",
        lambda authorization: ("t", {**stub.users[42], "user_id": 42, "is_admin": False}),
    )
    return stub


def _session(fake):
    return {**fake.users[42], "user_id": 42, "is_admin": False}


def _captured(order, payment_id, **overrides):
    payment = {
        "id": payment_id,
        "order_id": order["order_id"],
        "amount": order["amount"],
        "currency": "INR",
        "status": "captured",
    }
    payment.update(overrides)
    return payment


class _Request:
    def __init__(self, event, headers=None):
        self.headers = {"X-Razorpay-Signature": "sig", **(headers or {})}
        self._event = event

    async def body(self):
        return json.dumps(self._event).encode()

    async def json(self):
        return self._event


def _webhook(event, headers=None):
    return _run(api_module.razorpay_webhook(_Request(event, headers)))


def _pay(fake, order_id, payment_id, event="payment.captured"):
    order = fake.orders[order_id]
    return _webhook({"event": event, "payload": {"payment": {"entity": _captured(order, payment_id)}}})


def _refund(fake, order_id, refund_id, amount=None, refunded_total=None, payment_id=None):
    order = fake.orders[order_id]
    pid = payment_id or order["payment_id"]
    payment = {"id": pid, "order_id": order_id, "amount": order["amount"]}
    if refunded_total is not None:
        payment["amount_refunded"] = refunded_total
    return _webhook({
        "event": "refund.processed",
        "payload": {
            "refund": {"entity": {"id": refund_id, "payment_id": pid,
                                  "amount": order["amount"] if amount is None else amount}},
            "payment": {"entity": payment},
        },
    })


def _verify(fake, monkeypatch, order_id, payment_id, payment=None):
    order = fake.orders[order_id]
    monkeypatch.setattr(api_module, "_fetch_razorpay_payment", lambda pid: payment or _captured(order, pid))
    request = api_module.RazorpayVerifyRequest(order_id=order_id, payment_id=payment_id, signature="s")
    return _run(api_module.verify_razorpay_payment(request, authorization="Bearer t"))


def _entitlement(fake):
    return _run(api_module.billing_entitlement(authorization="Bearer t"))


# --- exactly once ------------------------------------------------------------


def test_an_order_grants_exactly_one_period(fake, monkeypatch):
    fake.add_order("order_1", "starter")
    assert _verify(fake, monkeypatch, "order_1", "pay_aaaaaa1").plan == "starter"
    # The webhook arriving after the browser call grants nothing more.
    assert _pay(fake, "order_1", "pay_aaaaaa1") == {"status": "ok"}
    assert len(fake.grants) == 1 and fake.users[42]["trial_used"] is True


def test_verify_refuses_an_order_belonging_to_another_user(fake, monkeypatch):
    fake.add_order("order_1", "starter", user_id=7)
    with pytest.raises(HTTPException) as excinfo:
        _verify(fake, monkeypatch, "order_1", "pay_aaaaaa1")
    assert excinfo.value.status_code == 404 and fake.grants == []


def test_webhook_grants_when_the_browser_call_never_arrives(fake):
    fake.add_order("order_1", "starter")
    assert _pay(fake, "order_1", "pay_aaaaaa1") == {"status": "granted"}
    assert fake.users[42]["plan"] == "starter" and fake.users[42]["subscription_status"] == "active"


def test_webhook_rejects_an_unsigned_payload(fake, monkeypatch):
    monkeypatch.setattr(api_module, "_verify_razorpay_webhook", lambda body, sig: False)
    fake.add_order("order_1", "starter")
    with pytest.raises(HTTPException) as excinfo:
        _pay(fake, "order_1", "pay_aaaaaa1")
    assert excinfo.value.status_code == 400 and fake.grants == []


# --- capture, amount and currency are checked before granting ----------------


def test_verify_does_not_grant_an_uncaptured_payment(fake, monkeypatch):
    order = fake.add_order("order_1", "starter")
    with pytest.raises(HTTPException) as excinfo:
        _verify(fake, monkeypatch, "order_1", "pay_aaaaaa1", payment=_captured(order, "pay_aaaaaa1", status="authorized"))
    assert excinfo.value.status_code == 409 and fake.grants == []
    assert fake.orders["order_1"]["status"] == "created"  # the webhook can still grant


@pytest.mark.parametrize("override", [{"amount": 100}, {"currency": "USD"}, {"order_id": "order_other"}])
def test_webhook_does_not_grant_a_mismatched_payment(fake, override):
    order = fake.add_order("order_1", "annual")
    payment = _captured(order, "pay_aaaaaa1", **override)
    assert _webhook({"event": "payment.captured", "payload": {"payment": {"entity": payment}}}) == {"status": "ok"}
    assert fake.grants == [] and fake.users[42]["plan"] == "free"


def test_verify_rejects_a_malformed_payment_id(fake, monkeypatch):
    fake.add_order("order_1", "starter")
    with pytest.raises(HTTPException) as excinfo:
        _verify(fake, monkeypatch, "order_1", "../orders")
    assert excinfo.value.status_code == 400


# --- switching never discards paid time --------------------------------------


def test_switch_to_starter_keeps_annual_until_it_ends(fake):
    fake.add_order("order_a", "annual")
    _pay(fake, "order_a", "pay_annual1")
    annual_end = fake.users[42]["subscription_renewal"]
    fake.advance(30)
    fake.add_order("order_s", "starter")
    assert _pay(fake, "order_s", "pay_start1") == {"status": "granted"}
    assert fake.users[42]["plan"] == "annual" and fake.users[42]["subscription_renewal"] == annual_end
    view = _entitlement(fake)
    assert [s.plan_code for s in view.segments] == ["annual", "starter"]
    assert view.segments[1].start == annual_end and view.segments[1].end == annual_end + timedelta(days=30)

    # After Annual ends, the next request finds Starter running, not "free".
    fake.advance(340)
    assert api_module._subscription_active(_session(fake)) is True
    assert fake.users[42]["plan"] == "starter"
    fake.advance(30)
    assert api_module._subscription_active(_session(fake)) is False
    assert fake.users[42]["plan"] == "free"


def test_extend_adds_to_the_end_instead_of_resetting(fake):
    fake.add_order("o1", "annual")
    _pay(fake, "o1", "pay_annual1")
    end = fake.users[42]["subscription_renewal"]
    fake.advance(100)
    fake.add_order("o2", "annual")
    _pay(fake, "o2", "pay_annual2")
    assert _entitlement(fake).segments[-1].end == end + timedelta(days=365)


def test_lifetime_bought_during_annual_takes_effect_now_and_blocks_purchases(fake, monkeypatch):
    fake.add_order("o1", "annual")
    _pay(fake, "o1", "pay_annual1")
    annual_end = fake.users[42]["subscription_renewal"]
    fake.advance(1)
    fake.add_order("o2", "lifetime")
    _pay(fake, "o2", "pay_life1")
    assert fake.users[42]["plan"] == "lifetime" and fake.users[42]["subscription_renewal"] is None
    view = _entitlement(fake)
    assert (view.plan, view.subscription_status) == ("lifetime", "active")
    assert [(s.plan_code, s.start, s.end) for s in view.segments] == [("lifetime", fake.now, None)]
    assert view.purchases_blocked is True
    assert view.next_purchase_starts == annual_end  # timed chain only; the UI never shows it for Lifetime
    with pytest.raises(HTTPException) as excinfo:
        _run(api_module.create_razorpay_order(api_module.RazorpayOrderRequest(plan_code="starter"), authorization="t"))
    assert excinfo.value.status_code == 409


def test_refunding_lifetime_mid_annual_returns_the_annual_with_its_original_end(fake):
    fake.add_order("o1", "annual")
    _pay(fake, "o1", "pay_annual1")
    annual_end = fake.users[42]["subscription_renewal"]
    fake.add_order("o2", "lifetime")
    _pay(fake, "o2", "pay_life1")
    fake.advance(10)
    assert _refund(fake, "o2", "rfnd_l") == {"status": "revoked"}
    assert fake.users[42]["plan"] == "annual" and fake.users[42]["subscription_renewal"] == annual_end
    view = _entitlement(fake)
    assert [(s.plan_code, s.end) for s in view.segments] == [("annual", annual_end)]
    assert view.purchases_blocked is False and view.next_purchase_starts == annual_end


def test_refunding_lifetime_after_the_annual_ended_leaves_free(fake):
    fake.add_order("o1", "annual")
    _pay(fake, "o1", "pay_annual1")
    fake.add_order("o2", "lifetime")
    _pay(fake, "o2", "pay_life1")
    fake.advance(400)
    assert api_module._subscription_active(_session(fake)) is True
    assert _refund(fake, "o2", "rfnd_l") == {"status": "revoked"}
    assert fake.users[42]["plan"] == "free"
    assert api_module._subscription_active(_session(fake)) is False


def test_a_partial_refund_keeps_lifetime(fake):
    fake.add_order("o1", "annual")
    _pay(fake, "o1", "pay_annual1")
    fake.add_order("o2", "lifetime")  # 200000 paise
    _pay(fake, "o2", "pay_life1")
    assert _refund(fake, "o2", "rfnd_l", amount=50000) == {"status": "partial"}
    assert fake.users[42]["plan"] == "lifetime"
    assert _entitlement(fake).purchases_blocked is True


def test_a_payment_that_lands_after_lifetime_is_kept_for_refund_not_granted(fake):
    # Two checkouts were open; Lifetime was paid first.
    fake.add_order("o_life", "lifetime")
    fake.add_order("o_starter", "starter")
    _pay(fake, "o_life", "pay_life1")
    assert _pay(fake, "o_starter", "pay_start1") == {"status": "refund_due"}
    assert fake.orders["o_starter"]["status"] == "refund_due"
    assert [g["order_id"] for g in fake.grants] == ["o_life"]


def test_order_endpoint_records_the_purchase_terms(fake, monkeypatch):
    class _Resp:
        def raise_for_status(self):
            pass

        def json(self):
            return {"id": "order_new", "amount": 50000, "currency": "INR", "status": "created"}

    monkeypatch.setattr(api_module.requests, "post", lambda *a, **k: _Resp())
    response = _run(api_module.create_razorpay_order(api_module.RazorpayOrderRequest(plan_code="annual"), authorization="t"))
    assert response.order_id == "order_new"
    assert fake.orders["order_new"]["plan_code"] == "annual" and fake.orders["order_new"]["interval_days"] == 365


# --- refunds revoke only their own purchase -----------------------------------


def test_refund_of_the_current_purchase_ends_access(fake):
    fake.add_order("order_1", "starter")
    _pay(fake, "order_1", "pay_aaaaaa1")
    assert _refund(fake, "order_1", "rfnd_1") == {"status": "revoked"}
    assert fake.users[42]["plan"] == "free"
    assert _refund(fake, "order_1", "rfnd_1") == {"status": "duplicate"}  # replay


def test_refund_of_a_queued_switch_leaves_the_current_plan_alone(fake):
    fake.add_order("o_a", "annual")
    _pay(fake, "o_a", "pay_annual1")
    annual_end = fake.users[42]["subscription_renewal"]
    fake.add_order("o_s", "starter")
    _pay(fake, "o_s", "pay_start1")
    assert _refund(fake, "o_s", "rfnd_s") == {"status": "revoked"}
    assert fake.users[42]["plan"] == "annual" and fake.users[42]["subscription_renewal"] == annual_end
    assert [s.plan_code for s in _entitlement(fake).segments] == ["annual"]


def test_refund_of_the_current_purchase_starts_the_queued_one_now(fake):
    fake.add_order("o_a", "annual")
    _pay(fake, "o_a", "pay_annual1")
    fake.add_order("o_s", "starter")
    _pay(fake, "o_s", "pay_start1")
    fake.advance(100)
    _refund(fake, "o_a", "rfnd_a")
    assert fake.users[42]["plan"] == "starter"
    assert fake.users[42]["subscription_renewal"] == fake.now + timedelta(days=30)


def test_partial_refunds_revoke_only_when_they_reach_the_full_amount(fake):
    fake.add_order("order_1", "annual")  # 50000 paise
    _pay(fake, "order_1", "pay_annual1")
    assert _refund(fake, "order_1", "rfnd_1", amount=20000) == {"status": "partial"}
    assert fake.users[42]["plan"] == "annual"
    assert _refund(fake, "order_1", "rfnd_2", amount=30000) == {"status": "revoked"}
    assert fake.users[42]["plan"] == "free"


def test_a_payment_refunded_before_settlement_never_funds_the_order(fake):
    fake.add_order("order_1", "starter")
    assert _refund(fake, "order_1", "rfnd_1", payment_id="pay_aaaaaa1") == {"status": "unsettled"}
    assert _pay(fake, "order_1", "pay_aaaaaa1") == {"status": "refunded_payment"}
    assert fake.grants == []
    # Another attempt on the same order can still fund it.
    assert _pay(fake, "order_1", "pay_bbbbbb2") == {"status": "granted"}


def test_a_partial_refund_before_settlement_does_not_block_the_order(fake):
    fake.add_order("order_1", "starter")  # 5000 paise
    assert _refund(fake, "order_1", "rfnd_1", amount=1000, payment_id="pay_aaaaaa1") == {"status": "unsettled"}
    assert _pay(fake, "order_1", "pay_aaaaaa1") == {"status": "granted"}


def test_refunding_a_duplicate_payment_never_revokes_the_plan(fake):
    # Two captured payments on one order: only the first funded the grant.
    fake.add_order("order_1", "annual")
    _pay(fake, "order_1", "pay_first01")
    assert _refund(fake, "order_1", "rfnd_dup", payment_id="pay_second2") == {"status": "other_payment"}
    assert fake.users[42]["plan"] == "annual"
    assert fake.orders["order_1"]["status"] == "paid"


def test_overlapping_cumulative_evidence_is_not_double_counted(fake):
    # Refund 1 arrives late carrying a cumulative total that already includes
    # refund 2; the old max(previous + delta, cumulative) overshot here.
    fake.add_order("order_1", "annual")  # 50000 paise
    _pay(fake, "order_1", "pay_annual1")
    assert _refund(fake, "order_1", "rfnd_2", amount=20000) == {"status": "partial"}
    assert _refund(fake, "order_1", "rfnd_1", amount=15000, refunded_total=35000) == {"status": "partial"}
    assert fake.users[42]["plan"] == "annual"  # 35000 of 50000 refunded
    assert _refund(fake, "order_1", "rfnd_3", amount=15000) == {"status": "revoked"}


def test_refund_of_a_refund_due_payment_closes_it_without_touching_access(fake):
    fake.add_order("o_life", "lifetime")
    fake.add_order("o_s", "starter")
    _pay(fake, "o_life", "pay_life1")
    _pay(fake, "o_s", "pay_start1")
    assert _refund(fake, "o_s", "rfnd_s") == {"status": "refund_due_closed"}
    assert fake.orders["o_s"]["status"] == "refunded" and fake.users[42]["plan"] == "lifetime"


def test_refund_of_a_pre_ledger_grant_goes_to_review(fake):
    # Migrated (legacy) grant: its funding payment was never recorded.
    order = fake.add_order("order_old", "annual")
    order["status"] = "paid"
    fake.grants.append({"id": 1, "user_id": 42, "plan_code": "annual", "source": "legacy",
                        "order_id": "order_old", "duration": timedelta(days=365),
                        "allocated_at": fake.now, "refunded_amount": 0, "revoked_at": None})
    fake.refresh_entitlement(42, api_module.billing.project)
    assert _refund(fake, "order_old", "rfnd_x", payment_id="pay_unknown") == {"status": "needs_review"}
    assert fake.users[42]["plan"] == "annual"


def test_refund_without_an_order_entity_is_found_by_payment_id(fake):
    fake.add_order("order_1", "starter")
    _pay(fake, "order_1", "pay_aaaaaa1")
    event = {
        "event": "refund.processed",
        "payload": {"refund": {"entity": {"id": "rfnd_1", "payment_id": "pay_aaaaaa1", "amount": 5000}}},
    }
    assert _webhook(event) == {"status": "revoked"}


# --- trial and lapse -----------------------------------------------------------


def test_trial_then_purchase_keeps_the_trial_days(fake):
    status = _run(api_module.start_billing_trial(api_module.TrialStartRequest(plan_code="starter"), authorization="t"))
    assert status.subscription_status == "trialing"
    trial_end = status.subscription_renewal
    fake.advance(5)
    fake.add_order("o1", "annual")
    _pay(fake, "o1", "pay_annual1")
    assert fake.users[42]["subscription_status"] == "trialing"
    assert _entitlement(fake).segments[1].start == trial_end
    with pytest.raises(HTTPException) as excinfo:  # one trial only
        _run(api_module.start_billing_trial(api_module.TrialStartRequest(plan_code="starter"), authorization="t"))
    assert excinfo.value.status_code == 409


def test_an_expired_period_loses_access(fake):
    fake.add_order("order_1", "starter")
    _pay(fake, "order_1", "pay_aaaaaa1")
    fake.advance(31)
    assert api_module._subscription_active(_session(fake)) is False
    assert fake.users[42]["plan"] == "free"


def test_a_running_period_needs_no_database_round_trip(fake, monkeypatch):
    fake.add_order("order_1", "starter")
    _pay(fake, "order_1", "pay_aaaaaa1")
    monkeypatch.setattr(fake, "refresh_entitlement", lambda *a, **k: pytest.fail("refreshed while active"))
    assert api_module._subscription_active(_session(fake)) is True


def test_free_plan_has_no_paid_access(fake):
    assert api_module._subscription_active(_session(fake)) is False


def test_cancel_changes_nothing_because_nothing_renews(fake):
    fake.add_order("order_1", "annual")
    _pay(fake, "order_1", "pay_annual1")
    before = dict(fake.users[42])
    status = _run(api_module.cancel_subscription(authorization="t"))
    assert status.plan == "annual" and fake.users[42] == before


def test_order_status_is_visible_to_its_owner_only(fake):
    fake.add_order("order_1", "starter")
    _pay(fake, "order_1", "pay_aaaaaa1")
    status = _run(api_module.razorpay_order_status("order_1", authorization="t"))
    assert status.status == "paid"
    fake.add_order("order_other", "starter", user_id=7)
    with pytest.raises(HTTPException) as excinfo:
        _run(api_module.razorpay_order_status("order_other", authorization="t"))
    assert excinfo.value.status_code == 404


def test_grant_log_names_the_plan_bought_not_the_plan_running(fake, caplog):
    fake.add_order("o_a", "annual")
    _pay(fake, "o_a", "pay_annual1")
    fake.add_order("o_s", "starter")
    with caplog.at_level("INFO"):
        _pay(fake, "o_s", "pay_start1")
    assert any("order_id=o_s" in r.getMessage() and "plan=starter" in r.getMessage() for r in caplog.records)

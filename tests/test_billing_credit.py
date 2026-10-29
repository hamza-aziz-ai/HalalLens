"""Upgrade credit at checkout for Lifetime (D-030).

The calculator (api/billing.py) on frozen clocks, then checkout, settlement,
refunds and the reconciler through the API against tests/billing_fake.py.
The SQL, the CHECK constraint and concurrency are in
tests/test_billing_postgres.py (opt-in).
"""

import itertools
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import HTTPException, Response

from api import billing
from api.razorpay_client import RazorpayError, payment_created_at
from jobs.reconcile_payments import Reconciler
from tests.billing_fake import FakeRazorpay, ReconcileFake
from tests.test_billing import _captured, _refund, _run, _webhook, api_module, fake  # noqa: F401 (fixture)

T0 = datetime(2026, 1, 1, tzinfo=timezone.utc)
DAY = timedelta(days=1)
LIST = 200000  # Lifetime, paise


def grant(gid, plan, at_day, days, *, source="razorpay", order_id=None, revoked_day=None):
    return {
        "id": gid, "plan_code": plan, "source": source, "order_id": order_id,
        "allocated_at": T0 + at_day * DAY, "duration": None if days is None else days * DAY,
        "revoked_at": None if revoked_day is None else T0 + revoked_day * DAY,
    }


def paid(order_id, amount, *, refunded=0, pending=False, currency="INR", status="paid"):
    return {order_id: {"order_id": order_id, "amount": amount, "currency": currency, "status": status,
                       "payment_id": f"pay_{order_id}", "refunded": refunded, "refund_pending": pending}}


# --- the calculator ------------------------------------------------------------


def test_running_grant_credits_the_unused_share_floored():
    grants = [grant(1, "annual", 0, 365, order_id="o1")]
    quote = billing.upgrade_quote(grants, paid("o1", 50000), T0 + 100 * DAY, LIST)
    # 50000 * 265/365 = 36301.37 -> 36301
    assert (quote["credit_amount"], quote["amount"], quote["blocked"]) == (36301, LIST - 36301, False)
    (source,) = quote["sources"]
    assert source["state"] == "running" and source["payment_id"] == "pay_o1" and source["net_paid"] == 50000


def test_exact_boundaries_start_end_and_microseconds():
    grants = [grant(1, "starter", 0, 30, order_id="o1")]
    funding = paid("o1", 5000)
    assert billing.upgrade_quote(grants, funding, T0, LIST)["credit_amount"] == 5000  # nothing used yet
    assert billing.upgrade_quote(grants, funding, T0 + 30 * DAY, LIST)["credit_amount"] == 0  # ended
    one_us_left = T0 + 30 * DAY - timedelta(microseconds=1)
    assert billing.upgrade_quote(grants, funding, one_us_left, LIST)["credit_amount"] == 0  # floor
    assert billing.credit_sources(grants, funding, T0 + 30 * DAY)[0]["state"] == "expired"


def test_queued_grant_gives_its_full_net_paid_and_floors_are_per_source():
    grants = [grant(1, "starter", 0, 30, order_id="o1"), grant(2, "annual", 0, 365, order_id="o2")]
    funding = {**paid("o1", 5000), **paid("o2", 50000)}
    quote = billing.upgrade_quote(grants, funding, T0 + DAY, LIST)
    assert [(s["state"], s["credit"]) for s in quote["sources"]] == [("running", 4833), ("queued", 50000)]
    assert quote["credit_amount"] == 54833 and quote["amount"] == LIST - 54833


def test_trial_and_legacy_grants_give_no_credit():
    grants = [grant(1, "starter", 0, 30, source="trial"), grant(2, "annual", 0, 365, source="legacy", order_id="o2")]
    assert billing.upgrade_quote(grants, paid("o2", 50000), T0 + DAY, LIST)["credit_amount"] == 0


def test_partial_refunds_reduce_the_net_paid_and_the_order_amount_wins_over_the_catalogue():
    grants = [grant(1, "annual", 0, 365, order_id="o1")]
    # Bought at an old price of 400 rupees, 10000 paise refunded: credit is on 30000, not 50000.
    assert billing.upgrade_quote(grants, paid("o1", 40000, refunded=10000), T0, LIST)["credit_amount"] == 30000
    assert billing.upgrade_quote(grants, paid("o1", 40000, refunded=90000), T0, LIST)["credit_amount"] == 0


@pytest.mark.parametrize("funding", [
    paid("o1", 50000, pending=True),
    paid("o1", 50000, currency="USD"),
    paid("o1", 50000, status="refunded"),
    {"o1": {**paid("o1", 50000)["o1"], "payment_id": None}},
    {},
])
def test_ineligible_sources_give_nothing(funding):
    assert billing.credit_sources([grant(1, "annual", 0, 365, order_id="o1")], funding, T0) == []


def test_revoked_grants_give_nothing():
    grants = [grant(1, "annual", 0, 365, order_id="o1", revoked_day=0)]
    assert billing.credit_sources(grants, paid("o1", 50000), T0) == []


def test_credit_never_exceeds_the_list_price_and_below_one_rupee_is_blocked():
    grants = [grant(i, "annual", 0, 365, order_id=f"o{i}") for i in range(1, 6)]
    funding = {k: v for i in range(1, 6) for k, v in paid(f"o{i}", 50000).items()}
    quote = billing.upgrade_quote(grants, funding, T0, LIST)
    assert (quote["credit_amount"], quote["amount"], quote["blocked"]) == (LIST, 0, True)
    assert billing.upgrade_quote(grants[:1], paid("o1", 50000), T0, 50099)["blocked"] is True   # 99 paise
    assert billing.upgrade_quote(grants[:1], paid("o1", 50000), T0, 50100)["blocked"] is False  # one rupee


def test_naive_clock_is_refused():
    with pytest.raises(ValueError):
        billing.credit_sources([], {}, datetime(2026, 1, 1))


def _terms(sources, valid_until):
    return {"credit_version": 1, "price_valid_until": valid_until, "credit_detail": {"sources": sources}}


def test_refusal_window_is_inclusive_at_second_resolution():
    grants = [grant(1, "annual", 0, 365, order_id="o1")]
    funding = paid("o1", 50000)
    valid_until = T0 + timedelta(minutes=15, microseconds=500000)
    order = _terms(billing.credit_sources(grants, funding, T0), valid_until)
    edge = int((T0 + timedelta(minutes=15)).timestamp())
    assert billing.credit_refusal(order, grants, funding, edge) is None
    assert billing.credit_refusal(order, grants, funding, edge + 1) == "price_expired"


def test_refusal_when_a_credited_source_changed_but_not_for_a_zero_credit_source():
    grants = [grant(1, "starter", 0, 30, order_id="o1"), grant(2, "annual", 0, 365, order_id="o2")]
    funding = {**paid("o1", 5000), **paid("o2", 50000)}
    sources = billing.credit_sources(grants, funding, T0 + 40 * DAY)  # starter expired: credit 0
    order = _terms(sources, T0 + 41 * DAY)
    at = int((T0 + 40 * DAY).timestamp())
    assert billing.credit_refusal(order, grants, funding, at) is None
    assert billing.credit_refusal(order, grants, {**funding, **paid("o1", 5000, refunded=5000)}, at) is None
    for changed in (paid("o2", 50000, refunded=1), paid("o2", 50000, pending=True), {"o2": None}):
        changed_funding = {**funding, **{k: v for k, v in changed.items() if v}}
        if changed == {"o2": None}:
            changed_funding.pop("o2")
        assert billing.credit_refusal(order, grants, changed_funding, at) == "credit_changed"
    revoked = [grants[0], grant(2, "annual", 0, 365, order_id="o2", revoked_day=40)]
    assert billing.credit_refusal(order, revoked, funding, at) == "credit_changed"


def test_payment_created_at_reads_only_a_positive_integer():
    assert payment_created_at({"created_at": 1767225600}) == 1767225600
    for bad in ({}, {"created_at": None}, {"created_at": "1767225600"}, {"created_at": True}, {"created_at": 0}):
        assert payment_created_at(bad) is None


# --- checkout, settlement and refunds through the API ----------------------------


@pytest.fixture()
def rzp_orders(fake, monkeypatch):
    """Razorpay order creation that echoes the requested amount; records each request."""

    posted = []
    ids = itertools.count(1)

    class _Resp:
        def __init__(self, body):
            self.body = body

        def raise_for_status(self):
            pass

        def json(self):
            return self.body

    def post(url, json, auth, timeout):
        posted.append(json)
        return _Resp({"id": f"order_n{next(ids)}", "amount": json["amount"], "currency": "INR", "status": "created"})

    monkeypatch.setattr(api_module.requests, "post", post)
    return posted


def _buy(fake, plan_code):
    return _run(api_module.create_razorpay_order(api_module.RazorpayOrderRequest(plan_code=plan_code), authorization="t"))


def _epoch(when):
    return int(when.timestamp())


def _pay_at(order_id, payment_id, fake, created_at, event="payment.captured"):
    order = fake.orders[order_id]
    payment = _captured(order, payment_id)
    if created_at is not None:
        payment["created_at"] = created_at
    return _webhook({"event": event, "payload": {"payment": {"entity": payment}}})


def _entitlement():
    response = Response()
    view = _run(api_module.billing_entitlement(response, authorization="Bearer t"))
    return view, response


def _annual_bought_100_days_ago(fake, rzp_orders):
    order = _buy(fake, "annual")
    assert _pay_at(order.order_id, "pay_annual1", fake, _epoch(fake.now)) == {"status": "granted"}
    fake.advance(100)
    return order.order_id


def test_preview_and_order_carry_the_same_breakdown(fake, rzp_orders):
    annual = _annual_bought_100_days_ago(fake, rzp_orders)
    view, response = _entitlement()
    assert response.headers["Cache-Control"] == "no-store"
    q = view.lifetime_quote
    assert (q.plan_code, q.list_amount, q.credit_amount, q.amount, q.blocked) == ("lifetime", LIST, 36301, 163699, False)
    assert q.valid_for_seconds == 900

    order = _buy(fake, "lifetime")
    assert (order.list_amount, order.credit_amount, order.amount) == (LIST, 36301, 163699)
    assert rzp_orders[-1]["amount"] == 163699  # Razorpay charges the payable, not the list price
    stored = fake.orders[order.order_id]
    assert stored["credit_version"] == 1 and stored["priced_at"] == fake.now
    assert stored["price_valid_until"] == fake.now + timedelta(minutes=15) == order.price_valid_until
    (source,) = stored["credit_detail"]["sources"]
    assert (source["order_id"], source["payment_id"], source["net_paid"], source["credit"]) == (
        annual, "pay_annual1", 50000, 36301)


def test_receipts_are_unique_within_one_second(fake, rzp_orders):
    _buy(fake, "starter")
    _buy(fake, "starter")
    assert rzp_orders[0]["receipt"] != rzp_orders[1]["receipt"] and len(rzp_orders[0]["receipt"]) <= 40


def test_ordinary_orders_keep_list_price_and_no_credit_terms(fake, rzp_orders):
    _annual_bought_100_days_ago(fake, rzp_orders)
    order = _buy(fake, "starter")
    stored = fake.orders[order.order_id]
    assert (order.amount, order.list_amount, order.credit_amount) == (5000, 5000, 0)
    assert stored["credit_version"] is None and stored["price_valid_until"] is None
    # Settles without any attempt time, exactly as before D-030.
    assert _pay_at(order.order_id, "pay_start1", fake, None) == {"status": "granted"}


def test_a_razorpay_order_for_another_amount_is_not_stored(fake, monkeypatch, rzp_orders):
    _annual_bought_100_days_ago(fake, rzp_orders)
    before = set(fake.orders)

    class _Wrong:
        def raise_for_status(self):
            pass

        def json(self):
            return {"id": "order_wrong", "amount": LIST, "currency": "INR", "status": "created"}

    monkeypatch.setattr(api_module.requests, "post", lambda *a, **k: _Wrong())
    with pytest.raises(HTTPException) as excinfo:
        _buy(fake, "lifetime")
    assert excinfo.value.status_code == 503 and set(fake.orders) == before


def test_payable_below_one_rupee_blocks_checkout(fake, rzp_orders):
    fake.plans["lifetime"]["price_inr"] = 500
    order = _buy(fake, "annual")
    _pay_at(order.order_id, "pay_annual1", fake, _epoch(fake.now))
    assert _entitlement()[0].lifetime_quote.blocked is True
    count = len(rzp_orders)
    with pytest.raises(HTTPException) as excinfo:
        _buy(fake, "lifetime")
    assert excinfo.value.status_code == 409 and "contact support" in excinfo.value.detail
    assert len(rzp_orders) == count  # no Razorpay order


def test_a_valid_credited_payment_grants_lifetime_and_keeps_the_annual_underneath(fake, rzp_orders):
    annual = _annual_bought_100_days_ago(fake, rzp_orders)
    order = _buy(fake, "lifetime")
    fake.advance(5 / 1440)
    assert _pay_at(order.order_id, "pay_life1", fake, _epoch(fake.now)) == {"status": "granted"}
    assert fake.users[42]["plan"] == "lifetime"
    assert next(g for g in fake.grants if g["order_id"] == annual)["revoked_at"] is None
    view, _ = _entitlement()
    assert view.lifetime_quote is None and view.purchases_blocked is True
    # A replayed webhook grants nothing more.
    assert _pay_at(order.order_id, "pay_life1", fake, _epoch(fake.now)) == {"status": "ok"}
    assert len(fake.grants) == 2


def test_a_source_refunded_between_quote_and_payment_makes_it_refund_due(fake, monkeypatch, rzp_orders):
    annual = _annual_bought_100_days_ago(fake, rzp_orders)
    order = _buy(fake, "lifetime")
    assert _refund(fake, annual, "rfnd_a", amount=10000) == {"status": "partial"}
    monkeypatch.setattr(api_module, "_fetch_razorpay_payment",
                        lambda pid: {**_captured(fake.orders[order.order_id], pid), "created_at": _epoch(fake.now)})
    request = api_module.RazorpayVerifyRequest(order_id=order.order_id, payment_id="pay_life01", signature="s")
    with pytest.raises(HTTPException) as excinfo:
        _run(api_module.verify_razorpay_payment(request, authorization="t"))
    assert excinfo.value.status_code == 409 and "refunded" in excinfo.value.detail
    assert "Lifetime access already covers" not in excinfo.value.detail
    stored = fake.orders[order.order_id]
    assert (stored["status"], stored["refund_due_reason"], stored["payment_id"]) == ("refund_due", "credit_changed", "pay_life01")
    assert fake.users[42]["plan"] == "annual" and len(fake.grants) == 1
    status = _run(api_module.razorpay_order_status(order.order_id, authorization="t"))
    assert (status.status, status.reason) == ("refund_due", "credit_changed")


def test_an_attempt_created_after_the_window_is_refund_due(fake, rzp_orders):
    _annual_bought_100_days_ago(fake, rzp_orders)
    order = _buy(fake, "lifetime")
    late = _epoch(fake.now + timedelta(minutes=15)) + 1
    assert _pay_at(order.order_id, "pay_life1", fake, late) == {"status": "refund_due"}
    assert fake.orders[order.order_id]["refund_due_reason"] == "price_expired"
    assert fake.orders[order.order_id]["amount"] == 163699  # the refund owed is the charged amount


def test_a_late_capture_of_an_attempt_created_inside_the_window_is_honoured(fake, rzp_orders):
    _annual_bought_100_days_ago(fake, rzp_orders)
    order = _buy(fake, "lifetime")
    created = _epoch(fake.now + timedelta(minutes=15))  # the last second of the window
    fake.advance(1)  # captured a day later
    assert _pay_at(order.order_id, "pay_life1", fake, created) == {"status": "granted"}


def test_missing_attempt_time_is_fetched_and_otherwise_left_for_a_retry(fake, monkeypatch, rzp_orders):
    _annual_bought_100_days_ago(fake, rzp_orders)
    order = _buy(fake, "lifetime")
    calls = []

    def fetch_fails(self, payment_id):
        calls.append(payment_id)
        raise RazorpayError("down")

    monkeypatch.setattr(api_module.RazorpayClient, "fetch_payment", fetch_fails)
    assert _pay_at(order.order_id, "pay_life1", fake, None) == {"status": "retry"}
    assert calls == ["pay_life1"] and fake.orders[order.order_id]["status"] == "created" and len(fake.grants) == 1
    assert not any(e["event_id"] == "pay_life1" for e in fake.events)  # nothing recorded
    monkeypatch.setattr(api_module.RazorpayClient, "fetch_payment",
                        lambda self, pid: {"id": pid, "created_at": _epoch(fake.now)})
    assert _pay_at(order.order_id, "pay_life1", fake, None) == {"status": "granted"}


def test_two_credited_checkouts_settle_one_lifetime_and_refund_the_other(fake, rzp_orders):
    _annual_bought_100_days_ago(fake, rzp_orders)
    first, second = _buy(fake, "lifetime"), _buy(fake, "lifetime")
    assert _pay_at(first.order_id, "pay_life1", fake, _epoch(fake.now)) == {"status": "granted"}
    assert _pay_at(second.order_id, "pay_life2", fake, _epoch(fake.now)) == {"status": "refund_due"}
    assert fake.orders[second.order_id]["refund_due_reason"] == "lifetime_held"


def test_a_refunded_source_after_settlement_is_tracked_and_alerted_not_clawed_back(fake, monkeypatch, rzp_orders):
    alerts = []
    monkeypatch.setattr(api_module.billing_notifier, "notify", lambda *a: alerts.append(a))
    annual = _annual_bought_100_days_ago(fake, rzp_orders)
    order = _buy(fake, "lifetime")
    _pay_at(order.order_id, "pay_life1", fake, _epoch(fake.now))
    assert _refund(fake, annual, "rfnd_a") == {"status": "revoked"}
    assert fake.users[42]["plan"] == "lifetime"  # no access change beyond the existing rules
    item = fake.tracked[("credit_conflict", "rfnd_a")]
    assert (item["order_id"], item["resolved_at"]) == (order.order_id, None)
    assert len(alerts) == 1 and "credit_conflict" in alerts[0][1]
    assert _refund(fake, annual, "rfnd_a") == {"status": "duplicate"} and len(alerts) == 1


def test_a_lifetime_without_credit_is_an_ordinary_order_with_no_price_window(fake, rzp_orders):
    order = _buy(fake, "lifetime")
    stored = fake.orders[order.order_id]
    assert (order.amount, order.credit_amount) == (LIST, 0)
    assert stored["credit_version"] is None and stored["price_valid_until"] is None
    fake.advance(1)  # paid a day later: no window to miss
    assert _pay_at(order.order_id, "pay_life1", fake, None) == {"status": "granted"}


def test_refunding_a_source_that_gave_no_credit_raises_no_conflict(fake, rzp_orders):
    annual = _buy(fake, "annual")
    _pay_at(annual.order_id, "pay_annual1", fake, _epoch(fake.now))
    fake.advance(400)  # the Annual has expired: it gives 0 credit
    starter = _buy(fake, "starter")
    _pay_at(starter.order_id, "pay_start1", fake, _epoch(fake.now))
    fake.advance(10)
    order = _buy(fake, "lifetime")
    assert order.credit_amount > 0
    _pay_at(order.order_id, "pay_life1", fake, _epoch(fake.now))
    _refund(fake, annual.order_id, "rfnd_old")
    assert ("credit_conflict", "rfnd_old") not in fake.tracked
    _refund(fake, starter.order_id, "rfnd_start")
    assert ("credit_conflict", "rfnd_start") in fake.tracked


def test_full_lifetime_refund_returns_the_charge_and_later_upgrades_are_priced_fresh(fake, rzp_orders):
    _annual_bought_100_days_ago(fake, rzp_orders)
    order = _buy(fake, "lifetime")
    _pay_at(order.order_id, "pay_life1", fake, _epoch(fake.now))
    assert _refund(fake, order.order_id, "rfnd_l", amount=163698) == {"status": "partial"}
    assert fake.users[42]["plan"] == "lifetime"  # partial: kept
    assert _refund(fake, order.order_id, "rfnd_l2", amount=1) == {"status": "revoked"}  # reaches the charged amount
    assert fake.users[42]["plan"] == "annual"
    fake.advance(65)
    quote = _entitlement()[0].lifetime_quote
    assert quote.credit_amount == 50000 * 200 // 365  # 165 of 365 days used now


def test_an_unpaid_pre_migration_order_completes_exactly_as_before(fake):
    fake.add_order("order_old", "lifetime")  # backfilled: list = amount, no credit_version
    assert _pay_at("order_old", "pay_old1", fake, None) == {"status": "granted"}
    assert fake.users[42]["plan"] == "lifetime"


# --- the reconciler ---------------------------------------------------------------


def _credited_order(db, order_id, created):
    quote, priced_at = db.quote_upgrade(42, lambda g, f, now: billing.upgrade_quote(g, f, now, LIST))
    db.create_razorpay_order(
        user_id=42, order_id=order_id, amount=quote["amount"], currency="INR", status="created", payload={},
        plan_code="lifetime", interval_days=0, list_amount=LIST, credit_amount=quote["credit_amount"],
        priced_at=priced_at, price_valid_until=priced_at + billing.PRICE_VALIDITY, credit_version=1,
        credit_detail={"sources": quote["sources"]},
    )
    db.orders[order_id]["created_at"] = created
    return db.orders[order_id]


def test_reconciler_recovers_a_credited_order_and_alerts_on_a_later_source_refund():
    db = ReconcileFake()
    rzp = FakeRazorpay(db)
    alerts = []
    rec = Reconciler(db, rzp, lambda severity, message, details=None: alerts.append(message))
    annual = db.add_order("order_a", "annual")
    db.settle_razorpay_order(order_id="order_a", payment_id="pay_a", expected_user_id=None, event_type="t",
                             payload={}, project=billing.project, lifetime_held=billing.lifetime_held)
    rzp.pay("pay_a", annual)
    db.advance(100)
    annual["created_at"] = db.now  # keep the sweep window short (bootstrap: the first order)
    life = _credited_order(db, "order_l", db.now)
    assert life["amount"] == LIST - 36301
    rzp.pay("pay_l", life)  # webhook missed
    db.advance(20 / 1440)
    rec.run(db.now)
    assert db.users[42]["plan"] == "lifetime" and db.orders["order_l"]["status"] == "paid"
    rzp.refund("rfnd_a", "pay_a")  # the Annual refunded from the dashboard, no webhook
    db.advance(20 / 1440)
    rec.run(db.now)
    assert db.open_items().get(("credit_conflict", "rfnd_a")) == "credit_conflict"
    assert any("credit_conflict" in m for m in alerts)
    rec.run(db.now + timedelta(days=2))  # never resolved by ordinary reconciliation
    assert db.open_items().get(("credit_conflict", "rfnd_a")) == "credit_conflict"


def test_reconciler_turns_a_pending_source_refund_into_no_credit():
    db = ReconcileFake()
    rzp = FakeRazorpay(db)
    rec = Reconciler(db, rzp, lambda *a: None)
    annual = db.add_order("order_a", "annual")
    db.settle_razorpay_order(order_id="order_a", payment_id="pay_a", expected_user_id=None, event_type="t",
                             payload={}, project=billing.project, lifetime_held=billing.lifetime_held)
    rzp.pay("pay_a", annual)
    rzp.refund("rfnd_p", "pay_a", amount=1000, status="pending")
    rec.handle_refund(rzp.refunds["rfnd_p"], db.now)
    assert db.tracked[("refund", "rfnd_p")]["order_id"] == "order_a"
    quote, _ = db.quote_upgrade(42, lambda g, f, now: billing.upgrade_quote(g, f, now, LIST))
    assert quote["credit_amount"] == 0


def test_reconciler_tracks_a_credited_payment_without_attempt_time_as_pending():
    db = ReconcileFake()
    rzp = FakeRazorpay(db)
    rec = Reconciler(db, rzp, lambda *a: None)
    life = _credited_order(db, "order_l", db.now)
    payment = rzp.pay("pay_l", life)
    payment.pop("created_at")
    rec.handle_payment(payment, db.now)
    assert db.orders["order_l"]["status"] == "created"
    assert db.open_items() == {("payment", "pay_l"): "pending"}

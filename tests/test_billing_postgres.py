"""Billing SQL (D-024) against a real, disposable PostgreSQL.

Opt-in like tests/test_auth_postgres.py: skipped unless HALALLENS_TEST_PG_DSN
points at a throwaway database (the schema is dropped and rebuilt). Proves
what the fake cannot: the migration keeps an existing period's exact end,
settlement is all-or-nothing, and the per-user lock serialises concurrent
settlements.
"""

import os
import threading
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from api.billing import fold, lifetime_held, project

DSN = os.getenv("HALALLENS_TEST_PG_DSN")
pytestmark = pytest.mark.skipif(not DSN, reason="HALALLENS_TEST_PG_DSN not set (disposable Postgres only)")

ROOT = Path(__file__).resolve().parents[1]
MIGRATION = ROOT / "database/migrations/20261029_subscription_grants.sql"


@pytest.fixture()
def db():
    import psycopg2
    from psycopg2.extras import RealDictCursor

    from database.database_manager import BSEDatabaseManager

    admin = psycopg2.connect(DSN)
    admin.autocommit = True
    with admin.cursor() as cur:
        cur.execute("DROP SCHEMA public CASCADE; CREATE SCHEMA public;")
        cur.execute((ROOT / "database/schema.sql").read_text(encoding="utf-8"))

    @contextmanager
    def get_connection():
        conn = psycopg2.connect(DSN, cursor_factory=RealDictCursor)
        try:
            yield conn
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    manager = BSEDatabaseManager.__new__(BSEDatabaseManager)  # no pool, no startup DDL
    manager.get_connection = get_connection
    yield manager, admin
    admin.close()


def _user(admin, email="buyer@example.com"):
    with admin.cursor() as cur:
        cur.execute("INSERT INTO users (email, email_verified_at) VALUES (%s, NOW()) RETURNING id", (email,))
        return cur.fetchone()[0]


def _order(admin, user_id, order_id, plan_code):
    with admin.cursor() as cur:
        cur.execute(
            "INSERT INTO razorpay_orders (order_id, user_id, amount, currency, status, payload, plan_code, interval_days) "
            "SELECT %s, %s, price_inr * 100, 'INR', 'created', '{}'::jsonb, code, interval_days "
            "FROM subscription_plans WHERE code = %s",
            (order_id, user_id, plan_code),
        )


def _refund(manager, order_id, payment_id, refund_id, amount):
    return manager.refund_razorpay_payment(
        order_id=order_id, payment_id=payment_id, refund_id=refund_id, refund_amount=amount,
        event_type="refund.processed", payload={}, project=project,
    )[0]


def _plan(admin, user_id):
    with admin.cursor() as cur:
        cur.execute("SELECT plan FROM users WHERE id = %s", (user_id,))
        return cur.fetchone()[0]


def _settle(manager, order_id, payment_id, **kw):
    return manager.settle_razorpay_order(
        order_id=order_id, payment_id=payment_id, expected_user_id=None, event_type="payment.captured",
        payload={}, project=kw.get("project", project), lifetime_held=lifetime_held,
    )


def test_migration_keeps_the_existing_period_end_and_links_the_order(db):
    manager, admin = db
    user_id = _user(admin)
    with admin.cursor() as cur:
        # The pre-ledger shape: DATE renewal, no grants, terms only in the payload.
        cur.execute("DROP TABLE subscription_grants")
        cur.execute("ALTER TABLE users ALTER COLUMN subscription_renewal TYPE DATE")
        cur.execute("ALTER TABLE razorpay_orders DROP COLUMN plan_code, DROP COLUMN interval_days, DROP COLUMN payment_id")
        cur.execute(
            "UPDATE users SET plan='annual', subscription_status='active', subscription_renewal='2027-10-29', "
            "plan_started_at='2026-10-29 07:56:04+00' WHERE id=%s",
            (user_id,),
        )
        cur.execute(
            "INSERT INTO razorpay_orders (order_id, user_id, amount, status, payload) VALUES "
            "('order_paid', %s, 50000, 'paid', '{\"notes\": {\"plan_code\": \"annual\"}}'), "
            "('order_open', %s, 5000, 'created', '{\"notes\": {\"plan_code\": \"starter\"}}')",
            (user_id, user_id),
        )
        cur.execute(MIGRATION.read_text(encoding="utf-8"))
        cur.execute(MIGRATION.read_text(encoding="utf-8"))  # idempotent

    grants = manager.get_subscription_grants(user_id)
    assert len(grants) == 1 and grants[0]["source"] == "legacy" and grants[0]["order_id"] == "order_paid"
    (segment,) = fold(grants)
    assert segment.end == datetime(2027, 10, 29, tzinfo=timezone.utc)  # exactly the old boundary
    order = manager.get_razorpay_order("order_open")
    assert (order["plan_code"], order["interval_days"]) == ("starter", 30)


def test_settlement_is_all_or_nothing(db):
    manager, admin = db
    user_id = _user(admin)
    _order(admin, user_id, "order_1", "starter")

    def crash(grants, now):
        raise RuntimeError("crash after the grant insert")

    with pytest.raises(RuntimeError):
        _settle(manager, "order_1", "pay_1", project=crash)
    assert manager.get_razorpay_order("order_1")["status"] == "created"  # still claimable
    assert manager.get_subscription_grants(user_id) == []
    assert _settle(manager, "order_1", "pay_1")[0] == "granted"  # the retry works


def test_the_same_order_settles_once_under_concurrency(db):
    manager, admin = db
    user_id = _user(admin)
    _order(admin, user_id, "order_1", "annual")
    results = []
    threads = [threading.Thread(target=lambda: results.append(_settle(manager, "order_1", "pay_1")[0])) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert sorted(results) == ["granted"] + ["settled"] * 7
    assert len(manager.get_subscription_grants(user_id)) == 1


def test_concurrent_purchases_stack_without_overlap(db):
    manager, admin = db
    user_id = _user(admin)
    for i in range(6):
        _order(admin, user_id, f"order_{i}", "starter")
    threads = [threading.Thread(target=_settle, args=(manager, f"order_{i}", f"pay_{i}")) for i in range(6)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    segments = fold(manager.get_subscription_grants(user_id))
    assert len(segments) == 6
    for earlier, later in zip(segments, segments[1:]):
        assert later.start == earlier.end  # back to back, no overlap, no gap
    assert segments[-1].end - segments[0].start == timedelta(days=180)


def test_refund_of_a_queued_purchase_keeps_the_current_one(db):
    manager, admin = db
    user_id = _user(admin)
    _order(admin, user_id, "order_a", "annual")
    _order(admin, user_id, "order_s", "starter")
    _settle(manager, "order_a", "pay_a")
    _settle(manager, "order_s", "pay_s")

    def refund(refund_id):
        return _refund(manager, None, "pay_s", refund_id, 5000)

    assert refund("rfnd_1") == "revoked"
    assert refund("rfnd_1") == "duplicate"
    with admin.cursor() as cur:
        cur.execute("SELECT plan FROM users WHERE id = %s", (user_id,))
        assert cur.fetchone()[0] == "annual"
    segments = fold(manager.get_subscription_grants(user_id))
    assert segments[1].start == segments[1].end  # the refunded Starter takes no time


def test_lifetime_turns_a_late_payment_into_refund_due(db):
    manager, admin = db
    user_id = _user(admin)
    _order(admin, user_id, "order_life", "lifetime")
    _order(admin, user_id, "order_s", "starter")
    assert _settle(manager, "order_life", "pay_l")[0] == "granted"
    assert _settle(manager, "order_s", "pay_s")[0] == "refund_due"
    assert manager.get_razorpay_order("order_s")["status"] == "refund_due"
    assert len(manager.get_subscription_grants(user_id)) == 1


def test_lifetime_bought_during_annual_is_projected_at_settlement_and_its_refund_restores_annual(db):
    manager, admin = db
    user_id = _user(admin)
    _order(admin, user_id, "order_a", "annual")
    _order(admin, user_id, "order_life", "lifetime")
    _settle(manager, "order_a", "pay_a")
    with admin.cursor() as cur:
        cur.execute("SELECT subscription_renewal FROM users WHERE id = %s", (user_id,))
        annual_end = cur.fetchone()[0]
    assert _settle(manager, "order_life", "pay_l")[0] == "granted"
    assert _plan(admin, user_id) == "lifetime"
    assert _refund(manager, "order_life", "pay_l", "rfnd_l", 200000) == "revoked"
    with admin.cursor() as cur:
        cur.execute("SELECT plan, subscription_renewal FROM users WHERE id = %s", (user_id,))
        assert cur.fetchone() == ("annual", annual_end)


def test_lifetime_and_another_purchase_racing_never_strand_money(db):
    # Without the per-user lock both settle, and the Starter grant lands under
    # Lifetime where it can never be used: paid for, worth nothing, nobody told.
    manager, admin = db
    for round_ in range(15):
        user_id = _user(admin, f"race{round_}@example.com")
        _order(admin, user_id, f"life_{round_}", "lifetime")
        _order(admin, user_id, f"start_{round_}", "starter")
        barrier = threading.Barrier(2)

        def run(order_id, payment_id):
            barrier.wait()
            _settle(manager, order_id, payment_id)

        threads = [
            threading.Thread(target=run, args=(f"life_{round_}", f"pay_l{round_}")),
            threading.Thread(target=run, args=(f"start_{round_}", f"pay_s{round_}")),
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        grants = manager.get_subscription_grants(user_id)
        plans = [g["plan_code"] for g in sorted(grants, key=lambda g: (g["allocated_at"], g["id"]))]
        assert plans in (["starter", "lifetime"], ["lifetime"]), plans


def test_refunding_a_duplicate_payment_leaves_the_plan(db):
    manager, admin = db
    user_id = _user(admin)
    _order(admin, user_id, "order_1", "annual")
    _settle(manager, "order_1", "pay_first")
    # A second captured attempt on the same order is refunded (order_id present).
    assert _refund(manager, "order_1", "pay_second", "rfnd_dup", 50000) == "other_payment"
    assert _plan(admin, user_id) == "annual"
    assert manager.get_razorpay_order("order_1")["status"] == "paid"


def test_refund_totals_are_summed_per_refund_never_double_counted(db):
    manager, admin = db
    user_id = _user(admin)
    _order(admin, user_id, "order_1", "annual")  # 50000 paise
    _settle(manager, "order_1", "pay_1")
    assert _refund(manager, "order_1", "pay_1", "rfnd_2", 20000) == "partial"
    assert _refund(manager, "order_1", "pay_1", "rfnd_1", 15000) == "partial"
    assert _refund(manager, "order_1", "pay_1", "rfnd_1", 15000) == "duplicate"
    assert _plan(admin, user_id) == "annual"
    assert _refund(manager, "order_1", "pay_1", "rfnd_3", 15000) == "revoked"
    assert _plan(admin, user_id) == "free"


def test_a_payment_refunded_before_settlement_cannot_fund_the_order(db):
    manager, admin = db
    user_id = _user(admin)
    _order(admin, user_id, "order_1", "starter")
    assert _refund(manager, "order_1", "pay_1", "rfnd_1", 5000) == "unsettled"
    assert _settle(manager, "order_1", "pay_1")[0] == "refunded_payment"
    assert _settle(manager, "order_1", "pay_2")[0] == "granted"  # another attempt still can


def _db_now(admin):
    with admin.cursor() as cur:
        cur.execute("SELECT NOW()")
        return cur.fetchone()[0]


def test_reconciler_end_to_end_on_real_sql(db):
    from types import SimpleNamespace

    from jobs.reconcile_payments import Reconciler
    from tests.billing_fake import FakeRazorpay

    manager, admin = db
    user_id = _user(admin)
    _order(admin, user_id, "order_1", "starter")
    _order(admin, user_id, "order_2", "annual")
    with admin.cursor() as cur:  # orders created a while ago, so they fall inside the window
        cur.execute("UPDATE razorpay_orders SET created_at = NOW() - INTERVAL '2 hours'")
    clock = SimpleNamespace(now=_db_now(admin) - timedelta(hours=1))
    rzp = FakeRazorpay(clock)
    rzp.pay("pay_1", manager.get_razorpay_order("order_1"))                 # missed webhook
    rzp.pay("pay_2", manager.get_razorpay_order("order_2"), amount=100)     # mismatch
    alerts = []
    summary = Reconciler(manager, rzp, lambda *a: alerts.append(a)).run(_db_now(admin))
    assert summary.get("webhook_missed") == 1
    assert _plan(admin, user_id) == "starter"
    with admin.cursor() as cur:
        cur.execute("SELECT kind, provider_id, reason FROM billing_tracked WHERE resolved_at IS NULL")
        open_items = {(k, p): r for k, p, r in cur.fetchall()}
    assert open_items == {("payment", "pay_2"): "mismatch"}
    state = manager.get_reconcile_state()
    assert state["payments_checkpoint"] and state["refunds_checkpoint"] and state["last_success_at"]
    assert state["last_error"] is None


def test_checkpoints_never_move_back_and_tracking_reopens(db):
    manager, admin = db
    now = _db_now(admin)
    manager.save_reconcile_progress(checkpoints={"payments": now})
    manager.save_reconcile_progress(checkpoints={"payments": now - timedelta(days=3)})
    assert manager.get_reconcile_state()["payments_checkpoint"] == now
    manager.track_billing_item(kind="payment", provider_id="pay_x", order_id=None, reason="pending",
                               last_status="created", recheck_after_seconds=900)
    manager.resolve_billing_item("payment", "pay_x")
    row = manager.track_billing_item(kind="payment", provider_id="pay_x", order_id="o", reason="duplicate",
                                     last_status="captured", recheck_after_seconds=900)
    assert row["resolved_at"] is None and row["reason"] == "duplicate" and row["attempts"] == 2
    with admin.cursor() as cur:  # a week-old pending item is looked at daily, never retired
        cur.execute("UPDATE billing_tracked SET first_seen = NOW() - INTERVAL '8 days'")
    row = manager.track_billing_item(kind="payment", provider_id="pay_x", order_id="o", reason="pending",
                                     last_status="created", recheck_after_seconds=900)
    assert row["next_check_at"] - _db_now(admin) > timedelta(hours=23)


def test_legacy_binding_applies_recorded_refunds_on_real_sql(db):
    manager, admin = db
    user_id = _user(admin)
    with admin.cursor() as cur:
        cur.execute(
            "INSERT INTO razorpay_orders (order_id, user_id, amount, status, payload, plan_code, interval_days) "
            "VALUES ('order_old', %s, 50000, 'paid', '{}', 'annual', 365)", (user_id,))
        cur.execute(
            "INSERT INTO subscription_grants (user_id, plan_code, source, order_id, duration, allocated_at) "
            "VALUES (%s, 'annual', 'legacy', 'order_old', INTERVAL '365 days', NOW())", (user_id,))
    manager.refresh_entitlement(user_id, project)
    assert _refund(manager, "order_old", "pay_old", "rfnd_1", 50000) == "needs_review"
    assert _plan(admin, user_id) == "annual"  # held for review: funding payment unknown
    assert manager.bind_legacy_payment(order_id="order_old", payment_id="pay_old", project=project)[0] == "bound"
    assert _plan(admin, user_id) == "free"    # the recorded refund now applies
    assert manager.bind_legacy_payment(order_id="order_old", payment_id="pay_old", project=project)[0] == "already_bound"


def test_the_advisory_lock_lets_only_one_run_through(db):
    import psycopg2

    from jobs.reconcile_payments import LOCK_KEY

    first, second = psycopg2.connect(DSN), psycopg2.connect(DSN)
    first.autocommit = second.autocommit = True
    try:
        with first.cursor() as a, second.cursor() as b:
            a.execute("SELECT pg_try_advisory_lock(%s)", (LOCK_KEY,))
            b.execute("SELECT pg_try_advisory_lock(%s)", (LOCK_KEY,))
            assert a.fetchone()[0] is True and b.fetchone()[0] is False
            a.execute("SELECT pg_advisory_unlock(%s)", (LOCK_KEY,))
            b.execute("SELECT pg_try_advisory_lock(%s)", (LOCK_KEY,))
            assert b.fetchone()[0] is True
    finally:
        first.close()
        second.close()


def _duplicate_on_real_sql(manager, admin):
    user_id = _user(admin)
    _order(admin, user_id, "order_1", "annual")
    _settle(manager, "order_1", "pay_1")
    return user_id


def _intent(manager, key, reason="duplicate", payment_id="pay_2", amount=50000):
    return manager.create_refund_intent(
        payment_id=payment_id, order_id="order_1", reason=reason, amount=amount, currency="INR",
        idempotency_key=key, request_body={"amount": amount, "notes": {"halallens_refund_key": key}},
    )


def test_one_refund_intent_per_payment_even_under_concurrency(db):
    manager, admin = db
    _duplicate_on_real_sql(manager, admin)
    results = []
    threads = [threading.Thread(target=lambda i=i: results.append(_intent(manager, f"key-{i}"))) for i in range(6)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    statuses = sorted(r[0] for r in results)
    assert statuses == ["created"] + ["existing"] * 5
    keys = {r[1]["idempotency_key"] for r in results}
    assert len(keys) == 1  # every caller got the one stored request


def test_refund_intents_require_a_proven_duplicate_and_matching_terms(db):
    manager, admin = db
    _duplicate_on_real_sql(manager, admin)
    assert _intent(manager, "k1", payment_id="pay_1")[0] == "ineligible"  # the funding payment itself
    assert _intent(manager, "k2", amount=100)[0] == "ineligible"          # wrong amount
    assert _intent(manager, "k3", reason="refund_due")[0] == "ineligible"  # order is not refund_due


def test_refund_action_state_never_moves_backwards_and_manual_refunds_settle_the_obligation(db):
    manager, admin = db
    _duplicate_on_real_sql(manager, admin)
    manager.track_billing_item(kind="payment", provider_id="pay_2", order_id="order_1", reason="duplicate",
                               last_status="captured", recheck_after_seconds=0)
    _, action = _intent(manager, "k1")
    assert manager.update_refund_action(action["id"], state="blocked")["state"] == "blocked"
    assert manager.update_refund_action(action["id"], state="created")["state"] == "blocked"
    # Two manual partial refunds of the duplicate: open after the first, settled after both.
    assert _refund(manager, "order_1", "pay_2", "rfnd_m1", 20000) == "other_payment"
    assert manager.sync_refund_action("pay_2")["obligation_settled"] is False
    assert _refund(manager, "order_1", "pay_2", "rfnd_m2", 30000) == "other_payment"
    synced = manager.sync_refund_action("pay_2")
    assert synced["obligation_settled"] is True and synced["action_state"] == "blocked"
    with admin.cursor() as cur:
        cur.execute("SELECT resolved_at FROM billing_tracked WHERE provider_id = 'pay_2'")
        assert cur.fetchone()[0] is not None


# --- upgrade credit (D-030) ----------------------------------------------------------

CREDIT_MIGRATION = ROOT / "database/migrations/20261030_lifetime_upgrade_credit.sql"


def test_credit_migration_backfills_old_orders_and_is_idempotent(db):
    import psycopg2

    manager, admin = db
    user_id = _user(admin)
    with admin.cursor() as cur:
        # The pre-D-030 shape.
        cur.execute("ALTER TABLE razorpay_orders DROP CONSTRAINT razorpay_orders_credit_terms_check")
        cur.execute(
            "ALTER TABLE razorpay_orders DROP COLUMN list_amount, DROP COLUMN credit_amount, DROP COLUMN priced_at, "
            "DROP COLUMN price_valid_until, DROP COLUMN credit_version, DROP COLUMN credit_detail, "
            "DROP COLUMN refund_due_reason"
        )
        cur.execute("ALTER TABLE billing_tracked DROP CONSTRAINT billing_tracked_kind_check")
        cur.execute("ALTER TABLE billing_tracked ADD CONSTRAINT billing_tracked_kind_check "
                    "CHECK (kind IN ('payment', 'refund', 'order'))")
    _order(admin, user_id, "order_old", "lifetime")  # unpaid, made before the migration
    with admin.cursor() as cur:
        cur.execute(CREDIT_MIGRATION.read_text(encoding="utf-8"))
        cur.execute(CREDIT_MIGRATION.read_text(encoding="utf-8"))  # idempotent
    order = manager.get_razorpay_order("order_old")
    assert (order["list_amount"], order["credit_amount"], order["credit_version"]) == (200000, 0, None)
    # Completes exactly as before: no attempt time needed.
    assert _settle(manager, "order_old", "pay_old")[0] == "granted"
    with admin.cursor() as cur, pytest.raises(psycopg2.errors.CheckViolation):
        cur.execute("UPDATE razorpay_orders SET credit_amount = 1 WHERE order_id = 'order_old'")
    manager.track_billing_item(kind="credit_conflict", provider_id="rfnd_x", order_id="order_old",
                               reason="credit_conflict", last_status=None, recheck_after_seconds=0)


def _credited(manager, user_id, order_id):
    """A Lifetime order priced with credit on the database clock, as the API stores it."""

    from api.billing import CREDIT_VERSION, PRICE_VALIDITY, upgrade_quote

    quote, priced_at = manager.quote_upgrade(user_id, lambda g, f, now: upgrade_quote(g, f, now, 200000))
    manager.create_razorpay_order(
        user_id=user_id, order_id=order_id, amount=quote["amount"], currency="INR", status="created", payload={},
        plan_code="lifetime", interval_days=0, list_amount=200000, credit_amount=quote["credit_amount"],
        priced_at=priced_at, price_valid_until=priced_at + PRICE_VALIDITY, credit_version=CREDIT_VERSION,
        credit_detail={"sources": quote["sources"]},
    )
    return quote, int(priced_at.timestamp())


def _settle_credited(manager, order_id, payment_id, created_at):
    from api.billing import credit_refusal

    return manager.settle_razorpay_order(
        order_id=order_id, payment_id=payment_id, expected_user_id=None, event_type="payment.captured",
        payload={}, project=project, lifetime_held=lifetime_held, payment_created_at=created_at,
        credit_refusal=credit_refusal,
    )


def test_credited_lifetime_on_real_sql(db):
    manager, admin = db
    user_id = _user(admin)
    _order(admin, user_id, "order_a", "annual")
    _settle(manager, "order_a", "pay_a")
    quote, created = _credited(manager, user_id, "order_l")
    assert 0 < quote["credit_amount"] <= 50000 and quote["amount"] == 200000 - quote["credit_amount"]
    order = manager.get_razorpay_order("order_l")
    assert order["credit_detail"]["sources"][0]["payment_id"] == "pay_a"
    assert _settle_credited(manager, "order_l", "pay_l", None)[0] == "retry"
    assert manager.get_razorpay_order("order_l")["status"] == "created"
    assert _settle_credited(manager, "order_l", "pay_l", created)[0] == "granted"
    assert _plan(admin, user_id) == "lifetime"
    # The Annual is refunded afterwards: alert item, access unchanged, never due for a re-check.
    assert _refund(manager, "order_a", "pay_a", "rfnd_a", 50000) == "revoked"
    assert _plan(admin, user_id) == "lifetime"
    with admin.cursor() as cur:
        cur.execute("SELECT order_id, reason, resolved_at FROM billing_tracked WHERE kind = 'credit_conflict'")
        assert cur.fetchall() == [("order_l", "credit_conflict", None)]
        cur.execute("UPDATE billing_tracked SET next_check_at = NOW() - INTERVAL '1 day'")
    assert manager.due_billing_items(10) == []


def test_credited_lifetime_refund_due_reasons_on_real_sql(db):
    manager, admin = db
    user_id = _user(admin)
    _order(admin, user_id, "order_a", "annual")
    _settle(manager, "order_a", "pay_a")
    _, created = _credited(manager, user_id, "order_late")
    _, created2 = _credited(manager, user_id, "order_changed")
    assert _settle_credited(manager, "order_late", "pay_late", created + 15 * 60 + 2)[0] == "refund_due"
    assert _refund(manager, "order_a", "pay_a", "rfnd_part", 100) == "partial"
    assert _settle_credited(manager, "order_changed", "pay_ch", created2)[0] == "refund_due"
    reasons = {o: manager.get_razorpay_order(o)["refund_due_reason"] for o in ("order_late", "order_changed")}
    assert reasons == {"order_late": "price_expired", "order_changed": "credit_changed"}
    assert _plan(admin, user_id) == "annual"


def test_credited_settlement_racing_a_source_refund_never_grants_on_stale_credit_silently(db):
    manager, admin = db
    for round_ in range(10):
        user_id = _user(admin, f"credit{round_}@example.com")
        _order(admin, user_id, f"a_{round_}", "annual")
        _settle(manager, f"a_{round_}", f"pay_a{round_}")
        _, created = _credited(manager, user_id, f"l_{round_}")
        barrier = threading.Barrier(2)
        out = {}

        def settle():
            barrier.wait()
            out["settle"] = _settle_credited(manager, f"l_{round_}", f"pay_l{round_}", created)[0]

        def refund():
            barrier.wait()
            out["refund"] = _refund(manager, f"a_{round_}", f"pay_a{round_}", f"rfnd_{round_}", 50000)

        threads = [threading.Thread(target=settle), threading.Thread(target=refund)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        with admin.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM billing_tracked WHERE kind = 'credit_conflict' AND order_id = %s",
                        (f"l_{round_}",))
            conflicts = cur.fetchone()[0]
        # Either the refund came first (no grant) or the grant came first (alert opened).
        assert (out["settle"], conflicts) in (("refund_due", 0), ("granted", 1)), (out, conflicts)

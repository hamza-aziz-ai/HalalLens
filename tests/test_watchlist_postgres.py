"""Watchlist observation and alert-email SQL against a real, disposable PostgreSQL.

Opt-in: skipped unless HALALLENS_TEST_PG_DSN points at a throwaway database
(the schema is dropped and rebuilt). Locking cannot be proven with mocks, so
this is the narrow exception to "tests need no live Postgres"
(docs/TESTING.md). Example:

    docker run -d --rm --name wl-pg -e POSTGRES_PASSWORD=pw -p 55432:5432 postgres:17.11-trixie
    HALALLENS_TEST_PG_DSN=postgresql://postgres:pw@localhost:55432/postgres pipenv run pytest tests/test_watchlist_postgres.py -v
"""

import os
import threading
import time
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

DSN = os.getenv("HALALLENS_TEST_PG_DSN")
pytestmark = pytest.mark.skipif(not DSN, reason="HALALLENS_TEST_PG_DSN not set (disposable Postgres only)")

ROOT = Path(__file__).resolve().parents[1]
FILED = datetime(2026, 1, 1, 9, 30, tzinfo=timezone.utc)


@pytest.fixture()
def env():
    import psycopg2
    from psycopg2.extras import RealDictCursor

    from alerts.storage import WatchEntry, WatchlistStorage
    from database.database_manager import BSEDatabaseManager

    admin = psycopg2.connect(DSN)
    admin.autocommit = True
    with admin.cursor() as cur:
        cur.execute("DROP SCHEMA public CASCADE; CREATE SCHEMA public;")
        cur.execute((ROOT / "database/schema.sql").read_text(encoding="utf-8"))
        # The migration is idempotent on top of the current schema.
        cur.execute((ROOT / "database/migrations/20261030_alert_emails.sql").read_text(encoding="utf-8"))
        cur.execute(
            "INSERT INTO users (email, email_verified_at) VALUES ('a@x.test', now()), ('b@x.test', now())"
        )
        cur.execute(
            "INSERT INTO subscription_grants (user_id, plan_code, source, duration, allocated_at) "
            "SELECT id, 'starter', 'legacy', interval '30 days', now() - interval '1 day' FROM users"
        )
        cur.execute(
            "INSERT INTO announcements (symbol, symbol_alias, filing_date, raw_json) VALUES ('ABC', 'ABCALIAS', %s, '{}')",
            (FILED,),
        )
        cur.execute("INSERT INTO financial_snapshots (symbol, filing_date) VALUES ('ABC', %s)", (FILED,))

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
    manager.connection_params = {"dsn": DSN}
    store = WatchlistStorage(lambda: manager)
    store.add(WatchEntry(user_id=1, symbol="ABC"))
    store.add(WatchEntry(user_id=2, symbol="ABC"))
    yield store, manager, admin
    admin.close()


def _evaluate(admin, verdict, is_compliant, evaluated_at):
    with admin.cursor() as cur:
        cur.execute(
            """
            INSERT INTO filing_evaluations (symbol, filing_date, verdict, is_compliant, evaluated_at)
            VALUES ('ABC', %(fd)s, %(v)s, %(c)s, %(at)s)
            ON CONFLICT (symbol, filing_date) DO UPDATE
               SET verdict = EXCLUDED.verdict, is_compliant = EXCLUDED.is_compliant, evaluated_at = EXCLUDED.evaluated_at
            """,
            {"fd": FILED, "v": verdict, "c": is_compliant, "at": FILED + timedelta(days=evaluated_at)},
        )


def _row(admin, user_id=1):
    from psycopg2.extras import RealDictCursor

    with admin.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute("SELECT * FROM watchlist_entries WHERE user_id = %s", (user_id,))
        return cur.fetchone()


KEY = (1, "ABC", "compliance_flip")


def test_migration_on_an_existing_table_leaves_nothing_pending():
    import psycopg2

    admin = psycopg2.connect(DSN)
    admin.autocommit = True
    with admin.cursor() as cur:
        cur.execute("DROP SCHEMA public CASCADE; CREATE SCHEMA public;")
        cur.execute("CREATE TABLE users (id SERIAL PRIMARY KEY, email TEXT)")
        cur.execute("INSERT INTO users (email) VALUES ('a@x'), ('b@x')")
        cur.execute((ROOT / "database/migrations/20261029_watchlist_entries.sql").read_text(encoding="utf-8"))
        cur.execute(
            "INSERT INTO watchlist_entries (user_id, symbol, last_is_compliant) VALUES (1, 'A', true), (1, 'B', false), (2, 'A', NULL)"
        )
        migration = (ROOT / "database/migrations/20261030_alert_emails.sql").read_text(encoding="utf-8")
        cur.execute(migration)
        cur.execute(migration)  # idempotent
        cur.execute(
            "SELECT count(*) FROM watchlist_entries WHERE last_is_compliant IS DISTINCT FROM notified_is_compliant"
        )
        assert cur.fetchone()[0] == 0
        cur.execute("SELECT bool_and(alert_emails) FROM users")
        assert cur.fetchone()[0] is True
    admin.close()


def test_seed_is_silent_and_a_flip_is_pending_with_its_observation(env):
    store, _, admin = env
    _evaluate(admin, "compliant", True, 1)
    assert store.observe("ABC").flipped == []
    row = _row(admin)
    assert row["last_is_compliant"] is True and row["notified_is_compliant"] is True
    assert row["observed_filing_date"] == FILED
    # Rows come back by column name, as from the production pool (RealDictCursor).
    assert [(e.user_id, e.symbol, e.last_is_compliant) for e in store.list(1)] == [(1, "ABC", True)]

    _evaluate(admin, "non-compliant", False, 2)
    assert sorted(store.observe("ABC").flipped) == [1, 2]
    row = _row(admin)
    assert row["last_is_compliant"] is False and row["notified_is_compliant"] is True
    assert row["observed_evaluated_at"] == FILED + timedelta(days=2)


def test_alias_open_issue_and_unknown_never_move(env):
    store, _, admin = env
    _evaluate(admin, "compliant", True, 1)
    assert store.observe("ABCALIAS").is_compliant is True  # an alias finds the canonical filing
    store.observe("ABC")
    _evaluate(admin, "non-compliant", False, 2)
    with admin.cursor() as cur:
        cur.execute(
            "INSERT INTO data_quality_issues (symbol, filing_date, issue_type) VALUES ('ABC', %s, 'ratio_anomaly')",
            (FILED,),
        )
    assert store.observe("ABC").is_compliant is None
    assert store.observe("NOPE").is_compliant is None
    assert _row(admin)["last_is_compliant"] is True


def test_a_stale_observation_never_overwrites_newer_state(env):
    store, _, admin = env
    _evaluate(admin, "compliant", True, 1)
    store.observe("ABC")
    _evaluate(admin, "non-compliant", False, 3)
    store.observe("ABC")
    _evaluate(admin, "compliant", True, 2)  # an older evaluation, e.g. a slow writer's
    assert store.observe("ABC").flipped == []
    assert _row(admin)["last_is_compliant"] is False


def test_observation_waits_for_the_filing_lock(env):
    store, manager, admin = env
    _evaluate(admin, "compliant", True, 1)
    store.observe("ABC")
    _evaluate(admin, "non-compliant", False, 2)
    import psycopg2

    holder = psycopg2.connect(DSN)
    with holder.cursor() as cur:
        manager._lock_filing(cur, "ABC", FILED)  # a publication in progress
        result = {}
        worker = threading.Thread(target=lambda: result.update(o=store.observe("ABC")))
        worker.start()
        time.sleep(0.5)
        assert worker.is_alive()  # blocked behind the publication's lock
        cur.execute(
            "UPDATE filing_evaluations SET verdict = 'needs-review', is_compliant = NULL WHERE symbol = 'ABC'"
        )
    holder.commit()  # releases the lock with the masked verdict published
    worker.join(5)
    holder.close()
    assert result["o"].is_compliant is None and _row(admin)["last_is_compliant"] is True


@pytest.mark.parametrize("round_", range(10))
def test_concurrent_manual_and_scheduled_observations_flip_once(env, round_):
    store, _, admin = env
    _evaluate(admin, "compliant", True, 1)
    store.observe("ABC")
    _evaluate(admin, "non-compliant", False, 2 + round_)
    barrier = threading.Barrier(8)
    flips = []

    def run(i):
        barrier.wait()
        flips.extend(store.observe("ABC", user_id=1 if i % 2 else None).flipped)

    threads = [threading.Thread(target=run, args=(i,)) for i in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert sorted(flips) == [1, 2]


def _run(store, manager, mail, enabled=True):
    from alerts import delivery

    return delivery.run(store, manager.get_subscription_grants, enabled=enabled, send=mail,
                        sender="alerts@x.test", base_url="https://app.test")


def test_flip_is_sent_once_and_acknowledged(env):
    store, manager, admin = env
    _evaluate(admin, "compliant", True, 1)
    store.observe("ABC")
    _evaluate(admin, "non-compliant", False, 2)
    sent = []
    counts = _run(store, manager, lambda to, subject, body, message_id=None: sent.append(to))
    assert counts["sent"] == 2 and sorted(sent) == ["a@x.test", "b@x.test"]
    assert _row(admin)["notified_is_compliant"] is False
    assert _run(store, manager, lambda *a, **k: sent.append("again"))["sent"] == 0


def test_acknowledge_is_a_compare_and_set(env):
    store, _, admin = env
    _evaluate(admin, "compliant", True, 1)
    store.observe("ABC")
    _evaluate(admin, "non-compliant", False, 2)
    store.observe("ABC")
    # B (False) was submitted; meanwhile a newer evaluation said A (True) again.
    _evaluate(admin, "compliant", True, 3)
    store.observe("ABC")
    assert store.acknowledge(KEY, True, False) is True
    row = _row(admin)
    assert row["notified_is_compliant"] is False and row["last_is_compliant"] is True  # correction pending
    assert store.acknowledge(KEY, True, False) is False  # another sender already moved it


def test_failure_backoff_terminal_and_reset_on_a_new_target(env):
    store, _, admin = env
    _evaluate(admin, "compliant", True, 1)
    store.observe("ABC")
    _evaluate(admin, "non-compliant", False, 2)
    store.observe("ABC")
    store.record_failure(KEY, True, False, 900, False)
    row = _row(admin)
    assert row["notify_attempts"] == 1 and row["notify_next_at"] is not None and row["notify_failed_at"] is None
    assert KEY not in store.pending(5, 50)  # not due yet
    store.record_failure(KEY, True, True, 900, True)  # a stale target: ignored
    assert _row(admin)["notify_failed_at"] is None
    store.record_failure(KEY, True, False, 0, True)
    assert _row(admin)["notify_failed_at"] is not None
    _evaluate(admin, "compliant", True, 3)
    store.observe("ABC")
    _evaluate(admin, "non-compliant", False, 4)
    store.observe("ABC")
    row = _row(admin)
    assert row["notify_attempts"] == 0 and row["notify_failed_at"] is None and row["notify_next_at"] is None
    assert KEY in store.pending(5, 50)


def test_pending_is_fair_and_capped(env):
    store, _, admin = env
    _evaluate(admin, "compliant", True, 1)
    store.observe("ABC")
    _evaluate(admin, "non-compliant", False, 2)
    store.observe("ABC")
    store.defer(KEY, 0)  # user 1 tried before: behind user 2's never-tried row
    time.sleep(0.05)
    assert store.pending(5, 50)[0] == (2, "ABC", "compliance_flip")
    assert store.pending(5, 1) == [(2, "ABC", "compliance_flip")]


def test_kill_switch_rebaselines_and_ineligible_users_are_silenced(env):
    store, manager, admin = env
    _evaluate(admin, "compliant", True, 1)
    store.observe("ABC")
    _evaluate(admin, "non-compliant", False, 2)
    sent = []
    counts = _run(store, manager, lambda *a, **k: sent.append(1), enabled=False)
    assert counts["rebaselined"] == 2 and sent == []

    _evaluate(admin, "compliant", True, 3)
    store.set_alert_emails(1, False)  # opted out
    with admin.cursor() as cur:  # user 2: the timed grant replaced by a refunded Lifetime
        cur.execute("DELETE FROM subscription_grants WHERE user_id = 2")
        cur.execute(
            "INSERT INTO subscription_grants (user_id, plan_code, source, duration, allocated_at, revoked_at) "
            "VALUES (2, 'lifetime', 'legacy', NULL, now() - interval '2 days', now() - interval '1 day')"
        )
    counts = _run(store, manager, lambda *a, **k: sent.append(1))
    assert counts["silenced"] == 2 and sent == []
    assert store.get_alert_emails(1) is False and store.get_alert_emails(2) is True

    with admin.cursor() as cur:  # an unrevoked Lifetime overlay: eligible again
        cur.execute(
            "INSERT INTO subscription_grants (user_id, plan_code, source, duration, allocated_at) "
            "VALUES (2, 'lifetime', 'legacy', NULL, now() - interval '1 hour')"
        )
    _evaluate(admin, "non-compliant", False, 4)
    assert _run(store, manager, lambda *a, **k: sent.append(1))["sent"] == 1


def test_a_second_sender_cannot_take_the_lock(env):
    from alerts import delivery

    store, manager, admin = env
    _evaluate(admin, "compliant", True, 1)
    store.observe("ABC")
    _evaluate(admin, "non-compliant", False, 2)
    sent = []
    send = lambda *a, **k: sent.append(1)  # noqa: E731
    with admin.cursor() as cur:
        cur.execute("SELECT pg_advisory_lock(%s, %s)", delivery.LOCK_KEY)
        counts = delivery.run_locked(manager, enabled=True, send=send, sender="a@x.test", base_url="https://app.test")
        assert counts == {"skipped_locked": 1} and sent == []
        cur.execute("SELECT pg_advisory_unlock(%s, %s)", delivery.LOCK_KEY)
    counts = delivery.run_locked(manager, enabled=True, send=send, sender="a@x.test", base_url="https://app.test")
    assert counts["sent"] == 2

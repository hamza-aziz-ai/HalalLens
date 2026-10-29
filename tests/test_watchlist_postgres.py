"""Acceptance test of the watchlist storage against a real, disposable PostgreSQL.

Opt-in: skipped unless HALALLENS_TEST_PG_DSN points at a throwaway database
(the test creates and drops its own tables). Locking cannot be proven with
mocks, so this is the narrow exception to "tests need no live Postgres"
(docs/TESTING.md). Example:

    docker run -d --rm --name wl-pg -e POSTGRES_PASSWORD=pw -p 55432:5432 postgres:14
    HALALLENS_TEST_PG_DSN=postgresql://postgres:pw@localhost:55432/postgres pipenv run pytest tests/test_watchlist_postgres.py -v
"""

import os
import threading
from contextlib import contextmanager
from pathlib import Path

import pytest

DSN = os.getenv("HALALLENS_TEST_PG_DSN")
pytestmark = pytest.mark.skipif(not DSN, reason="HALALLENS_TEST_PG_DSN not set (disposable Postgres only)")

MIGRATION = Path(__file__).resolve().parents[1] / "database/migrations/20261029_watchlist_entries.sql"


class _DB:
    """get_connection() like BSEDatabaseManager: rollback on error, no commit."""

    @contextmanager
    def get_connection(self):
        import psycopg2

        conn = psycopg2.connect(DSN)
        try:
            yield conn
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()


@pytest.fixture()
def storage():
    import psycopg2

    from alerts.storage import WatchEntry, WatchlistStorage

    conn = psycopg2.connect(DSN)
    conn.autocommit = True
    with conn.cursor() as cur:
        # Start from an empty schema: the auth and billing Postgres tests leave
        # the full schema behind, whose foreign keys block dropping users alone.
        cur.execute("DROP SCHEMA public CASCADE; CREATE SCHEMA public;")
        cur.execute("CREATE TABLE users (id SERIAL PRIMARY KEY, email TEXT)")
        cur.execute("INSERT INTO users (email) VALUES ('a@x'), ('b@x')")
        cur.execute(MIGRATION.read_text(encoding="utf-8"))
    store = WatchlistStorage(lambda: _DB())
    store.add(WatchEntry(user_id=1, symbol="ABC"))
    store.add(WatchEntry(user_id=2, symbol="ABC"))
    yield store, conn
    with conn.cursor() as cur:
        cur.execute("DROP TABLE IF EXISTS watchlist_entries; DROP TABLE IF EXISTS users;")
    conn.close()


def _race(storage, verdicts, user_id=1):
    """Run transitions at once on independent connections; return outcomes."""

    barrier = threading.Barrier(len(verdicts))
    outcomes = [None] * len(verdicts)

    def run(i, verdict):
        barrier.wait()
        outcomes[i] = storage.transition(user_id, "ABC", "compliance_flip", verdict)

    threads = [threading.Thread(target=run, args=(i, v)) for i, v in enumerate(verdicts)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    return outcomes


def _baseline(store, user_id=1):
    return store.list(user_id)[0].last_is_compliant


@pytest.mark.parametrize("round_", range(20))
def test_concurrent_identical_flips_alert_exactly_once(storage, round_):
    store, _ = storage
    assert store.transition(1, "ABC", "compliance_flip", True) == "baseline"
    outcomes = _race(store, [False] * 8)
    assert outcomes.count("flip") == 1 and outcomes.count(None) == 7
    assert _baseline(store) is False
    # Put it back for the next round.
    assert store.transition(1, "ABC", "compliance_flip", True) == "flip"


@pytest.mark.parametrize("round_", range(20))
def test_concurrent_opposite_verdicts_from_null_never_lose_the_flip(storage, round_):
    store, conn = storage
    with conn.cursor() as cur:
        cur.execute("UPDATE watchlist_entries SET last_is_compliant = NULL")
    outcomes = sorted(map(str, _race(store, [True, False])))
    # One seeds the baseline, the other then sees it and flips: never two Nones.
    assert outcomes == ["baseline", "flip"]


def test_concurrent_identical_seeds_set_one_baseline(storage):
    store, _ = storage
    outcomes = _race(store, [True] * 8)
    assert outcomes.count("baseline") == 1 and outcomes.count(None) == 7


def test_readding_during_transitions_keeps_the_baseline(storage):
    from alerts.storage import WatchEntry

    store, _ = storage
    store.transition(1, "ABC", "compliance_flip", True)
    store.add(WatchEntry(user_id=1, symbol="ABC"))
    assert _baseline(store) is True


def test_owner_isolation_and_cascade(storage):
    store, conn = storage
    store.transition(1, "ABC", "compliance_flip", True)
    store.transition(1, "ABC", "compliance_flip", False)
    assert _baseline(store, 2) is None  # user 2 untouched
    with conn.cursor() as cur:
        cur.execute("DELETE FROM users WHERE id = 1")
        cur.execute("SELECT count(*) FROM watchlist_entries WHERE user_id = 1")
        assert cur.fetchone()[0] == 0


def test_failed_statement_rolls_back_and_changes_nothing(storage):
    store, _ = storage
    store.transition(1, "ABC", "compliance_flip", True)
    with pytest.raises(Exception):  # psycopg2 cannot adapt the symbol: the statement fails
        store.transition(1, object(), "compliance_flip", False)
    assert _baseline(store) is True

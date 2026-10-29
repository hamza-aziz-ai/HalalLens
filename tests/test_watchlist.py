#!/usr/bin/env python3
"""Tests for watchlist storage and the alert engine (observation only)."""

from datetime import datetime, timezone

import pytest

from alerts import AlertEngine, WatchEntry, WatchlistStorage
from alerts.storage import _EVALUATION_SQL, _FLIP_SQL, _NEWEST_FILING_SQL, _SEED_SQL, conclusive
from tests.watchlist_fake import MemoryWatchlistStorage

FILED = datetime(2026, 1, 1, tzinfo=timezone.utc)


def _evaluation(verdict, is_compliant, evaluated_at=1, filed=FILED, open_issues=False):
    return {
        "verdict": verdict,
        "is_compliant": is_compliant,
        "filing_date": filed,
        "evaluated_at": datetime(2026, 2, evaluated_at, tzinfo=timezone.utc),
        "open_issues": open_issues,
    }


COMPLIANT = _evaluation("compliant", True)
NON_COMPLIANT = _evaluation("non-compliant", False, evaluated_at=2)


def test_watchlist_add_and_list():
    storage = MemoryWatchlistStorage()
    storage.add(WatchEntry(user_id=1, symbol="TCS"))

    items = storage.list(1)
    assert len(items) == 1
    assert items[0].symbol == "TCS"


def test_seed_is_silent_and_a_flip_becomes_pending():
    storage = MemoryWatchlistStorage()
    storage.add(WatchEntry(user_id=2, symbol="INFY"))
    engine = AlertEngine(storage)

    storage.filings["INFY"] = COMPLIANT
    assert engine.check("INFY", user_id=2) == []  # first conclusive verdict: baseline
    row = storage.rows[(2, "INFY", "compliance_flip")]
    assert row["last_is_compliant"] is True and row["notified_is_compliant"] is True  # nothing pending

    storage.filings["INFY"] = NON_COMPLIANT
    events = engine.check("INFY", user_id=2)
    assert [(e.user_id, e.message) for e in events] == [("user:2", "INFY compliance flipped to Non-Halal.")]
    assert row["last_is_compliant"] is False and row["notified_is_compliant"] is True  # pending
    assert row["observed_evaluated_at"] == NON_COMPLIANT["evaluated_at"]
    assert engine.check("INFY", user_id=2) == []  # no repeat


@pytest.mark.parametrize(
    "record",
    [
        None,  # unknown symbol / no evaluation
        _evaluation(None, None),
        _evaluation("needs-review", None),
        _evaluation("insufficient-data", None),
        _evaluation("compliant", False),  # inconsistent pair
        _evaluation("non-compliant", True),
        _evaluation("non-compliant", False, open_issues=True),  # masked by an open issue
    ],
)
def test_no_conclusive_verdict_never_moves_anything(record):
    storage = MemoryWatchlistStorage()
    storage.add(WatchEntry(user_id=3, symbol="WIPRO"))
    engine = AlertEngine(storage)
    storage.filings["WIPRO"] = COMPLIANT
    engine.check("WIPRO", user_id=3)

    storage.filings["WIPRO"] = record
    assert engine.check("WIPRO", user_id=3) == []
    assert storage.list(3)[0].last_is_compliant is True  # baseline untouched

    storage.filings["WIPRO"] = NON_COMPLIANT  # True -> None -> False flips once
    assert len(engine.check("WIPRO", user_id=3)) == 1


def test_a_stale_observation_never_overwrites_newer_state():
    storage = MemoryWatchlistStorage()
    storage.add(WatchEntry(user_id=4, symbol="TCS"))
    engine = AlertEngine(storage)
    storage.filings["TCS"] = COMPLIANT
    engine.check("TCS", user_id=4)
    storage.filings["TCS"] = NON_COMPLIANT
    engine.check("TCS", user_id=4)

    # A slow observer still holding the older evaluation of the same filing ...
    storage.filings["TCS"] = COMPLIANT
    assert engine.check("TCS", user_id=4) == []
    # ... or of an older filing.
    storage.filings["TCS"] = _evaluation("compliant", True, evaluated_at=9, filed=datetime(2025, 1, 1, tzinfo=timezone.utc))
    assert engine.check("TCS", user_id=4) == []
    assert storage.list(4)[0].last_is_compliant is False


def test_alert_engine_only_touches_the_given_user():
    storage = MemoryWatchlistStorage()
    storage.add(WatchEntry(user_id=10, symbol="TCS"))
    storage.add(WatchEntry(user_id=11, symbol="TCS"))
    engine = AlertEngine(storage)

    storage.filings["TCS"] = COMPLIANT
    assert engine.check("TCS", user_id=10) == []
    storage.filings["TCS"] = NON_COMPLIANT
    assert [e.user_id for e in engine.check("TCS", user_id=10)] == ["user:10"]
    # User 11's baseline was never seeded or moved by user 10's checks.
    assert storage.list(11)[0].last_is_compliant is None


def test_readding_a_symbol_keeps_its_baseline():
    storage = MemoryWatchlistStorage()
    storage.add(WatchEntry(user_id=4, symbol="TCS"))
    storage.filings["TCS"] = COMPLIANT
    AlertEngine(storage).check("TCS", user_id=4)
    storage.add(WatchEntry(user_id=4, symbol="TCS"))
    assert storage.list(4)[0].last_is_compliant is True


@pytest.mark.parametrize("owner", [0, -1, None, "", "user:1", "1", True, 1.0])
def test_alert_engine_rejects_anything_but_a_positive_integer_owner(owner):
    storage = MemoryWatchlistStorage()
    storage.add(WatchEntry(user_id=5, symbol="TCS"))
    storage.filings["TCS"] = COMPLIANT
    with pytest.raises(ValueError):
        AlertEngine(storage).check("TCS", user_id=owner)
    assert storage.list(5)[0].last_is_compliant is None


@pytest.mark.parametrize(
    "verdict, is_compliant, issues, expected",
    [
        ("compliant", True, False, True),
        ("non-compliant", False, False, False),
        ("compliant", True, True, None),
        ("needs-review", None, False, None),
        ("compliant", None, False, None),
        (None, None, False, None),
    ],
)
def test_conclusive(verdict, is_compliant, issues, expected):
    assert conclusive(verdict, is_compliant, issues) is expected


# --- the PostgreSQL storage's statements, without a database ------------------


class _Cursor:
    def __init__(self, results):
        self.results = list(results)
        self.statements = []
        self.rowcount = 0

    def execute(self, sql, params=None):
        self.statements.append((sql, params))
        self.rowcount = 1

    def fetchone(self):
        return self.results.pop(0)

    def fetchall(self):
        return self.results.pop(0)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class _DB:
    def __init__(self, results=()):
        self.cursor_obj = _Cursor(results)
        self.commits = 0
        self.locked = []

    def _lock_filing(self, cursor, symbol, filing_date):
        cursor.execute("LOCK", (symbol, filing_date))

    def get_connection(self):
        db = self

        class _Conn:
            def cursor(self):
                return db.cursor_obj

            def commit(self):
                db.commits += 1

            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

        return _Conn()


def test_postgres_observe_locks_the_filing_then_seeds_before_flipping():
    filing = {"symbol": "TCSLTD", "filing_date": FILED}
    evaluation = {"verdict": "non-compliant", "is_compliant": False, "evaluated_at": FILED, "open_issues": False}
    db = _DB([filing, evaluation, [{"user_id": 7}]])
    observation = WatchlistStorage(lambda: db).observe("TCS", user_id=7)
    assert [sql for sql, _ in db.cursor_obj.statements] == [_NEWEST_FILING_SQL, "LOCK", _EVALUATION_SQL, _SEED_SQL, _FLIP_SQL]
    assert db.cursor_obj.statements[1][1] == ("TCSLTD", FILED)  # the D-027 lock on the canonical filing
    assert db.cursor_obj.statements[3][1]["watch_symbol"] == "TCS"  # rows keyed by the watched symbol
    assert observation.is_compliant is False and observation.flipped == [7]
    assert db.commits == 1


@pytest.mark.parametrize(
    "results",
    [
        [None],  # no filing: no lock, nothing moved
        [{"symbol": "TCS", "filing_date": FILED}, None],  # not evaluated
        [{"symbol": "TCS", "filing_date": FILED},
         {"verdict": "compliant", "is_compliant": True, "evaluated_at": FILED, "open_issues": True}],
    ],
)
def test_postgres_observe_without_a_verdict_writes_nothing(results):
    db = _DB(results)
    assert WatchlistStorage(lambda: db).observe("TCS").is_compliant is None
    assert _SEED_SQL not in [sql for sql, _ in db.cursor_obj.statements]
    assert db.commits == 1


def test_postgres_add_keeps_the_baseline_and_list_is_owner_scoped():
    db = _DB([[{"user_id": 7, "symbol": "TCS", "trigger": "compliance_flip", "last_is_compliant": True}]])
    storage = WatchlistStorage(lambda: db)
    storage.add(WatchEntry(user_id=7, symbol="TCS"))
    assert "ON CONFLICT (user_id, symbol, trigger) DO NOTHING" in db.cursor_obj.statements[0][0]
    assert storage.list(7) == [WatchEntry(7, "TCS", "compliance_flip", True)]
    assert db.cursor_obj.statements[1][1] == {"user_id": 7}
    assert db.commits == 2
    with pytest.raises(ValueError):
        storage.list(None)

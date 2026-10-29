#!/usr/bin/env python3
"""Tests for watchlist storage and alert engine."""

import pytest

from alerts import AlertEngine, WatchEntry, WatchlistStorage
from alerts.storage import _FLIP_SQL, _SEED_SQL
from tests.watchlist_fake import MemoryWatchlistStorage


def test_watchlist_add_and_list():
    storage = MemoryWatchlistStorage()
    storage.add(WatchEntry(user_id=1, symbol="TCS"))

    items = storage.list(1)
    assert len(items) == 1
    assert items[0].symbol == "TCS"


def test_alert_engine_emits_on_flip():
    storage = MemoryWatchlistStorage()
    storage.add(WatchEntry(user_id=2, symbol="INFY"))
    engine = AlertEngine(storage)

    # First conclusive verdict seeds the baseline
    assert engine.process_verdict("INFY", True, user_id=2) == []

    events_flip = engine.process_verdict("INFY", False, user_id=2)
    assert len(events_flip) == 1
    assert events_flip[0].user_id == "user:2"
    assert "Non-Halal" in events_flip[0].message
    assert engine.process_verdict("INFY", False, user_id=2) == []  # no repeat


def test_unknown_verdict_neither_alerts_nor_moves_the_baseline():
    storage = MemoryWatchlistStorage()
    storage.add(WatchEntry(user_id=3, symbol="WIPRO"))
    engine = AlertEngine(storage)

    assert engine.process_verdict("WIPRO", True, user_id=3) == []  # seeds baseline
    assert engine.process_verdict("WIPRO", None, user_id=3) == []  # unknown: no alert
    assert storage.list(3)[0].last_is_compliant is True  # baseline untouched

    events = engine.process_verdict("WIPRO", False, user_id=3)  # True -> None -> False flips once
    assert len(events) == 1
    assert "Non-Halal" in events[0].message
    assert engine.process_verdict("WIPRO", None, user_id=3) == []


def test_alert_engine_only_touches_the_given_user():
    storage = MemoryWatchlistStorage()
    storage.add(WatchEntry(user_id=10, symbol="TCS"))
    storage.add(WatchEntry(user_id=11, symbol="TCS"))
    engine = AlertEngine(storage)

    assert engine.process_verdict("TCS", True, user_id=10) == []
    events = engine.process_verdict("TCS", False, user_id=10)
    assert [e.user_id for e in events] == ["user:10"]
    # User 11's baseline was never seeded or moved by user 10's checks.
    assert storage.list(11)[0].last_is_compliant is None


def test_readding_a_symbol_keeps_its_baseline():
    storage = MemoryWatchlistStorage()
    storage.add(WatchEntry(user_id=4, symbol="TCS"))
    AlertEngine(storage).process_verdict("TCS", True, user_id=4)
    storage.add(WatchEntry(user_id=4, symbol="TCS"))
    assert storage.list(4)[0].last_is_compliant is True


@pytest.mark.parametrize("owner", [0, -1, None, "", "user:1", "1", True, 1.0])
def test_alert_engine_rejects_anything_but_a_positive_integer_owner(owner):
    storage = MemoryWatchlistStorage()
    storage.add(WatchEntry(user_id=5, symbol="TCS"))
    with pytest.raises(ValueError):
        AlertEngine(storage).process_verdict("TCS", True, user_id=owner)
    assert storage.list(5)[0].last_is_compliant is None


class _Cursor:
    def __init__(self, rowcounts):
        self.rowcounts = list(rowcounts)
        self.statements = []
        self.rowcount = 0

    def execute(self, sql, params):
        self.statements.append((sql, params))
        self.rowcount = self.rowcounts.pop(0)

    def fetchall(self):
        return [(7, "TCS", "compliance_flip", True)]

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class _DB:
    def __init__(self, rowcounts=()):
        self.cursor_obj = _Cursor(rowcounts)
        self.commits = 0

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


@pytest.mark.parametrize(
    "rowcounts, outcome, statements",
    [
        ([1], "baseline", [_SEED_SQL]),  # NULL row: seeded, no flip attempted
        ([0, 1], "flip", [_SEED_SQL, _FLIP_SQL]),  # seed first, then the flip
        ([0, 0], None, [_SEED_SQL, _FLIP_SQL]),  # same verdict or no row
    ],
)
def test_postgres_transition_seeds_before_flipping_and_commits(rowcounts, outcome, statements):
    db = _DB(rowcounts)
    storage = WatchlistStorage(lambda: db)
    assert storage.transition(7, "TCS", "compliance_flip", False) == outcome
    assert [sql for sql, _ in db.cursor_obj.statements] == statements
    assert db.cursor_obj.statements[0][1] == {
        "user_id": 7, "symbol": "TCS", "trigger": "compliance_flip", "verdict": False,
    }
    assert db.commits == 1


def test_postgres_add_keeps_the_baseline_and_list_is_owner_scoped():
    db = _DB([1, 1])
    storage = WatchlistStorage(lambda: db)
    storage.add(WatchEntry(user_id=7, symbol="TCS"))
    assert "ON CONFLICT (user_id, symbol, trigger) DO NOTHING" in db.cursor_obj.statements[0][0]
    assert storage.list(7) == [WatchEntry(7, "TCS", "compliance_flip", True)]
    assert db.cursor_obj.statements[1][1] == {"user_id": 7}
    assert db.commits == 2
    with pytest.raises(ValueError):
        storage.list(None)

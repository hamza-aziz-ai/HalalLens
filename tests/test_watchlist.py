#!/usr/bin/env python3
"""Tests for watchlist storage and alert engine."""

from pathlib import Path

import pytest

from alerts import AlertEngine, WatchEntry, WatchlistStorage


def test_watchlist_upsert_and_list(tmp_path: Path):
    storage = WatchlistStorage(tmp_path / "watch.json")
    entry = WatchEntry(user_id="u1", symbol="TCS")
    storage.upsert(entry)

    items = storage.list("u1")
    assert len(items) == 1
    assert items[0].symbol == "TCS"


def test_alert_engine_emits_on_flip(tmp_path: Path):
    storage = WatchlistStorage(tmp_path / "watch.json")
    storage.upsert(WatchEntry(user_id="u2", symbol="INFY"))
    engine = AlertEngine(storage)

    # First update seeds last_is_compliant
    events_initial = engine.process_verdict("INFY", True, user_id="u2")
    assert events_initial == []

    events_flip = engine.process_verdict("INFY", False, user_id="u2")
    assert len(events_flip) == 1
    assert "Non-Halal" in events_flip[0].message


def test_unknown_verdict_neither_alerts_nor_moves_the_baseline(tmp_path: Path):
    storage = WatchlistStorage(tmp_path / "watch.json")
    storage.upsert(WatchEntry(user_id="u3", symbol="WIPRO"))
    engine = AlertEngine(storage)

    assert engine.process_verdict("WIPRO", True, user_id="u3") == []  # seeds baseline
    assert engine.process_verdict("WIPRO", None, user_id="u3") == []  # unknown: no alert
    assert storage.list("u3")[0].last_is_compliant is True  # baseline untouched

    events = engine.process_verdict("WIPRO", False, user_id="u3")  # True -> None -> False flips once
    assert len(events) == 1
    assert "Non-Halal" in events[0].message
    assert engine.process_verdict("WIPRO", None, user_id="u3") == []


def test_alert_engine_only_touches_the_given_user(tmp_path: Path):
    storage = WatchlistStorage(tmp_path / "watch.json")
    storage.upsert(WatchEntry(user_id="alice", symbol="TCS"))
    storage.upsert(WatchEntry(user_id="bob", symbol="TCS"))
    engine = AlertEngine(storage)

    assert engine.process_verdict("TCS", True, user_id="alice") == []
    events = engine.process_verdict("TCS", False, user_id="alice")
    assert [e.user_id for e in events] == ["alice"]
    # Bob's baseline was never seeded or moved by Alice's checks.
    assert storage.list("bob")[0].last_is_compliant is None


@pytest.mark.parametrize("owner", ["", "   ", None])
def test_alert_engine_rejects_a_blank_owner(tmp_path: Path, owner):
    storage = WatchlistStorage(tmp_path / "watch.json")
    storage.upsert(WatchEntry(user_id="alice", symbol="TCS"))
    with pytest.raises(ValueError):
        AlertEngine(storage).process_verdict("TCS", True, user_id=owner)
    assert storage.list("alice")[0].last_is_compliant is None

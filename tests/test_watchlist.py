#!/usr/bin/env python3
"""Tests for watchlist storage and alert engine."""

from pathlib import Path

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
    events_initial = engine.process_verdict("INFY", True)
    assert events_initial == []

    events_flip = engine.process_verdict("INFY", False)
    assert len(events_flip) == 1
    assert "Non-Halal" in events_flip[0].message

#!/usr/bin/env python3
"""Tests for FastAPI route handlers without spinning up an HTTP client."""

import asyncio
import importlib
from datetime import datetime

import pytest

from alerts import AlertEngine, WatchlistStorage

api_module = importlib.import_module("api.app")
from api.app import (
    AlertCheckPayload,
    FinancialSnapshotPayload,
    HalalScoreRequest,
    MarketDataPayload,
    WatchlistEntryPayload,
)


def _sample_request() -> HalalScoreRequest:
    return HalalScoreRequest(
        snapshot=FinancialSnapshotPayload(
            symbol="TCS",
            filing_date=datetime(2024, 6, 30),
            total_debt=25_000_000,
            cash_equiv=10_000_000,
            revenue=200_000_000,
            non_permissible_income=5_000_000,
        ),
        market_data=MarketDataPayload(market_cap=400_000_000),
    )


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def test_halal_score_handler_returns_expected_ratios():
    response = _run(api_module.halal_score(_sample_request()))
    assert response.symbol == "TCS"
    assert response.is_compliant is True
    assert "debt_to_market_cap" in response.ratios


def test_narrate_handler_produces_summary():
    response = _run(api_module.narrate(_sample_request()))
    assert response.symbol == "TCS"
    assert isinstance(response.summary, str)
    assert len(response.bullets) == 3


def test_halal_score_handler_requires_market_cap():
    payload = _sample_request()
    payload.market_data.market_cap = None
    payload.market_data.trailing_market_cap = None
    with pytest.raises(Exception) as excinfo:
        _run(api_module.halal_score(payload))
    assert "market_cap or trailing_market_cap is required" in str(excinfo.value)


@pytest.fixture()
def isolated_watch_storage(tmp_path):
    storage = WatchlistStorage(tmp_path / "watch.json")
    api_module.watch_storage = storage
    api_module.alert_engine = AlertEngine(storage)
    yield


def test_watchlist_and_alert_handlers(isolated_watch_storage):
    entry = WatchlistEntryPayload(
        user_id="user-1",
        symbol="INFY",
        trigger="compliance_flip",
    )

    stored = _run(api_module.add_watchlist(entry))
    assert stored.user_id == "user-1"

    items = _run(api_module.list_watchlist("user-1"))
    assert len(items) == 1
    assert items[0].symbol == "INFY"

    empty_events = _run(
        api_module.check_alerts(AlertCheckPayload(symbol="INFY", is_compliant=True))
    )
    assert empty_events == []

    events = _run(
        api_module.check_alerts(AlertCheckPayload(symbol="INFY", is_compliant=False))
    )
    assert len(events) == 1
    assert "Non-Halal" in events[0].message

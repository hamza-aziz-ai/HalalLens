#!/usr/bin/env python3
"""Tests for market data fallback resolver."""

from datetime import date, datetime, timedelta

from market_data.resolver import BhavcopyMarketResolver
from market_data.bhavcopy import BSEBhavRecord


class FakeBhavcopyClient:
    def __init__(self):
        self.bse = {}
        self.nse = {}

    def fetch_bse_equity(self, as_of: date):
        return self.bse.get(as_of, {})

    def fetch_nse_market_caps(self, as_of: date):
        return self.nse.get(as_of, {})


def _record(symbol: str, isin: str, price: float) -> BSEBhavRecord:
    return BSEBhavRecord(symbol=symbol, isin=isin, close=price, company_name="Demo")


def test_resolver_returns_market_cap_and_price():
    today = date(2024, 7, 1)
    client = FakeBhavcopyClient()
    client.bse[today] = {"544198": _record("544198", "INE0000A", 215.7)}
    client.nse[today] = {"INE0000A": 14_949_183_488.0}

    resolver = BhavcopyMarketResolver(client=client, lookback_days=2)
    cap, price = resolver.resolve("544198", datetime(2024, 7, 1, 12, 0))

    assert cap == 14_949_183_488.0
    assert price == 215.7


def test_resolver_uses_lookback_days():
    today = date(2024, 7, 10)
    previous = today - timedelta(days=1)
    client = FakeBhavcopyClient()
    client.bse[previous] = {"531779": _record("531779", "INE9999B", 100.0)}
    client.nse[previous] = {"INE9999B": 500_000_000.0}

    resolver = BhavcopyMarketResolver(client=client, lookback_days=3)
    cap, price = resolver.resolve("531779", datetime(2024, 7, 10, 9, 0))

    assert cap == 500_000_000.0
    assert price == 100.0


def test_resolver_uses_nse_lookback_for_market_cap():
    today = date(2024, 7, 10)
    older = today - timedelta(days=30)
    client = FakeBhavcopyClient()
    client.bse[today] = {"500325": _record("500325", "INE8888Z", 2760.0)}
    client.nse[older] = {"INE8888Z": 18_000_000_000.0}

    resolver = BhavcopyMarketResolver(
        client=client,
        lookback_days=5,
        nse_lookback_days=60,
    )
    cap, price = resolver.resolve("500325", datetime(2024, 7, 10, 9, 0))

    assert cap == 18_000_000_000.0
    assert price == 2760.0


def test_resolver_returns_price_when_market_cap_missing():
    today = date(2024, 6, 30)
    client = FakeBhavcopyClient()
    client.bse[today] = {"540148": _record("540148", "INE1234C", 88.5)}
    client.nse[today] = {}

    resolver = BhavcopyMarketResolver(client=client, lookback_days=1)
    cap, price = resolver.resolve("540148", datetime(2024, 6, 30, 15, 0))

    assert cap is None
    assert price == 88.5


def test_resolver_prefers_cached_quotes():
    today = date(2024, 7, 20)
    calls = []

    def loader(symbol: str, trade_date: date):
        calls.append(trade_date)
        if trade_date == today:
            return (1_000_000_000.0, 123.45, "bhavcopy")
        return None

    writer_calls = []

    def writer(symbol, trade_date, share_price, market_cap, provider):
        writer_calls.append((symbol, trade_date, share_price, market_cap, provider))

    client = FakeBhavcopyClient()
    resolver = BhavcopyMarketResolver(
        client=client, cache_loader=loader, cache_writer=writer
    )

    cap, price = resolver.resolve("500325", datetime(2024, 7, 20, 9, 0))

    assert cap == 1_000_000_000.0
    assert price == 123.45
    assert writer_calls == []
    assert today in calls

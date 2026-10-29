#!/usr/bin/env python3
"""Integration-ish tests that mock DB manager for filings endpoint."""

from datetime import datetime, timezone
from typing import Dict

import importlib
import pytest
from tests.quality_fake import MemoryQualityDB
from tests.utils import run_async

api_module = importlib.import_module("api.app")


class DummyDB(MemoryQualityDB):
    def __init__(self, filing: Dict):
        super().__init__()
        self.filing = filing

    def get_recent_filings(self, limit: int = 20):
        return [self.filing]

    def get_latest_filing(self, symbol: str):
        return self.filing

    def get_cached_market_data(self, symbol: str, as_of=None):
        return (1_000_000_000, None, "yahoo")

    def insert_market_snapshot(self, symbol, market_cap, share_price, provider="yahoo"):
        return None

    def get_bhavcopy_quote(self, symbol, trade_date):
        return None

    def upsert_bhavcopy_quote(
        self, *, symbol, trade_date, share_price, market_cap, provider="bhavcopy"
    ):
        self.last_bhavcopy = (symbol, trade_date, share_price, market_cap, provider)

    def get_symbol_code(self, symbol: str):
        return "ABC"

    def get_symbol_metadata(self, identifier: str):
        return {"symbol": "ABC", "symbol_alias": "ABC"}

    def get_symbol_alias(self, symbol: str):
        return "ABC"

    def get_database_stats(self):
        return {"total_announcements": 1}

    def insert_feedback(self, **kwargs):
        self.last_feedback = kwargs
        return {
            "id": 1,
            "symbol": kwargs.get("symbol"),
            "filing_date": kwargs.get("filing_date"),
            "verdict": kwargs.get("verdict"),
            "message": kwargs.get("message"),
            "contact": kwargs.get("contact"),
            "source": kwargs.get("source"),
            "status": kwargs.get("status", "open"),
            "review_notes": None,
            "resolved_at": None,
            "resolved_by": None,
            "public_token": kwargs.get("public_token", "token"),
            "status_updated_at": datetime.now(timezone.utc),
            "reevaluated_at": None,
            "reevaluation_notes": None,
            "created_at": datetime.now(timezone.utc),
        }


@pytest.fixture(autouse=True)
def patch_db(monkeypatch):
    record = {
        "symbol": "ABC",
        "company_name": "ABC LTD",
        "filing_date": datetime(2024, 6, 30),
        "category": "Result",
        "headline": "Quarterly",
        "confidence": "HIGH",
        "total_debt": 10_000_000,
        "cash_equiv": 5_000_000,
        "revenue": 100_000_000,
        "interest_income": 500_000,
        "dividend_income": 100_000,
        "ratios": None,
    }
    dummy = DummyDB(record)
    monkeypatch.setattr(api_module, "DB_MANAGER", dummy)
    monkeypatch.setattr(api_module, "indian_api_enabled", lambda: False)
    yield


def test_filings_detail_computes_ratios():
    response = run_async(api_module.filing_detail("ABC"))
    assert response.symbol == "ABC"
    assert response.ratios is not None
    assert response.ratios["debt_to_market_cap"].passed is True


def test_recent_filings_uses_db():
    rows = run_async(api_module.recent_filings())
    assert len(rows) == 1
    assert rows[0].symbol == "ABC"


def test_feedback_endpoint_stores_message():
    payload = api_module.FeedbackPayload(
        symbol="ABC",
        verdict="compliant",
        message="Numbers look off",
        contact="qa@example.com",
    )
    response = run_async(api_module.submit_feedback(payload))
    assert response.status == "received"
    assert response.tracking_token
    assert api_module.DB_MANAGER.last_feedback["symbol"] == "ABC"


def test_feedback_requires_message():
    payload = api_module.FeedbackPayload(symbol="ABC", message="   ")
    with pytest.raises(Exception):
        run_async(api_module.submit_feedback(payload))

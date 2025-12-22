#!/usr/bin/env python3
"""Tests for FastAPI route handlers without spinning up an HTTP client."""

import asyncio
import importlib
from datetime import datetime, timezone

import pytest

from alerts import AlertEngine, WatchlistStorage

api_module = importlib.import_module("api.app")
from api.app import (
    AlertCheckPayload,
    FinancialSnapshotPayload,
    HalalScoreRequest,
    MarketDataPayload,
    WatchlistEntryPayload,
    FeedbackUpdatePayload,
    GovernanceOverridePayload,
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
    assert len(response.bullets) >= 3


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


class FeedbackDBStub:
    def __init__(self):
        self.reports = [
            {
                "id": 1,
                "symbol": "TCS",
                "filing_date": datetime(2024, 7, 1),
                "verdict": "non-compliant",
                "message": "Verdict looks off",
                "contact": "analyst@example.com",
                "source": "ui",
                "status": "open",
                "review_notes": None,
                "resolved_at": None,
                "resolved_by": None,
                "public_token": "token123",
                "status_updated_at": datetime(2024, 7, 2, 12, 0),
                "reevaluated_at": None,
                "reevaluation_notes": None,
                "created_at": datetime(2024, 7, 2),
            }
        ]

    def get_filing(self, symbol, filing_date):
        return None

    def get_quality_issues(self, symbol, filing_date):
        return []

    def get_cached_market_data(self, symbol, as_of=None):
        return (500_000_000, None, "yahoo")

    def insert_market_snapshot(self, symbol, market_cap, share_price, provider="yahoo"):
        return None

    def get_bhavcopy_quote(self, symbol, trade_date):
        return None

    def upsert_bhavcopy_quote(
        self, *, symbol, trade_date, share_price, market_cap, provider="bhavcopy"
    ):
        return None

    def resolve_quality_issues(self, symbol, filing_date, issue_types=None):
        return []

    def record_quality_issue(self, symbol, filing_date, issue_type, details):
        return None

    def upsert_filing_evaluation(self, **kwargs):
        return None

    def get_bhavcopy_quote(self, symbol, trade_date):
        return None

    def upsert_bhavcopy_quote(
        self, *, symbol, trade_date, share_price, market_cap, provider="bhavcopy"
    ):
        return None

    def list_feedback_reports(self, status=None, limit=50):
        rows = self.reports
        if status:
            rows = [row for row in rows if row["status"] == status]
        return rows[:limit]

    def update_feedback_report(self, feedback_id, status, reviewer=None, review_notes=None):
        for row in self.reports:
            if row["id"] == feedback_id:
                row["status"] = status
                if review_notes is not None:
                    row["review_notes"] = review_notes
                if status == "resolved":
                    row["resolved_at"] = datetime(2024, 7, 3)
                    row["resolved_by"] = reviewer
                else:
                    row["resolved_at"] = None
                    row["resolved_by"] = None
                row["status_updated_at"] = datetime(2024, 7, 3, 9, 0)
                return row
        return None

    def record_feedback_reevaluation(self, feedback_id, notes):
        for row in self.reports:
            if row["id"] == feedback_id:
                row["reevaluated_at"] = datetime(2024, 7, 3, 10, 0)
                row["reevaluation_notes"] = notes
                return row
        return None

    def get_feedback_by_token(self, token):
        for row in self.reports:
            if row["public_token"] == token:
                return row
        return None


class GovernanceOverrideDBStub:
    def __init__(self):
        self.rows = []

    def list_governance_overrides(self, symbol=None, limit=50):
        rows = self.rows
        if symbol:
            rows = [row for row in rows if row["symbol"] == symbol]
        return rows[:limit]

    def upsert_governance_override(
        self,
        *,
        symbol,
        filing_date,
        accounts_receivable=None,
        liquid_assets=None,
        non_halal_income=None,
        governance_notes=None,
        reviewer=None,
        reason=None,
        source="manual",
    ):
        row = {
            "symbol": symbol,
            "filing_date": filing_date,
            "accounts_receivable": accounts_receivable,
            "liquid_assets": liquid_assets,
            "non_halal_income": non_halal_income,
            "governance_notes": governance_notes,
            "reviewer": reviewer,
            "reason": reason,
            "source": source,
            "created_at": datetime.now(timezone.utc),
            "updated_at": datetime.now(timezone.utc),
        }
        self.rows = [r for r in self.rows if not (r["symbol"] == symbol and r["filing_date"] == filing_date)]
        self.rows.append(row)
        return row

    def delete_governance_override(self, symbol, filing_date):
        before = len(self.rows)
        self.rows = [r for r in self.rows if not (r["symbol"] == symbol and r["filing_date"] == filing_date)]
        return len(self.rows) < before

    def get_bhavcopy_quote(self, symbol, trade_date):
        return None

    def upsert_bhavcopy_quote(
        self, *, symbol, trade_date, share_price, market_cap, provider="bhavcopy"
    ):
        return None


class HistoryDBStub:
    def __init__(self):
        self.last_history_limit = None
        self.history = [
            {
                "symbol": "TCS",
                "company_name": "Tata Consultancy Services",
                "filing_date": datetime(2024, 6, 30, tzinfo=timezone.utc),
                "category": "Result",
                "headline": "Q1 Results",
                "confidence": "HIGH",
                "total_debt": 100.0,
                "cash_equiv": 50.0,
                "revenue": 500.0,
                "interest_income": 5.0,
                "dividend_income": 2.0,
                "audit_status": "audited",
                "ratios": None,
                "market_cap_used": 1000.0,
                "trailing_cap_used": None,
            }
        ]

    def get_filing_history(self, symbol, limit=10):
        if symbol != "TCS":
            return []
        self.last_history_limit = limit
        return self.history[:limit]

    def resolve_quality_issues(self, symbol, filing_date, issue_types=None):
        return 0

    def upsert_filing_evaluation(self, **kwargs):
        return None

    def get_symbol_metadata(self, identifier):
        return {"symbol": "TCS", "symbol_alias": "TCS"} if identifier == "TCS" else None


def test_feedback_queue_endpoints(monkeypatch):
    db = FeedbackDBStub()
    monkeypatch.setattr(api_module, "DB_MANAGER", db)

    reports = _run(api_module.list_feedback(status="open", limit=10))
    assert len(reports) == 1
    assert reports[0].status == "open"

    payload = FeedbackUpdatePayload(status="resolved", review_notes="fixed", reviewer="qa")
    updated = _run(api_module.update_feedback(1, payload))
    assert updated.status == "resolved"
    assert updated.review_notes == "fixed"
    assert updated.reevaluation_notes is not None


def test_resolve_bse_code_uses_indian_api(monkeypatch):
    monkeypatch.setattr(api_module, "indian_api_enabled", lambda: True)

    class DummySnapshot:
        def __init__(self):
            self.symbol = "TCS"
            self.market_cap = None
            self.share_price = None
            self.shares_outstanding = None
            self.end_date = None
            self.metrics = {}
            self.bse_code = "532540"
            self.nse_code = "TCS"

    monkeypatch.setattr(
        api_module,
        "fetch_indian_financial_snapshot",
        lambda symbol, target_date=None: DummySnapshot(),
    )
    class NoopDB:
        def get_symbol_metadata(self, identifier):
            return None

    monkeypatch.setattr(api_module, "DB_MANAGER", NoopDB())
    api_module.SYMBOL_METADATA_CACHE.clear()

    code = api_module._resolve_bse_script_code("TCS")
    assert code == "532540"
    assert api_module.SYMBOL_METADATA_CACHE["TCS"]["symbol"] == "532540"


def test_feedback_public_status(monkeypatch):
    db = FeedbackDBStub()
    monkeypatch.setattr(api_module, "DB_MANAGER", db)
    response = _run(api_module.feedback_status("token123"))
    assert response.ticket_id == 1
    assert response.status == "open"


def test_filing_detail_respects_governance_overrides(monkeypatch):
    class OverrideDB:
        def __init__(self):
            self.record = {
                "symbol": "ABC",
                "company_name": "ABC Ltd",
                "filing_date": datetime(2024, 7, 1, tzinfo=timezone.utc),
                "category": "Result",
                "headline": "Result",
                "confidence": "HIGH",
                "total_debt": 10_000_000,
                "cash_equiv": 4_000_000,
                "revenue": 50_000_000,
                "interest_income": 100_000,
                "dividend_income": 40_000,
                "ratios": None,
                "accounts_receivable": 5_000_000,
                "liquid_assets": 8_000_000,
                "non_halal_income": 25_000,
                "governance_notes": "auto",
                "governance_override_applied": True,
                "governance_override_source": "manual",
                "governance_override_reviewer": "ops",
                "governance_override_reason": "pdf typo",
                "governance_override_updated_at": datetime(
                    2024, 7, 2, tzinfo=timezone.utc
                ),
            }

        def get_latest_filing(self, symbol):
            return self.record

        def get_cached_market_data(self, symbol, as_of=None):
            return (400_000_000, None, "yahoo")

        def insert_market_snapshot(self, symbol, market_cap, share_price, provider="yahoo"):
            return None

        def upsert_filing_evaluation(self, **kwargs):
            return None

        def resolve_quality_issues(self, symbol, filing_date, issue_types=None):
            return []

        def record_quality_issue(self, symbol, filing_date, issue_type, details):
            return None

        def get_quality_issues(self, symbol, filing_date):
            return []

        def get_symbol_metadata(self, identifier):
            return {"symbol": "ABC", "symbol_alias": "ABC"}

        def get_symbol_alias(self, symbol):
            return "ABC"

        def get_symbol_code(self, symbol):
            return "ABC"

        def get_bhavcopy_quote(self, symbol, trade_date):
            return None

        def upsert_bhavcopy_quote(
            self, *, symbol, trade_date, share_price, market_cap, provider="bhavcopy"
        ):
            return None

    db = OverrideDB()
    monkeypatch.setattr(api_module, "DB_MANAGER", db)

    result = _run(api_module.filing_detail("ABC"))
    assert result.symbol == "ABC"
    assert result.accounts_receivable == 5_000_000
    assert result.governance_override_applied is True
    assert result.governance_override_reviewer == "ops"
    assert "debt_to_market_cap" in result.ratios


def test_governance_override_endpoints(monkeypatch):
    db = GovernanceOverrideDBStub()
    monkeypatch.setattr(api_module, "DB_MANAGER", db)
    filing_date = datetime(2024, 6, 30, tzinfo=timezone.utc)

    payload = GovernanceOverridePayload(
        symbol="TCS",
        filing_date=filing_date,
        accounts_receivable=100.0,
        reason="Manual fix",
        reviewer="ops",
    )
    created = _run(api_module.upsert_governance_override(payload))
    assert created.symbol == "TCS"

    overrides = _run(api_module.list_governance_overrides(symbol="TCS", limit=5))
    assert len(overrides) == 1
    assert overrides[0].accounts_receivable == 100.0

    _run(
        api_module.delete_governance_override("TCS", filing_date.isoformat())
    )
    overrides = _run(api_module.list_governance_overrides(symbol="TCS", limit=5))
    assert overrides == []


def test_filing_history_endpoint(monkeypatch):
    db = HistoryDBStub()
    monkeypatch.setattr(api_module, "DB_MANAGER", db)
    history = _run(api_module.filing_history("TCS", limit=5))
    assert len(history) == 1
    entry = history[0]
    assert entry.symbol == "TCS"
    assert entry.market_cap_used == 1000.0
    assert "debt_to_market_cap" in entry.ratios
    assert db.last_history_limit == 5

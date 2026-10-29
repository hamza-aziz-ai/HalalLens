#!/usr/bin/env python3
"""Tests for FastAPI route handlers without spinning up an HTTP client."""

import asyncio
import importlib
import json
from datetime import datetime, timezone
from typing import Any, Dict

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from alerts import AlertEngine
from evaluation import quality
from tests.quality_fake import MemoryQualityDB
from tests.watchlist_fake import MemoryWatchlistStorage

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
            interest_income=1_000_000,
            dividend_income=0,
            accounts_receivable=20_000_000,
            liquid_assets=40_000_000,
        ),
        market_data=MarketDataPayload(market_cap=400_000_000),
    )


def _partial_request() -> HalalScoreRequest:
    """Only debt/cash/revenue/market cap: must screen as insufficient, not pass."""

    return HalalScoreRequest(
        snapshot=FinancialSnapshotPayload(
            symbol="TCS",
            filing_date=datetime(2024, 6, 30),
            total_debt=25_000_000,
            cash_equiv=10_000_000,
            revenue=200_000_000,
        ),
        market_data=MarketDataPayload(market_cap=400_000_000),
    )


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


@pytest.fixture()
def paid_access(monkeypatch):
    monkeypatch.setattr(
        api_module,
        "_require_paid_feature",
        lambda authorization, feature: {
            "user_id": 1,
            "email": "subscriber@example.com",
            "plan": "starter",
            "subscription_status": "active",
        },
    )


@pytest.fixture()
def admin_access(monkeypatch):
    """Stand in for an authenticated operator on admin-gated routes."""

    monkeypatch.setattr(
        api_module,
        "_require_admin",
        lambda authorization, feature: {
            "user_id": 99,
            "email": "ops@example.com",
            "plan": "starter",
            "subscription_status": "active",
            "is_admin": True,
        },
    )


def test_halal_score_handler_returns_expected_ratios():
    response = _run(api_module.halal_score(_sample_request()))
    assert response.symbol == "TCS"
    assert response.is_compliant is True
    assert response.screen_verdict == "compliant"
    assert "debt_to_market_cap" in response.ratios


def test_halal_score_partial_data_is_insufficient_not_a_500():
    response = _run(api_module.halal_score(_partial_request()))
    assert response.is_compliant is None
    assert response.screen_verdict == "insufficient-data"
    assert response.missing_inputs["non_permissible_income"] == "missing"


def test_narrate_partial_data_is_not_called_non_compliant(paid_access):
    response = _run(api_module.narrate(_partial_request()))
    assert response.is_compliant is None
    assert response.screen_verdict == "insufficient-data"
    assert "NOT compliant" not in response.verdict
    assert "insufficient" in response.verdict.lower()


def test_narrate_handler_produces_summary(paid_access):
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
def isolated_watch_storage():
    storage = MemoryWatchlistStorage()
    api_module.watch_storage = storage
    api_module.alert_engine = AlertEngine(storage)
    yield


def test_watchlist_and_alert_handlers(isolated_watch_storage, paid_access, monkeypatch):
    # The client-supplied user_id is deliberately someone else's: the handler
    # must ignore it and key the entry off the authenticated session instead.
    entry = WatchlistEntryPayload(
        user_id="victim-user",
        symbol="INFY",
        trigger="compliance_flip",
    )

    stored = _run(api_module.add_watchlist(entry))
    assert stored.user_id == "user:1"

    items = _run(api_module.list_watchlist("victim-user"))
    assert len(items) == 1
    assert items[0].symbol == "INFY"
    assert items[0].user_id == "user:1"

    # The verdict comes from the stored evaluation, never from the request.
    stored = {"verdict": "compliant", "is_compliant": True}

    class FilingDB:
        def get_latest_filing(self, symbol):
            return {"symbol": symbol, "filing_date": datetime(2026, 1, 1), **stored}

        def get_quality_issues(self, symbol, filing_date):
            return []

    monkeypatch.setattr(api_module, "_get_db", lambda: FilingDB())
    monkeypatch.setattr(api_module.email_notifier, "send", lambda event: None)

    assert _run(api_module.check_alerts(AlertCheckPayload(symbol="INFY"))) == []
    # A caller claiming a flip changes nothing: the stored verdict is unchanged.
    spoofed = AlertCheckPayload.model_validate({"symbol": "INFY", "is_compliant": False})
    assert _run(api_module.check_alerts(spoofed)) == []

    stored.update(verdict="non-compliant", is_compliant=False)
    events = _run(api_module.check_alerts(AlertCheckPayload(symbol="infy")))
    assert len(events) == 1
    assert events[0].user_id == "user:1"


def test_google_start_requires_config(monkeypatch):
    monkeypatch.setattr(api_module, "GOOGLE_CLIENT_ID", "cid", raising=False)
    monkeypatch.setattr(api_module, "GOOGLE_CLIENT_SECRET", "secret", raising=False)
    monkeypatch.setattr(
        api_module, "GOOGLE_REDIRECT_URI", "http://localhost/callback", raising=False
    )
    from tests.auth_fake import AuthDB

    monkeypatch.setattr(api_module, "_get_db", lambda: AuthDB())
    response = _run(api_module.auth_google_start())
    assert response.status_code == 307
    assert "accounts.google.com" in response.headers["location"]
    assert "hl_oauth=" in response.headers["set-cookie"]


class FeedbackDBStub(MemoryQualityDB):
    def __init__(self):
        super().__init__()
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
        self.events = [
            {
                "id": 1,
                "feedback_id": 1,
                "event_type": "submitted",
                "status": "open",
                "reviewer": None,
                "details": "Ticket created",
                "source": "ui",
                "created_at": datetime(2024, 7, 2, tzinfo=timezone.utc),
            }
        ]
        self.next_event_id = 2

    def _add_event(
        self,
        feedback_id,
        event_type,
        status=None,
        reviewer=None,
        details=None,
        source="api",
    ):
        event = {
            "id": self.next_event_id,
            "feedback_id": feedback_id,
            "event_type": event_type,
            "status": status,
            "reviewer": reviewer,
            "details": details,
            "source": source,
            "created_at": datetime(2024, 7, 3, tzinfo=timezone.utc),
        }
        self.next_event_id += 1
        self.events.append(event)
        return event

    def get_filing(self, symbol, filing_date):
        return None

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
                self._add_event(
                    feedback_id,
                    "status_change",
                    status=status,
                    reviewer=reviewer,
                    details=review_notes,
                )
                return row
        return None

    def record_feedback_reevaluation(self, feedback_id, notes):
        for row in self.reports:
            if row["id"] == feedback_id:
                row["reevaluated_at"] = datetime(2024, 7, 3, 10, 0)
                row["reevaluation_notes"] = notes
                self._add_event(
                    feedback_id,
                    "reevaluated",
                    status=row.get("status"),
                    reviewer=row.get("resolved_by"),
                    details=notes,
                )
                return row
        return None

    def get_feedback_by_token(self, token):
        for row in self.reports:
            if row["public_token"] == token:
                return row
        return None

    def get_feedback_events(self, feedback_id):
        return [dict(event) for event in self.events if event["feedback_id"] == feedback_id]

    def get_feedback_events_by_token(self, token):
        report = self.get_feedback_by_token(token)
        if not report:
            return []
        return self.get_feedback_events(report["id"])


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


class HistoryDBStub(MemoryQualityDB):
    def __init__(self):
        super().__init__()
        self.last_history_limit = None
        self.last_history_cursor = None
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
                "accounts_receivable": 120.0,
                "liquid_assets": 80.0,
                "non_halal_income": 4.0,
                "governance_notes": "Initial extraction",
                "governance_override_applied": True,
                "governance_override_reviewer": "Lead QA",
                "governance_override_reason": "Rounded figures",
                "governance_override_updated_at": datetime(2024, 7, 1, tzinfo=timezone.utc),
                "audit_status": "audited",
                "ratios": None,
                "market_cap_used": 1000.0,
                "trailing_cap_used": None,
            }
        ]
        self.override = {
            "symbol": "TCS",
            "filing_date": datetime(2024, 6, 30, tzinfo=timezone.utc),
            "accounts_receivable": 130.0,
            "liquid_assets": 90.0,
            "non_halal_income": 3.0,
            "governance_notes": "Manual tweak",
            "reviewer": "QA",
            "reason": "Verified PDF",
            "source": "manual",
            "updated_at": datetime(2024, 7, 2, tzinfo=timezone.utc),
        }

    def get_filing_history(self, symbol, limit=10, cursor_ts=None):
        if symbol != "TCS":
            return []
        self.last_history_limit = limit
        self.last_history_cursor = cursor_ts
        return self.history[:limit]

    def get_filing(self, symbol, filing_date):
        for row in self.history:
            if row["symbol"] == symbol and row["filing_date"] == filing_date:
                return dict(row)
        return None

    def insert_announcements(self, payloads):
        return len(payloads)

    def insert_financial_snapshots(self, snapshots):
        return len(snapshots)

    def insert_market_snapshot(self, symbol, market_cap, share_price, provider="indianapi"):
        return None

    def get_symbol_metadata(self, identifier):
        return {"symbol": "TCS", "symbol_alias": "TCS"} if identifier == "TCS" else None
    def get_governance_override(self, symbol, filing_date):
        if self.override and self.override["symbol"] == symbol and self.override["filing_date"] == filing_date:
            return dict(self.override)
        return None

    def get_indianapi_snapshot(self, symbol, target_date=None):
        return None

    def insert_indianapi_snapshot(self, **kwargs):
        return None


def test_feedback_queue_endpoints(monkeypatch, admin_access):
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
            self.company_name = "Tata Consultancy Services"
            self.raw = {}

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
    assert len(response.events) >= 1


def test_feedback_events_endpoint(monkeypatch, admin_access):
    db = FeedbackDBStub()
    monkeypatch.setattr(api_module, "DB_MANAGER", db)
    events = _run(api_module.feedback_events(1))
    assert len(events) >= 1
    assert events[0].event_type == "submitted"


def test_filing_detail_respects_governance_overrides(monkeypatch):
    class OverrideDB(MemoryQualityDB):
        def __init__(self):
            super().__init__()
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


def test_governance_override_endpoints(monkeypatch, admin_access):
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


def test_filing_history_endpoint(monkeypatch, paid_access):
    db = HistoryDBStub()
    monkeypatch.setattr(api_module, "DB_MANAGER", db)
    response = _run(api_module.filing_history("TCS", limit=5))
    history = response.entries
    assert len(history) == 1
    entry = history[0]
    assert entry.symbol == "TCS"
    assert entry.market_cap_used == 1000.0
    assert "debt_to_market_cap" in entry.ratios
    assert db.last_history_limit == 6  # limit + 1
    assert response.next_cursor is None


def test_governance_review_endpoint(monkeypatch, admin_access):
    db = HistoryDBStub()
    monkeypatch.setattr(api_module, "DB_MANAGER", db)

    class DummySnapshot:
        def __init__(self):
            self.symbol = "TCS"
            self.metrics = {
                "accounts_receivable": 140.0,
                "liquid_assets": 95.0,
                "non_halal_income": 2.5,
            }
            self.end_date = datetime(2024, 6, 30).date()
            self.market_cap = 1_200.0

    monkeypatch.setattr(
        api_module,
        "_load_indian_snapshot_for_filing",
        lambda symbol, filing_date: DummySnapshot(),
    )

    response = _run(
        api_module.governance_review(
            "TCS", datetime(2024, 6, 30, tzinfo=timezone.utc).isoformat()
        )
    )
    assert response.ingested.metrics["accounts_receivable"] == 120.0
    assert response.override is not None
    assert response.indian_api is not None
    assert "accounts_receivable" in response.differences


def test_filing_history_pagination_cursor(monkeypatch, paid_access):
    db = HistoryDBStub()
    monkeypatch.setattr(api_module, "DB_MANAGER", db)
    cursor = datetime(2024, 6, 30, tzinfo=timezone.utc).isoformat()
    _run(api_module.filing_history("TCS", limit=3, cursor=cursor))
    assert db.last_history_cursor == datetime(2024, 6, 30, tzinfo=timezone.utc)


def test_filing_history_falls_back_to_indian_api(monkeypatch, paid_access):
    db = HistoryDBStub()
    db.history = []
    monkeypatch.setattr(api_module, "DB_MANAGER", db)
    monkeypatch.setattr(api_module, "indian_api_enabled", lambda: True)

    def fake_supp(symbol, limit, existing):
        db.history.append(
            {
                "symbol": "TCS",
                "company_name": "Tata Consultancy Services",
                "filing_date": datetime(2024, 3, 31, tzinfo=timezone.utc),
                "category": "Result",
                "headline": "Synthetic",
                "confidence": "MEDIUM",
                "total_debt": 10.0,
                "cash_equiv": 5.0,
                "revenue": 50.0,
                "interest_income": 1.0,
                "dividend_income": 0.5,
                "audit_status": "indianapi",
                "ratios": {
                    "debt_to_market_cap": {
                        "value": 0.1,
                        "threshold": 0.3,
                        "passed": True,
                        "note": "auto",
                        "provider": "indianapi",
                    }
                },
                "market_cap_used": 100.0,
                "trailing_cap_used": None,
                "market_data_provider": "indianapi",
            }
        )
        return True

    monkeypatch.setattr(
        api_module, "_supplement_history_from_indian_api", fake_supp
    )

    response = _run(api_module.filing_history("TCS", limit=2))
    history = response.entries
    assert len(history) == 1
    assert db.last_history_limit == 3


def test_filing_detail_persists_indian_api_snapshot(monkeypatch, paid_access):
    class RealtimeDBStub(MemoryQualityDB):
        def __init__(self):
            super().__init__()
            self.announcement = None
            self.snapshot_payload = None
            self.market_snapshot = None
            self.indian_payload = None
            self.latest_record = None
            self.evaluation = None

        def get_latest_filing(self, identifier):
            if not self.latest_record:
                return None
            if identifier in (
                self.latest_record.get("symbol"),
                self.latest_record.get("symbol_alias"),
            ):
                return dict(self.latest_record)
            return None

        def insert_announcements(self, payloads):
            self.announcement = payloads[-1]

        def insert_financial_snapshots(self, snapshots):
            self.snapshot_payload = snapshots[-1]
            extracted = self.snapshot_payload.get("extracted_data") or {}
            record = {
                "symbol": self.snapshot_payload["symbol"],
                "symbol_alias": self.announcement.get("symbol_alias"),
                "company_name": self.announcement.get("company_name"),
                "filing_date": self.snapshot_payload["filing_date"],
                "category": self.announcement.get("category"),
                "headline": self.announcement.get("headline"),
                "confidence": self.announcement.get("confidence"),
                "audit_status": extracted.get("audit_status"),
                "total_debt": extracted.get("total_debt"),
                "cash_equiv": extracted.get("cash_equiv"),
                "revenue": extracted.get("revenue"),
                "interest_income": extracted.get("interest_income"),
                "dividend_income": extracted.get("dividend_income"),
                "accounts_receivable": extracted.get("accounts_receivable"),
                "liquid_assets": extracted.get("liquid_assets"),
                "non_halal_income": extracted.get("non_halal_income"),
                "governance_notes": extracted.get("governance_notes"),
                "ratios": None,
                "quality_issues": [],
            }
            if self.market_snapshot:
                record["market_cap_used"] = self.market_snapshot.get("market_cap")
                record["market_data_provider"] = self.market_snapshot.get("provider")
            else:
                record["market_cap_used"] = None
                record["market_data_provider"] = None
            record["trailing_cap_used"] = None
            self.latest_record = record
            return 1

        def insert_indianapi_snapshot(
            self, *, symbol, symbol_alias, company_name, snapshot_date, payload
        ):
            self.indian_payload = payload

        def get_filing(self, symbol, filing_date):
            return None

        def insert_market_snapshot(self, symbol, market_cap, share_price, provider="yahoo"):
            self.market_snapshot = {
                "symbol": symbol,
                "market_cap": market_cap,
                "share_price": share_price,
                "provider": provider,
            }

        def get_cached_market_data(self, symbol, as_of=None):
            return None

        def publish_filing_evaluation(self, **kwargs):
            published = super().publish_filing_evaluation(**kwargs)
            self.evaluation = self.writes[-1]
            if self.latest_record:
                self.latest_record["ratios"] = kwargs.get("ratios")
                self.latest_record["is_compliant"] = published["is_compliant"]
                self.latest_record["verdict"] = published["verdict"]
                self.latest_record["summary"] = published["summary"]
                self.latest_record["market_cap_used"] = kwargs.get("market_cap_used")
                self.latest_record["market_data_provider"] = kwargs.get(
                    "market_data_provider"
                )
            return published

        def get_symbol_metadata(self, identifier):
            return {"symbol": identifier, "symbol_alias": identifier}

        def get_symbol_alias(self, symbol):
            return symbol

        def get_symbol_code(self, identifier):
            return identifier

    class DummyFetcher:
        def get_company_announcements(self, code, start, end):
            return []

    class DummyProcessor:
        def process_announcements(self, announcements):
            return []

    class DummySnapshot:
        def __init__(self):
            self.symbol = "TCS"
            self.market_cap = 12_000_000.0
            self.share_price = 3324.9
            self.shares_outstanding = 361.81
            self.end_date = datetime(2025, 3, 31).date()
            self.metrics = {
                "total_debt": 100.0,
                "cash_equiv": 50.0,
                "revenue": 500.0,
                "interest_income": 5.0,
                "dividend_income": 2.0,
                "non_halal_income": 1.0,
                "accounts_receivable": 75.0,
                "liquid_assets": 125.0,
            }
            self.bse_code = "532540"
            self.nse_code = "TCS"
            self.company_name = "Tata Consultancy Services"
            self.raw = {"mock": True}

    db = RealtimeDBStub()
    monkeypatch.setattr(api_module, "DB_MANAGER", db)
    monkeypatch.setattr(api_module, "_get_db", lambda: db)
    monkeypatch.setattr(api_module, "_get_realtime_fetcher", lambda: DummyFetcher())
    monkeypatch.setattr(api_module, "_get_realtime_processor", lambda: DummyProcessor())
    monkeypatch.setattr(api_module, "indian_api_enabled", lambda: True)
    monkeypatch.setattr(
        api_module,
        "fetch_indian_financial_snapshot",
        lambda symbol, target_date=None: DummySnapshot(),
    )
    api_module.SYMBOL_METADATA_CACHE.clear()

    result = _run(api_module.filing_detail("TCS", refresh=True))
    assert result.symbol == "532540"
    assert result.company_name == "Tata Consultancy Services"
    assert result.total_debt == 100.0
    assert result.market_cap_used == 12_000_000.0
    assert result.market_data_provider == "indianapi"
    assert db.announcement is not None
    assert db.snapshot_payload is not None
    assert db.indian_payload is not None


def test_structured_enrichment_applies_overrides(monkeypatch):
    monkeypatch.setattr(api_module, "indian_api_enabled", lambda: True)
    monkeypatch.setattr(api_module, "_indian_api_candidates", lambda symbol: ["TCS"])

    class DummySnapshot:
        def __init__(self):
            self.metrics = {
                "accounts_receivable": 1_000_000.0,
                "liquid_assets": 2_000_000.0,
                "non_halal_income": 50_000.0,
                "total_debt": 100.0,
            }
            self.market_cap = None

    monkeypatch.setattr(
        api_module,
        "fetch_indian_financial_snapshot",
        lambda symbol, target_date=None: DummySnapshot(),
    )

    captured = {}

    def fake_persist(symbol, filing_date, overrides, note):
        captured["symbol"] = symbol
        captured["overrides"] = overrides
        captured["note"] = note

    monkeypatch.setattr(api_module, "_persist_structured_override", fake_persist)

    record = {
        "symbol": "TCS",
        "filing_date": datetime(2025, 3, 31, tzinfo=timezone.utc),
        "accounts_receivable": 100.0,
        "liquid_assets": 150.0,
        "non_permissible_income": 1.0,
        "non_halal_income": 1.0,
        "quality_issues": [],
    }

    api_module._maybe_enrich_record_with_indian_api(record)

    assert record["accounts_receivable"] == 1_000_000.0
    assert record["non_halal_income"] == 50_000.0
    assert captured["symbol"] == "TCS"
    assert {"accounts_receivable", "non_halal_income"} <= captured["overrides"].keys()
    assert any("Structured metrics" in issue for issue in record["quality_issues"])


def test_record_provider_failure_emits_warning(monkeypatch):
    notifications = []

    class DummyNotifier:
        def notify(self, level, title, details=None):
            notifications.append((level, title, details))

    monkeypatch.setattr(api_module, "market_notifier", DummyNotifier())
    monkeypatch.setattr(api_module, "MARKET_FAILURE_ALERT_THRESHOLD", 2)
    api_module.PROVIDER_FAILURES.clear()

    api_module._record_provider_failure("indianapi", "TCS", "timeout")
    assert notifications == []
    api_module._record_provider_failure("indianapi", "TCS", "timeout")
    assert len(notifications) == 1
    level, title, details = notifications[0]
    assert level == "WARNING"
    assert "INDIANAPI quotes repeatedly failing for TCS" in title
    assert "timeout" in details
    assert api_module.PROVIDER_FAILURES.get("indianapi:TCS") == 0


def test_reset_provider_failure(monkeypatch):
    monkeypatch.setattr(api_module, "MARKET_FAILURE_ALERT_THRESHOLD", 2)
    api_module.PROVIDER_FAILURES.clear()
    captured = []

    class DummyNotifier:
        def notify(self, level, title, details=None):
            captured.append((level, title, details))

    monkeypatch.setattr(api_module, "market_notifier", DummyNotifier())

    api_module._record_provider_failure("bhavcopy", "500325", "missing cap")
    api_module._reset_provider_failure("bhavcopy", "500325")
    api_module._record_provider_failure("bhavcopy", "500325", "missing cap")
    assert captured == []


def test_ops_metrics_endpoint(monkeypatch, tmp_path, admin_access):
    metrics_file = tmp_path / "ingestion.jsonl"
    metrics_file.write_text(
        json.dumps(
            {
                "status": "success",
                "started_at": "2025-12-24T00:00:00Z",
                "duration_seconds": 12.3,
                "timestamp": "2025-12-24T00:00:15Z",
            }
        )
        + "\n"
    )
    monkeypatch.setattr(api_module, "INGESTION_METRICS_PATH", metrics_file)
    api_module.MARKET_ALERT_EVENTS.clear()
    api_module.LLM_FAILURE_EVENTS.clear()
    api_module.MARKET_ALERT_EVENTS.append(
        {"event": "market_lookup_failure", "symbol": "TCS", "timestamp": "now"}
    )
    api_module.LLM_FAILURE_EVENTS.append(
        {"symbol": "TCS", "message": "boom", "timestamp": "now"}
    )

    response = _run(api_module.ops_metrics())
    assert response["ingestion"]["available"] is True
    assert response["market_data"]["recent_alerts"]
    assert response["llm"]["failure_count"] == 1


@pytest.mark.parametrize(
    "overrides, quality_issues, stored_issues, verdict, is_compliant",
    [
        ({}, [], [], "compliant", True),
        ({"interest_income": None}, [], [], "insufficient-data", None),
        ({}, ["anomaly"], [], "needs-review", None),
        # Nothing new detected, but an issue from another source is still open.
        ({}, [], [("source_review", "Unresolved source-quality review")], "needs-review", None),
        # Every open issue blocks, including a type no code knows about yet.
        ({}, [], [("some-future-type", None)], "needs-review", None),
        ({"total_debt": 400_000_000}, [], [], "non-compliant", False),
    ],
    ids=["compliant", "insufficient", "needs-review", "stored-issue-only", "unknown-type", "non-compliant"],
)
def test_persisted_and_returned_verdict_pair_match(
    monkeypatch, overrides, quality_issues, stored_issues, verdict, is_compliant
):
    db = MemoryQualityDB()
    for issue_type, details in stored_issues:
        db.seed_issue("TCS", datetime(2024, 6, 30), issue_type, details)

    monkeypatch.setattr(api_module, "_get_db", lambda: db)
    monkeypatch.setattr(api_module, "_maybe_enrich_record_with_indian_api", lambda record: None)
    monkeypatch.setattr(
        quality, "detect_ratio_anomalies", lambda snapshot, evaluation: quality_issues
    )
    record = {
        "symbol": "TCS",
        "filing_date": datetime(2024, 6, 30),
        "total_debt": 25_000_000,
        "cash_equiv": 10_000_000,
        "revenue": 200_000_000,
        "non_halal_income": 5_000_000,
        "interest_income": 1_000_000,
        "dividend_income": 0,
        "accounts_receivable": 20_000_000,
        "liquid_assets": 40_000_000,
        "market_cap_used": 400_000_000,
        "ratios": None,
    }
    record.update(overrides)

    api_module._ensure_filing_evaluation(record, allow_market_fetch=False)

    stored = db.writes[-1]
    assert (stored["verdict"], stored["is_compliant"]) == (verdict, is_compliant)
    assert (record["verdict"], record["is_compliant"]) == (verdict, is_compliant)


@pytest.mark.parametrize("field", ["total_debt", "interest_income", "non_halal_income"])
def test_snapshot_payload_rejects_booleans(field):
    """JSON false must not become a verified 0.0 (it used to count as zero income)."""

    with pytest.raises(ValidationError):
        FinancialSnapshotPayload(
            symbol="TCS", filing_date=datetime(2024, 6, 30), **{field: False}
        )


def test_market_data_payload_rejects_booleans():
    with pytest.raises(ValidationError):
        MarketDataPayload(market_cap=False, trailing_market_cap=400_000_000)


def test_narration_cache_key_changes_with_verdict():
    from dataclasses import replace

    from ratio_engine import FinancialSnapshotInput, MarketDataInput, RatioEngine

    evaluation = RatioEngine().evaluate(
        FinancialSnapshotInput(**_sample_request().snapshot.model_dump()),
        MarketDataInput(market_cap=400_000_000),
    )
    other = replace(evaluation, verdict="insufficient-data")

    assert evaluation.verdict == "compliant"
    assert api_module._narration_cache_key(evaluation) != api_module._narration_cache_key(
        other
    )


def test_transient_record_keeps_its_existing_blocking_issue(monkeypatch):
    """Nothing is stored for a transient record, but issues it carries still block."""

    def no_db():
        raise AssertionError("a transient record must not touch the database")

    monkeypatch.setattr(api_module, "_get_db", no_db)
    monkeypatch.setattr(api_module, "_maybe_enrich_record_with_indian_api", lambda record: None)
    monkeypatch.setattr(quality, "detect_ratio_anomalies", lambda snapshot, evaluation: [])
    record = {
        "symbol": "TCS",
        "filing_date": datetime(2024, 6, 30),
        "total_debt": 25_000_000,
        "cash_equiv": 10_000_000,
        "revenue": 200_000_000,
        "non_halal_income": 5_000_000,
        "interest_income": 1_000_000,
        "dividend_income": 0,
        "accounts_receivable": 20_000_000,
        "liquid_assets": 40_000_000,
        "market_cap_used": 400_000_000,
        "ratios": None,
        "_transient": True,
        "quality_issues": ["Unresolved source-quality review"],
    }

    api_module._ensure_filing_evaluation(record, allow_market_fetch=False)

    assert (record["verdict"], record["is_compliant"]) == ("needs-review", None)
    assert record["quality_issues"] == ["Unresolved source-quality review"]

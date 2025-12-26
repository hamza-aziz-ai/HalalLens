#!/usr/bin/env python3
"""Tests for governance enrichment inside backfill job."""

from datetime import datetime, timezone

import types

import pytest

from ratio_engine import FinancialSnapshotInput
import jobs.backfill_evaluations as backfill


class DummyDB:
    def __init__(self):
        self.overrides = None
        self.issues = []

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
        source=None,
    ):
        self.overrides = {
            "symbol": symbol,
            "accounts_receivable": accounts_receivable,
            "liquid_assets": liquid_assets,
            "non_halal_income": non_halal_income,
            "reason": reason,
            "source": source,
            "governance_notes": governance_notes,
        }

    def record_quality_issue(self, symbol, filing_date, issue_type, details):
        self.issues.append((symbol, issue_type, details))


class DummySnapshot:
    def __init__(self):
        self.metrics = {
            "total_debt": 100.0,
            "accounts_receivable": 1_000_000.0,
            "liquid_assets": 2_000_000.0,
            "non_halal_income": 50_000.0,
        }


@pytest.fixture(autouse=True)
def enable_indian_api(monkeypatch):
    monkeypatch.setattr(backfill, "indian_api_enabled", lambda: True)
    monkeypatch.setattr(backfill, "_indian_api_candidates", lambda symbol, db: ["TCS"])


def test_enrichment_applies_structured_overrides(monkeypatch):
    db = DummyDB()
    snapshot = FinancialSnapshotInput(
        symbol="TCS",
        filing_date=datetime(2025, 3, 31, tzinfo=timezone.utc),
        accounts_receivable=100.0,
        liquid_assets=150.0,
        non_permissible_income=1.0,
        non_halal_income=1.0,
    )

    monkeypatch.setattr(
        backfill,
        "fetch_indian_financial_snapshot",
        lambda symbol, target_date=None: DummySnapshot(),
    )

    backfill._enrich_snapshot_with_indian_api(snapshot, db)

    assert snapshot.accounts_receivable == 1_000_000.0
    assert snapshot.liquid_assets == 2_000_000.0
    assert snapshot.non_halal_income == 50_000.0
    assert db.overrides["accounts_receivable"] == 1_000_000.0
    assert any("governance_override" in issue[1] for issue in db.issues)

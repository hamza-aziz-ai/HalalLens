#!/usr/bin/env python3
"""Tests for the narration engine."""

from datetime import datetime

from narrator import NarrationEngine
from ratio_engine import (
    FinancialSnapshotInput,
    MarketDataInput,
    RatioEngine,
)


def test_narration_contains_all_ratios():
    engine = RatioEngine()
    snapshot = FinancialSnapshotInput(
        symbol="ABC",
        filing_date=datetime(2024, 6, 30),
        total_debt=10_000_000,
        cash_equiv=2_000_000,
        revenue=100_000_000,
        non_permissible_income=500_000,
    )
    market = MarketDataInput(market_cap=200_000_000)

    evaluation = engine.evaluate(snapshot, market)

    narrator = NarrationEngine()
    result = narrator.build(evaluation)

    assert "ABC" in result.summary
    assert len(result.bullets) == 3
    assert any("Debt to market cap" in bullet for bullet in result.bullets)
    assert result.verdict.lower().startswith("compliant")


def test_narration_handles_missing_metrics():
    engine = RatioEngine()
    snapshot = FinancialSnapshotInput(
        symbol="XYZ",
        filing_date=datetime(2024, 6, 30),
        total_debt=None,
        revenue=None,
    )
    market = MarketDataInput(market_cap=None, trailing_market_cap=100_000_000)

    evaluation = engine.evaluate(snapshot, market)

    narrator = NarrationEngine()
    result = narrator.build(evaluation)

    assert "Insufficient" in result.bullets[-1] or any(
        "cannot compute" in bullet for bullet in result.bullets
    )
    assert result.citations != []

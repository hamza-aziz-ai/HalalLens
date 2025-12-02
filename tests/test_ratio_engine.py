#!/usr/bin/env python3
"""Unit tests for the ratio engine."""

from datetime import datetime

import pytest

from ratio_engine import (
    FinancialSnapshotInput,
    MarketDataInput,
    RatioEngine,
    RatioThresholds,
)


def make_snapshot(**overrides) -> FinancialSnapshotInput:
    """Helper to build a snapshot with sane defaults."""

    base = dict(
        symbol="TEST",
        filing_date=datetime(2024, 1, 1),
        total_debt=25_000_000,
        cash_equiv=5_000_000,
        revenue=100_000_000,
        interest_income=500_000,
        dividend_income=250_000,
        non_permissible_income=100_000,
    )
    base.update(overrides)
    return FinancialSnapshotInput(**base)


def test_all_ratios_pass_when_under_thresholds():
    engine = RatioEngine()
    snapshot = make_snapshot()
    market = MarketDataInput(market_cap=200_000_000)

    result = engine.evaluate(snapshot, market)

    assert result.is_compliant is True
    assert pytest.approx(result.ratios["debt_to_market_cap"].value) == 0.125
    assert result.ratios["cash_to_market_cap"].passed is True
    assert result.ratios["non_permissible_income_ratio"].note == "Non-permissible income / revenue"


def test_any_failed_ratio_marks_non_compliant():
    thresholds = RatioThresholds(max_debt_to_market_cap=0.20)
    engine = RatioEngine(thresholds)
    snapshot = make_snapshot(total_debt=60_000_000)
    market = MarketDataInput(market_cap=200_000_000)

    result = engine.evaluate(snapshot, market)

    assert result.is_compliant is False
    assert result.ratios["debt_to_market_cap"].passed is False
    assert result.ratios["cash_to_market_cap"].passed is True


def test_missing_inputs_reported_and_verdict_false():
    engine = RatioEngine()
    snapshot = make_snapshot(revenue=None)
    market = MarketDataInput(market_cap=None, trailing_market_cap=None)

    result = engine.evaluate(snapshot, market)

    assert result.is_compliant is False
    assert result.ratios["debt_to_market_cap"].value is None
    assert result.missing_inputs["market_cap"] == "missing_or_zero"
    assert result.missing_inputs["revenue"] == "missing_or_zero"


def test_trailing_market_cap_fallback_and_income_aggregation():
    engine = RatioEngine()
    snapshot = make_snapshot(
        non_permissible_income=200_000,
        interest_income=300_000,
        dividend_income=100_000,
    )
    market = MarketDataInput(market_cap=None, trailing_market_cap=100_000_000)

    result = engine.evaluate(snapshot, market)

    assert result.ratios["debt_to_market_cap"].passed is True
    assert result.ratios["cash_to_market_cap"].note == "Cash & equivalents / market cap"
    assert pytest.approx(result.ratios["non_permissible_income_ratio"].value) == 0.006

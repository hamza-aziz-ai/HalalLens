#!/usr/bin/env python3
"""Untrusted values must never become a verified number on the way to the engine.

`coerce_amount` is the one shared normaliser; every converter delegates to it.
These tests cover it directly, each converter, and the real ETL parser through
to the engine.
"""

import importlib
from datetime import datetime
from decimal import Decimal

import pytest

from etl.financial_data_processor import FinancialDataProcessor as FDP
from market_data.indian_api import _to_float
from pydantic import ValidationError
from ratio_engine import (
    FinancialSnapshotInput,
    MarketDataInput,
    RatioEngine,
    RatioThresholds,
)
from ratio_engine.amounts import coerce_amount
from ratio_engine.run_from_cache import _safe_get_float, to_snapshot

api_module = importlib.import_module("api.app")
backfill = importlib.import_module("jobs.backfill_evaluations")
ingest_bse = importlib.import_module("jobs.ingest_bse")
ingest_indianapi = importlib.import_module("jobs.ingest_indianapi")

CONVERTERS = {
    "amounts": coerce_amount,
    "etl": FDP._coerce_numeric,
    "vendor": _to_float,
    "cache": lambda value: _safe_get_float({"x": value}, "x"),
    "api_float": api_module._coerce_float,
    "api_metric": api_module._coerce_metric_value,
    "backfill": backfill._coerce_float,
    "ingest_bse": ingest_bse._coerce_float,
    "ingest_indianapi": ingest_indianapi._coerce_number,
}

UNKNOWN = [
    None,
    True,
    False,
    "",
    "  ",
    "abc",
    "1e-400",
    Decimal("1e-1600"),
    float("nan"),
    float("inf"),
    "nan",
    "inf",
    Decimal("sNaN"),
    10**400,
]

KNOWN = [
    (0, 0.0),
    (0.0, 0.0),
    (-0.0, 0.0),
    ("0", 0.0),
    ("0.0", 0.0),
    ("-0", 0.0),
    ("0e-400", 0.0),
    (Decimal("0"), 0.0),
    (Decimal("-0.00"), 0.0),
    (12, 12.0),
    (12.5, 12.5),
    ("1,234.5", 1234.5),
    ("  7 ", 7.0),
    (Decimal("2.5"), 2.5),
    (-3.5, -3.5),
]


@pytest.mark.parametrize("name", CONVERTERS)
@pytest.mark.parametrize("value", UNKNOWN, ids=repr)
def test_every_converter_treats_unusable_values_as_unknown(name, value):
    assert CONVERTERS[name](value) is None


@pytest.mark.parametrize("name", CONVERTERS)
@pytest.mark.parametrize("value, expected", KNOWN, ids=repr)
def test_every_converter_keeps_legitimate_numbers_and_zeros(name, value, expected):
    result = CONVERTERS[name](value)

    assert result == expected
    assert isinstance(result, float)


def test_vendor_converter_still_strips_percent_signs():
    assert _to_float("12.5%") == 12.5
    assert _to_float("1e-400%") is None


# --- Real ETL parser -> engine ----------------------------------------------


def _engine_result_from_structured(payload):
    metrics = FDP._parse_structured_json(payload, scale_hint=1.0)
    snapshot = FinancialSnapshotInput(
        symbol="X",
        filing_date=datetime(2024, 6, 30),
        total_debt=metrics.get("total_debt"),
        cash_equiv=metrics.get("cash_equiv"),
        revenue=metrics.get("revenue"),
        interest_income=metrics.get("interest_income"),
        dividend_income=metrics.get("dividend_income"),
        non_permissible_income=metrics.get("non_halal_income"),
        accounts_receivable=metrics.get("accounts_receivable"),
        liquid_assets=metrics.get("liquid_assets"),
    )
    return metrics, RatioEngine().evaluate(
        snapshot, MarketDataInput(market_cap=400_000_000)
    )


COMPLETE = {
    "Borrowings": {"Total": 25_000_000},
    "CashAndCashEquivalents": 10_000_000,
    "RevenueFromOperations": 200_000_000,
    "InterestIncome": 1_000_000,
    "DividendIncome": 0,
    "AccountsReceivable": 20_000_000,
    "CurrentAssets": 40_000_000,  # the ETL maps liquid_assets from current assets
    "NonPermissible": {"Income": 5_000_000},
}


def test_structured_parser_complete_payload_screens_compliant():
    metrics, result = _engine_result_from_structured({"Financials": COMPLETE})

    assert result.missing_inputs == {}, metrics
    assert result.verdict == "compliant"


@pytest.mark.parametrize("flag", [True, False])
def test_structured_parser_boolean_fields_are_not_zeros(flag):
    payload = {
        "Financials": {
            **COMPLETE,
            "InterestIncome": flag,
            "DividendIncome": flag,
            "NonPermissible": {"Income": flag},
        }
    }
    metrics, result = _engine_result_from_structured(payload)

    assert "interest_income" not in metrics
    assert "dividend_income" not in metrics
    assert "non_halal_income" not in metrics
    assert result.verdict == "insufficient-data"


def test_structured_parser_underflowing_string_is_not_a_zero():
    payload = {"Financials": {**COMPLETE, "InterestIncome": "1e-400"}}
    metrics, result = _engine_result_from_structured(payload)

    assert "interest_income" not in metrics
    assert result.verdict == "insufficient-data"


# --- Public API boundary -----------------------------------------------------


@pytest.mark.parametrize("tiny", ["1e-400", "not a number", ""])
def test_api_payload_rejects_unusable_string_amounts(tiny):
    with pytest.raises(ValidationError):
        api_module.FinancialSnapshotPayload(
            symbol="TCS", filing_date=datetime(2024, 6, 30), interest_income=tiny
        )


def test_api_payload_accepts_zero_strings_and_numbers():
    payload = api_module.FinancialSnapshotPayload(
        symbol="TCS",
        filing_date=datetime(2024, 6, 30),
        interest_income="0",
        dividend_income="0e-400",
        total_debt=12,
    )

    assert payload.interest_income == 0.0
    assert payload.dividend_income == 0.0
    assert payload.total_debt == 12.0


# --- Cache mapper ------------------------------------------------------------


def _cache_entry(**extracted):
    base = {
        "total_debt": 25_000_000,
        "cash_equiv": 10_000_000,
        "revenue": 200_000_000,
        "interest_income": 1_000_000,
        "dividend_income": 0,
        "accounts_receivable": 20_000_000,
        "liquid_assets": 40_000_000,
        "non_halal_income": 5_000_000,
    }
    base.update(extracted)
    return {"symbol": "TCS", "filing_date": "2024-06-30T00:00:00", "extracted_data": base}


def test_cache_mapper_carries_every_required_input():
    snapshot = to_snapshot(_cache_entry())
    result = RatioEngine().evaluate(snapshot, MarketDataInput(market_cap=400_000_000))

    assert result.missing_inputs == {}
    assert result.verdict == "compliant"


def test_cache_mapper_incomplete_filing_is_insufficient():
    snapshot = to_snapshot(_cache_entry(liquid_assets=None))
    result = RatioEngine().evaluate(snapshot, MarketDataInput(market_cap=400_000_000))

    assert result.missing_inputs == {"liquid_assets": "missing"}
    assert result.verdict == "insufficient-data"


def test_cache_mapper_prefers_explicit_non_permissible_income():
    snapshot = to_snapshot(_cache_entry(non_permissible_income=7, non_halal_income=9))

    assert snapshot.non_permissible_income == 7.0


# --- Threshold and market-cap validation ------------------------------------


@pytest.mark.parametrize(
    "bad",
    [float("inf"), float("nan"), True, -0.1, Decimal("0.3"), "0.3", None],
    ids=repr,
)
def test_invalid_thresholds_are_rejected_at_construction(bad):
    with pytest.raises(ValueError):
        RatioEngine(RatioThresholds(max_debt_to_market_cap=bad))


def test_valid_custom_thresholds_still_work():
    engine = RatioEngine(RatioThresholds(max_debt_to_market_cap=0.2, max_cash_to_market_cap=1))
    snapshot = FinancialSnapshotInput(
        symbol="X",
        filing_date=datetime(2024, 6, 30),
        total_debt=25,
        cash_equiv=100,
        revenue=100,
        non_permissible_income=0,
        interest_income=0,
        dividend_income=0,
        accounts_receivable=0,
        liquid_assets=0,
    )

    result = engine.evaluate(snapshot, MarketDataInput(market_cap=100))

    assert result.ratios["debt_to_market_cap"].passed is False  # 25% > the custom 20%
    assert result.ratios["cash_to_market_cap"].passed is True  # 100% <= the custom 1 (int)


@pytest.mark.parametrize(
    "cap",
    [True, False, Decimal("sNaN"), float("nan"), -1.0, "abc"],
    ids=repr,
)
def test_unusable_primary_market_cap_is_not_rescued_by_trailing(cap):
    """No raising equality check, and no silent fallback to the trailing cap."""

    snapshot = FinancialSnapshotInput(
        symbol="X",
        filing_date=datetime(2024, 6, 30),
        total_debt=1,
        cash_equiv=1,
        revenue=100,
        non_permissible_income=0,
        interest_income=0,
        dividend_income=0,
        accounts_receivable=1,
        liquid_assets=1,
    )

    result = RatioEngine().evaluate(
        snapshot, MarketDataInput(market_cap=cap, trailing_market_cap=400_000_000)
    )

    assert result.missing_inputs["market_cap"] == "invalid"
    assert result.verdict == "insufficient-data"


@pytest.mark.parametrize("zero", [0, 0.0, "0", Decimal("0")], ids=repr)
def test_numeric_zero_primary_market_cap_falls_back_to_trailing(zero):
    snapshot = FinancialSnapshotInput(
        symbol="X",
        filing_date=datetime(2024, 6, 30),
        total_debt=1,
        cash_equiv=1,
        revenue=100,
        non_permissible_income=0,
        interest_income=0,
        dividend_income=0,
        accounts_receivable=1,
        liquid_assets=1,
    )

    result = RatioEngine().evaluate(
        snapshot, MarketDataInput(market_cap=zero, trailing_market_cap=400_000_000)
    )

    assert result.verdict == "compliant"


@pytest.mark.parametrize("huge", [10**400, -(10**400)])
def test_integer_thresholds_beyond_float_range_raise_value_error(huge):
    with pytest.raises(ValueError):
        RatioEngine(RatioThresholds(max_debt_to_market_cap=huge))


def test_converters_changed_formats_are_pinned():
    # Bytes used to reach float() in some wrappers; they are now unknown.
    assert coerce_amount(b"12") is None
    # Comma-formatted numbers are accepted by the API / cache wrappers.
    assert api_module._coerce_float("1,234.5") == 1234.5
    assert _safe_get_float({"x": "1,234.5"}, "x") == 1234.5
    # Malformed IndianAPI strings are unknown instead of raising.
    assert ingest_indianapi._coerce_number("12 crore") is None
    # The vendor mapper now parses Decimals and NumPy scalars it used to drop.
    import numpy as np

    assert _to_float(Decimal("3.5")) == 3.5
    assert _to_float(np.int64(5)) == 5.0

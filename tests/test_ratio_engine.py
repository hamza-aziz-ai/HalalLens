#!/usr/bin/env python3
"""Unit tests for the ratio engine."""

from datetime import datetime

import pytest

from ratio_engine import (
    REQUIRED_RATIOS,
    FinancialSnapshotInput,
    MarketDataInput,
    RatioEngine,
    RatioThresholds,
    build_summary,
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
        accounts_receivable=15_000_000,
        liquid_assets=30_000_000,
        non_halal_income=50_000,
    )
    base.update(overrides)
    return FinancialSnapshotInput(**base)


def test_all_ratios_pass_when_under_thresholds():
    engine = RatioEngine()
    snapshot = make_snapshot()
    market = MarketDataInput(market_cap=200_000_000)

    result = engine.evaluate(snapshot, market)

    assert result.is_compliant is True
    debt_ratio = result.ratios["debt_to_market_cap"]
    assert pytest.approx(debt_ratio.value) == 0.125
    assert debt_ratio.provider == "manual"
    assert result.ratios["cash_to_market_cap"].passed is True
    assert result.ratios["receivables_to_market_cap"].passed is True
    assert result.ratios["liquid_assets_to_market_cap"].passed is True
    assert (
        result.ratios["non_permissible_income_ratio"].note
        == "Non-permissible income / revenue"
    )


def test_any_failed_ratio_marks_non_compliant():
    thresholds = RatioThresholds(max_debt_to_market_cap=0.20)
    engine = RatioEngine(thresholds)
    snapshot = make_snapshot(total_debt=60_000_000)
    market = MarketDataInput(market_cap=200_000_000)

    result = engine.evaluate(snapshot, market)

    assert result.is_compliant is False
    assert result.ratios["debt_to_market_cap"].passed is False
    assert result.ratios["cash_to_market_cap"].passed is True


def test_receivables_ratio_failure_marks_non_compliant():
    engine = RatioEngine()
    snapshot = make_snapshot(accounts_receivable=200_000_000)
    market = MarketDataInput(market_cap=250_000_000)

    result = engine.evaluate(snapshot, market)

    assert result.is_compliant is False
    assert result.ratios["receivables_to_market_cap"].passed is False


def test_missing_inputs_reported_and_verdict_insufficient():
    engine = RatioEngine()
    snapshot = make_snapshot(revenue=None)
    market = MarketDataInput(market_cap=None, trailing_market_cap=None)

    result = engine.evaluate(snapshot, market)

    assert result.verdict == "insufficient-data"
    assert result.is_compliant is None
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
    assert (
        result.ratios["cash_to_market_cap"].note == "Cash & equivalents / market cap"
    )
    assert pytest.approx(result.ratios["non_permissible_income_ratio"].value) == 0.006


def test_interest_expense_not_treated_as_non_permissible_income():
    engine = RatioEngine()
    snapshot = make_snapshot(
        non_permissible_income=0.0,
        interest_income=-2_000_000,
        dividend_income=-500_000,
        revenue=200_000_000,
        non_halal_income=0.0,
    )
    market = MarketDataInput(market_cap=500_000_000)

    result = engine.evaluate(snapshot, market)
    assert result.ratios["non_permissible_income_ratio"].value == 0.0


def test_provider_metadata_propagates_from_market_input():
    engine = RatioEngine()
    snapshot = make_snapshot()
    market = MarketDataInput(market_cap=300_000_000, provider="tiingo")

    result = engine.evaluate(snapshot, market)
    assert result.ratios["cash_to_market_cap"].provider == "tiingo"


# --- Golden set -------------------------------------------------------------
# Default fixture at a 200M market cap: debt 12.5%, cash 2.5%, income 0.85%,
# receivables 7.5%, liquid assets 15%. Each row changes one thing.

NAN = float("nan")
INF = float("inf")
CAP = 200_000_000

GOLDEN = [
    # id, snapshot overrides, market kwargs, verdict, {input: reason} subset of missing_inputs
    ("all-pass", {}, {}, "compliant", {}),
    ("debt-at-30pct", {"total_debt": 60_000_000}, {}, "compliant", {}),
    ("debt-over-30pct", {"total_debt": 60_000_001}, {}, "non-compliant", {}),
    ("cash-at-30pct", {"cash_equiv": 60_000_000}, {}, "compliant", {}),
    ("cash-over-30pct", {"cash_equiv": 60_000_001}, {}, "non-compliant", {}),
    (
        "income-at-5pct",
        {"non_permissible_income": 5_000_000, "interest_income": 0.0, "dividend_income": 0.0},
        {},
        "compliant",
        {},
    ),
    (
        "income-over-5pct",
        {"non_permissible_income": 5_000_001, "interest_income": 0.0, "dividend_income": 0.0},
        {},
        "non-compliant",
        {},
    ),
    ("receivables-at-cap", {"accounts_receivable": 134_000_000}, {}, "compliant", {}),
    ("receivables-over-cap", {"accounts_receivable": 134_000_001}, {}, "non-compliant", {}),
    ("liquid-at-cap", {"liquid_assets": 98_000_000}, {}, "compliant", {}),
    ("liquid-over-cap", {"liquid_assets": 98_000_001}, {}, "non-compliant", {}),
    # A single missing required input is never a pass.
    ("debt-missing", {"total_debt": None}, {}, "insufficient-data", {"total_debt": "missing"}),
    ("cash-missing", {"cash_equiv": None}, {}, "insufficient-data", {"cash_equiv": "missing"}),
    ("revenue-missing", {"revenue": None}, {}, "insufficient-data", {"revenue": "missing_or_zero"}),
    (
        "receivables-missing",
        {"accounts_receivable": None},
        {},
        "insufficient-data",
        {"accounts_receivable": "missing"},
    ),
    ("liquid-missing", {"liquid_assets": None}, {}, "insufficient-data", {"liquid_assets": "missing"}),
    # Income is never assumed zero when a part is unknown.
    (
        "income-base-missing",
        {"non_permissible_income": None, "non_halal_income": None},
        {},
        "insufficient-data",
        {"non_permissible_income": "missing"},
    ),
    ("interest-missing", {"interest_income": None}, {}, "insufficient-data", {"interest_income": "missing"}),
    ("dividend-missing", {"dividend_income": None}, {}, "insufficient-data", {"dividend_income": "missing"}),
    # Alias: non_halal_income stands in only when the primary field is None.
    ("alias-used", {"non_permissible_income": None, "non_halal_income": 100_000}, {}, "compliant", {}),
    # A conclusive failure beats missing data elsewhere.
    ("failure-plus-missing", {"total_debt": 60_000_001, "cash_equiv": None}, {}, "non-compliant", {}),
    # Market cap handling.
    ("trailing-cap-fallback", {}, {"market_cap": None, "trailing_market_cap": CAP}, "compliant", {}),
    ("zero-cap-uses-trailing", {}, {"market_cap": 0, "trailing_market_cap": CAP}, "compliant", {}),
    (
        "no-cap",
        {},
        {"market_cap": None, "trailing_market_cap": None},
        "insufficient-data",
        {"market_cap": "missing_or_zero"},
    ),
    (
        "negative-cap-not-hidden-by-trailing",
        {},
        {"market_cap": -CAP, "trailing_market_cap": CAP},
        "insufficient-data",
        {"market_cap": "invalid"},
    ),
    ("nan-cap", {}, {"market_cap": NAN, "trailing_market_cap": CAP}, "insufficient-data", {"market_cap": "invalid"}),
    # Invalid numerators / denominators.
    ("negative-debt", {"total_debt": -1.0}, {}, "insufficient-data", {"total_debt": "invalid"}),
    ("negative-revenue", {"revenue": -100.0}, {}, "insufficient-data", {"revenue": "invalid"}),
    ("zero-revenue", {"revenue": 0.0}, {}, "insufficient-data", {"revenue": "missing_or_zero"}),
    # A negative base must not offset positive interest (it used to compute -10% and pass).
    (
        "negative-base-cannot-offset-interest",
        {"non_permissible_income": -20.0, "interest_income": 10.0, "dividend_income": 0.0, "revenue": 100.0},
        {},
        "insufficient-data",
        {"non_permissible_income": "invalid"},
    ),
    # NaN/inf must never be coerced to zero by the positive-only conversion.
    ("nan-interest", {"interest_income": NAN}, {}, "insufficient-data", {"interest_income": "invalid"}),
    ("inf-interest", {"interest_income": INF}, {}, "insufficient-data", {"interest_income": "invalid"}),
    ("nan-base", {"non_permissible_income": NAN}, {}, "insufficient-data", {"non_permissible_income": "invalid"}),
    # Net interest expense is known and contributes zero.
    ("negative-interest-is-known", {"interest_income": -5_000_000.0}, {}, "compliant", {}),
]


@pytest.mark.parametrize(
    "overrides, market_kwargs, verdict, missing",
    [case[1:] for case in GOLDEN],
    ids=[case[0] for case in GOLDEN],
)
def test_golden_verdicts(overrides, market_kwargs, verdict, missing):
    market = MarketDataInput(**({"market_cap": CAP} | market_kwargs))
    result = RatioEngine().evaluate(make_snapshot(**overrides), market)

    assert result.verdict == verdict
    assert result.is_compliant is {"compliant": True, "non-compliant": False}.get(verdict)
    for name, reason in missing.items():
        assert result.missing_inputs.get(name) == reason


def test_only_debt_computed_is_insufficient_not_compliant():
    """Regression: one computed passing ratio used to yield is_compliant=True."""

    snapshot = FinancialSnapshotInput(
        symbol="X", filing_date=datetime(2024, 1, 1), total_debt=1.0
    )
    result = RatioEngine().evaluate(snapshot, MarketDataInput(market_cap=CAP))

    assert result.ratios["debt_to_market_cap"].passed is True
    assert result.verdict == "insufficient-data"
    assert result.is_compliant is None


def test_everything_missing_is_insufficient():
    snapshot = FinancialSnapshotInput(symbol="X", filing_date=datetime(2024, 1, 1))
    result = RatioEngine().evaluate(snapshot, MarketDataInput())

    assert result.verdict == "insufficient-data"
    assert result.is_compliant is None


def test_explicit_zero_primary_income_beats_nonzero_alias():
    snapshot = make_snapshot(
        non_permissible_income=0.0,
        non_halal_income=999_999_999.0,
        interest_income=0.0,
        dividend_income=0.0,
    )
    result = RatioEngine().evaluate(snapshot, MarketDataInput(market_cap=CAP))

    assert result.ratios["non_permissible_income_ratio"].value == 0.0
    assert result.verdict == "compliant"


def test_every_required_ratio_is_computed_by_the_engine():
    result = RatioEngine().evaluate(make_snapshot(), MarketDataInput(market_cap=CAP))

    assert set(REQUIRED_RATIOS) == set(result.ratios)


def test_is_compliant_is_a_property_not_a_serialised_field():
    from dataclasses import asdict

    result = RatioEngine().evaluate(make_snapshot(), MarketDataInput(market_cap=CAP))

    assert "is_compliant" not in asdict(result)
    assert asdict(result)["verdict"] == "compliant"


def test_summary_matches_verdict():
    engine = RatioEngine()
    market = MarketDataInput(market_cap=CAP)

    ok = engine.evaluate(make_snapshot(), market)
    bad = engine.evaluate(make_snapshot(total_debt=60_000_001), market)
    unknown = engine.evaluate(make_snapshot(interest_income=None), market)

    assert "within" in build_summary(ok)
    assert "Debt to market cap exceeded" in build_summary(bad)
    assert "Insufficient data" in build_summary(unknown)
    assert "interest_income" in build_summary(unknown)


# --- Council review regressions ---------------------------------------------

EDGE = [
    # id, snapshot overrides, market kwargs, verdict, {input: reason}
    ("bool-debt", {"total_debt": True}, {}, "insufficient-data", {"total_debt": "invalid"}),
    (
        "bool-income-parts",
        {"non_permissible_income": False, "interest_income": False, "dividend_income": False},
        {},
        "insufficient-data",
        {"non_permissible_income": "invalid", "interest_income": "invalid", "dividend_income": "invalid"},
    ),
    (
        "bool-market-cap-is-not-a-zero-cap",
        {},
        {"market_cap": False, "trailing_market_cap": CAP},
        "insufficient-data",
        {"market_cap": "invalid"},
    ),
    ("huge-int-debt", {"total_debt": 10**400}, {}, "insufficient-data", {"total_debt": "invalid"}),
    (
        "unrepresentable-quotient",
        {"total_debt": 1e308},
        {"market_cap": 1e-308},
        "insufficient-data",
        {"total_debt": "invalid"},
    ),
    # (0.1 + 0.2) / 6 is exactly 5% in decimal terms; binary floats give 0.05000000000000001.
    (
        "fractional-income-exactly-5pct",
        {"non_permissible_income": 0.1, "interest_income": 0.2, "dividend_income": 0.0, "revenue": 6.0},
        {},
        "compliant",
        {},
    ),
]


@pytest.mark.parametrize(
    "overrides, market_kwargs, verdict, missing",
    [case[1:] for case in EDGE],
    ids=[case[0] for case in EDGE],
)
def test_edge_verdicts(overrides, market_kwargs, verdict, missing):
    market = MarketDataInput(**({"market_cap": CAP} | market_kwargs))
    result = RatioEngine().evaluate(make_snapshot(**overrides), market)

    assert result.verdict == verdict
    for name, reason in missing.items():
        assert result.missing_inputs.get(name) == reason


def test_decimal_comparison_has_no_tolerance():
    """0.30000000000000004 is above a 0.30 cap; Decimal must not hide that."""

    snapshot = make_snapshot(
        total_debt=0.30000000000000004,
        cash_equiv=0.0,
        accounts_receivable=0.0,
        liquid_assets=0.0,
        non_permissible_income=0.0,
        interest_income=0.0,
        dividend_income=0.0,
        revenue=100.0,
    )
    result = RatioEngine().evaluate(snapshot, MarketDataInput(market_cap=1.0))

    assert result.ratios["debt_to_market_cap"].passed is False
    assert result.verdict == "non-compliant"


@pytest.mark.parametrize(
    "overrides, expected",
    [
        ({"interest_income": None}, {"interest_income": "missing"}),
        ({"dividend_income": None}, {"dividend_income": "missing"}),
        (
            {"non_permissible_income": None, "non_halal_income": None},
            {"non_permissible_income": "missing"},
        ),
        ({"non_permissible_income": -1.0}, {"non_permissible_income": "invalid"}),
    ],
    ids=["interest", "dividend", "base", "negative-base"],
)
def test_missing_inputs_name_only_the_unusable_components(overrides, expected):
    result = RatioEngine().evaluate(
        make_snapshot(**overrides), MarketDataInput(market_cap=CAP)
    )

    assert result.missing_inputs == expected


def test_run_from_cache_exports_verdict_and_nullable_boolean():
    from ratio_engine.run_from_cache import evaluate_snapshots

    complete = make_snapshot(symbol="OK")
    partial = make_snapshot(symbol="PART", interest_income=None)

    out = evaluate_snapshots(
        [({"minio_path": "a"}, complete), ({"minio_path": "b"}, partial)],
        {},
        CAP,
    )

    assert [(row["verdict"], row["is_compliant"]) for row in out] == [
        ("compliant", True),
        ("insufficient-data", None),
    ]


# --- Round-two regressions: exact decisions and the supported numeric domain --

import decimal  # noqa: E402
from decimal import Decimal  # noqa: E402


def _income_case(**overrides):
    base = dict(
        non_permissible_income=Decimal("0.3"),
        interest_income=1e-30,
        dividend_income=0.0,
        revenue=6.0,
    )
    base.update(overrides)
    return RatioEngine().evaluate(make_snapshot(**base), MarketDataInput(market_cap=CAP))


def test_tiny_interest_is_not_rounded_away():
    """0.3 + 1e-30 over 6 is a hair above 5%; 28-digit rounding used to pass it."""

    result = _income_case()

    assert result.ratios["non_permissible_income_ratio"].passed is False
    assert result.verdict == "non-compliant"


def test_decisions_do_not_depend_on_the_ambient_decimal_context():
    expected = _income_case().verdict

    with decimal.localcontext() as ctx:
        ctx.prec = 2
        low_precision = _income_case().verdict
        debt = RatioEngine().evaluate(
            make_snapshot(total_debt=0.304), MarketDataInput(market_cap=1.0)
        )
    with decimal.localcontext() as ctx:
        ctx.traps[decimal.Inexact] = True
        trapped = _income_case().verdict

    assert low_precision == trapped == expected == "non-compliant"
    assert debt.ratios["debt_to_market_cap"].passed is False  # 0.304 > 0.30, not "0.30"


def test_integers_keep_their_last_digit():
    snapshot = make_snapshot(
        total_debt=30_000_000_000_000_001,
        cash_equiv=0,
        accounts_receivable=0,
        liquid_assets=0,
        non_permissible_income=0,
        interest_income=0,
        dividend_income=0,
        revenue=100,
    )
    result = RatioEngine().evaluate(snapshot, MarketDataInput(market_cap=10**17))

    assert result.ratios["debt_to_market_cap"].passed is False


def test_int_beyond_float_range_is_invalid():
    result = RatioEngine().evaluate(
        make_snapshot(total_debt=10**400), MarketDataInput(market_cap=CAP)
    )

    assert result.missing_inputs["total_debt"] == "invalid"
    assert result.verdict == "insufficient-data"


@pytest.mark.parametrize(
    "zero",
    [0, 0.0, -0.0, "0", "0.0", "-0", "0e-400", Decimal("0"), Decimal("-0.00")],
)
def test_every_spelling_of_zero_is_a_known_zero(zero):
    result = RatioEngine().evaluate(
        make_snapshot(interest_income=zero), MarketDataInput(market_cap=CAP)
    )

    assert "interest_income" not in result.missing_inputs
    assert result.verdict == "compliant"


@pytest.mark.parametrize("tiny", ["1e-400", Decimal("1e-1600")])
def test_a_positive_amount_that_underflows_is_not_a_known_zero(tiny):
    result = RatioEngine().evaluate(
        make_snapshot(interest_income=tiny), MarketDataInput(market_cap=CAP)
    )

    assert result.missing_inputs["interest_income"] == "invalid"
    assert result.verdict == "insufficient-data"

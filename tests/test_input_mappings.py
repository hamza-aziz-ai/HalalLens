#!/usr/bin/env python3
"""D-028: an engine input the mappers cannot establish stays missing, never guessed.

Focused mapper tests for the ETL (XBRL/JSON/PDF tables) and the Indian API
vendor, plus fixture -> mapper -> engine regressions. No live services.
"""

from datetime import datetime

import pandas as pd
import pytest

from etl import financial_data_processor as fdp_module
from etl.financial_data_processor import FinancialDataProcessor as FDP
from market_data import indian_api
from ratio_engine import FinancialSnapshotInput, MarketDataInput, RatioEngine

CAP = 200_000_000
CRORE = indian_api.INR_CRORE


def _xbrl(**facts) -> bytes:
    """One element per (tag, value); a list value repeats the tag (contexts)."""
    body = ""
    for tag, value in facts.items():
        for item in value if isinstance(value, list) else [value]:
            body += f"<{tag}>{item}</{tag}>"
    return f"<xbrl>{body}</xbrl>".encode()


@pytest.fixture
def processor(tmp_path, monkeypatch):
    """A real FDP with no MinIO or Postgres behind it."""

    class _NoStorage:
        client = None
        bucket_name = "test"

    monkeypatch.setattr(fdp_module, "BSEPDFStorage", _NoStorage)
    return FDP(
        download_dir=str(tmp_path / "dl"),
        cache_dir=str(tmp_path / "cache"),
        db_manager=object(),
    )


def _tables(processor, *tables):
    """Parse Camelot-like tables (lists of rows) the way the PDF path does."""
    metrics, conflicts = {}, set()
    for rows in tables:
        processor._parse_table_for_metrics(pd.DataFrame(rows), metrics, conflicts)
    return metrics


def _vendor(rows, end_date="2024-03-31"):
    """A minimal Indian API payload with one financials entry."""
    return {
        "marketCap": CAP / CRORE,
        "financials": [
            {
                "EndDate": end_date,
                "stockFinancialMap": {
                    statement: [{"key": k, "value": str(v)} for k, v in items]
                    for statement, items in rows.items()
                },
            }
        ],
    }


def _snapshot(extracted: dict) -> FinancialSnapshotInput:
    """Mapper output to engine input, as jobs.ingest_bse builds it."""
    return FinancialSnapshotInput(
        symbol="TEST",
        filing_date=datetime(2024, 1, 1),
        total_debt=extracted.get("total_debt"),
        cash_equiv=extracted.get("cash_equiv"),
        revenue=extracted.get("revenue"),
        interest_income=extracted.get("interest_income"),
        dividend_income=extracted.get("dividend_income"),
        non_permissible_income=extracted.get(
            "non_permissible_income", extracted.get("non_halal_income")
        ),
        accounts_receivable=extracted.get("accounts_receivable"),
        liquid_assets=extracted.get("liquid_assets"),
    )


# --- Liquid assets ------------------------------------------------------------


@pytest.mark.parametrize(
    "tag",
    ["CurrentAssets", "TotalCurrentAssets", "NetCurrentAssets", "TradeReceivables", "CashAndBankBalances"],
)
def test_structured_non_liquid_tags_never_fill_liquid_assets(tag):
    assert "liquid_assets" not in FDP._parse_xbrl(_xbrl(**{tag: 100}))


@pytest.mark.parametrize(
    "label",
    ["Total current assets", "Net current assets", "Cash and bank balances", "Trade receivables"],
)
def test_pdf_non_liquid_rows_never_fill_liquid_assets(processor, label):
    assert "liquid_assets" not in _tables(processor, [[label, "100"]])


def test_explicit_liquid_assets_line_maps(processor):
    assert FDP._parse_xbrl(_xbrl(LiquidAssets=40))["liquid_assets"] == 40
    assert _tables(processor, [["Liquid assets", "40"]])["liquid_assets"] == 40
    for label in ("Net liquid assets", "Illiquid assets", "Non-liquid assets"):
        assert "liquid_assets" not in _tables(processor, [[label, "40"]])
        assert "liquid_assets" not in FDP._parse_xbrl(_xbrl(**{FDP._normalize_tag(label): 40}))


def test_vendor_never_derives_liquid_assets():
    flat = {"cashequivalents": 5.0, "totalreceivablesnet": 2.0, "shortterminvestments": 1.0}
    assert "liquid_assets" not in indian_api._build_metrics(flat)
    assert indian_api._build_metrics({"liquidassets": 3.0})["liquid_assets"] == 3.0 * CRORE
    assert indian_api._build_metrics({"liquidassets": 0.0})["liquid_assets"] == 0.0


# --- Prohibited-income base ---------------------------------------------------


@pytest.mark.parametrize(
    "tag",
    ["NonPermissibleIncome", "ImpermissibleIncome", "HaramIncome", "ProhibitedIncome", "TotalNonPermissibleIncome"],
)
def test_prohibited_income_labels_never_fill_the_base(processor, tag):
    assert "non_halal_income" not in FDP._parse_xbrl(_xbrl(**{tag: 5}))
    assert "non_halal_income" not in FDP._parse_structured_json({tag: 5})
    assert "non_halal_income" not in _tables(processor, [["Non-permissible income", "5"]])


def test_vendor_other_net_is_not_prohibited_income():
    assert "non_halal_income" not in indian_api._build_metrics({"othernet": 0.25})
    assert "non_halal_income" not in indian_api._build_metrics({"nonpermissibleincome": 0.25})


# --- Interest and dividend income ---------------------------------------------


def test_interest_never_fills_both_interest_and_base(processor):
    for metrics in (
        FDP._parse_xbrl(_xbrl(InterestIncome=500)),
        _tables(processor, [["Interest income", "500"]]),
    ):
        assert metrics["interest_income"] == 500
        assert "non_halal_income" not in metrics


@pytest.mark.parametrize(
    "tag",
    [
        "InterestIncomeNet",
        "NetInterestIncome",
        "InterestIncomeExpenseNet",
        "InterestIncomeExpense",
        "FinanceIncome",
        "OtherIncomeIncludingInterestIncome",
        "InterestIncomeAccrued",
        "InterestIncomeReceivable",
    ],
)
def test_net_expense_and_finance_income_tags_abstain(tag):
    assert "interest_income" not in FDP._parse_xbrl(_xbrl(**{tag: 7}))


@pytest.mark.parametrize(
    "label",
    [
        "Interest income, net",
        "Net interest income",
        "Interest income / (expense)",
        "Other income (including interest income)",
    ],
)
def test_net_and_inclusive_interest_rows_abstain(processor, label):
    assert _tables(processor, [[label, "7"]]) == {}


def test_gross_interest_income_maps():
    assert FDP._parse_xbrl(_xbrl(InterestIncomeOnDeposits=12))["interest_income"] == 12
    assert indian_api._build_metrics({"interestincome": 1.0})["interest_income"] == 1.0 * CRORE


def test_vendor_net_interest_is_not_interest_income():
    assert "interest_income" not in indian_api._build_metrics({"interestincexpnetnonoptotal": 1.0})


@pytest.mark.parametrize(
    "label",
    ["Dividend income paid", "Proposed dividend income", "Dividend income payable", "Dividend income declared"],
)
def test_dividends_paid_or_declared_never_fill_dividend_income(processor, label):
    assert "dividend_income" not in _tables(processor, [[label, "3"]])
    assert "dividend_income" not in FDP._parse_xbrl(_xbrl(**{FDP._normalize_tag(label): 3}))


def test_dividends_paid_tags_never_fill_dividend_income():
    assert "dividend_income" not in FDP._parse_xbrl(_xbrl(DividendsPaid=3))
    assert "dividend_income" not in indian_api._build_metrics({"totalcashdividendspaid": 0.5})


# --- Zero, absence and ambiguity ----------------------------------------------


def test_explicit_zero_survives_and_absent_stays_missing(processor):
    metrics = FDP._parse_xbrl(_xbrl(InterestIncome=0, RevenueFromOperations=100))
    assert metrics["interest_income"] == 0.0
    assert "dividend_income" not in metrics
    assert _tables(processor, [["Dividend income", "0"]]) == {"dividend_income": 0.0}


def test_conflicting_repeated_facts_abstain():
    # Two contexts (e.g. this quarter and last) with different values: missing.
    assert "interest_income" not in FDP._parse_xbrl(_xbrl(InterestIncome=[10, 12]))
    assert "liquid_assets" not in FDP._parse_xbrl(_xbrl(LiquidAssets=[10, 12, 10]))
    # The same value repeated is not ambiguous.
    assert FDP._parse_xbrl(_xbrl(DividendIncome=[4, 4]))["dividend_income"] == 4
    # Fields outside D-028 keep first-match behaviour.
    assert FDP._parse_xbrl(_xbrl(RevenueFromOperations=[100, 90]))["revenue"] == 100
    payload = [{"InterestIncome": 10}, {"InterestIncome": 12}]
    assert "interest_income" not in FDP._parse_structured_json(payload)


def test_conflicting_pdf_columns_and_tables_abstain(processor):
    # Several period columns in one row: the rightmost is not known to be ours.
    assert _tables(processor, [["Interest income", "10", "12"]]) == {}
    # The same row in two tables (standalone vs consolidated) with other values.
    assert _tables(processor, [["Liquid assets", "40"]], [["Liquid assets", "45"]]) == {}
    assert _tables(processor, [["Liquid assets", "40"]], [["Liquid assets", "40"]]) == {
        "liquid_assets": 40
    }


def test_vendor_conflicting_repeated_keys_abstain():
    payload = _vendor({"INC": [("InterestIncome", 1)], "CAS": [("InterestIncome", 2)]})
    snapshot = indian_api.snapshot_from_payload(payload, symbol="TEST")
    assert "interest_income" not in snapshot.metrics

    payload = _vendor({"INC": [("InterestIncome", 1)], "CAS": [("InterestIncome", 1)]})
    snapshot = indian_api.snapshot_from_payload(payload, symbol="TEST")
    assert snapshot.metrics["interest_income"] == 1.0 * CRORE


def test_metric_cache_version_bumped(processor):
    keys = []
    processor._fetch_cached_metrics = lambda key: keys.append(key) or {"cached": 1}
    assert processor._get_or_extract_pdf_metrics({"minio_path": "a/b.pdf"}) == {"cached": 1}
    assert keys == ["metrics/v5/a/b.pdf.json"]


# --- Fixture -> mapper -> engine ----------------------------------------------


def test_old_wrong_xbrl_mappings_now_give_insufficient_data():
    xbrl = _xbrl(
        Borrowings=20_000_000,
        CashAndCashEquivalents=5_000_000,
        RevenueFromOperations=100_000_000,
        TradeReceivables=10_000_000,
        CurrentAssets=150_000_000,  # used to become liquid_assets (75% of cap: a false fail)
        NonPermissibleIncome=0,  # used to become the base
        InterestIncomeExpenseNet=-300_000,  # a net figure, not gross interest
        DividendIncome=0,
    )
    result = RatioEngine().evaluate(_snapshot(FDP._parse_xbrl(xbrl)), MarketDataInput(market_cap=CAP))

    assert result.verdict == "insufficient-data"
    assert result.missing_inputs["liquid_assets"] == "missing"
    assert result.missing_inputs["non_permissible_income"] == "missing"
    assert result.missing_inputs["interest_income"] == "missing"


def test_old_wrong_vendor_mappings_now_give_insufficient_data():
    payload = _vendor(
        {
            "BAL": [("TotalDebt", 2), ("CashEquivalents", 0.5), ("TotalReceivablesNet", 1), ("ShortTermInvestments", 1)],
            "INC": [("TotalRevenue", 10), ("InterestIncExpNetNonOpTotal", -0.03), ("OtherNet", 0)],
        }
    )
    snapshot = indian_api.snapshot_from_payload(payload, symbol="TEST")
    result = RatioEngine().evaluate(
        _snapshot(snapshot.metrics), MarketDataInput(market_cap=snapshot.market_cap)
    )

    assert result.verdict == "insufficient-data"
    for name in ("liquid_assets", "non_permissible_income", "interest_income", "dividend_income"):
        assert result.missing_inputs[name] == "missing"


def test_failing_ratio_is_conclusive_despite_rejected_inputs():
    xbrl = _xbrl(
        Borrowings=70_000_000,  # 35% of cap
        RevenueFromOperations=100_000_000,
        NetCurrentAssets=1,
        FinanceIncome=1,
    )
    result = RatioEngine().evaluate(_snapshot(FDP._parse_xbrl(xbrl)), MarketDataInput(market_cap=CAP))

    assert result.verdict == "non-compliant"
    assert result.missing_inputs["liquid_assets"] == "missing"


def test_complete_verified_fixture_needs_a_supplied_base():
    xbrl = _xbrl(
        Borrowings=20_000_000,
        CashAndCashEquivalents=5_000_000,
        RevenueFromOperations=100_000_000,
        TradeReceivables=10_000_000,
        LiquidAssets=40_000_000,
        InterestIncome=1_000_000,
        DividendIncome=0,
    )
    extracted = FDP._parse_xbrl(xbrl)
    market = MarketDataInput(market_cap=CAP)

    # Extraction never supplies the base (D-028), so the filing stays insufficient...
    assert RatioEngine().evaluate(_snapshot(extracted), market).verdict == "insufficient-data"
    # ...until a reviewed source (a governance override) gives it; an explicit 0 counts.
    result = RatioEngine().evaluate(_snapshot(extracted | {"non_halal_income": 0.0}), market)
    assert result.verdict == "compliant"
    assert result.ratios["non_permissible_income_ratio"].value == pytest.approx(0.01)

#!/usr/bin/env python3
"""Recompute mode of jobs/backfill_evaluations.py, and the plain backfill's skip.

Recompute repairs stored evaluations after a ratio-logic change: current stored
inputs only (no vendor or Bhavcopy calls), dry run by default, and a
before/after CSV that is created, never overwritten, before any database write.

Records here mirror the columns `get_recent_filings` really selects; a contract
test keeps them honest (a stub with an invented `ratios` key once hid a no-op).
"""

import csv
import importlib
import inspect
import os
from datetime import datetime

import pytest

from database.database_manager import BSEDatabaseManager

backfill = importlib.import_module("jobs.backfill_evaluations")

FILING = datetime(2024, 6, 30)
CAP = 400_000_000.0


def _record(symbol, **overrides):
    record = {
        "symbol": symbol,
        "filing_date": FILING,
        "total_debt": 25_000_000,
        "cash_equiv": 10_000_000,
        "revenue": 200_000_000,
        "non_halal_income": 5_000_000,
        "interest_income": 1_000_000,
        "dividend_income": 0,
        "accounts_receivable": 20_000_000,
        "liquid_assets": 40_000_000,
        "has_ratios": True,
        "verdict": "compliant",
        "is_compliant": True,
        "evaluation_updated_at": datetime(2026, 1, 1),
        "market_cap_used": CAP,
        "trailing_cap_used": None,
        "market_data_provider": "bhavcopy",
    }
    record.update(overrides)
    return record


DEFAULT_RECORDS = [
    _record("SAME"),  # still compliant
    _record("PARTIAL", interest_income=None),  # old engine passed it; new one cannot
    _record("NOCAP", market_cap_used=None),  # no stored cap: skipped, never fetched
    _record("NULLRATIOS", has_ratios=False),  # evaluation row with NULL/empty ratios
    _record("NEVER", has_ratios=None, verdict=None, is_compliant=None, evaluation_updated_at=None),
    _record("REVIEW"),  # open quality issue
]


class StubDB:
    def __init__(self, records, report=None):
        self.records = records
        self.writes = []
        self.report = report
        self.reads = 0

    def get_recent_filings(self, limit=500):
        self.reads += 1
        return [dict(r) for r in self.records][:limit]

    def get_quality_issues(self, symbol, filing_date):
        return ["anomaly"] if symbol == "REVIEW" else []

    def parse_iso_datetime(self, value):
        return datetime.fromisoformat(value)

    def upsert_filing_evaluation(self, **kwargs):
        # The evidence must already be on disk when the first write happens.
        assert self.report is None or os.path.exists(self.report)
        self.writes.append(kwargs)

    def __getattr__(self, name):  # close(), market-failure bookkeeping, ...
        return lambda *args, **kwargs: None


@pytest.fixture()
def env(monkeypatch):
    state = {"records": DEFAULT_RECORDS, "report": None, "db": None}

    def factory():
        state["db"] = StubDB(state["records"], state["report"])
        return state["db"]

    def no_vendor(*args, **kwargs):
        raise AssertionError("recompute must not fetch market data or vendor payloads")

    monkeypatch.setattr(backfill, "BSEDatabaseManager", factory)
    monkeypatch.setattr(backfill, "configure_logging", lambda *a, **k: None)
    state["no_vendor"] = no_vendor
    monkeypatch.setattr(backfill, "_lookup_market_data", no_vendor)
    monkeypatch.setattr(backfill, "_enrich_snapshot_with_indian_api", no_vendor)
    return state


def _by_symbol(rows):
    return {row["symbol"]: row for row in rows}


# --- Query contract ------------------------------------------------------------


def test_every_key_the_jobs_read_is_selected_by_the_query():
    sql = inspect.getsource(BSEDatabaseManager.get_recent_filings)
    for key in (
        "has_ratios",
        "verdict",
        "is_compliant",
        "market_cap_used",
        "trailing_cap_used",
        "market_data_provider",
        "interest_income",
        "dividend_income",
        "non_halal_income",
        "accounts_receivable",
        "liquid_assets",
        "total_debt",
        "cash_equiv",
        "revenue",
    ):
        assert f".{key}" in sql or f"AS {key}" in sql, key


def test_the_query_does_not_return_the_ratios_json():
    """/filings/recent shares this query; FilingResponse.ratios must stay null there."""

    sql = inspect.getsource(BSEDatabaseManager.get_recent_filings)
    select = sql.split("FROM announcements")[0]
    assert "fe.ratios," not in select
    assert "AS ratios" not in select


# --- Recompute -------------------------------------------------------------------


def test_dry_run_reports_transitions_and_writes_nothing(env):
    rows = _by_symbol(backfill.recompute(limit=500))

    assert env["db"].writes == []
    assert set(rows) == {"SAME", "PARTIAL", "NOCAP", "REVIEW"}  # NULL/empty ratios and never-evaluated excluded
    assert (rows["SAME"]["new_verdict"], rows["SAME"]["changed"]) == ("compliant", False)
    assert rows["PARTIAL"]["new_verdict"] == "insufficient-data"
    assert rows["PARTIAL"]["new_is_compliant"] is None
    assert rows["PARTIAL"]["changed"] is True
    assert "interest_income=missing" in rows["PARTIAL"]["missing_inputs"]
    assert rows["NOCAP"]["status"] == "skipped: no stored market cap"
    assert (rows["REVIEW"]["new_verdict"], rows["REVIEW"]["new_is_compliant"]) == ("needs-review", None)


@pytest.mark.parametrize(
    "primary, verdict",
    [
        (None, "compliant"),  # absent primary: the trailing cap stands in
        (0, "compliant"),  # numeric zero is absent too
        (-CAP, "insufficient-data"),  # invalid primary is never rescued
        (float("nan"), "insufficient-data"),
    ],
    ids=["absent", "zero", "negative", "nan"],
)
def test_stored_caps_reach_the_engine_unchanged(env, primary, verdict):
    env["records"] = [_record("CAP", market_cap_used=primary, trailing_cap_used=CAP)]

    row = backfill.recompute()[0]

    assert row["new_verdict"] == verdict
    if verdict == "insufficient-data":
        assert "market_cap=invalid" in row["missing_inputs"]


def test_report_is_a_before_after_csv_with_inputs(env, tmp_path):
    report = tmp_path / "recompute.csv"

    backfill.recompute(report=str(report))

    with open(report, newline="", encoding="utf-8") as handle:
        rows = {row["symbol"]: row for row in csv.DictReader(handle)}
    assert list(rows) == ["SAME", "PARTIAL", "NOCAP", "REVIEW"]
    assert (rows["PARTIAL"]["old_verdict"], rows["PARTIAL"]["new_verdict"]) == (
        "compliant",
        "insufficient-data",
    )
    assert rows["PARTIAL"]["interest_income"] == ""  # the input that made it unknown
    assert rows["PARTIAL"]["market_data_provider"] == "bhavcopy"
    assert env["db"].writes == []  # a report alone is still a dry run


def test_existing_report_is_never_overwritten(env, tmp_path):
    report = tmp_path / "recompute.csv"
    report.write_text("earlier evidence", encoding="utf-8")

    with pytest.raises(FileExistsError):
        backfill.recompute(write=True, report=str(report))

    assert report.read_text(encoding="utf-8") == "earlier evidence"
    assert env["db"] is None  # refused before touching the database


def test_report_neutralises_spreadsheet_formulas(env, tmp_path):
    env["records"] = [_record("=1+1")]
    report = tmp_path / "recompute.csv"

    backfill.recompute(report=str(report))

    with open(report, newline="", encoding="utf-8") as handle:
        assert next(csv.DictReader(handle))["symbol"] == "'=1+1"


def test_write_requires_a_report():
    with pytest.raises(ValueError):
        backfill.recompute(write=True)


@pytest.mark.parametrize("limit", [0, -5])
def test_limit_must_be_positive(limit):
    with pytest.raises(ValueError):
        backfill.recompute(limit=limit)


def test_write_stores_current_inputs_after_the_report_exists(env, tmp_path):
    report = tmp_path / "recompute.csv"
    env["report"] = str(report)

    backfill.recompute(write=True, report=str(report))

    writes = {w["symbol"]: w for w in env["db"].writes}
    assert set(writes) == {"SAME", "PARTIAL", "REVIEW"}  # skipped rows are not written
    partial = writes["PARTIAL"]
    assert (partial["verdict"], partial["is_compliant"]) == ("insufficient-data", None)
    assert partial["narration_source"] == "recompute"
    assert partial["market_cap_used"] == CAP  # the stored cap, not a fresh lookup
    assert partial["market_data_provider"] == "bhavcopy"
    assert (writes["REVIEW"]["verdict"], writes["REVIEW"]["is_compliant"]) == ("needs-review", None)


# --- Plain backfill ---------------------------------------------------------------


def test_plain_backfill_skips_filings_that_already_have_ratios(env, monkeypatch):
    """It used to test a key the query never returns, so it overwrote them."""

    env["records"] = [_record("DONE"), _record("TODO", has_ratios=None)]
    monkeypatch.setattr(backfill, "_enrich_snapshot_with_indian_api", lambda *a, **k: None)
    monkeypatch.setattr(backfill, "_lookup_market_data", lambda *a, **k: (CAP, 100.0, "stub"))

    backfill.main(limit=10)

    assert [w["symbol"] for w in env["db"].writes] == ["TODO"]


# --- CLI ----------------------------------------------------------------------------


@pytest.mark.parametrize(
    "argv",
    [
        ["--write"],
        ["--report", "x.csv"],
        ["--recompute", "--write"],
        ["--recompute", "--limit", "0"],
    ],
)
def test_cli_rejects_unsafe_combinations(argv):
    with pytest.raises(SystemExit):
        backfill._parse_args(argv)


def test_cli_defaults_to_the_plain_backfill():
    args = backfill._parse_args([])

    assert (args.recompute, args.write, args.report, args.limit) == (False, False, None, 500)

#!/usr/bin/env python3
"""Recompute mode of jobs/backfill_evaluations.py.

It repairs stored evaluations after a ratio-logic change: frozen inputs only (no
vendor or Bhavcopy calls), dry run by default, and a before/after CSV that is
written before any database write.
"""

import csv
import importlib
import os
from datetime import datetime

import pytest

backfill = importlib.import_module("jobs.backfill_evaluations")

FILING = datetime(2024, 6, 30)


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
        "ratios": {"debt_to_market_cap": {}},  # already evaluated
        "verdict": "compliant",
        "is_compliant": True,
        "market_cap_used": 400_000_000.0,
        "trailing_cap_used": None,
        "market_data_provider": "bhavcopy",
    }
    record.update(overrides)
    return record


RECORDS = [
    _record("SAME"),  # still compliant
    _record("PARTIAL", interest_income=None),  # old engine passed it; new one cannot
    _record("NOCAP", market_cap_used=None),  # no stored cap: skipped, never fetched
    _record("NEVER", ratios=None),  # never evaluated: left to the plain backfill
    _record("REVIEW"),  # open quality issue
]


class StubDB:
    def __init__(self, report=None):
        self.writes = []
        self.report = report
        self.closed = False

    def get_recent_filings(self, limit=500):
        return [dict(r) for r in RECORDS][:limit]

    def get_quality_issues(self, symbol, filing_date):
        return ["anomaly"] if symbol == "REVIEW" else []

    def parse_iso_datetime(self, value):
        return datetime.fromisoformat(value)

    def upsert_filing_evaluation(self, **kwargs):
        # The evidence must already be on disk when the first write happens.
        assert self.report is None or os.path.exists(self.report)
        self.writes.append(kwargs)

    def close(self):
        self.closed = True


@pytest.fixture()
def stub_db(monkeypatch):
    holder = {}

    def factory():
        holder["db"] = StubDB(holder.get("report"))
        return holder["db"]

    def no_vendor(*args, **kwargs):
        raise AssertionError("recompute must not fetch market data or vendor payloads")

    monkeypatch.setattr(backfill, "BSEDatabaseManager", factory)
    monkeypatch.setattr(backfill, "_lookup_market_data", no_vendor)
    monkeypatch.setattr(backfill, "_enrich_snapshot_with_indian_api", no_vendor)
    return holder


def _by_symbol(rows):
    return {row["symbol"]: row for row in rows}


def test_dry_run_reports_transitions_and_writes_nothing(stub_db):
    rows = _by_symbol(backfill.recompute(limit=500))

    assert stub_db["db"].writes == []
    assert stub_db["db"].closed
    assert "NEVER" not in rows
    assert (rows["SAME"]["new_verdict"], rows["SAME"]["changed"]) == ("compliant", False)
    assert rows["PARTIAL"]["new_verdict"] == "insufficient-data"
    assert rows["PARTIAL"]["new_is_compliant"] is None
    assert rows["PARTIAL"]["changed"] is True
    assert "interest_income=missing" in rows["PARTIAL"]["missing_inputs"]
    assert rows["NOCAP"]["status"] == "skipped: no stored market cap"
    assert (rows["REVIEW"]["new_verdict"], rows["REVIEW"]["new_is_compliant"]) == ("needs-review", None)


def test_report_is_a_before_after_csv(stub_db, tmp_path):
    report = tmp_path / "recompute.csv"

    backfill.recompute(report=str(report))

    with open(report, newline="", encoding="utf-8") as handle:
        rows = {row["symbol"]: row for row in csv.DictReader(handle)}
    assert list(rows) == ["SAME", "PARTIAL", "NOCAP", "REVIEW"]
    assert (rows["PARTIAL"]["old_verdict"], rows["PARTIAL"]["new_verdict"]) == (
        "compliant",
        "insufficient-data",
    )
    assert stub_db["db"].writes == []  # a report alone is still a dry run


def test_write_requires_a_report():
    with pytest.raises(ValueError):
        backfill.recompute(write=True)


def test_write_stores_frozen_inputs_after_the_report_exists(stub_db, tmp_path):
    report = tmp_path / "recompute.csv"
    stub_db["report"] = str(report)

    backfill.recompute(write=True, report=str(report))

    writes = {w["symbol"]: w for w in stub_db["db"].writes}
    assert set(writes) == {"SAME", "PARTIAL", "REVIEW"}  # skipped rows are not written
    partial = writes["PARTIAL"]
    assert (partial["verdict"], partial["is_compliant"]) == ("insufficient-data", None)
    assert partial["narration_source"] == "recompute"
    assert partial["market_cap_used"] == 400_000_000.0  # the stored cap, not a fresh lookup
    assert partial["market_data_provider"] == "bhavcopy"
    assert (writes["REVIEW"]["verdict"], writes["REVIEW"]["is_compliant"]) == ("needs-review", None)


@pytest.mark.parametrize(
    "argv",
    [["--write"], ["--report", "x.csv"], ["--recompute", "--write"]],
)
def test_cli_rejects_unsafe_combinations(argv):
    with pytest.raises(SystemExit):
        backfill._parse_args(argv)


def test_cli_defaults_to_the_plain_backfill():
    args = backfill._parse_args([])

    assert (args.recompute, args.write, args.report, args.limit) == (False, False, None, 500)

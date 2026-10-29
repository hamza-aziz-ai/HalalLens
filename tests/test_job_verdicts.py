#!/usr/bin/env python3
"""Every job that persists an evaluation publishes through the shared overlay.

The four jobs used to derive "compliant" from a boolean on their own, and later
stored the engine's pair without the quality overlay. They now publish through
`evaluation.quality.publish_evaluation` (D-027): the engine's pair when no issue
is open, needs-review / None when one is open or newly detected. These tests pin
that for each of them so one cannot drift from the others again.
"""

import importlib
from datetime import datetime

import pytest

from evaluation import quality
from ratio_engine import FinancialSnapshotInput
from tests.quality_fake import MemoryQualityDB

FILING = datetime(2024, 6, 30)


class StubDB(MemoryQualityDB):
    """Publishes through the in-memory overlay; any other DB call is a harmless no-op."""

    def __init__(self, record):
        super().__init__()
        self.record = record

    def get_recent_filings(self, limit=500):
        return [self.record]

    def get_filings_needing_evaluation(self, **kwargs):
        return [self.record]

    def get_filing(self, symbol, filing_date):
        return self.record

    def get_cached_market_data(self, *args, **kwargs):
        return (400_000_000.0, 100.0, "stub")

    def parse_iso_datetime(self, value):
        return datetime.fromisoformat(value)

    def __getattr__(self, name):  # close(), resolve_*, record_* ...
        return lambda *args, **kwargs: None


def _record(**overrides):
    record = {
        "symbol": "TCS",
        "filing_date": FILING,
        "total_debt": 25_000_000,
        "cash_equiv": 10_000_000,
        "revenue": 200_000_000,
        "non_halal_income": 5_000_000,
        "interest_income": 1_000_000,
        "dividend_income": 0,
        "accounts_receivable": 20_000_000,
        "liquid_assets": 40_000_000,
        "ratios": None,
        "market_cap_used": 400_000_000.0,
    }
    record.update(overrides)
    return record


def _run_backfill(monkeypatch, db):
    module = importlib.import_module("jobs.backfill_evaluations")
    monkeypatch.setattr(module, "BSEDatabaseManager", lambda: db)
    monkeypatch.setattr(module, "configure_logging", lambda *a, **k: None)
    monkeypatch.setattr(module, "_enrich_snapshot_with_indian_api", lambda *a, **k: None)
    monkeypatch.setattr(
        module, "_lookup_market_data", lambda *a, **k: (400_000_000.0, 100.0, "stub")
    )
    module.main(limit=1)


def _run_precompute(monkeypatch, db):
    module = importlib.import_module("jobs.precompute_evaluations")
    monkeypatch.setattr(module, "BSEDatabaseManager", lambda: db)
    monkeypatch.setattr(module, "_enrich_snapshot_with_indian_api", lambda *a, **k: None)
    module.run_precompute(limit=1)


def _run_ingest_bse(monkeypatch, db):
    module = importlib.import_module("jobs.ingest_bse")

    def snapshot(record, _db):
        return FinancialSnapshotInput(
            symbol=record["symbol"],
            filing_date=record["filing_date"],
            total_debt=record["total_debt"],
            cash_equiv=record["cash_equiv"],
            revenue=record["revenue"],
            interest_income=record["interest_income"],
            dividend_income=record["dividend_income"],
            non_permissible_income=record["non_halal_income"],
            accounts_receivable=record["accounts_receivable"],
            liquid_assets=record["liquid_assets"],
        )

    monkeypatch.setattr(module, "_snapshot_from_record", snapshot)
    monkeypatch.setattr(module, "_enrich_snapshot_with_indian_api", lambda *a, **k: None)
    monkeypatch.setattr(
        module, "_lookup_market_data", lambda *a, **k: (400_000_000.0, 100.0, "stub")
    )
    module._evaluate_and_store(db, [db.record])


def _run_ingest_indianapi(monkeypatch, db):
    module = importlib.import_module("jobs.ingest_indianapi")
    module._evaluate_snapshot(db, "TCS", FILING)


JOBS = {
    "backfill": _run_backfill,
    "precompute": _run_precompute,
    "ingest_bse": _run_ingest_bse,
    "ingest_indianapi": _run_ingest_indianapi,
}

CASES = [
    ({}, "compliant", True),
    ({"interest_income": None}, "insufficient-data", None),
    ({"total_debt": 400_000_000}, "non-compliant", False),
]


@pytest.mark.parametrize("job", JOBS)
@pytest.mark.parametrize(
    "overrides, verdict, is_compliant", CASES, ids=["compliant", "insufficient", "non-compliant"]
)
def test_job_persists_engine_verdict(monkeypatch, job, overrides, verdict, is_compliant):
    db = StubDB(_record(**overrides))

    JOBS[job](monkeypatch, db)

    assert len(db.writes) == 1
    written = db.writes[0]
    assert (written["verdict"], written["is_compliant"]) == (verdict, is_compliant)
    if verdict == "insufficient-data":
        assert written["summary"].startswith("Insufficient data")


# --- Real adapters must not turn booleans into amounts -----------------------

BOOL_FIELDS = ("non_halal_income", "interest_income", "dividend_income")


def _bool_record(value):
    return _record(**{field: value for field in BOOL_FIELDS})


def _real_snapshots(record):
    """The real record -> FinancialSnapshotInput mappers of each module."""

    backfill = importlib.import_module("jobs.backfill_evaluations")
    ingest_bse = importlib.import_module("jobs.ingest_bse")
    ingest_indianapi = importlib.import_module("jobs.ingest_indianapi")
    api_module = importlib.import_module("api.app")
    return {
        "backfill": backfill._snapshot_from_record(record),
        # The BSE mapper reads the metrics from record["extracted_data"].
        "ingest_bse": ingest_bse._snapshot_from_record(
            {
                "symbol": record["symbol"],
                "filing_date": record["filing_date"],
                "extracted_data": record,
            },
            StubDB(record),
        ),
        "ingest_indianapi": ingest_indianapi._snapshot_from_record(record),
        "api": api_module._snapshot_from_record(record),
    }


@pytest.mark.parametrize("flag", [True, False])
def test_real_adapters_treat_booleans_as_unknown(flag):
    from ratio_engine import MarketDataInput, RatioEngine

    for name, snapshot in _real_snapshots(_bool_record(flag)).items():
        assert snapshot is not None, name
        assert snapshot.non_permissible_income is None, name
        assert snapshot.interest_income is None, name
        assert snapshot.dividend_income is None, name
        result = RatioEngine().evaluate(snapshot, MarketDataInput(market_cap=400_000_000.0))
        assert result.verdict == "insufficient-data", name


def test_real_adapters_still_map_numbers():
    snapshots = _real_snapshots(_record())

    for name, snapshot in snapshots.items():
        assert snapshot.interest_income == 1_000_000.0, name
        assert snapshot.dividend_income == 0.0, name
        assert snapshot.non_permissible_income == 5_000_000.0, name


@pytest.mark.parametrize("job", JOBS)
def test_job_summary_matches_verdict(monkeypatch, job):
    expectations = {
        "compliant": ({}, "All configured financial checks"),
        "insufficient-data": ({"interest_income": None}, "Insufficient data"),
        "non-compliant": ({"total_debt": 400_000_000}, "Debt to market cap exceeded"),
    }
    for _verdict, (overrides, prefix) in expectations.items():
        db = StubDB(_record(**overrides))
        JOBS[job](monkeypatch, db)
        assert db.writes[0]["summary"].startswith(prefix), (job, _verdict)


def _run_indianapi_with_cap(cap, record=None):
    module = importlib.import_module("jobs.ingest_indianapi")
    db = StubDB(record or _record())
    db.get_cached_market_data = lambda *args, **kwargs: (cap, 100.0, "stub")
    module._evaluate_snapshot(db, "TCS", FILING)
    return db


@pytest.mark.parametrize("cap", [True, float("nan"), float("inf"), "1e-400"], ids=repr)
def test_ingest_indianapi_unusable_cached_cap_is_still_evaluated(cap):
    """Skipping would leave an older conclusive row; unknown must be written."""

    db = _run_indianapi_with_cap(cap)

    assert len(db.writes) == 1
    assert (db.writes[0]["verdict"], db.writes[0]["is_compliant"]) == (
        "insufficient-data",
        None,
    )
    assert db.writes[0]["market_cap_used"] is None


def test_ingest_indianapi_unusable_cap_does_not_hide_a_conclusive_failure():
    # Income above 5% of revenue fails regardless of the market cap.
    record = _record(non_halal_income=50_000_000)

    db = _run_indianapi_with_cap(float("nan"), record)

    assert len(db.writes) == 1
    assert (db.writes[0]["verdict"], db.writes[0]["is_compliant"]) == (
        "non-compliant",
        False,
    )


def test_ingest_indianapi_without_any_cached_cap_writes_nothing():
    db = _run_indianapi_with_cap(None)

    assert db.writes == []


# --- Shared publication overlay (D-027) ---------------------------------------

KEY = ("TCS", FILING)
# Trips all three anomaly rules: income above revenue, cash above 2x the cap,
# and tiny revenue against large non-permissible income.
ANOMALOUS = dict(revenue=500_000, non_halal_income=600_000, cash_equiv=1_000_000_000)


@pytest.mark.parametrize("job", JOBS)
@pytest.mark.parametrize("issue_type", ["market-data-missing", "governance_override", "some-future-type"])
def test_job_publishes_needs_review_while_any_issue_is_open(monkeypatch, job, issue_type):
    db = StubDB(_record())
    db.seed_issue(*KEY, issue_type, "open elsewhere")

    JOBS[job](monkeypatch, db)

    assert len(db.writes) == 1
    written = db.writes[0]
    assert (written["verdict"], written["is_compliant"], written["summary"]) == (
        "needs-review",
        None,
        quality.REVIEW_SUMMARY,
    )
    assert db.issues[KEY] == {issue_type: "open elsewhere"}  # publishing resolves nothing else


@pytest.mark.parametrize("job", JOBS)
def test_job_records_detected_anomalies_as_one_row(monkeypatch, job):
    db = StubDB(_record(**ANOMALOUS))

    JOBS[job](monkeypatch, db)
    first = db.issues[KEY]["ratio_anomaly"]
    JOBS[job](monkeypatch, db)

    assert list(db.issues[KEY]) == ["ratio_anomaly"]
    assert db.issues[KEY]["ratio_anomaly"] == first  # deterministic across runs
    assert first.count("(>") == 2 and "Revenue figure" in first
    for written in db.writes:
        assert (written["verdict"], written["is_compliant"], written["summary"]) == (
            "needs-review",
            None,
            quality.ANOMALY_SUMMARY,
        )


@pytest.mark.parametrize("job", JOBS)
def test_resolution_alone_keeps_needs_review_until_the_next_evaluation(monkeypatch, job):
    db = StubDB(_record())
    db.seed_issue(*KEY, "ratio_anomaly", "stale anomaly")
    db.seed_issue(*KEY, "governance_override", "override under review")

    JOBS[job](monkeypatch, db)  # clean data: only the detector's own row is resolved
    assert db.issues[KEY] == {"governance_override": "override under review"}
    assert db.evaluations[KEY]["verdict"] == "needs-review"

    db.resolve_quality_issues(*KEY, ["governance_override"])
    assert db.evaluations[KEY]["verdict"] == "needs-review"  # resolving restores nothing

    JOBS[job](monkeypatch, db)  # a new evaluation through the shared path
    assert (db.evaluations[KEY]["verdict"], db.evaluations[KEY]["is_compliant"]) == (
        "compliant",
        True,
    )

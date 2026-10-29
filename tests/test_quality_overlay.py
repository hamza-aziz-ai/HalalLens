"""The shared publication overlay (D-027), offline.

RatioEngine owns the verdict; evaluation.quality only masks it: no open issue
publishes the engine's pair unchanged, any open issue (any type) publishes
needs-review / None. These tests pin the pure policy, the API's fail-closed
reads, masking of stored and warm-cache results, and the scoped market-data
recovery. The lock and the transaction are proven against a real database in
tests/test_quality_postgres.py; the per-job writers in tests/test_job_verdicts.py.
"""

import asyncio
import importlib
from datetime import datetime, timezone

import pytest
from fastapi import HTTPException

from evaluation import quality
from ratio_engine import FinancialSnapshotInput, MarketDataInput, RatioEngine
from tests.quality_fake import MemoryQualityDB

api_module = importlib.import_module("api.app")

FILING = datetime(2024, 6, 30, tzinfo=timezone.utc)
CAP = 400_000_000.0
INPUTS = {
    "total_debt": 25_000_000,
    "cash_equiv": 10_000_000,
    "revenue": 200_000_000,
    "non_halal_income": 5_000_000,
    "interest_income": 1_000_000,
    "dividend_income": 0,
    "accounts_receivable": 20_000_000,
    "liquid_assets": 40_000_000,
}
# Trips all three detector rules: income above revenue, cash above 2x the cap,
# and tiny revenue against large non-permissible income.
ANOMALOUS = {**INPUTS, "revenue": 500_000, "non_halal_income": 600_000, "cash_equiv": 1_000_000_000}


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def _evaluate(**inputs):
    snapshot = FinancialSnapshotInput(
        symbol="TCS",
        filing_date=FILING,
        non_permissible_income=inputs.pop("non_halal_income"),
        **inputs,
    )
    return snapshot, RatioEngine().evaluate(snapshot, MarketDataInput(market_cap=CAP))


# --- Pure policy ---------------------------------------------------------------


@pytest.mark.parametrize("verdict, is_compliant", [
    ("compliant", True), ("non-compliant", False), ("insufficient-data", None),
])
def test_no_open_issue_passes_the_engine_result_through_unchanged(verdict, is_compliant):
    assert quality.publish(verdict, is_compliant, "engine summary", []) == (
        verdict, is_compliant, "engine summary",
    )


@pytest.mark.parametrize("issue_type", ["ratio_anomaly", "governance_override", "never-seen-before"])
def test_any_open_issue_type_publishes_needs_review(issue_type):
    issues = [{"issue_type": issue_type, "details": None}]
    assert quality.publish("compliant", True, "s", issues) == (
        "needs-review", None, quality.REVIEW_SUMMARY,
    )
    assert quality.publish("non-compliant", False, "s", issues, ["anomaly"])[2] == quality.ANOMALY_SUMMARY


def test_masking_never_unmasks_a_stored_needs_review():
    stored = {"verdict": "needs-review", "is_compliant": None, "summary": quality.ANOMALY_SUMMARY}
    quality.mask_stored(stored, [])
    assert stored == {"verdict": "needs-review", "is_compliant": None, "summary": quality.ANOMALY_SUMMARY}

    conclusive = {"verdict": "compliant", "is_compliant": True, "summary": "ok"}
    quality.mask_stored(conclusive, ["open"])
    assert (conclusive["verdict"], conclusive["is_compliant"]) == ("needs-review", None)

    unevaluated = {"verdict": None, "is_compliant": None}
    quality.mask_stored(unevaluated, ["open"])
    assert unevaluated["verdict"] is None


def test_multiple_anomalies_combine_into_one_deterministic_row():
    snapshot, evaluation = _evaluate(**ANOMALOUS)
    anomalies = quality.detect_ratio_anomalies(snapshot, evaluation)

    assert len(anomalies) == 3
    detail = quality.combined_anomaly(anomalies)
    assert detail == quality.combined_anomaly(list(anomalies)) == " ".join(anomalies)
    assert detail.index("Non-permissible") < detail.index("Cash to market cap") < detail.index("Revenue figure")

    open_issues = [
        {"issue_type": "ratio_anomaly", "details": "older text"},
        {"issue_type": "governance_override", "details": "kept"},
    ]
    assert quality.reconcile(open_issues, anomalies) == [
        {"issue_type": "governance_override", "details": "kept"},
        {"issue_type": "ratio_anomaly", "details": detail},
    ]
    # A clean evaluation resolves only the detector's own row.
    assert quality.reconcile(open_issues, []) == [{"issue_type": "governance_override", "details": "kept"}]
    # The detector did not run: nothing changes.
    assert quality.reconcile(open_issues, None) == open_issues


# --- API: fresh evaluation, fail-closed ----------------------------------------


def _record(**overrides):
    record = {"symbol": "TCS", "filing_date": FILING, **INPUTS, "market_cap_used": CAP, "ratios": None}
    record.update(overrides)
    return record


@pytest.fixture()
def api_db(monkeypatch):
    db = MemoryQualityDB()
    monkeypatch.setattr(api_module, "_get_db", lambda: db)
    monkeypatch.setattr(api_module, "_maybe_enrich_record_with_indian_api", lambda record: None)
    monkeypatch.setattr(api_module, "RECENT_FILINGS_CACHE", {})
    monkeypatch.setattr(api_module, "HISTORY_CACHE", {})
    return db


def test_api_records_a_new_anomaly_and_publishes_needs_review(api_db):
    record = _record(**ANOMALOUS)

    api_module._ensure_filing_evaluation(record, allow_market_fetch=False)

    assert (record["verdict"], record["is_compliant"], record["summary"]) == (
        "needs-review", None, quality.ANOMALY_SUMMARY,
    )
    assert list(api_db.issues[("TCS", FILING)]) == ["ratio_anomaly"]
    assert api_db.writes[-1]["verdict"] == "needs-review"


def test_api_publication_failure_is_503_and_publishes_nothing(api_db, monkeypatch):
    def down(**kwargs):
        raise RuntimeError("db down")

    monkeypatch.setattr(api_db, "publish_filing_evaluation", down)
    record = _record()

    with pytest.raises(HTTPException) as exc:
        api_module._ensure_filing_evaluation(record, allow_market_fetch=False)

    assert exc.value.status_code == 503
    assert "verdict" not in record and "is_compliant" not in record


def test_transient_record_blocks_on_detected_and_carried_issues(monkeypatch):
    monkeypatch.setattr(api_module, "_get_db", lambda: pytest.fail("transient records are never stored"))
    monkeypatch.setattr(api_module, "_maybe_enrich_record_with_indian_api", lambda record: None)
    record = _record(**ANOMALOUS, _transient=True, quality_issues=["carried"])

    api_module._ensure_filing_evaluation(record, allow_market_fetch=False)

    assert (record["verdict"], record["is_compliant"]) == ("needs-review", None)
    assert record["quality_issues"][-1] == "carried" and len(record["quality_issues"]) == 4


def test_indian_history_entry_publishes_through_the_overlay(api_db, monkeypatch):
    class Snapshot:
        symbol = "TCS"
        end_date = FILING.date()
        market_cap = CAP
        share_price = 100.0
        bse_code = "532540"
        company_name = "TCS"
        raw = {}
        metrics = dict(INPUTS)

    filing_dt = datetime(2024, 6, 30, tzinfo=timezone.utc)
    api_db.seed_issue("TCS", filing_dt, "governance_override", "open")
    api_db.get_filing = lambda symbol, filing_date: None
    for name in ("insert_announcements", "insert_financial_snapshots", "insert_market_snapshot"):
        setattr(api_db, name, lambda *a, **k: None)

    assert api_module._persist_indian_history_entry(Snapshot()) is True
    assert (api_db.writes[-1]["verdict"], api_db.writes[-1]["is_compliant"]) == ("needs-review", None)


# --- API: stored and cached results are masked -----------------------------------


def _stored(verdict="compliant", is_compliant=True):
    return {
        **_record(),
        "ratios": {"debt_to_market_cap": {"value": 0.1, "threshold": 0.3, "passed": True, "note": "ok"}},
        "verdict": verdict,
        "is_compliant": is_compliant,
        "summary": "engine summary",
        "company_name": "TCS",
        "category": "Result",
    }


def test_filing_detail_masks_a_stored_conclusive_result(api_db, monkeypatch):
    stored = _stored()
    api_db.get_latest_filing = lambda symbol: dict(stored)
    monkeypatch.setattr(api_module, "DB_MANAGER", api_db)

    assert _run(api_module.filing_detail("TCS")).verdict == "compliant"

    api_db.seed_issue("TCS", FILING, "market_data_fetch_failed", "primary down")
    response = _run(api_module.filing_detail("TCS"))
    assert (response.verdict, response.is_compliant) == ("needs-review", None)
    assert response.quality_issues == ["primary down"]


def test_filing_detail_issue_read_failure_is_503(api_db, monkeypatch):
    api_db.get_latest_filing = lambda symbol: _stored()
    monkeypatch.setattr(api_module, "DB_MANAGER", api_db)

    def down(symbol, filing_date):
        raise RuntimeError("db down")

    api_db.get_quality_issues = down
    with pytest.raises(HTTPException) as exc:
        _run(api_module.filing_detail("TCS"))
    assert exc.value.status_code == 503


def test_recent_filings_warm_cache_is_masked_by_a_new_issue(api_db):
    calls = []
    api_db.get_recent_filings = lambda limit=20: calls.append(limit) or [_stored()]

    assert _run(api_module.recent_filings(limit=5))[0].verdict == "compliant"
    api_db.record_quality_issue("TCS", FILING, "ratio_anomaly", "debt ratio > 100%")
    second = _run(api_module.recent_filings(limit=5))[0]

    assert calls == [5]  # the second response came from the warm cache
    assert (second.verdict, second.is_compliant) == ("needs-review", None)


def test_history_warm_cache_is_masked_by_a_new_issue(api_db, monkeypatch):
    monkeypatch.setattr(api_module, "_require_paid_feature", lambda authorization, feature: {"user_id": 1})
    calls = []
    api_db.get_filing_history = lambda symbol, limit=10, cursor_ts=None: calls.append(limit) or [_stored()]

    assert _run(api_module.filing_history("TCS", limit=5)).entries[0].verdict == "compliant"
    api_db.record_quality_issue("TCS", FILING, "some-future-type", None)
    entry = _run(api_module.filing_history("TCS", limit=5)).entries[0]

    assert calls == [6]
    assert (entry.verdict, entry.is_compliant) == ("needs-review", None)


# --- Scoped market-data recovery ----------------------------------------------------

UNRELATED = {"governance_override": "override", "ratio_anomaly": "anomaly"}


class MarketDB(MemoryQualityDB):
    def __init__(self, cached=None):
        super().__init__()
        self.cached = cached
        for issue_type in (*quality.PRIMARY_LOOKUP_DISPROVES, *UNRELATED):
            self.seed_issue("TCS", FILING, issue_type, issue_type)

    def get_cached_market_data(self, symbol, as_of=None):
        return self.cached

    def __getattr__(self, name):  # insert_market_snapshot, symbol lookups, ...
        return lambda *args, **kwargs: None

    def open_types(self):
        return set(self.issues[("TCS", FILING)])


class Resolver:
    def __init__(self, cap, price=100.0):
        self.result = (cap, price)

    def resolve(self, symbol, as_of):
        return self.result


class Vendor:
    market_cap = CAP
    share_price = 100.0


def _job_lookup(module_name, monkeypatch, db, *, vendor, bhavcopy):
    module = importlib.import_module(module_name)
    monkeypatch.setattr(module, "MARKET_CACHE", {})
    monkeypatch.setattr(module, "indian_api_enabled", lambda: vendor is not None)
    monkeypatch.setattr(module, "fetch_indian_financial_snapshot", lambda *a, **k: vendor)
    monkeypatch.setattr(module, "bhavcopy_resolver", bhavcopy)
    return module._lookup_market_data("TCS", FILING, db)


def _api_lookup(monkeypatch, db, *, vendor, bhavcopy):
    monkeypatch.setattr(api_module, "_get_db", lambda: db)
    monkeypatch.setattr(api_module, "MARKET_CACHE", {})
    monkeypatch.setattr(api_module, "indian_api_enabled", lambda: vendor is not None)
    monkeypatch.setattr(api_module, "_indian_api_candidates", lambda symbol: ["TCS"])
    monkeypatch.setattr(api_module, "fetch_indian_financial_snapshot", lambda *a, **k: vendor)
    monkeypatch.setattr(api_module, "bhavcopy_resolver", bhavcopy)
    return api_module._market_data_for_filing("TCS", FILING)


LOOKUPS = {
    "api": lambda mp, db, **kw: _api_lookup(mp, db, **kw),
    "backfill": lambda mp, db, **kw: _job_lookup("jobs.backfill_evaluations", mp, db, **kw),
    "ingest_bse": lambda mp, db, **kw: _job_lookup("jobs.ingest_bse", mp, db, **kw),
}


@pytest.mark.parametrize("path", LOOKUPS)
def test_primary_provider_success_clears_only_market_issues(monkeypatch, path):
    db = MarketDB()
    LOOKUPS[path](monkeypatch, db, vendor=Vendor(), bhavcopy=Resolver(None, None))
    assert db.open_types() == set(UNRELATED)


@pytest.mark.parametrize("path", LOOKUPS)
def test_bhavcopy_success_does_not_clear_a_primary_provider_failure(monkeypatch, path):
    db = MarketDB()
    LOOKUPS[path](monkeypatch, db, vendor=None, bhavcopy=Resolver(CAP))
    assert db.open_types() == {"market_data_fetch_failed", *UNRELATED}


@pytest.mark.parametrize("path", LOOKUPS)
def test_a_stored_cap_proves_nothing(monkeypatch, path):
    db = MarketDB(cached=(CAP, 100.0, "bhavcopy"))
    LOOKUPS[path](monkeypatch, db, vendor=None, bhavcopy=Resolver(None, None))
    assert db.open_types() == {*quality.PRIMARY_LOOKUP_DISPROVES, *UNRELATED}


@pytest.mark.parametrize("path", LOOKUPS)
def test_bhavcopy_price_with_an_older_stored_cap_proves_nothing(monkeypatch, path):
    db = MarketDB()
    # Only the "any date" fallback finds a cap: the Bhavcopy returned a price alone.
    db.get_cached_market_data = lambda symbol, as_of=None: (CAP, 90.0, "bhavcopy") if as_of is None else None

    cap, _, _ = LOOKUPS[path](monkeypatch, db, vendor=None, bhavcopy=Resolver(None, 100.0))

    assert cap == CAP
    assert db.open_types() == {*quality.PRIMARY_LOOKUP_DISPROVES, *UNRELATED}

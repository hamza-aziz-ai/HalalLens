"""The shared publication overlay (D-027) against a real, disposable PostgreSQL.

Opt-in like tests/test_auth_postgres.py: skipped unless HALALLENS_TEST_PG_DSN
points at a throwaway database (the test drops and recreates the public schema
from database/schema.sql). Proves what the in-memory fake cannot: the SQL runs,
the per-filing advisory lock serialises a publication against a concurrently
recorded blocker (never a conclusive row next to an open issue), and a failure
mid-publication rolls the whole transaction back.
"""

import os
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

import pytest

DSN = os.getenv("HALALLENS_TEST_PG_DSN")
pytestmark = pytest.mark.skipif(not DSN, reason="HALALLENS_TEST_PG_DSN not set (disposable Postgres only)")

ROOT = Path(__file__).resolve().parents[1]
FILING = datetime(2024, 6, 30, tzinfo=timezone.utc)
ENGINE = dict(verdict="compliant", is_compliant=True, summary="All configured financial checks passed.")


@pytest.fixture()
def db():
    import psycopg2
    from psycopg2.extras import RealDictCursor

    from database.database_manager import BSEDatabaseManager

    admin = psycopg2.connect(DSN)
    admin.autocommit = True
    with admin.cursor() as cur:
        cur.execute("DROP SCHEMA public CASCADE; CREATE SCHEMA public;")
        cur.execute((ROOT / "database/schema.sql").read_text(encoding="utf-8"))
        cur.execute(
            "INSERT INTO announcements (symbol, filing_date, raw_json) VALUES ('TCS', %s, '{}')",
            (FILING,),
        )

    @contextmanager
    def get_connection():
        conn = psycopg2.connect(DSN, cursor_factory=RealDictCursor)
        try:
            yield conn
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    manager = BSEDatabaseManager.__new__(BSEDatabaseManager)  # no pool, no startup DDL
    manager.get_connection = get_connection
    yield manager, admin
    admin.close()


def _publish(manager, anomalies=(), symbol="TCS", **overrides):
    kwargs = dict(
        symbol=symbol,
        filing_date=FILING,
        ratios={"debt_to_market_cap": {"value": 0.1}},
        anomalies=list(anomalies),
        narration_source="test",
        market_cap_used=400_000_000,
        trailing_cap_used=None,
        market_data_provider="test",
        **ENGINE,
    )
    kwargs.update(overrides)
    return manager.publish_filing_evaluation(**kwargs)


def _evaluation(admin):
    with admin.cursor() as cur:
        cur.execute(
            "SELECT verdict, is_compliant, summary, evaluated_at FROM filing_evaluations WHERE symbol = 'TCS'"
        )
        return cur.fetchone()


def _issues(admin, open_only=True):
    with admin.cursor() as cur:
        cur.execute(
            "SELECT issue_type, details, created_at FROM data_quality_issues WHERE symbol = 'TCS'"
            + (" AND resolved_at IS NULL" if open_only else "")
            + " ORDER BY issue_type"
        )
        return cur.fetchall()


def test_clean_publication_stores_the_engine_pair(db):
    manager, admin = db

    published = _publish(manager)

    assert (published["verdict"], published["is_compliant"]) == ("compliant", True)
    assert _evaluation(admin)[:2] == ("compliant", True)


def test_any_open_issue_masks_and_publication_resolves_nothing_else(db):
    manager, admin = db
    manager.record_quality_issue("TCS", FILING, "some-future-type", "open")

    published = _publish(manager)

    assert (published["verdict"], published["is_compliant"]) == ("needs-review", None)
    assert _evaluation(admin)[:2] == ("needs-review", None)
    assert [row[0] for row in _issues(admin)] == ["some-future-type"]


def test_anomalies_combine_into_one_row_without_timestamp_churn(db):
    manager, admin = db

    _publish(manager, anomalies=["first anomaly.", "second anomaly."])
    first = _issues(admin)
    _publish(manager, anomalies=["first anomaly.", "second anomaly."])

    assert first == _issues(admin)  # identical: no rewrite, created_at kept
    assert [(t, d) for t, d, _ in first] == [("ratio_anomaly", "first anomaly. second anomaly.")]
    assert _evaluation(admin)[:3] == ("needs-review", None, "Flagged for manual review due to anomalous ratios.")


def test_a_clean_evaluation_resolves_only_the_detector_row(db):
    manager, admin = db
    _publish(manager, anomalies=["anomaly."])
    manager.record_quality_issue("TCS", FILING, "governance_override", "override")

    _publish(manager)

    assert [row[0] for row in _issues(admin)] == ["governance_override"]
    assert _evaluation(admin)[:2] == ("needs-review", None)


def test_recording_a_blocker_downgrades_the_published_row_and_keeps_evaluated_at(db):
    manager, admin = db
    _publish(manager)
    evaluated_at = _evaluation(admin)[3]

    manager.record_quality_issue("TCS", FILING, "market-data-missing", "missing")

    assert _evaluation(admin) == (
        "needs-review",
        None,
        "Flagged for manual review: unresolved quality issues remain.",
        evaluated_at,
    )


def test_resolution_alone_keeps_needs_review_until_a_new_publication(db):
    manager, admin = db
    manager.record_quality_issue("TCS", FILING, "governance_override", "override")
    _publish(manager)

    manager.resolve_quality_issues("TCS", FILING, ["governance_override"])
    assert _evaluation(admin)[:2] == ("needs-review", None)

    _publish(manager)
    assert _evaluation(admin)[:2] == ("compliant", True)


def test_a_stale_preview_is_rejected_and_rolled_back(db):
    from evaluation.quality import StalePublication

    manager, admin = db
    _publish(manager)
    before = _evaluation(admin)
    expect = {"evaluated_at": before[3], "verdict": "compliant", "is_compliant": True, "issue_types": ()}
    manager.record_quality_issue("TCS", FILING, "governance_override", "arrived after the preview")

    with pytest.raises(StalePublication):
        _publish(manager, anomalies=["new anomaly."], expect=expect)

    assert _evaluation(admin)[0] == "needs-review"  # the downgrade, not the preview
    assert [row[0] for row in _issues(admin)] == ["governance_override"]  # anomaly row rolled back


def test_a_failure_after_the_issue_write_rolls_everything_back(db):
    manager, admin = db

    # No announcement for this symbol: the evaluation insert fails on its
    # foreign key after the anomaly row was written in the same transaction.
    with pytest.raises(Exception):
        _publish(manager, anomalies=["anomaly."], symbol="NOFILING")

    with admin.cursor() as cur:
        cur.execute("SELECT count(*) FROM data_quality_issues WHERE symbol = 'NOFILING'")
        assert cur.fetchone()[0] == 0


def test_a_blocker_recorded_during_a_publication_never_leaves_a_conclusive_row(db, monkeypatch):
    """The race the advisory lock closes.

    The publication reads "no open issues" and pauses before its upsert; a
    blocker is recorded meanwhile. Without the lock the blocker commits first
    (its downgrade finds no row yet), then the publication writes a conclusive
    row next to an open issue. With the lock the blocker waits, then downgrades.
    """

    from evaluation import quality

    manager, admin = db
    read_done, blocker_done = threading.Event(), threading.Event()
    real_reconcile = quality.reconcile

    def paused_reconcile(open_issues, anomalies):
        result = real_reconcile(open_issues, anomalies)
        if threading.current_thread().name == "publisher":
            read_done.set()
            blocker_done.wait(timeout=2)  # with the lock the blocker cannot finish
        return result

    monkeypatch.setattr(quality, "reconcile", paused_reconcile)
    errors = []

    def publisher():
        try:
            _publish(manager)
        except Exception as exc:  # pragma: no cover - surfaced below
            errors.append(exc)

    def blocker():
        try:
            read_done.wait(timeout=5)
            manager.record_quality_issue("TCS", FILING, "market-data-missing", "recorded mid-publication")
            blocker_done.set()
        except Exception as exc:  # pragma: no cover - surfaced below
            errors.append(exc)

    threads = [threading.Thread(target=publisher, name="publisher"), threading.Thread(target=blocker)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=15)

    assert not errors
    assert [row[0] for row in _issues(admin)] == ["market-data-missing"]
    assert _evaluation(admin)[:2] == ("needs-review", None)

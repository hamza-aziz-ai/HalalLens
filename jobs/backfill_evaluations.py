#!/usr/bin/env python3
"""Backfill filing_evaluations for historical snapshots."""

from __future__ import annotations

import argparse
import csv
import logging
import os
from dataclasses import asdict
from datetime import datetime
from typing import Dict, Optional, List, Tuple
from collections import defaultdict

from database import BSEDatabaseManager
from evaluation import quality
from market_data import (
    BhavcopyMarketResolver,
    fetch_indian_financial_snapshot,
    indian_api_enabled,
)
from ratio_engine import FinancialSnapshotInput, MarketDataInput, RatioEngine, build_summary
from ratio_engine.amounts import coerce_amount
from config.logging_config import configure_logging
from config import INDIAN_API_OVERRIDE_TOLERANCE

logger = logging.getLogger("backfill")
engine = RatioEngine()
bhavcopy_resolver = BhavcopyMarketResolver()
FAILED_MARKET_LOOKUPS: Dict[str, int] = defaultdict(int)
MARKET_FAILURE_THRESHOLD = 3
MARKET_CACHE: Dict[str, Tuple[Optional[float], Optional[float], Optional[str]]] = {}
STRUCTURED_FIELDS = {
    "accounts_receivable": "accounts_receivable",
    "liquid_assets": "liquid_assets",
    "non_permissible_income": "non_halal_income",
    "non_halal_income": "non_halal_income",
}


def _needs_override(current: Optional[float], candidate: Optional[float]) -> bool:
    if current is None or candidate is None:
        return False
    baseline = max(abs(current), 1.0)
    delta = abs(candidate - current) / baseline
    return delta >= INDIAN_API_OVERRIDE_TOLERANCE


def _coerce_float(value) -> Optional[float]:
    return coerce_amount(value)


def _snapshot_from_record(record: Dict) -> Optional[FinancialSnapshotInput]:
    filing_date = record.get("filing_date")
    symbol = record.get("symbol")
    if not symbol or not filing_date:
        return None
    return FinancialSnapshotInput(
        symbol=str(symbol).strip().upper(),
        filing_date=filing_date,
        total_debt=_coerce_float(record.get("total_debt")),
        cash_equiv=_coerce_float(record.get("cash_equiv")),
        revenue=_coerce_float(record.get("revenue")),
        interest_income=_coerce_float(record.get("interest_income")),
        dividend_income=_coerce_float(record.get("dividend_income")),
        non_permissible_income=_coerce_float(record.get("non_halal_income")),
        accounts_receivable=_coerce_float(record.get("accounts_receivable")),
        liquid_assets=_coerce_float(record.get("liquid_assets")),
    )


def _normalize_candidate(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    token = value.strip().upper()
    if not token:
        return None
    for suffix in (".BO", ".NS"):
        if token.endswith(suffix):
            token = token[: -len(suffix)]
    return token or None


def _indian_api_candidates(symbol: str, db: BSEDatabaseManager) -> List[str]:
    alias = db.get_symbol_alias(symbol)
    code = db.get_symbol_code(symbol)
    candidates: List[str] = []
    for candidate in (symbol, alias, code):
        cleaned = _normalize_candidate(candidate)
        if cleaned and cleaned not in candidates:
            candidates.append(cleaned)
    return candidates or ([symbol.strip().upper()] if symbol.strip() else [])


def _enrich_snapshot_with_indian_api(
    snapshot: FinancialSnapshotInput, db: BSEDatabaseManager
) -> None:
    if not indian_api_enabled():
        return
    fields = [
        "total_debt",
        "cash_equiv",
        "revenue",
        "interest_income",
        "dividend_income",
        "accounts_receivable",
        "liquid_assets",
        "non_permissible_income",
        "non_halal_income",
    ]
    if all(getattr(snapshot, field, None) is not None for field in fields):
        return

    candidates = _indian_api_candidates(snapshot.symbol, db)
    indian_snapshot = None
    for candidate in candidates:
        indian_snapshot = fetch_indian_financial_snapshot(
            candidate, target_date=snapshot.filing_date
        )
        if indian_snapshot:
            break
    if not indian_snapshot:
        return

    metrics = indian_snapshot.metrics
    overrides: Dict[str, float] = {}
    for field in fields:
        current = getattr(snapshot, field, None)
        if current is not None:
            continue
        key = "non_halal_income" if field in (
            "non_permissible_income",
            "non_halal_income",
        ) else field
        value = metrics.get(key)
        if value is not None:
            setattr(snapshot, field, value)
            if field == "non_permissible_income":
                snapshot.non_halal_income = value
    for field, column in STRUCTURED_FIELDS.items():
        current = getattr(snapshot, field, None)
        candidate = metrics.get(column)
        if field == "non_permissible_income" and candidate is None:
            candidate = metrics.get("non_halal_income")
        if not _needs_override(current, candidate):
            continue
        setattr(snapshot, field, candidate)
        if field == "non_permissible_income":
            snapshot.non_halal_income = candidate
        overrides[column] = candidate

    if overrides:
        reason = (
            "Structured governance metrics from Indian API (>{:.0%} delta)"
        ).format(INDIAN_API_OVERRIDE_TOLERANCE)
        try:
            db.upsert_governance_override(
                symbol=snapshot.symbol,
                filing_date=snapshot.filing_date,
                accounts_receivable=overrides.get("accounts_receivable"),
                liquid_assets=overrides.get("liquid_assets"),
                non_halal_income=overrides.get("non_halal_income"),
                governance_notes="Synchronized with Indian API structured data",
                reviewer="system",
                reason=reason,
                source="indianapi",
            )
            db.record_quality_issue(
                snapshot.symbol,
                snapshot.filing_date,
                "governance_override",
                f"Structured data override applied for {', '.join(overrides.keys())}",
            )
        except Exception as exc:  # pragma: no cover - defensive logging
            logger.debug(
                "Failed persisting Indian API override for %s: %s",
                snapshot.symbol,
                exc,
            )


def _clear_market_failure(
    symbol: str,
    filing_date: datetime,
    db: BSEDatabaseManager,
    disproved: Tuple[str, ...] = (),
) -> None:
    """Reset the process-local counter; resolve only the issue types the lookup disproved.

    A stored or cached cap disproves nothing (empty `disproved`); governance and
    anomaly issues are never resolved here. A failed resolve leaves the issue
    open, which can only block.
    """

    FAILED_MARKET_LOOKUPS.pop(symbol, None)
    if not disproved:
        return
    try:
        db.resolve_quality_issues(symbol, filing_date, issue_types=list(disproved))
    except Exception as exc:  # pragma: no cover
        logger.debug("Failed clearing market-data issue for %s: %s", symbol, exc)


def _record_market_failure(symbol: str, filing_date: datetime, db: BSEDatabaseManager) -> None:
    count = FAILED_MARKET_LOOKUPS[symbol] + 1
    FAILED_MARKET_LOOKUPS[symbol] = count
    if count >= MARKET_FAILURE_THRESHOLD:
        details = (
            f"Market data unavailable after {count} attempts "
            "(Indian API and Bhavcopy)."
        )
        logger.warning("%s market data unavailable after %d attempts", symbol, count)
        try:
            db.record_quality_issue(symbol, filing_date, "market-data-missing", details)
        except Exception as exc:  # pragma: no cover
            logger.debug("Failed recording market-data issue for %s: %s", symbol, exc)


def _lookup_market_data(
    symbol: str, filing_date: datetime, db: BSEDatabaseManager
) -> Tuple[Optional[float], Optional[float], Optional[str]]:
    cache_key = symbol.strip().upper()
    cached = MARKET_CACHE.get(cache_key)
    if cached and any(value is not None for value in cached[:2]):
        _clear_market_failure(cache_key, filing_date, db)
        return cached

    db_snapshot = db.get_cached_market_data(cache_key, filing_date)
    if db_snapshot and any(value is not None for value in db_snapshot[:2]):
        MARKET_CACHE[cache_key] = db_snapshot
        _clear_market_failure(cache_key, filing_date, db)
        cap, price, provider = db_snapshot
        return cap, price, provider or "cache"

    if indian_api_enabled():
        for candidate in _indian_api_candidates(cache_key, db):
            snapshot = fetch_indian_financial_snapshot(
                candidate, target_date=filing_date
            )
            if not snapshot:
                continue
            if snapshot.market_cap is None and snapshot.share_price is None:
                continue
            db.insert_market_snapshot(
                symbol=cache_key,
                market_cap=snapshot.market_cap,
                share_price=snapshot.share_price,
                provider="indianapi",
            )
            MARKET_CACHE[cache_key] = (
                snapshot.market_cap,
                snapshot.share_price,
                "indianapi",
            )
            _clear_market_failure(
                cache_key,
                filing_date,
                db,
                quality.PRIMARY_LOOKUP_DISPROVES if snapshot.market_cap is not None else (),
            )
            return snapshot.market_cap, snapshot.share_price, "indianapi"

    fallback_cap, fallback_price = bhavcopy_resolver.resolve(symbol, filing_date)
    if fallback_cap is not None or fallback_price is not None:
        # Only a cap the Bhavcopy itself returned proves anything.
        disproved = quality.FALLBACK_LOOKUP_DISPROVES if fallback_cap is not None else ()
        if fallback_cap is None and fallback_price is not None:
            cached_any = db.get_cached_market_data(cache_key)
            cached_cap = cached_any[0] if cached_any else None
            if cached_cap is not None:
                fallback_cap = cached_cap
        db.insert_market_snapshot(
            symbol=cache_key,
            market_cap=fallback_cap,
            share_price=fallback_price,
            provider="bhavcopy",
        )
        MARKET_CACHE[cache_key] = (fallback_cap, fallback_price, "bhavcopy")
        _clear_market_failure(cache_key, filing_date, db, disproved)
        return fallback_cap, fallback_price, "bhavcopy"

    _record_market_failure(cache_key, filing_date, db)
    return None, None, None


def main(limit: int = 500) -> None:
    configure_logging("backfill")

    db = BSEDatabaseManager()

    try:
        rows = db.get_recent_filings(limit=limit)
        logger.info("Backfilling %d filings", len(rows))

        count = 0
        for record in rows:
            # `has_ratios` is projected by get_recent_filings; the query never
            # returns the ratios JSON itself, so testing "ratios" never skipped.
            if record.get("has_ratios"):
                continue

            snapshot = _snapshot_from_record(record)
            if not snapshot:
                continue

            _enrich_snapshot_with_indian_api(snapshot, db)
            market_cap = share_price = None
            provider = None
            filing_dt = snapshot.filing_date
            if isinstance(filing_dt, str):
                try:
                    filing_dt = db.parse_iso_datetime(filing_dt)
                except Exception:
                    filing_dt = datetime.fromisoformat(filing_dt)

            market_cap, share_price, provider = _lookup_market_data(
                snapshot.symbol, filing_dt, db
            )

            if market_cap is None:
                _record_market_failure(snapshot.symbol, filing_dt, db)
                continue

            evaluation = engine.evaluate(
                snapshot,
                MarketDataInput(
                    market_cap=market_cap,
                    share_price=share_price,
                    provider=provider or "manual",
                ),
            )
            quality.publish_evaluation(
                db,
                snapshot,
                evaluation,
                filing_date=filing_dt,
                narration_source="backfill",
                market_cap_used=market_cap,
                trailing_cap_used=None,
                market_data_provider=provider,
            )
            count += 1

        logger.info("Backfill completed: %d evaluations stored", count)
    finally:
        db.close()


# --- Recompute stored evaluations (repair after a ratio-logic change) --------
# The plain backfill above only fills filings without an evaluation (and only
# within its window: get_recent_filings returns evaluated rows first, so a small
# --limit can be used up before any unevaluated row; jobs.precompute_evaluations
# is the scheduled path for those). This mode re-evaluates rows that already HAVE
# non-empty ratios, from the CURRENT stored inputs: the stored snapshot, current
# governance overrides (accounts_receivable, liquid_assets, non_halal_income) and
# the stored market caps, passed to the engine unchanged. It never calls the
# vendor or Bhavcopy. It is not a replay of an earlier dry run: a --write run
# re-reads the database. Dry run by default.
#
# Publication is simulated exactly (D-027): the anomaly detector runs, the
# detector-owned `ratio_anomaly` row is reconciled in memory, and every open
# issue masks the engine's pair as needs-review. A --write applies each row
# through publish_filing_evaluation only if the filing still matches its
# preview: inputs re-read just before the write, then the stored evaluation's
# timestamp, the open issue types and the published pair checked under the
# filing's lock. A stale row is skipped and logged, never written.

INPUT_FIELDS = (
    "total_debt",
    "cash_equiv",
    "revenue",
    "non_halal_income",
    "interest_income",
    "dividend_income",
    "accounts_receivable",
    "liquid_assets",
    "market_cap_used",
    "trailing_cap_used",
    "market_data_provider",
)
REPORT_FIELDS = (
    "symbol",
    "filing_date",
    "status",
    "old_verdict",
    "old_is_compliant",
    "new_verdict",
    "new_is_compliant",
    "changed",
    "missing_inputs",
    "quality_issues",
    "ratio_anomaly",
    *INPUT_FIELDS,
)


def _csv_safe(value):
    """Neutralise spreadsheet formulas in text cells (=, +, -, @, tab, CR)."""

    if isinstance(value, str) and value[:1] in ("=", "+", "-", "@", "\t", "\r"):
        return "'" + value
    return value


def _recompute_one(record: Dict, db: BSEDatabaseManager) -> Tuple[Dict, Optional[Dict]]:
    """Return (report row, publish kwargs or None) for one stored evaluation."""

    row = {
        "symbol": record.get("symbol"),
        "filing_date": record.get("filing_date"),
        "old_verdict": record.get("verdict"),
        "old_is_compliant": record.get("is_compliant"),
        **{field: record.get(field) for field in INPUT_FIELDS},  # the inputs actually used
    }
    snapshot = _snapshot_from_record(record)
    if not snapshot:
        row["status"] = "skipped: no snapshot"
        return row, None
    filing_dt = snapshot.filing_date
    if isinstance(filing_dt, str):
        try:
            filing_dt = db.parse_iso_datetime(filing_dt)
        except Exception:
            filing_dt = datetime.fromisoformat(filing_dt)

    # Passed to the engine unchanged: coercing here would turn an invalid stored
    # primary cap (NaN, negative) into "absent" and let the trailing cap rescue it.
    market_cap = record.get("market_cap_used")
    trailing_cap = record.get("trailing_cap_used")
    if market_cap is None and trailing_cap is None:
        # Fetching a cap now would mix new market data into the comparison.
        row["status"] = "skipped: no stored market cap"
        return row, None

    provider = record.get("market_data_provider")
    evaluation = engine.evaluate(
        snapshot,
        MarketDataInput(
            market_cap=market_cap,
            trailing_market_cap=trailing_cap,
            provider=provider or "manual",
        ),
    )
    # The same publication the --write would do, simulated without writes.
    anomalies = quality.detect_ratio_anomalies(snapshot, evaluation)
    open_issues = db.get_open_quality_issues(snapshot.symbol, filing_dt)
    issues = quality.reconcile(open_issues, anomalies)
    verdict, is_compliant, _ = quality.publish(
        evaluation.verdict, evaluation.is_compliant, None, issues, anomalies
    )
    stored = [i.get("details") for i in open_issues if i["issue_type"] == quality.RATIO_ANOMALY]
    detail = quality.combined_anomaly(anomalies)
    if detail and not stored:
        anomaly_change = "opened"
    elif detail and stored[0] != detail:
        anomaly_change = "updated"
    elif not detail and stored:
        anomaly_change = "resolved"
    else:
        anomaly_change = ""

    row.update(
        status="ok",
        new_verdict=verdict,
        new_is_compliant=is_compliant,
        changed=(verdict, is_compliant) != (row["old_verdict"], row["old_is_compliant"]),
        missing_inputs=";".join(
            f"{name}={reason}" for name, reason in sorted(evaluation.missing_inputs.items())
        ),
        quality_issues=";".join(quality.issue_types(issues)),
        ratio_anomaly=anomaly_change,
    )
    publish = dict(
        symbol=snapshot.symbol,
        filing_date=filing_dt,
        verdict=evaluation.verdict,
        is_compliant=evaluation.is_compliant,
        summary=build_summary(evaluation),
        ratios={name: asdict(comp) for name, comp in evaluation.ratios.items()},
        anomalies=anomalies,
        narration_source="recompute",
        market_cap_used=market_cap,
        trailing_cap_used=trailing_cap,
        market_data_provider=provider,
        expect={
            "evaluated_at": record.get("evaluation_updated_at"),
            "verdict": verdict,
            "is_compliant": is_compliant,
            "issue_types": quality.issue_types(issues),
        },
    )
    return row, publish


def _apply_preview(row: Dict, publish: Dict, db: BSEDatabaseManager) -> bool:
    """Write one previewed row if the filing still matches its preview."""

    # ponytail: inputs are re-read just before the locked write, not under the
    # lock; a snapshot re-parsed in that millisecond gap would be evaluated from
    # the older inputs and not picked up again (evaluated_at ends up newer).
    # Move the input check into publish_filing_evaluation if that ever matters.
    fresh = db.get_filing(publish["symbol"], publish["filing_date"])
    if (
        not fresh
        or not fresh.get("ratios")
        or any(fresh.get(field) != row.get(field) for field in INPUT_FIELDS)
    ):
        row["status"] = "stale: inputs changed since the preview"
    else:
        try:
            db.publish_filing_evaluation(**publish)
            return True
        except quality.StalePublication as exc:
            row["status"] = f"stale: {exc}"
    logger.warning("Recompute skipped %s@%s: %s", row["symbol"], row["filing_date"], row["status"])
    return False


def recompute(limit: int = 500, write: bool = False, report: Optional[str] = None) -> List[Dict]:
    """Re-evaluate the most recent `limit` stored evaluations.

    Dry run unless `write`; `write` requires `report`, and the report is created
    (never overwritten) BEFORE any database write. The CSV is evidence, not a
    backup: restore from a `pg_dump` of filing_evaluations. Each publication
    commits on its own, so a failure mid-run leaves earlier rows written. A row
    whose filing changed since the preview is skipped and logged as stale; the
    CSV still shows its preview, so check the log for skipped rows.
    """

    if limit < 1:
        raise ValueError("--limit must be at least 1")
    if write and not report:
        raise ValueError("--write needs --report: the before/after CSV must exist first")
    if report and os.path.exists(report):
        raise FileExistsError(f"{report} exists; keep earlier evidence and pick a new name")

    db = BSEDatabaseManager()
    try:
        results = [
            _recompute_one(record, db)
            for record in db.get_recent_filings(limit=limit)
            if record.get("has_ratios")  # no ratios yet: that is the plain backfill's job
        ]
        rows = [row for row, _ in results]
        if report:
            with open(report, "x", newline="", encoding="utf-8") as handle:
                writer = csv.DictWriter(handle, fieldnames=REPORT_FIELDS, extrasaction="ignore")
                writer.writeheader()
                writer.writerows({k: _csv_safe(v) for k, v in row.items()} for row in rows)
        written = 0
        if write:
            for row, publish in results:
                if publish is not None and _apply_preview(row, publish, db):
                    written += 1
        transitions: Dict[str, int] = defaultdict(int)
        for row in rows:
            transitions[f"{row.get('old_verdict')} -> {row.get('new_verdict', row['status'])}"] += 1
        logger.info(
            "Recompute %s: %d rows, %d written; %s",
            "write" if write else "dry run",
            len(rows),
            written,
            dict(transitions),
        )
        return rows
    finally:
        db.close()


def _parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--limit",
        type=int,
        default=500,
        help="Most recent filings to consider, evaluated rows first (default 500).",
    )
    parser.add_argument(
        "--recompute",
        action="store_true",
        help="Re-evaluate filings that already have an evaluation, from stored inputs only.",
    )
    parser.add_argument("--write", action="store_true", help="With --recompute: write the new verdicts.")
    parser.add_argument("--report", help="With --recompute: before/after CSV path.")
    args = parser.parse_args(argv)
    if (args.write or args.report) and not args.recompute:
        parser.error("--write and --report only apply with --recompute")
    if args.write and not args.report:
        parser.error("--write needs --report: the before/after CSV must exist first")
    if args.limit < 1:
        parser.error("--limit must be at least 1")
    return args


if __name__ == "__main__":
    _args = _parse_args()
    if _args.recompute:
        configure_logging("backfill")
        recompute(limit=_args.limit, write=_args.write, report=_args.report)
    else:
        main(limit=_args.limit)

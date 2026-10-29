#!/usr/bin/env python3
"""CLI entry-point to run the BSE ingestion ƒ+' ETL ƒ+' persistence flow."""

from __future__ import annotations

import argparse
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from collections import defaultdict


from crawler import BSEAnnouncementsFetcher
from database import BSEDatabaseManager
from etl import FinancialDataProcessor
from evaluation import quality
from market_data import (
    BhavcopyMarketResolver,
    fetch_indian_financial_snapshot,
    indian_api_enabled,
)
from ratio_engine import FinancialSnapshotInput, MarketDataInput, RatioEngine
from ratio_engine.amounts import coerce_amount
from config.logging_config import configure_logging as setup_file_logging
from config import INDIAN_API_OVERRIDE_TOLERANCE


logger = logging.getLogger("ingestion")
ratio_engine = RatioEngine()
MARKET_CACHE: Dict[str, Tuple[Optional[float], Optional[float], Optional[str]]] = {}
FAILED_MARKET_LOOKUPS: Dict[str, int] = defaultdict(int)
MARKET_FAILURE_THRESHOLD = 3
bhavcopy_resolver = BhavcopyMarketResolver()
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


def _normalize_bse_date(date_str: str) -> str:
    """Return YYYYMMDD string accepted by the BSE API."""

    cleaned = date_str.replace("-", "").strip()
    if len(cleaned) != 8 or not cleaned.isdigit():
        msg = "Date must be in YYYYMMDD or YYYY-MM-DD format"
        raise argparse.ArgumentTypeError(msg)
    return cleaned


def parse_args() -> argparse.Namespace:
    """Parse CLI arguments for the ingestion job."""

    today = datetime.now(timezone.utc).date()
    default_start = (today - timedelta(days=1)).strftime("%Y%m%d")
    default_end = today.strftime("%Y%m%d")

    parser = argparse.ArgumentParser(
        description="Fetch BSE announcements, extract financial data, and persist snapshots."
    )
    parser.add_argument(
        "--from-date",
        default=default_start,
        type=_normalize_bse_date,
        help="Start date (YYYYMMDD or YYYY-MM-DD). Defaults to yesterday.",
    )
    parser.add_argument(
        "--to-date",
        default=default_end,
        type=_normalize_bse_date,
        help="End date (YYYYMMDD or YYYY-MM-DD). Defaults to today.",
    )
    parser.add_argument(
        "--category",
        default="-1",
        help="Optional BSE category filter (default: all).",
    )
    parser.add_argument(
        "--cache-dir",
        default="./cache",
        type=Path,
        help="Directory for cached payloads and PDFs.",
    )
    parser.add_argument(
        "--download-dir",
        default="./downloads",
        type=Path,
        help="Directory for temporary downloads.",
    )
    parser.add_argument(
        "--save-cache",
        action="store_true",
        help="Persist fetched announcements as JSON in cache_dir for auditing.",
    )
    return parser.parse_args()


def _persist_announcements(
    db: BSEDatabaseManager, announcements: List[dict]
) -> int:
    """Store announcements via the database manager, guarding empty payloads."""

    if not announcements:
        return 0
    return db.insert_announcements(announcements)


def _persist_financial_snapshots(
    db: BSEDatabaseManager, processor: FinancialDataProcessor, snapshots: List[dict]
) -> int:
    """Insert extracted financial snapshots into the database."""

    if not snapshots:
        return 0
    db.insert_financial_snapshots(snapshots)
    processor.save_financial_data(snapshots)
    return len(snapshots)


def _coerce_float(value) -> Optional[float]:
    return coerce_amount(value)


def _snapshot_from_record(
    record: dict, db: BSEDatabaseManager
) -> Optional[FinancialSnapshotInput]:
    extracted = record.get("extracted_data") or {}
    filing_date = record.get("date") or record.get("filing_date")
    symbol = str(record.get("symbol") or "").strip()

    if not symbol or not filing_date:
        return None

    if isinstance(filing_date, str):
        filing_date = db.parse_iso_datetime(filing_date)

    snapshot = FinancialSnapshotInput(
        symbol=symbol,
        filing_date=filing_date,
        total_debt=_coerce_float(extracted.get("total_debt")),
        cash_equiv=_coerce_float(extracted.get("cash_equiv")),
        revenue=_coerce_float(extracted.get("revenue")),
        interest_income=_coerce_float(extracted.get("interest_income")),
        dividend_income=_coerce_float(extracted.get("dividend_income")),
        non_permissible_income=_coerce_float(
            extracted.get("non_permissible_income", extracted.get("non_halal_income"))
        ),
        accounts_receivable=_coerce_float(extracted.get("accounts_receivable")),
        liquid_assets=_coerce_float(extracted.get("liquid_assets")),
    )

    has_metrics = any(
        value is not None
        for value in (
            snapshot.total_debt,
            snapshot.cash_equiv,
            snapshot.revenue,
            snapshot.interest_income,
            snapshot.dividend_income,
            snapshot.accounts_receivable,
            snapshot.liquid_assets,
        )
    )
    if not has_metrics:
        return None
    return snapshot


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
        key = "non_halal_income" if field in (
            "non_permissible_income",
            "non_halal_income",
        ) else field
        value = metrics.get(key)
        if value is not None:
            if current is None:
                setattr(snapshot, field, value)
                if field == "non_permissible_income":
                    snapshot.non_halal_income = value
                continue
            target_column = STRUCTURED_FIELDS.get(field)
            if target_column and _needs_override(current, value):
                setattr(snapshot, field, value)
                if field == "non_permissible_income":
                    snapshot.non_halal_income = value
                overrides[target_column] = value
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
            logger.debug("Failed to persist Indian API override for %s: %s", snapshot.symbol, exc)


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
    except Exception as exc:  # pragma: no cover - defensive
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
            logger.debug("Failed to record market-data issue for %s: %s", symbol, exc)

def _lookup_market_data(
    symbol: str,
    as_of: datetime,
    db: BSEDatabaseManager,
) -> Tuple[Optional[float], Optional[float], Optional[str]]:
    cache_key = symbol.strip().upper()
    cached = MARKET_CACHE.get(cache_key)
    if cached and any(value is not None for value in cached[:2]):
        _clear_market_failure(cache_key, as_of, db)
        return cached

    db_snapshot = db.get_cached_market_data(cache_key, as_of)
    if db_snapshot:
        MARKET_CACHE[cache_key] = db_snapshot
        _clear_market_failure(cache_key, as_of, db)
        cap, price, provider = db_snapshot
        return cap, price, provider or "cache"

    if indian_api_enabled():
        for candidate in _indian_api_candidates(cache_key, db):
            snapshot = fetch_indian_financial_snapshot(candidate, target_date=as_of)
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
                as_of,
                db,
                quality.PRIMARY_LOOKUP_DISPROVES if snapshot.market_cap is not None else (),
            )
            return snapshot.market_cap, snapshot.share_price, "indianapi"

    fallback_cap, fallback_price = bhavcopy_resolver.resolve(symbol, as_of)
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
        _clear_market_failure(cache_key, as_of, db, disproved)
        return fallback_cap, fallback_price, "bhavcopy"
    _record_market_failure(cache_key, as_of, db)
    return None, None, None


def _evaluate_and_store(
    db: BSEDatabaseManager,
    snapshots: List[dict],
) -> int:
    """Compute ratio evaluations and persist them."""

    if not snapshots:
        return 0

    evaluations = 0
    for record in snapshots:
        snapshot_input = _snapshot_from_record(record, db)
        if not snapshot_input:
            continue

        _enrich_snapshot_with_indian_api(snapshot_input, db)
        market_cap, share_price, provider = _lookup_market_data(
            snapshot_input.symbol,
            snapshot_input.filing_date,
            db,
        )
        if market_cap is None:
            logger.debug(
                "Skipping evaluation for %s (market data unavailable)",
                snapshot_input.symbol,
            )
            continue

        market_input = MarketDataInput(
            market_cap=market_cap,
            share_price=share_price,
            provider=provider or "manual",
        )
        evaluation = ratio_engine.evaluate(snapshot_input, market_input)
        quality.publish_evaluation(
            db,
            snapshot_input,
            evaluation,
            filing_date=evaluation.filing_date,
            narration_source="ingestion",
            market_cap_used=market_cap,
            trailing_cap_used=None,
            market_data_provider=provider,
        )
        evaluations += 1

    return evaluations


def _run_with_args(args: argparse.Namespace) -> Dict[str, int]:
    logger.info("Starting BSE ingestion for %s -> %s", args.from_date, args.to_date)

    fetcher = BSEAnnouncementsFetcher(cache_dir=str(args.cache_dir))
    processor = FinancialDataProcessor(
        download_dir=str(args.download_dir), cache_dir=str(args.cache_dir)
    )
    db_manager = BSEDatabaseManager()
    metrics = {"announcements": 0, "snapshots": 0, "evaluations": 0}

    try:
        announcements = fetcher.get_announcements_paginated(
            args.from_date, args.to_date, category=args.category
        )
        logger.info("Fetched %d raw announcements", len(announcements))

        if args.save_cache and announcements:
            filename = f"bse_announcements_{args.from_date}_{args.to_date}.json"
            fetcher.save_to_cache(announcements, filename)

        inserted = _persist_announcements(db_manager, announcements)
        metrics["announcements"] = inserted
        logger.info("Announcements inserted/updated: %d", inserted)

        financial_data = processor.process_announcements(announcements)
        logger.info("Financial records processed: %d", len(financial_data))

        snapshot_count = _persist_financial_snapshots(
            db_manager, processor, financial_data
        )
        metrics["snapshots"] = snapshot_count
        logger.info("Financial snapshots stored: %d", snapshot_count)

        evaluations = _evaluate_and_store(db_manager, financial_data)
        metrics["evaluations"] = evaluations
        logger.info("Automated evaluations stored: %d", evaluations)

        stats = processor.get_statistics()
        logger.info("Processor stats: %s", stats)
    finally:
        fetcher.close()
        processor.close()
        db_manager.close()
    return metrics


def run_ingestion(
    from_date: Optional[str] = None,
    to_date: Optional[str] = None,
    *,
    category: str = "-1",
    cache_dir: Path | str = Path("./cache"),
    download_dir: Path | str = Path("./downloads"),
    save_cache: bool = False,
    configure_logging: bool = False,
) -> Dict[str, int]:
    """Programmatic entry point for running BSE ingestion."""

    today = datetime.now(timezone.utc).date()
    default_start = (today - timedelta(days=1)).strftime("%Y%m%d")
    default_end = today.strftime("%Y%m%d")

    start = from_date or default_start
    end = to_date or default_end

    args = argparse.Namespace(
        from_date=_normalize_bse_date(start),
        to_date=_normalize_bse_date(end),
        category=category,
        cache_dir=Path(cache_dir),
        download_dir=Path(download_dir),
        save_cache=save_cache,
    )
    if configure_logging:
        setup_file_logging("ingestion")
    return _run_with_args(args)


def main() -> None:
    args = parse_args()
    run_ingestion(
        args.from_date,
        args.to_date,
        category=args.category,
        cache_dir=args.cache_dir,
        download_dir=args.download_dir,
        save_cache=args.save_cache,
        configure_logging=True,
    )


if __name__ == "__main__":
    main()

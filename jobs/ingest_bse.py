#!/usr/bin/env python3
"""CLI entry-point to run the BSE ingestion ƒ+' ETL ƒ+' persistence flow."""

from __future__ import annotations

import argparse
import logging
from dataclasses import asdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Tuple


from crawler import BSEAnnouncementsFetcher
from database import BSEDatabaseManager
from etl import FinancialDataProcessor
from market_data import fetch_yahoo_quote, fetch_tiingo_quote, BhavcopyMarketResolver
from market_data.tickers import build_ticker_candidates, build_tiingo_tickers
from ratio_engine import FinancialSnapshotInput, MarketDataInput, RatioEngine


logger = logging.getLogger("ingestion")
ratio_engine = RatioEngine()
MARKET_CACHE: Dict[str, Tuple[Optional[float], Optional[float]]] = {}
bhavcopy_resolver = BhavcopyMarketResolver()


def _normalize_bse_date(date_str: str) -> str:
    """Return YYYYMMDD string accepted by the BSE API."""

    cleaned = date_str.replace("-", "").strip()
    if len(cleaned) != 8 or not cleaned.isdigit():
        msg = "Date must be in YYYYMMDD or YYYY-MM-DD format"
        raise argparse.ArgumentTypeError(msg)
    return cleaned


def parse_args() -> argparse.Namespace:
    """Parse CLI arguments for the ingestion job."""

    today = datetime.utcnow().date()
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
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    try:
        cleaned = str(value).replace(",", "").strip()
        return float(cleaned) if cleaned else None
    except ValueError:
        return None


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
        non_permissible_income=_coerce_float(extracted.get("non_permissible_income")),
    )

    has_metrics = any(
        value is not None
        for value in (
            snapshot.total_debt,
            snapshot.cash_equiv,
            snapshot.revenue,
            snapshot.interest_income,
            snapshot.dividend_income,
        )
    )
    if not has_metrics:
        return None
    return snapshot

def _lookup_market_data(
    symbol: str,
    as_of: datetime,
    db: BSEDatabaseManager,
) -> Tuple[Optional[float], Optional[float], Optional[str]]:
    cache_key = symbol.strip().upper()
    cached = MARKET_CACHE.get(cache_key)
    if cached and any(value is not None for value in cached):
        return cached[0], cached[1], None

    db_snapshot = db.get_cached_market_data(cache_key, as_of)
    if db_snapshot:
        MARKET_CACHE[cache_key] = db_snapshot
        return db_snapshot[0], db_snapshot[1], None

    alias = db.get_symbol_alias(cache_key)
    tiingo_tickers = build_tiingo_tickers(cache_key, alias)
    for ticker in tiingo_tickers:
        market_cap, share_price = fetch_tiingo_quote(ticker)
        if market_cap is None and share_price is None:
            continue
        MARKET_CACHE[cache_key] = (market_cap, share_price)
        return market_cap, share_price, "tiingo"

    tickers = build_ticker_candidates(cache_key, alias)

    for ticker in tickers:
        market_cap, share_price = fetch_yahoo_quote(
            ticker, backoff_seconds=30, retries=3
        )
        if market_cap is None and share_price is None:
            continue
        MARKET_CACHE[cache_key] = (market_cap, share_price)
        return market_cap, share_price, "yahoo"
    fallback_cap, fallback_price = bhavcopy_resolver.resolve(symbol, as_of)
    if fallback_cap is not None or fallback_price is not None:
        MARKET_CACHE[cache_key] = (fallback_cap, fallback_price)
        return fallback_cap, fallback_price, "bhavcopy"
    return None, None, None


def _derive_verdict(evaluation) -> str:
    has_ratios = any(comp.passed is not None for comp in evaluation.ratios.values())
    if not has_ratios:
        return "insufficient-data"
    return "compliant" if evaluation.is_compliant else "non-compliant"


FRIENDLY_LABELS = {
    "debt_to_market_cap": "Debt to market cap",
    "cash_to_market_cap": "Cash to market cap",
    "non_permissible_income_ratio": "Non-permissible income ratio",
}


def _build_summary(evaluation) -> str:
    failing = [
        FRIENDLY_LABELS.get(name, name)
        for name, comp in evaluation.ratios.items()
        if comp.passed is False
    ]
    if evaluation.is_compliant and not failing:
        return "All computed AAOIFI ratios are within the prescribed thresholds."
    if failing:
        return f"{', '.join(failing)} exceeded AAOIFI thresholds for this filing."
    if evaluation.missing_inputs:
        missing = ", ".join(sorted(evaluation.missing_inputs.keys()))
        return f"Insufficient data to compute all ratios (missing: {missing})."
    return "Ratios could not be computed for this filing."


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

        if provider:
            db.insert_market_snapshot(
                snapshot_input.symbol,
                market_cap,
                share_price,
                provider=provider,
            )

        market_input = MarketDataInput(market_cap=market_cap, share_price=share_price)
        evaluation = ratio_engine.evaluate(snapshot_input, market_input)

        verdict = _derive_verdict(evaluation)
        summary = _build_summary(evaluation)
        ratios_payload = {
            name: asdict(comp) for name, comp in evaluation.ratios.items()
        }

        db.upsert_filing_evaluation(
            symbol=evaluation.symbol,
            filing_date=evaluation.filing_date,
            is_compliant=evaluation.is_compliant
            if verdict != "insufficient-data"
            else None,
            ratios=ratios_payload,
            summary=summary,
            verdict=verdict,
            narration_source="ingestion",
            market_cap_used=market_cap,
            trailing_cap_used=None,
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

    today = datetime.utcnow().date()
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
        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s - %(levelname)s - %(name)s - %(message)s",
        )
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

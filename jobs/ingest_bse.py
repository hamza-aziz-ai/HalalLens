#!/usr/bin/env python3
"""CLI entry-point to run the BSE ingestion ƒ+' ETL ƒ+' persistence flow."""

from __future__ import annotations

import argparse
import logging
from dataclasses import asdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import requests

from crawler import BSEAnnouncementsFetcher
from database import BSEDatabaseManager
from etl import FinancialDataProcessor
from market_data import fetch_yahoo_quote
from ratio_engine import FinancialSnapshotInput, MarketDataInput, RatioEngine


logger = logging.getLogger("ingestion")
ratio_engine = RatioEngine()
MARKET_CACHE: Dict[str, Tuple[Optional[float], Optional[float]]] = {}


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


def _ticker_for_symbol(symbol: str) -> str:
    normalized = (symbol or "").strip().upper()
    if normalized.isdigit():
        return f"{normalized}.BO"
    return f"{normalized}.NS"


def _lookup_market_data(
    symbol: str,
    session: requests.Session,
    as_of: datetime,
    db: BSEDatabaseManager,
) -> Tuple[Optional[float], Optional[float]]:
    cache_key = symbol.strip().upper()
    cached = MARKET_CACHE.get(cache_key)
    if cached and any(value is not None for value in cached):
        return cached

    db_snapshot = db.get_cached_market_data(cache_key, as_of)
    if db_snapshot:
        MARKET_CACHE[cache_key] = db_snapshot
        return db_snapshot

    ticker = _ticker_for_symbol(symbol)
    market_cap, share_price = fetch_yahoo_quote(
        ticker, session=session, backoff_seconds=30, retries=3
    )
    if market_cap is not None or share_price is not None:
        MARKET_CACHE[cache_key] = (market_cap, share_price)
        db.insert_market_snapshot(
            symbol=cache_key,
            market_cap=market_cap,
            share_price=share_price,
            provider="yahoo",
        )
    return market_cap, share_price


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
    market_session: requests.Session,
) -> int:
    """Compute ratio evaluations and persist them."""

    if not snapshots:
        return 0

    evaluations = 0
    for record in snapshots:
        snapshot_input = _snapshot_from_record(record, db)
        if not snapshot_input:
            continue

        market_cap, share_price = _lookup_market_data(
            snapshot_input.symbol,
            market_session,
            snapshot_input.filing_date,
            db,
        )
        if market_cap is None:
            logger.debug(
                "Skipping evaluation for %s (market data unavailable)",
                snapshot_input.symbol,
            )
            continue

        db.insert_market_snapshot(
            snapshot_input.symbol, market_cap, share_price, provider="yahoo"
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


def main() -> None:
    args = parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(levelname)s - %(name)s - %(message)s",
    )

    logger.info(
        "Starting BSE ingestion for %s ƒ+' %s", args.from_date, args.to_date
    )

    fetcher = BSEAnnouncementsFetcher(cache_dir=str(args.cache_dir))
    processor = FinancialDataProcessor(
        download_dir=str(args.download_dir), cache_dir=str(args.cache_dir)
    )
    db_manager = BSEDatabaseManager()
    market_session = requests.Session()

    try:
        announcements = fetcher.get_announcements_paginated(
            args.from_date, args.to_date, category=args.category
        )
        logger.info("Fetched %d raw announcements", len(announcements))

        if args.save_cache and announcements:
            filename = (
                f"bse_announcements_{args.from_date}_{args.to_date}.json"
            )
            fetcher.save_to_cache(announcements, filename)

        inserted = _persist_announcements(db_manager, announcements)
        logger.info("Announcements inserted/updated: %d", inserted)

        financial_data = processor.process_announcements(announcements)
        logger.info(
            "Financial records processed: %d", len(financial_data)
        )

        snapshot_count = _persist_financial_snapshots(
            db_manager, processor, financial_data
        )
        logger.info("Financial snapshots stored: %d", snapshot_count)

        evaluations = _evaluate_and_store(db_manager, financial_data, market_session)
        logger.info("Automated evaluations stored: %d", evaluations)

        stats = processor.get_statistics()
        logger.info("Processor stats: %s", stats)

    finally:
        fetcher.close()
        processor.close()
        market_session.close()
        db_manager.close()


if __name__ == "__main__":
    main()

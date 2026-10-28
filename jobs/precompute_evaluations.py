#!/usr/bin/env python3
"""Precompute filing evaluations for recent filings."""

from __future__ import annotations

import argparse
import logging
from dataclasses import asdict
from datetime import datetime
from typing import Optional

from config.logging_config import configure_logging
from database import BSEDatabaseManager
from jobs.backfill_evaluations import (
    _clear_market_failure,
    _enrich_snapshot_with_indian_api,
    _lookup_market_data,
    _record_market_failure,
    _snapshot_from_record,
    engine,
)
from ratio_engine import MarketDataInput, build_summary

logger = logging.getLogger("evaluation_precompute")


def _normalize_filing_date(value: Optional[datetime], db: BSEDatabaseManager) -> datetime:
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        try:
            return db.parse_iso_datetime(value)
        except Exception:
            return datetime.fromisoformat(value)
    raise ValueError("Missing filing_date for evaluation")


def run_precompute(*, limit: int = 200, lookback_days: int = 365) -> int:
    db = BSEDatabaseManager()
    processed = 0
    try:
        rows = db.get_filings_needing_evaluation(
            limit=limit, lookback_days=lookback_days
        )
        if not rows:
            logger.info("No filings require evaluation within lookback window.")
            return 0
        logger.info("Precomputing %d filings (lookback=%dd)", len(rows), lookback_days)

        for record in rows:
            snapshot = _snapshot_from_record(record)
            if not snapshot:
                continue

            _enrich_snapshot_with_indian_api(snapshot, db)
            filing_dt = _normalize_filing_date(snapshot.filing_date, db)
            market_cap = record.get("market_cap_used")
            trailing_cap = record.get("trailing_cap_used")
            provider = record.get("market_data_provider")
            share_price = None

            if market_cap is None and trailing_cap is None:
                market_cap, share_price, provider = _lookup_market_data(
                    snapshot.symbol, filing_dt, db
                )

            if market_cap is None and trailing_cap is None:
                _record_market_failure(snapshot.symbol, filing_dt, db)
                continue

            _clear_market_failure(snapshot.symbol, filing_dt, db)
            evaluation = engine.evaluate(
                snapshot,
                MarketDataInput(
                    market_cap=market_cap,
                    trailing_market_cap=trailing_cap,
                    share_price=share_price,
                    provider=provider or "manual",
                ),
            )

            ratios_payload = {
                name: asdict(comp) for name, comp in evaluation.ratios.items()
            }
            verdict = evaluation.verdict
            summary = build_summary(evaluation)

            db.upsert_filing_evaluation(
                symbol=snapshot.symbol,
                filing_date=filing_dt,
                is_compliant=evaluation.is_compliant,
                ratios=ratios_payload,
                summary=summary,
                verdict=verdict,
                narration_source="precompute",
                market_cap_used=market_cap,
                trailing_cap_used=trailing_cap,
                market_data_provider=provider,
            )
            processed += 1

        logger.info("Precompute completed: %d evaluations stored", processed)
        return processed
    finally:
        db.close()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Precompute filing evaluations for recent filings.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=200,
        help="Max number of filings to precompute per run.",
    )
    parser.add_argument(
        "--lookback-days",
        type=int,
        default=365,
        help="Only consider filings within the last N days.",
    )
    return parser.parse_args()


def main() -> None:
    configure_logging("evaluation_precompute")
    args = parse_args()
    run_precompute(limit=args.limit, lookback_days=args.lookback_days)


if __name__ == "__main__":
    main()

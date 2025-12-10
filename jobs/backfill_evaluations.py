#!/usr/bin/env python3
"""Backfill filing_evaluations for historical snapshots."""

from __future__ import annotations

import logging
from dataclasses import asdict
from typing import Dict, Optional

from database import BSEDatabaseManager
from market_data import fetch_yahoo_quote
from market_data.tickers import build_ticker_candidates
from ratio_engine import FinancialSnapshotInput, MarketDataInput, RatioEngine

logger = logging.getLogger("backfill")
engine = RatioEngine()


def _coerce_float(value) -> Optional[float]:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(str(value).replace(",", ""))
    except ValueError:
        return None


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
        non_permissible_income=None,
    )


def _ticker_candidates(symbol: str, db: BSEDatabaseManager):
    alias = db.get_symbol_alias(symbol)
    return build_ticker_candidates(symbol, alias)


def main(limit: int = 500) -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(levelname)s - %(name)s - %(message)s",
    )

    db = BSEDatabaseManager()

    try:
        rows = db.get_recent_filings(limit=limit)
        logger.info("Backfilling %d filings", len(rows))

        count = 0
        for record in rows:
            if record.get("ratios"):
                continue

            snapshot = _snapshot_from_record(record)
            if not snapshot:
                continue

            tickers = _ticker_candidates(snapshot.symbol, db)
            market_cap = share_price = None
            for ticker in tickers:
                market_cap, share_price = fetch_yahoo_quote(
                    ticker, backoff_seconds=30, retries=3
                )
                if market_cap is not None or share_price is not None:
                    break
            if market_cap is None:
                continue

            evaluation = engine.evaluate(
                snapshot,
                MarketDataInput(market_cap=market_cap, share_price=share_price),
            )

            ratios_payload = {
                name: asdict(comp) for name, comp in evaluation.ratios.items()
            }
            verdict = (
                "compliant" if evaluation.is_compliant else "non-compliant"
            ) if any(comp.passed is not None for comp in evaluation.ratios.values()) else "insufficient-data"
            summary = "All computed AAOIFI ratios are within thresholds." if evaluation.is_compliant else "At least one ratio exceeds AAOIFI limits."

            db.upsert_filing_evaluation(
                symbol=snapshot.symbol,
                filing_date=snapshot.filing_date,
                is_compliant=evaluation.is_compliant,
                ratios=ratios_payload,
                summary=summary,
                verdict=verdict,
                narration_source="backfill",
                market_cap_used=market_cap,
                trailing_cap_used=None,
            )
            count += 1

        logger.info("Backfill completed: %d evaluations stored", count)
    finally:
        db.close()


if __name__ == "__main__":
    main()

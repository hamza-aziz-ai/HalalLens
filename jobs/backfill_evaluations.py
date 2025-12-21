#!/usr/bin/env python3
"""Backfill filing_evaluations for historical snapshots."""

from __future__ import annotations

import logging
from dataclasses import asdict
from typing import Dict, Optional
from collections import defaultdict

from database import BSEDatabaseManager
from market_data import fetch_yahoo_quote, fetch_tiingo_quote, BhavcopyMarketResolver
from market_data.tickers import build_ticker_candidates, build_tiingo_tickers
from ratio_engine import FinancialSnapshotInput, MarketDataInput, RatioEngine
from config.logging_config import configure_logging

logger = logging.getLogger("backfill")
engine = RatioEngine()
bhavcopy_resolver = BhavcopyMarketResolver()
FAILED_MARKET_LOOKUPS: Dict[str, int] = defaultdict(int)
MARKET_FAILURE_THRESHOLD = 3


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
        non_permissible_income=_coerce_float(record.get("non_halal_income")),
        accounts_receivable=_coerce_float(record.get("accounts_receivable")),
        liquid_assets=_coerce_float(record.get("liquid_assets")),
    )


def _ticker_candidates(symbol: str, db: BSEDatabaseManager):
    alias = db.get_symbol_alias(symbol)
    return build_ticker_candidates(symbol, alias)


def _clear_market_failure(symbol: str, filing_date: datetime, db: BSEDatabaseManager) -> None:
    if FAILED_MARKET_LOOKUPS.pop(symbol, None):
        try:
            db.resolve_quality_issues(symbol, filing_date)
        except Exception as exc:  # pragma: no cover
            logger.debug("Failed clearing market-data issue for %s: %s", symbol, exc)


def _record_market_failure(symbol: str, filing_date: datetime, db: BSEDatabaseManager) -> None:
    count = FAILED_MARKET_LOOKUPS[symbol] + 1
    FAILED_MARKET_LOOKUPS[symbol] = count
    if count >= MARKET_FAILURE_THRESHOLD:
        details = (
            f"Market data unavailable after {count} attempts "
            "(Tiingo, Yahoo Finance, Bhavcopy)."
        )
        logger.warning("%s market data unavailable after %d attempts", symbol, count)
        try:
            db.record_quality_issue(symbol, filing_date, "market-data-missing", details)
        except Exception as exc:  # pragma: no cover
            logger.debug("Failed recording market-data issue for %s: %s", symbol, exc)


def main(limit: int = 500) -> None:
    configure_logging("backfill")

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
            provider = None
            filing_dt = snapshot.filing_date
            if isinstance(filing_dt, str):
                try:
                    filing_dt = db.parse_iso_datetime(filing_dt)
                except Exception:
                    filing_dt = datetime.fromisoformat(filing_dt)

            cached = db.get_cached_market_data(snapshot.symbol, filing_dt)
            if cached and any(value is not None for value in cached[:2]):
                market_cap, share_price, provider = cached
            else:
                tiingo_tickers = build_tiingo_tickers(
                    snapshot.symbol, db.get_symbol_alias(snapshot.symbol)
                )
                for ticker in tiingo_tickers:
                    market_cap, share_price = fetch_tiingo_quote(ticker)
                    if market_cap is not None or share_price is not None:
                        provider = "tiingo"
                        db.insert_market_snapshot(
                            snapshot.symbol, market_cap, share_price, provider=provider
                        )
                        break
                if market_cap is None:
                    for ticker in tickers:
                        market_cap, share_price = fetch_yahoo_quote(
                            ticker, backoff_seconds=30, retries=3
                        )
                        if market_cap is not None or share_price is not None:
                            provider = "yahoo"
                            db.insert_market_snapshot(
                                snapshot.symbol,
                                market_cap,
                                share_price,
                                provider=provider,
                            )
                            break
                if market_cap is None:
                    fallback_cap, fallback_price = bhavcopy_resolver.resolve(
                        snapshot.symbol, snapshot.filing_date
                    )
                    market_cap = fallback_cap
                    if share_price is None:
                        share_price = fallback_price
                    if market_cap is not None or share_price is not None:
                        provider = "bhavcopy"
                        db.insert_market_snapshot(
                            snapshot.symbol,
                            market_cap,
                            share_price,
                            provider=provider,
                        )

            if market_cap is None:
                _record_market_failure(snapshot.symbol, filing_dt, db)
                continue
            _clear_market_failure(snapshot.symbol, filing_dt, db)

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
                filing_date=filing_dt,
                is_compliant=evaluation.is_compliant,
                ratios=ratios_payload,
                summary=summary,
                verdict=verdict,
                narration_source="backfill",
                market_cap_used=market_cap,
                trailing_cap_used=None,
                market_data_provider=provider,
            )
            count += 1

        logger.info("Backfill completed: %d evaluations stored", count)
    finally:
        db.close()


if __name__ == "__main__":
    main()

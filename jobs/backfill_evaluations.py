#!/usr/bin/env python3
"""Backfill filing_evaluations for historical snapshots."""

from __future__ import annotations

import logging
from dataclasses import asdict
from datetime import datetime
from typing import Dict, Optional, List, Tuple
from collections import defaultdict

from database import BSEDatabaseManager
from market_data import (
    BhavcopyMarketResolver,
    fetch_indian_financial_snapshot,
    indian_api_enabled,
)
from ratio_engine import FinancialSnapshotInput, MarketDataInput, RatioEngine
from config.logging_config import configure_logging

logger = logging.getLogger("backfill")
engine = RatioEngine()
bhavcopy_resolver = BhavcopyMarketResolver()
FAILED_MARKET_LOOKUPS: Dict[str, int] = defaultdict(int)
MARKET_FAILURE_THRESHOLD = 3
MARKET_CACHE: Dict[str, Tuple[Optional[float], Optional[float], Optional[str]]] = {}


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
            _clear_market_failure(cache_key, filing_date, db)
            return snapshot.market_cap, snapshot.share_price, "indianapi"

    fallback_cap, fallback_price = bhavcopy_resolver.resolve(symbol, filing_date)
    if fallback_cap is not None or fallback_price is not None:
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
        _clear_market_failure(cache_key, filing_date, db)
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
            if record.get("ratios"):
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

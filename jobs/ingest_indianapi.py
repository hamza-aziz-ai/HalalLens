#!/usr/bin/env python3
"""Ingest IndianAPI stock snapshots and persist them into PostgreSQL."""

from __future__ import annotations

import argparse
import logging
from dataclasses import asdict
from datetime import datetime, timezone
from typing import Dict, Iterable, List, Optional

from config.logging_config import configure_logging as setup_file_logging
from database import BSEDatabaseManager
from market_data import fetch_indian_financial_snapshot, indian_api_enabled
from ratio_engine import FinancialSnapshotInput, MarketDataInput, RatioEngine


logger = logging.getLogger("indianapi_ingestion")
ratio_engine = RatioEngine()


def _parse_symbols(raw: Optional[str]) -> List[str]:
    if not raw:
        return []
    return [token.strip().upper() for token in raw.split(",") if token.strip()]


def _announce_payload(
    symbol: str,
    alias: Optional[str],
    company_name: str,
    filing_dt: datetime,
    raw_payload: Dict,
) -> Dict:
    headline = f"Indian API snapshot for {company_name} ({symbol})"
    return {
        "symbol": symbol,
        "symbol_alias": alias or symbol,
        "company_name": company_name,
        "filing_date": filing_dt,
        "category": "Indian API Snapshot",
        "headline": headline,
        "confidence": "HIGH",
        "raw_json": raw_payload,
        "minio_path": None,
        "pdf_stored": False,
    }


def _financial_payload(
    symbol: str,
    filing_dt: datetime,
    metrics: Dict[str, float],
) -> Dict:
    extracted = {
        "total_debt": metrics.get("total_debt"),
        "cash_equiv": metrics.get("cash_equiv"),
        "revenue": metrics.get("revenue"),
        "interest_income": metrics.get("interest_income"),
        "dividend_income": metrics.get("dividend_income"),
        "accounts_receivable": metrics.get("accounts_receivable"),
        "liquid_assets": metrics.get("liquid_assets"),
        "non_halal_income": metrics.get("non_halal_income"),
    }
    payload = {
        "symbol": symbol,
        "filing_date": filing_dt,
        "fy_end": filing_dt.date(),
        "quarter": None,
        "audit_status": "indianapi",
        "governance_notes": "Derived from Indian API snapshot",
        "extracted_data": extracted,
    }
    for key, value in extracted.items():
        payload[key] = value
    return payload


def _ingest_symbol(db: BSEDatabaseManager, symbol: str) -> bool:
    logger.info("Fetching snapshot for %s", symbol)
    snapshot = fetch_indian_financial_snapshot(symbol)
    if not snapshot:
        logger.warning("Indian API returned no data for %s", symbol)
        return False

    symbol_code = snapshot.bse_code or snapshot.nse_code or snapshot.symbol
    alias = snapshot.nse_code or snapshot.symbol
    company = snapshot.company_name or alias or symbol_code
    filing_date = snapshot.end_date or datetime.utcnow().date()
    filing_dt = datetime(
        filing_date.year,
        filing_date.month,
        filing_date.day,
        tzinfo=timezone.utc,
    )

    announcement = _announce_payload(
        symbol=symbol_code,
        alias=alias,
        company_name=company,
        filing_dt=filing_dt,
        raw_payload=snapshot.raw,
    )
    db.insert_announcements([announcement])

    financial_snapshot = _financial_payload(symbol_code, filing_dt, snapshot.metrics)
    db.insert_financial_snapshots([financial_snapshot])

    db.insert_market_snapshot(
        symbol_code, snapshot.market_cap, snapshot.share_price, provider="indianapi"
    )
    db.insert_indianapi_snapshot(
        symbol=symbol_code,
        symbol_alias=alias,
        company_name=company,
        snapshot_date=filing_dt.date(),
        payload=snapshot.raw,
    )
    _evaluate_snapshot(db, symbol_code, filing_dt)

    logger.info(
        "Stored snapshot for %s (%s) dated %s",
        company,
        symbol_code,
        filing_dt.date().isoformat(),
    )
    return True


def _load_symbol_file(path: str) -> Iterable[str]:
    with open(path, "r", encoding="utf-8") as handle:
        for line in handle:
            cleaned = line.strip()
            if cleaned:
                yield cleaned


def _load_symbols(args: argparse.Namespace) -> List[str]:
    symbols = set(_parse_symbols(args.symbols))
    if args.symbol_file:
        symbols.update(token.strip().upper() for token in _load_symbol_file(args.symbol_file))
    return sorted(symbols)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Ingest company snapshots directly from IndianAPI."
    )
    parser.add_argument(
        "--symbols",
        help="Comma separated list of company identifiers (e.g., TCS,INFY,RELIANCE).",
    )
    parser.add_argument(
        "--symbol-file",
        help="Optional newline-delimited file containing one symbol per line.",
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        help="Logging level (default: INFO)",
    )
    args = parser.parse_args()

    setup_file_logging(
        "ingestion",
        level=args.log_level.upper(),
        fmt="%(asctime)s %(levelname)s [indianapi_ingestion] %(message)s",
    )

    if not indian_api_enabled():
        parser.error(
            "INDIAN_API_BASE_URL is not configured. Cannot run IndianAPI ingestion."
        )

    symbols = _load_symbols(args)
    if not symbols:
        parser.error("Provide at least one symbol via --symbols or --symbol-file.")

    db = BSEDatabaseManager()
    successes = 0
    for token in symbols:
        try:
            if _ingest_symbol(db, token):
                successes += 1
        except Exception as exc:  # pragma: no cover - operational logging path
            logger.exception("Failed to ingest %s: %s", token, exc)

    logger.info(
        "IndianAPI ingestion complete: %s succeeded out of %s requested symbols",
        successes,
        len(symbols),
    )


def _coerce_number(value: Optional[float]) -> Optional[float]:
    if value is None:
        return None
    return float(value)


def _snapshot_from_record(record: Dict) -> Optional[FinancialSnapshotInput]:
    filing_date = record.get("filing_date")
    symbol = record.get("symbol")
    if not symbol or not filing_date:
        return None
    return FinancialSnapshotInput(
        symbol=str(symbol).strip().upper(),
        filing_date=filing_date,
        total_debt=_coerce_number(record.get("total_debt")),
        cash_equiv=_coerce_number(record.get("cash_equiv")),
        revenue=_coerce_number(record.get("revenue")),
        interest_income=_coerce_number(record.get("interest_income")),
        dividend_income=_coerce_number(record.get("dividend_income")),
        non_permissible_income=_coerce_number(record.get("non_halal_income")),
        accounts_receivable=_coerce_number(record.get("accounts_receivable")),
        liquid_assets=_coerce_number(record.get("liquid_assets")),
    )


def _derive_verdict(evaluation) -> str:
    has_ratios = any(comp.passed is not None for comp in evaluation.ratios.values())
    if not has_ratios:
        return "insufficient-data"
    return "compliant" if evaluation.is_compliant else "non-compliant"


def _build_summary(evaluation) -> str:
    friendly = {
        "debt_to_market_cap": "Debt to market cap",
        "cash_to_market_cap": "Cash to market cap",
        "non_permissible_income_ratio": "Non-permissible income ratio",
        "receivables_to_market_cap": "Receivables to market cap",
        "liquid_assets_to_market_cap": "Liquid assets to market cap",
    }
    failing = [
        friendly.get(name, name)
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


def _evaluate_snapshot(db: BSEDatabaseManager, symbol: str, filing_dt: datetime) -> None:
    record = db.get_filing(symbol, filing_dt)
    if not record:
        return
    snapshot = _snapshot_from_record(record)
    if not snapshot:
        return
    market_cap_tuple = db.get_cached_market_data(symbol, filing_dt)
    if market_cap_tuple:
        market_cap, share_price, provider = market_cap_tuple
    else:
        market_cap_tuple = db.get_cached_market_data(symbol)
        if not market_cap_tuple:
            return
        market_cap, share_price, provider = market_cap_tuple
    if market_cap is None:
        return
    market_cap = float(market_cap)
    share_price = float(share_price) if share_price is not None else None
    evaluation = ratio_engine.evaluate(
        snapshot, MarketDataInput(market_cap=market_cap, share_price=share_price)
    )
    verdict = _derive_verdict(evaluation)
    summary = _build_summary(evaluation)
    ratios_payload = {name: asdict(comp) for name, comp in evaluation.ratios.items()}
    db.upsert_filing_evaluation(
        symbol=snapshot.symbol,
        filing_date=snapshot.filing_date,
        is_compliant=evaluation.is_compliant
        if verdict != "insufficient-data"
        else None,
        ratios=ratios_payload,
        summary=summary,
        verdict=verdict,
        narration_source="ingestion",
        market_cap_used=market_cap,
        trailing_cap_used=None,
        market_data_provider=provider,
    )


if __name__ == "__main__":
    main()

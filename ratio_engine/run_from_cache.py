#!/usr/bin/env python3
"""
Utility script to run the RatioEngine against cached financial data exports.

The ETL saves processed announcements to JSON (see cache/financial_data_*.json).
This script loads that file, builds FinancialSnapshotInput objects,
optionally enriches them with market-cap data, and emits ratio evaluations.
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

from ratio_engine.amounts import coerce_amount

from ratio_engine import (
    FinancialSnapshotInput,
    MarketDataInput,
    RatioEngine,
    RatioEvaluation,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run RatioEngine on cached JSON outputs")
    parser.add_argument(
        "--input",
        type=Path,
        required=True,
        help="Path to financial_data_*.json produced by FinancialDataProcessor",
    )
    parser.add_argument(
        "--market-data",
        type=Path,
        help="Optional JSON mapping symbol -> {\"market_cap\": float, \"trailing_market_cap\": float}",
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="Location to write ratio evaluations (defaults to cache/ratio_evaluations_<ts>.json)",
    )
    parser.add_argument(
        "--default-market-cap",
        type=float,
        default=None,
        help="Fallback market cap (in INR) used when symbol-specific data is missing",
    )
    return parser.parse_args()


def load_financial_records(path: Path) -> List[Dict]:
    if not path.exists():
        raise FileNotFoundError(f"Input JSON not found: {path}")
    with path.open() as handle:
        data = json.load(handle)
    if not isinstance(data, list):
        raise ValueError("Expected a list of financial snapshot entries")
    return data


def load_market_caps(path: Optional[Path]) -> Dict[str, Dict[str, float]]:
    if not path:
        return {}
    if not path.exists():
        raise FileNotFoundError(f"Market data JSON not found: {path}")
    with path.open() as handle:
        payload = json.load(handle)
    if isinstance(payload, dict):
        return payload
    raise ValueError("Market data JSON must be an object keyed by symbol")


def to_snapshot(entry: Dict) -> Optional[FinancialSnapshotInput]:
    extracted = entry.get("extracted_data") or {}
    if not extracted:
        return None

    symbol = entry.get("symbol")
    filing_date = entry.get("date") or entry.get("filing_date")
    if not symbol or not filing_date:
        return None

    if isinstance(filing_date, str):
        filing_date = datetime.fromisoformat(filing_date.replace(" ", "T"))

    return FinancialSnapshotInput(
        symbol=str(symbol),
        filing_date=filing_date,
        total_debt=_safe_get_float(extracted, "total_debt"),
        cash_equiv=_safe_get_float(extracted, "cash_equiv"),
        revenue=_safe_get_float(extracted, "revenue"),
        interest_income=_safe_get_float(extracted, "interest_income"),
        dividend_income=_safe_get_float(extracted, "dividend_income"),
        # Same fallback the jobs use: the extractor stores the base as non_halal_income.
        non_permissible_income=_safe_get_float(
            extracted,
            "non_permissible_income"
            if extracted.get("non_permissible_income") is not None
            else "non_halal_income",
        ),
        accounts_receivable=_safe_get_float(extracted, "accounts_receivable"),
        liquid_assets=_safe_get_float(extracted, "liquid_assets"),
    )


def _safe_get_float(payload: Dict, key: str) -> Optional[float]:
    return coerce_amount(payload.get(key))


def build_market_data(
    symbol: str,
    market_caps: Dict[str, Dict[str, float]],
    default_cap: Optional[float],
) -> MarketDataInput:
    entry = market_caps.get(symbol, {})
    market_cap = entry.get("market_cap")
    trailing_cap = entry.get("trailing_market_cap")
    if market_cap is None:
        market_cap = default_cap
    return MarketDataInput(market_cap=market_cap, trailing_market_cap=trailing_cap)


def evaluate_snapshots(
    snapshots: Iterable[Tuple[Dict, FinancialSnapshotInput]],
    market_caps: Dict[str, Dict[str, float]],
    default_cap: Optional[float],
) -> List[Dict]:
    engine = RatioEngine()
    evaluations: List[Dict] = []

    for raw_entry, snapshot in snapshots:
        market_data = build_market_data(snapshot.symbol, market_caps, default_cap)
        result: RatioEvaluation = engine.evaluate(snapshot, market_data)
        evaluations.append(
            {
                "symbol": result.symbol,
                "filing_date": result.filing_date.isoformat(),
                "verdict": result.verdict,
                "is_compliant": result.is_compliant,
                "ratios": {
                    name: {
                        "value": comp.value,
                        "threshold": comp.threshold,
                        "passed": comp.passed,
                        "note": comp.note,
                    }
                    for name, comp in result.ratios.items()
                },
                "missing_inputs": result.missing_inputs,
                "source_minio_path": raw_entry.get("minio_path"),
                "source_pdf": raw_entry.get("pdf_url"),
            }
        )

    return evaluations


def write_output(records: List[Dict], output_path: Optional[Path]) -> Path:
    if not output_path:
        ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        output_path = Path("cache") / f"ratio_evaluations_{ts}.json"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w") as handle:
        json.dump(records, handle, indent=2)
    return output_path


def main():
    args = parse_args()
    records = load_financial_records(args.input)
    market_caps = load_market_caps(args.market_data)

    prepared: List[Tuple[Dict, FinancialSnapshotInput]] = []
    for entry in records:
        snapshot = to_snapshot(entry)
        if snapshot:
            prepared.append((entry, snapshot))

    if not prepared:
        raise SystemExit("No financial snapshots with numeric data were found.")

    evaluations = evaluate_snapshots(prepared, market_caps, args.default_market_cap)
    output_path = write_output(evaluations, args.output)
    print(f"Computed {len(evaluations)} ratio evaluations → {output_path}")


if __name__ == "__main__":
    main()

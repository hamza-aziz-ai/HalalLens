#!/usr/bin/env python3
"""
Minimal demonstration for the RatioEngine.
"""

from datetime import datetime

from ratio_engine import (
    FinancialSnapshotInput,
    MarketDataInput,
    RatioEngine,
    RatioThresholds,
)


def main():
    engine = RatioEngine(RatioThresholds.default())

    snapshot = FinancialSnapshotInput(
        symbol="TEST",
        filing_date=datetime.utcnow(),
        total_debt=5_000_000,
        cash_equiv=2_000_000,
        revenue=50_000_000,
        interest_income=500_000,
        dividend_income=200_000,
    )

    market = MarketDataInput(
        market_cap=40_000_000,
    )

    result = engine.evaluate(snapshot, market)
    print(f"Symbol: {result.symbol}")
    print(f"Halal verdict: {result.is_compliant}")
    for key, comp in result.ratios.items():
        value = "n/a" if comp.value is None else f"{comp.value:.4f}"
        status = (
            "n/a" if comp.passed is None else ("PASS" if comp.passed else "FAIL")
        )
        print(f"  {key}: {value} <= {comp.threshold:.2f} -> {status}")


if __name__ == "__main__":
    main()

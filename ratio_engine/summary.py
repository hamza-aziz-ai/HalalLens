#!/usr/bin/env python3
"""Plain-text summary of a RatioEvaluation.

One implementation for the API, the ingestion jobs and the backfill, so the
wording can never disagree with `RatioEvaluation.verdict`.
"""

from __future__ import annotations

from ratio_engine.models import (
    COMPLIANT,
    NON_COMPLIANT,
    RatioEvaluation,
)

FRIENDLY_LABELS = {
    "debt_to_market_cap": "Debt to market cap",
    "cash_to_market_cap": "Cash to market cap",
    "non_permissible_income_ratio": "Non-permissible income ratio",
    "receivables_to_market_cap": "Receivables to market cap",
    "liquid_assets_to_market_cap": "Liquid assets to market cap",
}


def build_summary(evaluation: RatioEvaluation) -> str:
    if evaluation.verdict == COMPLIANT:
        return "All configured financial checks were computed and are within the configured thresholds."
    if evaluation.verdict == NON_COMPLIANT:
        failing = [
            FRIENDLY_LABELS.get(name, name)
            for name, comp in evaluation.ratios.items()
            if comp.passed is False
        ]
        return f"{', '.join(failing)} exceeded the configured thresholds for this filing."
    if evaluation.missing_inputs:
        missing = ", ".join(sorted(evaluation.missing_inputs))
        return f"Insufficient data to screen this filing (unusable inputs: {missing})."
    return "Insufficient data to screen this filing."

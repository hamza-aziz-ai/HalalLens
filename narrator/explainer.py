#!/usr/bin/env python3
"""Narration helpers for translating ratios into plain English."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List

from ratio_engine import RatioEvaluation


@dataclass
class NarrationResult:
    """Container for narrator output."""

    summary: str
    verdict: str
    bullets: List[str]
    citations: List[str]


class NarrationEngine:
    """Rule-based narrator that explains ratio outcomes deterministically."""

    ratio_labels: Dict[str, str] = {
        "debt_to_market_cap": "Debt to market cap",
        "cash_to_market_cap": "Cash to market cap",
        "non_permissible_income_ratio": "Non-permissible income ratio",
    }

    def build(self, evaluation: RatioEvaluation) -> NarrationResult:
        """Produce a plain-language narration from a ratio evaluation."""

        verdict = (
            "compliant with AAOIFI screens"
            if evaluation.is_compliant
            else "NOT compliant with AAOIFI screens"
        )
        summary = (
            f"{evaluation.symbol} is {verdict.lower()} for the filing dated "
            f"{evaluation.filing_date.date().isoformat()}."
        )

        bullets: List[str] = []
        citations: List[str] = []

        for key, computation in evaluation.ratios.items():
            label = self.ratio_labels.get(key, key.replace("_", " ").title())
            if computation.value is None:
                bullets.append(
                    f"{label}: cannot compute because {computation.note.lower()}."
                )
                continue

            value_pct = computation.value * 100
            threshold_pct = computation.threshold * 100
            status = "within" if computation.passed else "above"
            bullets.append(
                f"{label} is {value_pct:.2f}% vs {threshold_pct:.0f}% cap ( {status} limits )."
            )
            citations.append(
                f"{label} sourced from filing on {evaluation.filing_date.date().isoformat()}"
            )

        if not bullets:
            bullets.append(
                "Insufficient financial data to compute AAOIFI ratios for this filing."
            )

        return NarrationResult(
            summary=summary,
            verdict=verdict,
            bullets=bullets,
            citations=citations or [summary],
        )


__all__ = ["NarrationEngine", "NarrationResult"]

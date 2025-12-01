#!/usr/bin/env python3
"""
Core ratio engine implementation.
"""

from __future__ import annotations

from typing import Dict, Optional, Tuple

from ratio_engine.models import (
    FinancialSnapshotInput,
    MarketDataInput,
    RatioComputation,
    RatioEvaluation,
    RatioThresholds,
)


class RatioEngine:
    """Evaluates AAOIFI-style ratios for a given financial snapshot."""

    def __init__(self, thresholds: Optional[RatioThresholds] = None):
        self.thresholds = thresholds or RatioThresholds.default()

    def evaluate(
        self,
        snapshot: FinancialSnapshotInput,
        market_data: MarketDataInput,
    ) -> RatioEvaluation:
        ratios: Dict[str, RatioComputation] = {}
        missing: Dict[str, str] = {}

        debt_ratio = self._safe_ratio(
            snapshot.total_debt,
            market_data.market_cap or market_data.trailing_market_cap,
            "total_debt",
            "market_cap",
            missing,
        )
        ratios["debt_to_market_cap"] = self._build_computation(
            debt_ratio,
            self.thresholds.max_debt_to_market_cap,
            "Total debt / market cap",
        )

        cash_ratio = self._safe_ratio(
            snapshot.cash_equiv,
            market_data.market_cap or market_data.trailing_market_cap,
            "cash_equiv",
            "market_cap",
            missing,
        )
        ratios["cash_to_market_cap"] = self._build_computation(
            cash_ratio,
            self.thresholds.max_cash_to_market_cap,
            "Cash & equivalents / market cap",
        )

        non_perm_income = (
            (snapshot.non_permissible_income or 0.0)
            + (snapshot.interest_income or 0.0)
            + (snapshot.dividend_income or 0.0)
        )
        np_ratio = self._safe_ratio(
            non_perm_income,
            snapshot.revenue,
            "non_permissible_income",
            "revenue",
            missing,
        )
        ratios["non_permissible_income_ratio"] = self._build_computation(
            np_ratio,
            self.thresholds.max_non_permissible_income,
            "Non-permissible income / revenue",
        )

        is_compliant = self._aggregate_verdict(ratios)

        return RatioEvaluation(
            symbol=snapshot.symbol,
            filing_date=snapshot.filing_date,
            is_compliant=is_compliant if ratios else False,
            ratios=ratios,
            missing_inputs=missing,
        )

    def _safe_ratio(
        self,
        numerator: Optional[float],
        denominator: Optional[float],
        numerator_label: str,
        denominator_label: str,
        missing: Dict[str, str],
    ) -> Optional[float]:
        if numerator is None:
            missing[numerator_label] = "missing"
            return None
        if denominator in (None, 0):
            missing[denominator_label] = "missing_or_zero"
            return None
        return numerator / denominator

    def _build_computation(
        self,
        ratio_value: Optional[float],
        threshold: float,
        note: str,
    ) -> RatioComputation:
        if ratio_value is None:
            return RatioComputation(
                value=None,
                threshold=threshold,
                passed=None,
                note=f"{note} unavailable",
            )
        passed = ratio_value <= threshold
        return RatioComputation(
            value=ratio_value,
            threshold=threshold,
            passed=passed,
            note=note,
        )

    def _aggregate_verdict(self, ratios: Dict[str, RatioComputation]) -> bool:
        verdicts = [comp.passed for comp in ratios.values() if comp.passed is not None]
        if not verdicts:
            return False
        return all(verdicts)

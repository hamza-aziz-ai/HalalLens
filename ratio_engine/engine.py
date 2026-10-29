#!/usr/bin/env python3
"""
Core ratio engine implementation.
"""

from __future__ import annotations

import math
from dataclasses import fields
from decimal import (
    MAX_EMAX,
    MIN_EMIN,
    Context,
    Decimal,
    DivisionByZero,
    InvalidOperation,
    Overflow,
)
from typing import Dict, Optional, Tuple

from ratio_engine.models import (
    COMPLIANT,
    INSUFFICIENT_DATA,
    NON_COMPLIANT,
    FinancialSnapshotInput,
    MarketDataInput,
    RatioComputation,
    RatioEvaluation,
    RatioThresholds,
)

# A filing is "compliant" only when every one of these ratios was computed from
# valid inputs and passed. This is completeness of the *configured* screen, not
# a verified full AAOIFI assessment: AAOIFI SS21 backs the 30%/30%/5% limits,
# but not the receivables/liquid-assets market-cap gates (unverified).
REQUIRED_RATIOS = (
    "debt_to_market_cap",
    "cash_to_market_cap",
    "non_permissible_income_ratio",
    "receivables_to_market_cap",
    "liquid_assets_to_market_cap",
)

# Prohibited income is the residual sum: base figure + positive interest income
# + positive dividend income. Every part must be known (an explicit 0 counts);
# an unknown part is never assumed to be zero. The base must exclude interest
# and dividend income, or they are counted twice; since D-028 no extractor or
# vendor mapping fills it, so it comes only from a governance override. If the
# base is ever declared a complete aggregate, the summation below must change,
# not just this tuple.
REQUIRED_INCOME_INPUTS = ("non_permissible_income", "interest_income", "dividend_income")


# Threshold decisions are exact, not rounded by the caller's Decimal context.
# Supported input domain (enforced in RatioEngine._number): finite values within
# float range; every operand is a decimal of at most 17 significant digits, or
# an int (kept exact, up to ~309 digits). Sums and products then span well under
# 1500 digits of positional range, so this context never rounds them. Do not
# widen the domain (e.g. accept arbitrary Decimal precision) without raising it.
_CTX = Context(
    prec=1500,
    Emax=MAX_EMAX,
    Emin=MIN_EMIN,
    traps=[InvalidOperation, DivisionByZero, Overflow],
)


class RatioEngine:
    """Evaluates AAOIFI-style ratios for a given financial snapshot.

    Arithmetic is Decimal built from repr(float), so a ratio that is exactly on
    a threshold in decimal terms (0.1 + 0.2 over 6 against 5%) is not pushed over
    it by binary floating point. There is no tolerance: 0.30000000000000004
    still exceeds a 0.30 cap. The pass/fail decision is division-free
    (numerator <= threshold * denominator); division only produces the float
    `value` shown to users, which can underflow to 0.0 for a tiny ratio while
    the decision stays exact. Adapters (API/jobs) still convert to float, so
    integer precision is exact inside the engine, not end to end.
    """

    def __init__(self, thresholds: Optional[RatioThresholds] = None):
        self.thresholds = thresholds or RatioThresholds.default()
        self._validate_thresholds(self.thresholds)

    @staticmethod
    def _validate_thresholds(thresholds: RatioThresholds) -> None:
        """Only int/float limits within float range: the exact-arithmetic bound
        (see _CTX) holds for those, and an infinite or NaN limit would silently
        disable or break a check. Decimals are rejected for the same reason."""

        for field in fields(thresholds):
            value = getattr(thresholds, field.name)
            try:
                valid = (
                    not isinstance(value, bool)
                    and isinstance(value, (int, float))
                    and math.isfinite(value)
                    and value >= 0
                )
            except OverflowError:  # an int beyond float range
                valid = False
            if not valid:
                raise ValueError(f"invalid threshold {field.name}: {value!r}")

    def evaluate(
        self,
        snapshot: FinancialSnapshotInput,
        market_data: MarketDataInput,
    ) -> RatioEvaluation:
        ratios: Dict[str, RatioComputation] = {}
        missing: Dict[str, str] = {}
        provider = market_data.provider or "manual"
        market_cap = self._clean(
            self._market_cap(market_data), "market_cap", missing, denominator=True
        )

        debt_ratio = self._ratio(
            self._clean(snapshot.total_debt, "total_debt", missing),
            market_cap,
            "total_debt",
            missing,
        )
        ratios["debt_to_market_cap"] = self._build_computation(
            debt_ratio,
            self.thresholds.max_debt_to_market_cap,
            "Total debt / market cap",
            provider=provider,
        )

        cash_ratio = self._ratio(
            self._clean(snapshot.cash_equiv, "cash_equiv", missing),
            market_cap,
            "cash_equiv",
            missing,
        )
        ratios["cash_to_market_cap"] = self._build_computation(
            cash_ratio,
            self.thresholds.max_cash_to_market_cap,
            "Cash & equivalents / market cap",
            provider=provider,
        )

        np_ratio = self._ratio(
            self._non_permissible_income(snapshot, missing),
            self._clean(snapshot.revenue, "revenue", missing, denominator=True),
            "non_permissible_income",
            missing,
        )
        ratios["non_permissible_income_ratio"] = self._build_computation(
            np_ratio,
            self.thresholds.max_non_permissible_income,
            "Non-permissible income / revenue",
            provider="manual",
        )

        receivable_ratio = self._ratio(
            self._clean(snapshot.accounts_receivable, "accounts_receivable", missing),
            market_cap,
            "accounts_receivable",
            missing,
        )
        ratios["receivables_to_market_cap"] = self._build_computation(
            receivable_ratio,
            self.thresholds.max_receivables_to_market_cap,
            "Accounts receivable / market cap",
            provider=provider,
        )

        liquid_ratio = self._ratio(
            self._clean(snapshot.liquid_assets, "liquid_assets", missing),
            market_cap,
            "liquid_assets",
            missing,
        )
        ratios["liquid_assets_to_market_cap"] = self._build_computation(
            liquid_ratio,
            self.thresholds.max_liquid_assets_to_market_cap,
            "Liquid assets / market cap",
            provider=provider,
        )

        return RatioEvaluation(
            symbol=snapshot.symbol,
            filing_date=snapshot.filing_date,
            verdict=self._aggregate_verdict(ratios),
            ratios=ratios,
            missing_inputs=missing,
        )

    @staticmethod
    def _market_cap(market_data: MarketDataInput) -> Optional[float]:
        """Trailing cap only stands in when the primary cap is absent (None or
        a numeric 0).

        A negative, non-finite or boolean primary cap is kept so it is reported
        invalid instead of being hidden behind a valid trailing value.
        """

        primary = market_data.market_cap
        if primary is None:
            return market_data.trailing_market_cap
        # Zero-ness is judged on the validated number, never on the raw value
        # (a bool or Decimal('sNaN') must reach _clean and be reported invalid).
        number = RatioEngine._number(primary)
        if number is not None and number == 0:
            return market_data.trailing_market_cap
        return primary

    @staticmethod
    def _number(value) -> Optional[Decimal]:
        """A finite, non-boolean number as Decimal, else None (invalid).

        Only finite values within float range are supported (see _CTX).
        """

        if isinstance(value, bool):
            return None
        try:
            as_float = float(value)
        except (TypeError, ValueError, OverflowError):
            return None
        if not math.isfinite(as_float):
            return None
        if isinstance(value, int):
            return Decimal(value)  # exact; float() above only bounded the range
        if as_float == 0:
            # A numerically-zero source is a known zero ("0", "0e-400", 0.0). A
            # positive amount that underflowed to 0.0 ("1e-400") must not
            # silently become one. The exact parse is used as a boolean only.
            try:
                return Decimal(0) if Decimal(str(value)) == 0 else None
            except InvalidOperation:
                return None
        return Decimal(repr(as_float))

    def _clean(
        self,
        value,
        label: str,
        missing: Dict[str, str],
        *,
        denominator: bool = False,
    ) -> Optional[Decimal]:
        """A usable amount (>= 0, or > 0 for a denominator) or None with the reason recorded."""

        if value is None:
            missing.setdefault(label, "missing_or_zero" if denominator else "missing")
            return None
        number = self._number(value)
        if number is None or number < 0:
            missing[label] = "invalid"
            return None
        if denominator and number == 0:
            missing.setdefault(label, "missing_or_zero")
            return None
        return number

    @staticmethod
    def _ratio(
        numerator: Optional[Decimal],
        denominator: Optional[Decimal],
        label: str,
        missing: Dict[str, str],
    ) -> Optional[Tuple[Decimal, Decimal]]:
        """Pair two already-validated amounts; None if either is unusable.

        A None input was already reported by `_clean` / `_non_permissible_income`
        with its own reason, so nothing is recorded for it here. A quotient that
        cannot be shown as a finite number is invalid, not a computed failure.
        """

        if numerator is None or denominator is None:
            return None
        try:
            representable = math.isfinite(float(_CTX.divide(numerator, denominator)))
        except OverflowError:
            representable = False
        if not representable:
            missing[label] = "invalid"
            return None
        return numerator, denominator

    def _non_permissible_income(
        self, snapshot: FinancialSnapshotInput, missing: Dict[str, str]
    ) -> Optional[Decimal]:
        """Residual prohibited income, or None when a required part is unknown."""

        # `is not None`: an explicit 0 in the primary field must not fall through.
        base = snapshot.non_permissible_income
        if base is None:
            base = snapshot.non_halal_income
        # (label, value, signed). Interest/dividend are signed: a finite negative
        # value is net expense, known, and contributes 0. The base is never
        # signed, so it cannot offset positive interest.
        parts = (
            ("non_permissible_income", base, False),
            ("interest_income", snapshot.interest_income, True),
            ("dividend_income", snapshot.dividend_income, True),
        )
        total = Decimal(0)
        known = True
        for label, value, signed in parts:
            if value is None and label not in REQUIRED_INCOME_INPUTS:
                continue
            number = self._income_part(value, label, missing, signed=signed)
            if number is None:
                known = False
            else:
                total = _CTX.add(total, number)
        return total if known else None

    def _income_part(
        self, value, label: str, missing: Dict[str, str], *, signed: bool
    ) -> Optional[Decimal]:
        if value is None:
            missing.setdefault(label, "missing")
            return None
        # Finiteness is checked before any positive-only conversion: NaN must
        # not silently become 0.
        number = self._number(value)
        if number is None or (number < 0 and not signed):
            missing[label] = "invalid"
            return None
        return max(number, Decimal(0))

    def _build_computation(
        self,
        ratio_pair: Optional[Tuple[Decimal, Decimal]],
        threshold: float,
        note: str,
        provider: Optional[str] = None,
    ) -> RatioComputation:
        if ratio_pair is None:
            return RatioComputation(
                value=None,
                threshold=threshold,
                passed=None,
                note=f"{note} unavailable",
                provider=provider,
            )
        numerator, denominator = ratio_pair
        # str(float) is the shortest repr, so 0.30 compares as exactly 0.3.
        passed = numerator <= _CTX.multiply(Decimal(str(threshold)), denominator)
        return RatioComputation(
            value=float(_CTX.divide(numerator, denominator)),
            threshold=threshold,
            passed=passed,
            note=note,
            provider=provider,
        )

    @staticmethod
    def _aggregate_verdict(ratios: Dict[str, RatioComputation]) -> str:
        """Single source of truth for the verdict; consumers must not re-derive it.

        A failed ratio is conclusive even when other inputs are missing.
        """

        if any(comp.passed is False for comp in ratios.values()):
            return NON_COMPLIANT
        if all(
            name in ratios and ratios[name].passed is True for name in REQUIRED_RATIOS
        ):
            return COMPLIANT
        return INSUFFICIENT_DATA

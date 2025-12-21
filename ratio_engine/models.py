#!/usr/bin/env python3
"""
Data models used by the ratio engine.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, Optional


@dataclass
class FinancialSnapshotInput:
    """Normalized financial metrics extracted from filings."""

    symbol: str
    filing_date: datetime
    total_debt: Optional[float] = None
    cash_equiv: Optional[float] = None
    revenue: Optional[float] = None
    interest_income: Optional[float] = None
    dividend_income: Optional[float] = None
    non_permissible_income: Optional[float] = None
    accounts_receivable: Optional[float] = None
    liquid_assets: Optional[float] = None
    non_halal_income: Optional[float] = None


@dataclass
class MarketDataInput:
    """Supplementary market data required for AAOIFI style ratios."""

    market_cap: Optional[float] = None
    trailing_market_cap: Optional[float] = None
    share_price: Optional[float] = None


@dataclass
class RatioThresholds:
    """Thresholds inspired by AAOIFI guidelines."""

    max_debt_to_market_cap: float = 0.30  # 30%
    max_cash_to_market_cap: float = 0.30  # 30%
    max_non_permissible_income: float = 0.05  # 5%
    max_receivables_to_market_cap: float = 0.67  # 67%
    max_liquid_assets_to_market_cap: float = 0.49  # 49%

    @classmethod
    def default(cls) -> "RatioThresholds":
        return cls()


@dataclass
class RatioComputation:
    """Holds individual ratio values and threshold comparison."""

    value: Optional[float]
    threshold: float
    passed: Optional[bool]
    note: str = ""


@dataclass
class RatioEvaluation:
    """Final evaluation object returned by the engine."""

    symbol: str
    filing_date: datetime
    is_compliant: bool
    ratios: Dict[str, RatioComputation] = field(default_factory=dict)
    missing_inputs: Dict[str, str] = field(default_factory=dict)

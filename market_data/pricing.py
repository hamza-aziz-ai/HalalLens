#!/usr/bin/env python3
"""Placeholder market data provider."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass
class MarketSnapshot:
    symbol: str
    market_cap: Optional[float]
    share_price: Optional[float]


class MarketDataProvider:
    """Fetches market data for a symbol. Currently returns static stub."""

    def get_snapshot(self, symbol: str) -> MarketSnapshot:
        # TODO: integrate with NSE/BSE or cached snapshots
        return MarketSnapshot(symbol=symbol, market_cap=1_000_000_000, share_price=None)


__all__ = ["MarketDataProvider", "MarketSnapshot"]

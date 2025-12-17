#!/usr/bin/env python3
"""Fallback market data resolver using BSE/NSE bhavcopy files."""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Dict, Optional, Tuple

from market_data.bhavcopy import BhavcopyClient, BhavcopyError, BSEBhavRecord

LOGGER = logging.getLogger("market_data")


class BhavcopyMarketResolver:
    """Resolve market cap/share price via official bhavcopy files."""

    def __init__(
        self,
        *,
        client: Optional[BhavcopyClient] = None,
        lookback_days: int = 5,
        bse_cache_dir: Optional[Path] = None,
        nse_cache_dir: Optional[Path] = None,
    ) -> None:
        self.client = client or BhavcopyClient(
            bse_local_dir=bse_cache_dir or Path("cache/bhavcopy"),
            nse_local_dir=nse_cache_dir or Path("cache/mcap"),
        )
        self.lookback_days = max(1, lookback_days)
        self._bse_cache: Dict[date, Dict[str, BSEBhavRecord]] = {}
        self._nse_cache: Dict[date, Dict[str, float]] = {}

    def resolve(
        self, symbol: str, as_of: Optional[datetime | date] = None
    ) -> Tuple[Optional[float], Optional[float]]:
        """Return (market_cap, share_price) using recent bhavcopy files."""

        normalized = (symbol or "").strip().upper()
        if not normalized:
            return None, None

        target_date = self._coerce_date(as_of)
        best_price: Optional[float] = None
        for day in self._candidate_dates(target_date):
            records = self._load_bse(day)
            if not records:
                continue
            record = records.get(normalized)
            if not record:
                continue
            share_price = record.close
            if share_price is not None and best_price is None:
                best_price = share_price

            market_cap = self._lookup_market_cap(record.isin, day)
            if market_cap is not None:
                return market_cap, share_price

        return None, best_price

    def _coerce_date(self, value: Optional[datetime | date]) -> date:
        if isinstance(value, datetime):
            return value.date()
        if isinstance(value, date):
            return value
        return datetime.utcnow().date()

    def _candidate_dates(self, start: date) -> Tuple[date, ...]:
        days = []
        current = start
        for _ in range(self.lookback_days):
            days.append(current)
            current = current - timedelta(days=1)
        return tuple(days)

    def _load_bse(self, day: date) -> Dict[str, BSEBhavRecord]:
        if day in self._bse_cache:
            return self._bse_cache[day]
        try:
            records = self.client.fetch_bse_equity(day)
        except BhavcopyError as exc:  # pragma: no cover - network guarded
            LOGGER.debug("BSE bhavcopy unavailable for %s: %s", day, exc)
            records = {}
        self._bse_cache[day] = records
        return records

    def _load_nse(self, day: date) -> Dict[str, float]:
        if day in self._nse_cache:
            return self._nse_cache[day]
        try:
            mapping = self.client.fetch_nse_market_caps(day)
        except BhavcopyError as exc:  # pragma: no cover - network guarded
            LOGGER.debug("NSE market-cap file unavailable for %s: %s", day, exc)
            mapping = {}
        self._nse_cache[day] = mapping
        return mapping

    def _lookup_market_cap(self, isin: Optional[str], day: date) -> Optional[float]:
        if not isin:
            return None
        mapping = self._load_nse(day)
        return mapping.get(isin)


__all__ = ["BhavcopyMarketResolver"]

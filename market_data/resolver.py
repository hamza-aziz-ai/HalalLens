#!/usr/bin/env python3
"""Fallback market data resolver using BSE/NSE bhavcopy files."""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Callable, Dict, Optional, Tuple

from market_data.bhavcopy import BhavcopyClient, BhavcopyError, BSEBhavRecord

LOGGER = logging.getLogger("market_data")


CacheLoader = Callable[[str, date], Optional[Tuple[Optional[float], Optional[float], Optional[str]]]]
CacheWriter = Callable[[str, date, Optional[float], Optional[float], str], None]


class BhavcopyMarketResolver:
    """Resolve market cap/share price via official bhavcopy files."""

    def __init__(
        self,
        *,
        client: Optional[BhavcopyClient] = None,
        lookback_days: int = 5,
        nse_lookback_days: Optional[int] = None,
        bse_cache_dir: Optional[Path] = None,
        nse_cache_dir: Optional[Path] = None,
        cache_loader: Optional[CacheLoader] = None,
        cache_writer: Optional[CacheWriter] = None,
    ) -> None:
        self.client = client or BhavcopyClient(
            bse_local_dir=bse_cache_dir or Path("cache/bhavcopy"),
            nse_local_dir=nse_cache_dir or Path("cache/mcap"),
        )
        self.lookback_days = max(1, lookback_days)
        self.nse_lookback_days = max(
            self.lookback_days, (nse_lookback_days or self.lookback_days)
        )
        self._bse_cache: Dict[date, Dict[str, BSEBhavRecord]] = {}
        self._nse_cache: Dict[date, Dict[str, float]] = {}
        self._cache_loader = cache_loader
        self._cache_writer = cache_writer

    def resolve(
        self, symbol: str, as_of: Optional[datetime | date] = None
    ) -> Tuple[Optional[float], Optional[float]]:
        """Return (market_cap, share_price) using recent bhavcopy files."""

        normalized = (symbol or "").strip().upper()
        if not normalized:
            return None, None

        target_date = self._coerce_date(as_of)
        best_price: Optional[float] = None
        best_price_day: Optional[date] = None
        for day in self._candidate_dates(target_date):
            cached = self._load_cached(normalized, day)
            if cached:
                cached_cap, cached_price = cached
                if cached_cap is not None or cached_price is not None:
                    LOGGER.debug("Using cached Bhavcopy quote for %s @ %s", normalized, day)
                    return cached_cap, cached_price
            records = self._load_bse(day)
            if not records:
                continue
            record = records.get(normalized)
            if not record:
                continue
            share_price = record.close
            if share_price is not None and best_price is None:
                best_price = share_price
                best_price_day = day

            market_cap = self._lookup_market_cap(record.isin, day)
            if market_cap is not None:
                self._persist_quote(normalized, day, share_price, market_cap)
                return market_cap, share_price

        if best_price is not None and best_price_day is not None:
            self._persist_quote(normalized, best_price_day, best_price, None)
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

    def _nse_candidate_dates(self, start: date) -> Tuple[date, ...]:
        days = []
        current = start
        for _ in range(self.nse_lookback_days):
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
        for candidate in self._nse_candidate_dates(day):
            mapping = self._load_nse(candidate)
            value = mapping.get(isin)
            if value is not None:
                return value
        return None

    def _load_cached(
        self, symbol: str, trade_date: date
    ) -> Optional[Tuple[Optional[float], Optional[float]]]:
        if not self._cache_loader:
            return None
        try:
            cached = self._cache_loader(symbol, trade_date)
        except Exception as exc:  # pragma: no cover - defensive
            LOGGER.debug("Bhavcopy cache loader failed: %s", exc)
            return None
        if not cached:
            return None
        market_cap, share_price, _ = cached
        return market_cap, share_price

    def _persist_quote(
        self,
        symbol: str,
        trade_date: date,
        share_price: Optional[float],
        market_cap: Optional[float],
    ) -> None:
        if not self._cache_writer:
            return
        try:
            self._cache_writer(symbol, trade_date, share_price, market_cap, "bhavcopy")
        except Exception as exc:  # pragma: no cover - defensive
            LOGGER.debug("Failed to persist Bhavcopy quote for %s@%s: %s", symbol, trade_date, exc)


__all__ = ["BhavcopyMarketResolver"]

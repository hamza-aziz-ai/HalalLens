#!/usr/bin/env python3
"""Tiingo market data helper."""

from __future__ import annotations

import logging
from typing import Optional, Tuple

import requests

from config import TIINGO_API_TOKEN

LOGGER = logging.getLogger("market_data")
SESSION = requests.Session()
BASE_URL = "https://api.tiingo.com/tiingo/daily/{ticker}"


def fetch_tiingo_quote(
    ticker: str,
    *,
    token: Optional[str] = None,
    timeout: float = 10.0,
) -> Tuple[Optional[float], Optional[float]]:
    """Return (market_cap, share_price) from Tiingo for a ticker."""

    api_token = token or TIINGO_API_TOKEN
    if not api_token:
        return None, None

    params = {"token": api_token}
    try:
        response = SESSION.get(BASE_URL.format(ticker=ticker), params=params, timeout=timeout)
        response.raise_for_status()
    except requests.RequestException as exc:
        LOGGER.warning("Tiingo market data fetch failed for %s: %s", ticker, exc)
        return None, None

    payload = response.json()
    market_cap = payload.get("marketCap")
    share_price = payload.get("last") or payload.get("prevClose")
    if share_price is None:
        share_price = payload.get("close")
    if market_cap is None and share_price is None:
        return None, None
    return market_cap, share_price


__all__ = ["fetch_tiingo_quote"]

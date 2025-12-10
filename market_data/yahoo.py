#!/usr/bin/env python3
"""Yahoo Finance quote utilities shared across API and ingestion."""

from __future__ import annotations

import logging
import time
from typing import Optional, Tuple

import requests

LOGGER = logging.getLogger("market_data")
DEFAULT_TIMEOUT = 10


def _extract_numeric(node: Optional[dict], key: str) -> Optional[float]:
    """Return the raw numeric value from a Yahoo node."""

    if not node:
        return None
    value = node.get(key)
    if isinstance(value, dict):
        return value.get("raw")
    return value


def fetch_yahoo_quote(
    ticker: str,
    *,
    session: Optional[requests.Session] = None,
    timeout: float = DEFAULT_TIMEOUT,
    backoff_seconds: int = 30,
    retries: int = 2,
) -> Tuple[Optional[float], Optional[float]]:
    """
    Return (market_cap, share_price) for a ticker using Yahoo Finance.

    Retries on HTTP 429 with sleep-based backoff.
    """

    url = f"https://query1.finance.yahoo.com/v10/finance/quoteSummary/{ticker}"
    params = {"modules": "summaryDetail,price"}
    transport = session or requests
    attempts = retries + 1

    for attempt in range(attempts):
        try:
            response = transport.get(url, params=params, timeout=timeout)
            response.raise_for_status()
            payload = response.json()
        except requests.HTTPError:
            status = getattr(response, "status_code", None)
            if status == 429 and attempt < retries:
                LOGGER.warning(
                    "Yahoo rate limit for %s; retrying in %ss (attempt %s/%s)",
                    ticker,
                    backoff_seconds,
                    attempt + 1,
                    attempts,
                )
                time.sleep(backoff_seconds)
                continue
            LOGGER.warning(
                "Market data fetch failed for %s: %s", ticker, response.text
            )
            return None, None
        except requests.RequestException as exc:
            LOGGER.warning("Market data fetch failed for %s: %s", ticker, exc)
            return None, None
        except ValueError as exc:
            LOGGER.warning("Market data parse failed for %s: %s", ticker, exc)
            return None, None
        else:
            result = payload.get("quoteSummary", {}).get("result")
            if not result:
                return None, None

            summary = result[0]
            detail = summary.get("summaryDetail") or {}
            price = summary.get("price") or {}

            market_cap = _extract_numeric(detail, "marketCap")
            share_price = _extract_numeric(price, "regularMarketPrice")
            return market_cap, share_price

    return None, None

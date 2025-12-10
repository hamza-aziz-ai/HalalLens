#!/usr/bin/env python3
"""Yahoo Finance quote utilities shared across API and ingestion."""

from __future__ import annotations

import logging
import time
from typing import Optional, Tuple

import requests

LOGGER = logging.getLogger("market_data")
DEFAULT_TIMEOUT = 10
SESSION = requests.Session()
SESSION.headers.update(
    {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Connection": "keep-alive",
    }
)
CRUMB: Optional[str] = None
CRUMB_EXPIRY: float = 0.0
CRUMB_TTL_SECONDS = 1800


def _extract_numeric(node: Optional[dict], key: str) -> Optional[float]:
    """Return the raw numeric value from a Yahoo node."""

    if not node:
        return None
    value = node.get(key)
    if isinstance(value, dict):
        return value.get("raw")
    return value


def _refresh_crumb(timeout: float) -> None:
    global CRUMB, CRUMB_EXPIRY
    attempts = 3
    for attempt in range(attempts):
        resp = SESSION.get(
            "https://query1.finance.yahoo.com/v1/test/getcrumb",
            timeout=timeout,
        )
        if resp.status_code == 200:
            crumb = resp.text.strip()
            if crumb:
                CRUMB = crumb
                CRUMB_EXPIRY = time.time() + CRUMB_TTL_SECONDS
                return
        elif resp.status_code == 429 and attempt < attempts - 1:
            delay = (attempt + 1) * 5
            LOGGER.warning(
                "Yahoo crumb rate limit; retrying in %ss (attempt %s/%s)",
                delay,
                attempt + 1,
                attempts,
            )
            time.sleep(delay)
            continue
        resp.raise_for_status()
    raise RuntimeError("Unable to fetch Yahoo crumb")


def _ensure_crumb(timeout: float) -> None:
    if CRUMB and time.time() < CRUMB_EXPIRY:
        return
    _refresh_crumb(timeout)


def fetch_yahoo_quote(
    ticker: str,
    *,
    timeout: float = DEFAULT_TIMEOUT,
    backoff_seconds: int = 30,
    retries: int = 2,
) -> Tuple[Optional[float], Optional[float]]:
    """
    Return (market_cap, share_price) for a ticker using Yahoo Finance.

    Retries on HTTP 429 with sleep-based backoff.
    """
    response = None
    url = f"https://query1.finance.yahoo.com/v10/finance/quoteSummary/{ticker}"
    attempts = retries + 1

    for attempt in range(attempts):
        _ensure_crumb(timeout)
        params = {"modules": "summaryDetail,price", "crumb": CRUMB}
        try:
            response = SESSION.get(url, params=params, timeout=timeout)
            response.raise_for_status()
            payload = response.json()
        except requests.HTTPError:
            status = getattr(response, "status_code", None)
            body = getattr(response, "text", "")
            if status == 401 and "Invalid Crumb" in body:
                LOGGER.info("Yahoo crumb expired; refreshing and retrying %s", ticker)
                _invalidate_crumb()
                continue
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


def _invalidate_crumb() -> None:
    global CRUMB, CRUMB_EXPIRY
    CRUMB = None
    CRUMB_EXPIRY = 0.0

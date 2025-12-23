#!/usr/bin/env python3
"""Indian Stock Market API helper."""

from __future__ import annotations

import functools
import logging
import math
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any, Dict, Iterable, Optional, Tuple

import requests

from config import INDIAN_API_BASE_URL, INDIAN_API_KEY

LOGGER = logging.getLogger("market_data")
SESSION = requests.Session()
# Ignore host machine proxy settings so the hosted API can be reached directly.
# Without this, requests may attempt to tunnel through a non-existent proxy and fail.
SESSION.trust_env = False

BASE_URL = INDIAN_API_BASE_URL.rstrip("/") if INDIAN_API_BASE_URL else None
API_KEY = INDIAN_API_KEY


def is_enabled() -> bool:
    """Return True when the integration is configured."""

    return bool(BASE_URL)


@dataclass
class IndianAPISnapshot:
    """Normalized response from the Indian API."""

    symbol: str
    market_cap: Optional[float]
    share_price: Optional[float]
    shares_outstanding: Optional[float]
    end_date: Optional[date]
    metrics: Dict[str, float]
    bse_code: Optional[str] = None
    nse_code: Optional[str] = None
    company_name: Optional[str] = None
    raw: Dict[str, Any] = field(default_factory=dict)


def fetch_financial_snapshot(
    symbol: str,
    *,
    target_date: Optional[datetime | date] = None,
    timeout: float = 10.0,
) -> Optional[IndianAPISnapshot]:
    """Return normalized market/financial data for a symbol."""

    if not BASE_URL:
        return None
    normalized = (symbol or "").strip().upper()
    if not normalized:
        return None

    payload = _get_stock_payload(normalized, timeout=timeout)
    if not payload:
        return None

    share_price = _preferred_price(payload)
    shares_outstanding = _extract_shares_outstanding(payload)
    market_cap = _extract_market_cap(payload, share_price, shares_outstanding)
    bse_code = _normalize_bse_code(payload.get("exchangeCodeBse"))
    nse_code = _normalize_symbol(payload.get("exchangeCodeNse"))
    company_name = payload.get("companyName")

    entry = _select_financial_entry(payload.get("financials") or [], target_date)
    entry_date = _parse_date(entry.get("EndDate")) if entry else None
    flat_metrics = _flatten_entry(entry) if entry else {}
    metrics = _build_metrics(flat_metrics)

    return IndianAPISnapshot(
        symbol=normalized,
        market_cap=market_cap,
        share_price=share_price,
        shares_outstanding=shares_outstanding,
        end_date=entry_date,
        metrics=metrics,
        bse_code=bse_code,
        nse_code=nse_code,
        company_name=company_name,
        raw=payload,
    )


def fetch_market_quote(
    symbol: str,
    *,
    timeout: float = 10.0,
) -> Tuple[Optional[float], Optional[float]]:
    """Return (market_cap, share_price) for the symbol."""

    snapshot = fetch_financial_snapshot(symbol, timeout=timeout)
    if not snapshot:
        return None, None
    return snapshot.market_cap, snapshot.share_price


@functools.lru_cache(maxsize=256)
def _get_stock_payload(symbol: str, *, timeout: float) -> Optional[Dict]:
    params = {"name": symbol}
    headers = {}
    if API_KEY:
        headers["Authorization"] = f"Bearer {API_KEY}"
        params["api_key"] = API_KEY
        headers["X-API-Key"] = API_KEY

    url = f"{BASE_URL}/stock"
    try:
        response = SESSION.get(url, params=params, headers=headers, timeout=timeout)
        response.raise_for_status()
    except requests.RequestException as exc:  # pragma: no cover - network guarded
        LOGGER.debug("Indian API stock lookup failed for %s: %s", symbol, exc)
        return None
    try:
        payload = response.json()
    except ValueError:  # pragma: no cover - unexpected payload
        return None
    if not isinstance(payload, dict):
        return None
    return payload


def _preferred_price(payload: Dict[str, any]) -> Optional[float]:
    prices = payload.get("currentPrice") or {}
    for key in ("NSE", "BSE"):
        value = _to_float(prices.get(key))
        if value is not None:
            return value
    return None


def _extract_shares_outstanding(payload: Dict[str, any]) -> Optional[float]:
    entries = payload.get("financials") or []
    for entry in entries:
        flat = _flatten_entry(entry)
        value = flat.get("totalcommonsharesoutstanding")
        if value is not None:
            return value
    return None


def _extract_market_cap(
    payload: Dict[str, any],
    share_price: Optional[float],
    shares_outstanding: Optional[float],
) -> Optional[float]:
    direct = _to_float(payload.get("marketCap"))
    if direct is not None:
        return direct
    if share_price is None or shares_outstanding is None:
        return None
    return share_price * shares_outstanding


def _select_financial_entry(
    entries: Iterable[Dict],
    target_date: Optional[datetime | date],
) -> Optional[Dict]:
    target = _ensure_date(target_date)
    best_entry: Optional[Dict] = None
    best_delta = math.inf
    for entry in entries:
        end_date = _parse_date(entry.get("EndDate")) or _parse_date(entry.get("StatementDate"))
        delta = abs((target - end_date).days) if (target and end_date) else math.inf
        if delta < best_delta:
            best_delta = delta
            best_entry = entry
    if best_entry:
        return best_entry
    return next(iter(entries), None)


def _ensure_date(value: Optional[datetime | date]) -> Optional[date]:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return None


def _flatten_entry(entry: Dict[str, any]) -> Dict[str, float]:
    flattened: Dict[str, float] = {}
    if not entry:
        return flattened
    for rows in (entry.get("stockFinancialMap") or {}).values():
        if not isinstance(rows, list):
            continue
        for row in rows:
            key = row.get("key") or row.get("displayName")
            value = _to_float(row.get("value"))
            if key and value is not None:
                flattened[_normalize_key(key)] = value
    return flattened


def _build_metrics(flat: Dict[str, float]) -> Dict[str, float]:
    metrics: Dict[str, float] = {}

    def pick(*candidates: str) -> Optional[float]:
        for cand in candidates:
            if cand in flat:
                return flat[cand]
        return None

    metrics["total_debt"] = pick("totaldebt")
    metrics["cash_equiv"] = pick("cashequivalents", "cash", "cashandbankbalances")
    metrics["accounts_receivable"] = pick("totalreceivablesnet", "accountsreceivabletradenet", "tradereceivables")
    metrics["revenue"] = pick("totalrevenue", "revenue")
    metrics["interest_income"] = pick("interestincexpnetnonoptotal", "interestincome")
    metrics["dividend_income"] = pick("totalcashdividendspaid", "dpscommonstockprimaryissue")
    metrics["non_halal_income"] = pick("othernet", "nonpermissibleincome")

    short_term = pick("shortterminvestments")
    receivables = metrics.get("accounts_receivable") or 0.0
    cash_equiv = metrics.get("cash_equiv") or 0.0
    liquid_assets = pick("liquidassets")
    if liquid_assets is None:
        liquid_assets = cash_equiv + receivables + (short_term or 0.0)
    metrics["liquid_assets"] = liquid_assets if liquid_assets else None

    if metrics.get("dividend_income") is not None:
        metrics["dividend_income"] = abs(metrics["dividend_income"])

    return {key: value for key, value in metrics.items() if value is not None}


def _parse_date(value: Optional[str]) -> Optional[date]:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value).date()
    except ValueError:
        try:
            return datetime.strptime(value, "%d %b %Y").date()
        except ValueError:
            return None


def _normalize_key(name: str) -> str:
    return "".join(ch for ch in name.lower() if ch.isalnum())


def _normalize_symbol(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    token = str(value).strip().upper()
    return token or None


def _normalize_bse_code(value: Optional[object]) -> Optional[str]:
    if value is None:
        return None
    digits = "".join(ch for ch in str(value) if ch.isdigit())
    return digits or None


def _to_float(value: Optional[object]) -> Optional[float]:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        cleaned = value.replace(",", "").strip()
        if not cleaned:
            return None
        cleaned = cleaned.replace("%", "")
        try:
            return float(cleaned)
        except ValueError:
            return None
    return None


__all__ = ["fetch_financial_snapshot", "fetch_market_quote", "is_enabled", "IndianAPISnapshot"]

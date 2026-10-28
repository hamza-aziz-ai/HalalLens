#!/usr/bin/env python3
"""Indian Stock Market API helper."""

from __future__ import annotations

import functools
import json
import logging
import math
import os
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, Iterable, Optional, Tuple, List

import requests

from config import (
    INDIAN_API_BASE_URL,
    INDIAN_API_KEY,
    INDIAN_API_MONTHLY_LIMIT,
    INDIAN_API_QUOTA_FILE,
)
from ratio_engine.amounts import coerce_amount

LOGGER = logging.getLogger("market_data")
SESSION = requests.Session()
SESSION.trust_env = False

BASE_URL = INDIAN_API_BASE_URL.rstrip("/") if INDIAN_API_BASE_URL else None
API_KEY = INDIAN_API_KEY
INR_CRORE = 10_000_000.0  # 1 crore = 10^7 rupees


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

    return snapshot_from_payload(payload, symbol=normalized, target_date=target_date)


def snapshot_from_payload(
    payload: Dict,
    *,
    symbol: Optional[str],
    target_date: Optional[datetime | date] = None,
) -> Optional[IndianAPISnapshot]:
    """Build an IndianAPISnapshot from a cached payload."""

    if not payload:
        return None
    normalized = (symbol or "").strip().upper()
    if not normalized:
        normalized = _normalize_symbol(payload.get("symbol")) or ""
    if not normalized:
        return None

    profile = payload.get("companyProfile") or {}
    share_price = _preferred_price(payload)
    shares_outstanding = _extract_shares_outstanding(payload)
    market_cap = _extract_market_cap(payload, share_price, shares_outstanding)
    bse_code = _normalize_bse_code(
        payload.get("exchangeCodeBse") or profile.get("exchangeCodeBse")
    )
    nse_code = _normalize_symbol(
        payload.get("exchangeCodeNse") or profile.get("exchangeCodeNse")
    )
    company_name = payload.get("companyName") or profile.get("companyName")

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
    return _request_json(
        "/stock",
        {"name": symbol},
        timeout=timeout,
    )


_quota_warned_month: Optional[str] = None


def _consume_quota(limit: Optional[int] = None, path: Optional[str] = None) -> bool:
    """Count one vendor request against the monthly cap; False when it is used up.

    The count lives in a small JSON file (in the persistent cache volume) so it
    survives restarts and is shared by every process on the host; an exclusive
    lock keeps concurrent processes from overspending.
    """

    global _quota_warned_month
    limit = INDIAN_API_MONTHLY_LIMIT if limit is None else limit
    if limit <= 0:
        return True
    path = path or INDIAN_API_QUOTA_FILE
    month = datetime.now(timezone.utc).strftime("%Y-%m")
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    # ponytail: one host. A quota shared by several hosts needs a database counter.
    with open(path, "a+", encoding="utf-8") as handle:
        _lock(handle)
        try:
            handle.seek(0)
            try:
                counts = json.loads(handle.read() or "{}")
            except ValueError:
                counts = {}
            used = int(counts.get(month, 0))
            if used >= limit:
                if _quota_warned_month != month:
                    LOGGER.warning(
                        "Indian API monthly limit reached (%s/%s for %s); skipping vendor calls",
                        used, limit, month,
                    )
                    _quota_warned_month = month
                return False
            counts = {month: used + 1}  # only the current month is kept
            handle.seek(0)
            handle.truncate()
            handle.write(json.dumps(counts))
            handle.flush()
            return True
        finally:
            _unlock(handle)


try:  # POSIX hosts (the Docker images); development on Windows runs unlocked.
    import fcntl

    def _lock(handle) -> None:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)

    def _unlock(handle) -> None:
        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)

except ImportError:  # pragma: no cover - Windows

    def _lock(handle) -> None:
        return None

    def _unlock(handle) -> None:
        return None


def _request_json(path: str, params: Dict[str, Any], *, timeout: float) -> Optional[Dict]:
    if not BASE_URL:
        return None
    if not _consume_quota():
        return None
    # The key goes only in the header the vendor documents (X-Api-Key). In the
    # query string it would end up in URLs, and from there in logs and proxies.
    headers: Dict[str, str] = {"X-API-Key": API_KEY} if API_KEY else {}
    url = f"{BASE_URL}{path}"
    try:
        response = SESSION.get(url, params=dict(params), headers=headers, timeout=timeout)
        response.raise_for_status()
    except requests.RequestException as exc:  # pragma: no cover - network guarded
        LOGGER.debug("Indian API request to %s failed: %s", path, exc)
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
            return value * INR_CRORE
    direct = _to_float(payload.get("totalSharesOutstanding"))
    if direct is not None:
        return direct * INR_CRORE
    return None


def _extract_market_cap(
    payload: Dict[str, any],
    share_price: Optional[float],
    shares_outstanding: Optional[float],
) -> Optional[float]:
    direct = _to_float(payload.get("marketCap"))
    if direct is not None:
        return direct * INR_CRORE
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

    currency_fields = {
        "total_debt": ["totaldebt"],
        "cash_equiv": ["cashequivalents", "cash", "cashandbankbalances"],
        "accounts_receivable": [
            "totalreceivablesnet",
            "accountsreceivabletradenet",
            "tradereceivables",
        ],
        "revenue": ["totalrevenue", "revenue"],
        "interest_income": ["interestincexpnetnonoptotal", "interestincome"],
        "non_halal_income": ["othernet", "nonpermissibleincome"],
        "liquid_assets": ["liquidassets"],
    }

    for field, candidates in currency_fields.items():
        value = pick(*candidates)
        if value is not None:
            metrics[field] = _scale_currency(value)

    short_term = pick("shortterminvestments")
    if short_term is not None:
        short_term = _scale_currency(short_term)

    receivables = metrics.get("accounts_receivable") or 0.0
    cash_equiv = metrics.get("cash_equiv") or 0.0
    liquid_assets = metrics.get("liquid_assets")
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
    if isinstance(value, str):
        value = value.replace("%", "")
    return coerce_amount(value)


def _scale_currency(value: Optional[float]) -> Optional[float]:
    if value is None:
        return None
    return value * INR_CRORE


def fetch_financial_history(
    symbol: str,
    limit: int = 12,
    *,
    timeout: float = 10.0,
) -> List[IndianAPISnapshot]:
    """Return normalized historical entries for the symbol."""

    if not BASE_URL:
        return []
    normalized = (symbol or "").strip().upper()
    if not normalized:
        return []

    payload = _get_stock_payload(normalized, timeout=timeout)
    if not payload:
        return []

    entries = payload.get("financials") or []
    if not isinstance(entries, list):
        return []

    price_series = _fetch_price_series(normalized, timeout=timeout)
    company_name = payload.get("companyName") or (
        (payload.get("companyProfile") or {}).get("companyName")
    )
    bse_code = _normalize_bse_code(
        payload.get("exchangeCodeBse")
        or (payload.get("companyProfile") or {}).get("exchangeCodeBse")
    )
    nse_code = _normalize_symbol(
        payload.get("exchangeCodeNse")
        or (payload.get("companyProfile") or {}).get("exchangeCodeNse")
    )

    snapshots: List[IndianAPISnapshot] = []
    sorted_entries = sorted(
        entries,
        key=lambda item: _parse_date((item or {}).get("EndDate"))
        or date.min,
        reverse=True,
    )
    for entry in sorted_entries:
        if len(snapshots) >= limit:
            break
        flat = _flatten_entry(entry or {})
        metrics = _build_metrics(flat)
        period_end = _parse_date(entry.get("EndDate") or entry.get("StatementDate"))
        if not period_end:
            continue
        shares = _extract_shares_from_flat(flat)
        price = _nearest_price(price_series, period_end)
        market_cap = None
        if shares and price:
            market_cap = price * shares
        snapshot = IndianAPISnapshot(
            symbol=normalized,
            market_cap=market_cap,
            share_price=price,
            shares_outstanding=shares,
            end_date=period_end,
            metrics=metrics,
            bse_code=bse_code,
            nse_code=nse_code,
            company_name=company_name,
            raw=entry,
        )
        snapshots.append(snapshot)
    return snapshots


def _fetch_price_series(symbol: str, *, timeout: float) -> Dict[date, float]:
    payload = _request_json(
        "/historical_data",
        {
            "stock_name": symbol,
            "period": "10yr",
            "filter": "price",
        },
        timeout=timeout,
    )
    if not payload:
        return {}
    datasets = payload.get("datasets") or []
    price_series: Dict[date, float] = {}
    for dataset in datasets:
        metric = (dataset or {}).get("metric") or ""
        if "price" not in metric.lower():
            continue
        for value in dataset.get("values") or []:
            if not isinstance(value, list) or len(value) < 2:
                continue
            dt = _parse_date(value[0])
            price = _to_float(value[1])
            if dt and price is not None:
                price_series[dt] = price
        break
    return price_series


def _nearest_price(series: Dict[date, float], target: date, window: int = 10) -> Optional[float]:
    if not series or not target:
        return None
    for offset in range(window + 1):
        candidate = target - timedelta(days=offset)
        if candidate in series:
            return series[candidate]
    return None


def _extract_shares_from_flat(flat: Dict[str, float]) -> Optional[float]:
    for key in ("totalcommonsharesoutstanding", "totalsharesoutstanding"):
        if key in flat:
            value = _to_float(flat[key])
            if value is not None:
                return value * INR_CRORE
    return None


__all__ = [
    "fetch_financial_snapshot",
    "fetch_financial_history",
    "fetch_market_quote",
    "is_enabled",
    "IndianAPISnapshot",
]

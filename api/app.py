#!/usr/bin/env python3
"""FastAPI service exposing the Halal ratio engine."""

from __future__ import annotations

from dataclasses import asdict
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Literal, Deque
from collections import deque

import base64
import hashlib
import hmac
import logging
import os
import secrets
import time
import requests
from urllib.parse import urlencode
from fastapi import FastAPI, HTTPException, Header, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, ConfigDict, Field

from alerts import AlertEngine, AlertEvent, WatchEntry, WatchlistStorage, EmailNotifier
from config import (
    LLM_API_KEY,
    LLM_ENDPOINT,
    LLM_MAX_TOKENS,
    LLM_MODEL,
    LLM_PROVIDER,
    LLM_TEMPERATURE,
    LLM_TIMEOUT,
    NARRATOR_MODE,
    SMTP_HOST,
    SMTP_PORT,
    SMTP_USERNAME,
    SMTP_PASSWORD,
    ALERT_EMAIL_SENDER,
    ALERT_EMAIL_RECIPIENT,
    ALLOWED_ORIGINS,
    ALLOWED_ORIGIN_REGEX,
    DEFAULT_ALLOWED_ORIGINS,
    INDIAN_API_OVERRIDE_TOLERANCE,
    AUTH_TOKEN_TTL_HOURS,
    GOOGLE_CLIENT_ID,
    GOOGLE_CLIENT_SECRET,
    GOOGLE_REDIRECT_URI,
    FRONTEND_BASE_URL,
    ADMIN_EMAILS,
    RAZORPAY_KEY_ID,
    RAZORPAY_KEY_SECRET,
    RAZORPAY_WEBHOOK_SECRET,
    SUBSCRIPTION_PLAN_CODE,
    SUBSCRIPTION_PRICE_INR,
    SUBSCRIPTION_INTERVAL_DAYS,
)
from config.logging_config import configure_logging
from narrator import NarrationEngine, NarratorConfig
from ratio_engine import (
    FinancialSnapshotInput,
    MarketDataInput,
    RatioEngine,
)
from database import BSEDatabaseManager
from market_data import (
    fetch_indian_financial_snapshot,
    fetch_indian_financial_history,
    BhavcopyMarketResolver,
    snapshot_from_indian_payload,
    indian_api_enabled, IndianAPISnapshot,
)
from crawler import BSEAnnouncementsFetcher
from etl import FinancialDataProcessor
from monitoring.notifier import OpsNotifier
from monitoring.metrics import summarize_ingestion_metrics


class FinancialSnapshotPayload(BaseModel):
    """Request payload for financial snapshot metrics."""

    model_config = ConfigDict(extra="forbid")

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


class MarketDataPayload(BaseModel):
    """Request payload for market data metrics."""

    model_config = ConfigDict(extra="forbid")

    market_cap: Optional[float] = None
    trailing_market_cap: Optional[float] = None
    share_price: Optional[float] = None
    provider: Optional[str] = None


class HalalScoreRequest(BaseModel):
    """Top-level request body for /halal-score."""

    model_config = ConfigDict(extra="forbid")

    snapshot: FinancialSnapshotPayload
    market_data: MarketDataPayload


class RatioComputationPayload(BaseModel):
    """Response schema mirroring RatioComputation dataclass."""

    value: Optional[float]
    threshold: float
    passed: Optional[bool]
    note: str
    provider: Optional[str] = None


class HalalScoreResponse(BaseModel):
    """Standardized response returned to clients."""

    symbol: str
    filing_date: datetime
    is_compliant: bool
    ratios: Dict[str, RatioComputationPayload]
    missing_inputs: Dict[str, str]
    market_cap_used: Optional[float] = None
    trailing_cap_used: Optional[float] = None
    market_data_provider: Optional[str] = None


class UserProfile(BaseModel):
    """Public information about an authenticated user."""

    id: int
    email: str
    plan: str
    subscription_status: str
    subscription_renewal: Optional[date] = None
    full_name: Optional[str] = None
    avatar_url: Optional[str] = None
    is_admin: bool = False


class AuthTokenResponse(BaseModel):
    """Returned after registration or login."""

    token: str
    expires_at: datetime
    user: UserProfile


class RegisterRequest(BaseModel):
    """Payload for user registration."""

    model_config = ConfigDict(extra="forbid")

    email: str
    password: str


class LoginRequest(BaseModel):
    """Payload for user login."""

    model_config = ConfigDict(extra="forbid")

    email: str
    password: str


class BillingPlan(BaseModel):
    code: str
    name: str
    price_inr: int
    interval_days: int
    features: List[str]
    is_active: bool


class RazorpayOrderRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    plan_code: Optional[str] = None


class RazorpayOrderResponse(BaseModel):
    key_id: str
    order_id: str
    amount: int
    currency: str
    plan_code: str
    plan_name: str
    email: str


class RazorpayVerifyRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    order_id: str
    payment_id: str
    signature: str


class SubscriptionStatusResponse(BaseModel):
    plan: str
    subscription_status: str
    subscription_renewal: Optional[datetime] = None


GOVERNANCE_METRICS = [
    "total_debt",
    "cash_equiv",
    "revenue",
    "interest_income",
    "dividend_income",
    "accounts_receivable",
    "liquid_assets",
    "non_halal_income",
]


class GovernanceMetricSet(BaseModel):
    """Metrics captured from ingestion, overrides, or structured sources."""

    label: str
    source: str
    metrics: Dict[str, Optional[float]]
    applied: Optional[bool] = None
    reviewer: Optional[str] = None
    reason: Optional[str] = None
    notes: Optional[str] = None
    updated_at: Optional[datetime] = None
    snapshot_date: Optional[date] = None
    market_cap: Optional[float] = None


class GovernanceReviewResponse(BaseModel):
    """Comparison of governance metrics across sources."""

    symbol: str
    filing_date: datetime
    ingested: GovernanceMetricSet
    override: Optional[GovernanceMetricSet] = None
    indian_api: Optional[GovernanceMetricSet] = None
    differences: Dict[str, Dict[str, Optional[float]]] = Field(default_factory=dict)


LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
configure_logging(
    "api",
    level=LOG_LEVEL,
    fmt="%(asctime)s %(levelname)s [api] %(message)s",
)


app = FastAPI(title="Halal-Lens Ratio API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS or DEFAULT_ALLOWED_ORIGINS,
    allow_origin_regex=ALLOWED_ORIGIN_REGEX,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
engine = RatioEngine()
narrator_config = NarratorConfig(
    mode=NARRATOR_MODE,
    provider=LLM_PROVIDER,
    endpoint=LLM_ENDPOINT,
    model=LLM_MODEL,
    api_key=LLM_API_KEY,
    temperature=LLM_TEMPERATURE,
    max_tokens=LLM_MAX_TOKENS,
    timeout=LLM_TIMEOUT,
)
watch_storage = WatchlistStorage(Path("cache/watchlists.json"))
alert_engine = AlertEngine(watch_storage)
try:
    DB_MANAGER: Optional[BSEDatabaseManager] = BSEDatabaseManager()
except Exception:  # pragma: no cover
    logging.getLogger("api").warning(
        "Database unavailable; DB-backed endpoints will return 503"
    )
    DB_MANAGER = None
SYMBOL_METADATA_CACHE: Dict[str, Dict[str, str]] = {}
email_notifier = EmailNotifier(
    SMTP_HOST,
    SMTP_PORT,
    SMTP_USERNAME,
    SMTP_PASSWORD,
    ALERT_EMAIL_SENDER,
    ALERT_EMAIL_RECIPIENT,
)
market_logger = logging.getLogger("market_data")
MARKET_CACHE: Dict[
    str, tuple[float, tuple[Optional[float], Optional[float], Optional[str]]]
] = {}
CACHE_TTL_SECONDS = 300
BACKOFF_SECONDS = 30
REALTIME_LOOKBACK_DAYS = 30
REALTIME_LOOKBACK_MULTIPLIER = 4
_realtime_fetcher: Optional[BSEAnnouncementsFetcher] = None
_realtime_processor: Optional[FinancialDataProcessor] = None
api_logger = logging.getLogger("api")
FEEDBACK_STATUSES = {"open", "in_review", "resolved"}
TRACKING_TOKEN_LENGTH = 18
market_notifier = OpsNotifier(component="market_data")
MARKET_FAILURES: Dict[str, int] = {}
PROVIDER_FAILURES: Dict[str, int] = {}
MARKET_FAILURE_ALERT_THRESHOLD = int(
    os.getenv("MARKET_FAILURE_ALERT_THRESHOLD", "3")
)
OPS_EVENT_HISTORY = int(os.getenv("OPS_EVENT_HISTORY", "40"))
INGESTION_METRICS_PATH = Path(
    os.getenv("INGESTION_METRICS_PATH", "logs/metrics/ingestion_metrics.jsonl")
)
narration_notifier = OpsNotifier(component="narrator")
MARKET_ALERT_EVENTS: Deque[Dict[str, Any]] = deque(maxlen=OPS_EVENT_HISTORY)
LLM_FAILURE_EVENTS: Deque[Dict[str, Any]] = deque(maxlen=OPS_EVENT_HISTORY)


def _now_iso() -> str:
    return datetime.utcnow().replace(tzinfo=timezone.utc).isoformat()


def _record_market_event(event_type: str, **payload: Any) -> None:
    entry = {"timestamp": _now_iso(), "event": event_type}
    entry.update(payload)
    MARKET_ALERT_EVENTS.append(entry)


def _record_llm_failure(symbol: str, message: str) -> None:
    LLM_FAILURE_EVENTS.append(
        {
            "timestamp": _now_iso(),
            "symbol": symbol,
            "message": message,
        }
    )


def _handle_llm_failure(evaluation, exc: Exception) -> None:
    message = str(exc)
    _record_llm_failure(evaluation.symbol, message)
    narration_notifier.notify(
        "ERROR",
        f"LLM narration failed for {evaluation.symbol}",
        details=message,
    )


narrator = NarrationEngine(
    config=narrator_config,
    failure_callback=_handle_llm_failure,
)

GOOGLE_AUTH_ENDPOINT = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_ENDPOINT = "https://oauth2.googleapis.com/token"
GOOGLE_USERINFO_ENDPOINT = "https://openidconnect.googleapis.com/v1/userinfo"
GOOGLE_STATE_TTL = timedelta(minutes=10)
GOOGLE_STATE_CACHE: Dict[str, datetime] = {}
RAZORPAY_API_BASE = "https://api.razorpay.com/v1"


def _normalize_email(value: str) -> str:
    return (value or "").strip().lower()


def _is_admin_email(email: str) -> bool:
    if not email:
        return False
    return _normalize_email(email) in set(ADMIN_EMAILS)


def _apply_admin_flag(user_row: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if not user_row:
        return user_row
    if not _is_admin_email(user_row.get("email", "")):
        return user_row
    if user_row.get("is_admin"):
        return user_row
    _get_db().set_user_admin(user_row["id"], True)
    updated = dict(user_row)
    updated["is_admin"] = True
    return updated


def _hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    derived = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 100000)
    return base64.b64encode(salt + derived).decode("ascii")


def _verify_password(password: str, stored_hash: str) -> bool:
    try:
        data = base64.b64decode(stored_hash.encode("ascii"))
    except Exception:
        return False
    if len(data) < 32:
        return False
    salt = data[:16]
    saved = data[16:]
    derived = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 100000)
    return hmac.compare_digest(saved, derived)


def _serialize_user_profile(row: Dict[str, Any]) -> UserProfile:
    return UserProfile(
        id=row["id"],
        email=row["email"],
        plan=row.get("plan", "free"),
        subscription_status=row.get("subscription_status", "inactive"),
        subscription_renewal=row.get("subscription_renewal"),
        full_name=row.get("full_name"),
        avatar_url=row.get("avatar_url"),
        is_admin=bool(row.get("is_admin")),
    )


def _issue_session(user_id: int) -> Tuple[str, datetime]:
    expires_at = datetime.now(timezone.utc) + timedelta(hours=AUTH_TOKEN_TTL_HOURS)
    token = secrets.token_urlsafe(32)
    _get_db().create_user_session(token, user_id, expires_at)
    return token, expires_at


def _extract_token(authorization: Optional[str]) -> Optional[str]:
    if not authorization:
        return None
    parts = authorization.strip().split(" ", 1)
    if len(parts) != 2:
        return None
    scheme, token = parts
    if scheme.lower() != "bearer":
        return None
    return token.strip() or None


def _redact_token(token: Optional[str]) -> str:
    if not token:
        return "<none>"
    if len(token) <= 8:
        return token
    return f"{token[:6]}...{token[-4:]}"


def _require_session(authorization: Optional[str]) -> Tuple[str, Dict[str, Any]]:
    token = _extract_token(authorization)
    if not token:
        raise HTTPException(status_code=401, detail="Authorization token required")
    session = _get_db().get_session(token)
    if not session:
        raise HTTPException(status_code=401, detail="Invalid session")
    expires_at = session.get("expires_at")
    if isinstance(expires_at, datetime):
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)
        if expires_at < datetime.now(timezone.utc):
            _get_db().delete_session(token)
            raise HTTPException(status_code=401, detail="Session expired")
    return token, session


def _razorpay_enabled() -> bool:
    return bool(RAZORPAY_KEY_ID and RAZORPAY_KEY_SECRET)


def _ensure_razorpay_enabled() -> None:
    if not _razorpay_enabled():
        raise HTTPException(status_code=503, detail="Billing not configured")


def _subscription_active(session: Dict[str, Any]) -> bool:
    if session.get("is_admin"):
        return True
    if _is_admin_email(session.get("email", "")):
        user_id = session.get("user_id")
        if user_id:
            _get_db().set_user_admin(user_id, True)
        return True
    plan = (session.get("plan") or "free").lower()
    status = (session.get("subscription_status") or "inactive").lower()
    return plan != "free" and status in {"active", "trialing"}


def _require_paid_feature(
    authorization: Optional[str], feature: str
) -> Dict[str, Any]:
    _, session = _require_session(authorization)
    if not _subscription_active(session):
        raise HTTPException(
            status_code=402,
            detail=f"{feature} requires an active subscription",
        )
    return session


def _google_oauth_enabled() -> bool:
    return bool(GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET and GOOGLE_REDIRECT_URI)


def _ensure_google_oauth_enabled() -> None:
    if not _google_oauth_enabled():
        raise HTTPException(status_code=503, detail="Google SSO not configured")


def _store_google_state(state: str) -> None:
    now = datetime.now(timezone.utc)
    GOOGLE_STATE_CACHE[state] = now
    for key, created in list(GOOGLE_STATE_CACHE.items()):
        if now - created > GOOGLE_STATE_TTL:
            GOOGLE_STATE_CACHE.pop(key, None)


def _consume_google_state(state: str) -> None:
    created = GOOGLE_STATE_CACHE.pop(state, None)
    if not created:
        raise HTTPException(status_code=400, detail="Invalid OAuth state")
    if datetime.now(timezone.utc) - created > GOOGLE_STATE_TTL:
        raise HTTPException(status_code=400, detail="Expired OAuth state")


def _build_google_authorization_url(state: str) -> str:
    params = {
        "client_id": GOOGLE_CLIENT_ID,
        "redirect_uri": GOOGLE_REDIRECT_URI,
        "response_type": "code",
        "scope": "openid email profile",
        "access_type": "offline",
        "prompt": "consent",
        "state": state,
    }
    return f"{GOOGLE_AUTH_ENDPOINT}?{urlencode(params)}"


def _exchange_google_code(code: str) -> Dict[str, Any]:
    data = {
        "code": code,
        "client_id": GOOGLE_CLIENT_ID,
        "client_secret": GOOGLE_CLIENT_SECRET,
        "redirect_uri": GOOGLE_REDIRECT_URI,
        "grant_type": "authorization_code",
    }
    try:
        resp = requests.post(GOOGLE_TOKEN_ENDPOINT, data=data, timeout=10)
        resp.raise_for_status()
    except requests.RequestException as exc:  # pragma: no cover - network error
        api_logger.error("Google token exchange failed: %s", exc)
        raise HTTPException(status_code=502, detail="Google token exchange failed")
    payload = resp.json()
    if "access_token" not in payload:
        raise HTTPException(status_code=400, detail="Google response missing access token")
    return payload


def _fetch_google_profile(access_token: str) -> Dict[str, Any]:
    headers = {"Authorization": f"Bearer {access_token}"}
    try:
        resp = requests.get(GOOGLE_USERINFO_ENDPOINT, headers=headers, timeout=10)
        resp.raise_for_status()
    except requests.RequestException as exc:  # pragma: no cover - network error
        api_logger.error("Google profile fetch failed: %s", exc)
        raise HTTPException(status_code=502, detail="Google profile fetch failed")
    return resp.json()


def _verify_razorpay_signature(message: str, signature: str) -> bool:
    if not RAZORPAY_KEY_SECRET:
        return False
    digest = hmac.new(
        RAZORPAY_KEY_SECRET.encode("utf-8"),
        message.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(digest, signature)


def _verify_razorpay_webhook(body: bytes, signature: str) -> bool:
    if not RAZORPAY_WEBHOOK_SECRET:
        return False
    digest = hmac.new(
        RAZORPAY_WEBHOOK_SECRET.encode("utf-8"),
        body,
        hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(digest, signature)


def _create_razorpay_order(
    *,
    user_id: int,
    email: str,
    plan: Dict[str, Any],
) -> Dict[str, Any]:
    _ensure_razorpay_enabled()
    amount_paise = int(plan["price_inr"]) * 100
    receipt = f"user_{user_id}_{int(time.time())}"
    payload = {
        "amount": amount_paise,
        "currency": "INR",
        "receipt": receipt,
        "notes": {
            "user_id": str(user_id),
            "plan_code": plan["code"],
            "email": email,
        },
    }
    try:
        resp = requests.post(
            f"{RAZORPAY_API_BASE}/orders",
            json=payload,
            auth=(RAZORPAY_KEY_ID, RAZORPAY_KEY_SECRET),
            timeout=15,
        )
        resp.raise_for_status()
    except requests.RequestException as exc:
        api_logger.error("Razorpay order creation failed: %s", exc)
        raise HTTPException(status_code=502, detail="Failed to create order")
    order = resp.json()
    _get_db().create_razorpay_order(
        user_id=user_id,
        order_id=order["id"],
        amount=order["amount"],
        currency=order.get("currency", "INR"),
        status=order.get("status", "created"),
        payload=order,
    )
    return order


def _build_google_redirect(token: str, expires_at: datetime) -> str:
    params = urlencode({"token": token, "expires": expires_at.isoformat()})
    base = (FRONTEND_BASE_URL or "http://localhost:3001").rstrip("/")
    return f"{base}/login?{params}#{params}"


def _placeholder_password_hash() -> str:
    return _hash_password(secrets.token_urlsafe(32))


def _get_db() -> BSEDatabaseManager:
    if DB_MANAGER is None:
        raise HTTPException(status_code=503, detail="Database unavailable")
    return DB_MANAGER


def _load_cached_bhavcopy_quote(
    symbol: str, trade_date: date
) -> Optional[Tuple[Optional[float], Optional[float], Optional[str]]]:
    try:
        return _get_db().get_bhavcopy_quote(symbol, trade_date)
    except Exception:  # pragma: no cover - defensive
        return None


def _persist_bhavcopy_quote(
    symbol: str,
    trade_date: date,
    share_price: Optional[float],
    market_cap: Optional[float],
    provider: str = "bhavcopy",
) -> None:
    try:
        _get_db().upsert_bhavcopy_quote(
            symbol=symbol,
            trade_date=trade_date,
            share_price=share_price,
            market_cap=market_cap,
            provider=provider,
        )
    except Exception:  # pragma: no cover - defensive
        return


def _record_market_issue(
    symbol: str,
    filing_date: Optional[datetime],
    issue_type: str,
    details: str,
) -> None:
    if filing_date is None:
        return
    try:
        _get_db().record_quality_issue(symbol, filing_date, issue_type, details)
    except Exception:
        pass


def _maybe_enrich_record_with_indian_api(record: Dict[str, Any]) -> None:
    """Populate missing financial metrics using the Indian market API."""

    if not indian_api_enabled():
        return
    symbol = record.get("symbol")
    filing_date = record.get("filing_date")
    if not symbol or not filing_date:
        return

    fields = [
        "total_debt",
        "cash_equiv",
        "revenue",
        "interest_income",
        "dividend_income",
        "non_halal_income",
        "accounts_receivable",
        "liquid_assets",
    ]
    missing_fields = [field for field in fields if record.get(field) is None]
    needs_market_cap = record.get("market_cap_used") is None
    has_structured_values = any(
        record.get(field) is not None for field in STRUCTURED_FIELDS
    )
    if not missing_fields and not needs_market_cap and not has_structured_values:
        return

    snapshot = None
    for candidate in _indian_api_candidates(symbol):
        snapshot = fetch_indian_financial_snapshot(candidate, target_date=filing_date)
        if snapshot:
            break
    if not snapshot:
        return

    notes = []
    overrides: Dict[str, float] = {}
    override_labels: List[str] = []
    for field in missing_fields:
        value = snapshot.metrics.get(
            "non_halal_income" if field == "non_permissible_income" else field
        )
        if value is not None:
            record[field] = value
            if field == "non_permissible_income":
                record["non_halal_income"] = value
            notes.append(field.replace("_", " "))
    if notes:
        message = f"Enriched via Indian API for {', '.join(notes)}."
        existing = record.get("governance_notes")
        record["governance_notes"] = (
            f"{existing} {message}".strip() if existing else message
        )

    if needs_market_cap and snapshot.market_cap is not None:
        record["market_cap_used"] = snapshot.market_cap
        record["market_data_provider"] = "indianapi"

    for field, column in STRUCTURED_FIELDS.items():
        if field in missing_fields:
            continue
        current = record.get(field)
        candidate = snapshot.metrics.get(column)
        if field == "non_permissible_income" and candidate is None:
            candidate = snapshot.metrics.get("non_halal_income")
        if not _needs_structured_override(current, candidate):
            continue
        record[field] = candidate
        if field == "non_permissible_income":
            record["non_halal_income"] = candidate
        overrides[column] = candidate
        override_labels.append(field.replace("_", " "))

    if overrides and symbol and filing_date:
        message = (
            "Structured metrics synchronized from Indian API (>{:.0%} delta) for {}."
        ).format(INDIAN_API_OVERRIDE_TOLERANCE, ", ".join(override_labels))
        existing = record.get("governance_notes")
        record["governance_notes"] = (
            f"{existing} {message}".strip() if existing else message
        )
        issues = record.get("quality_issues") or []
        issues.append(message)
        record["quality_issues"] = issues
        _persist_structured_override(symbol, filing_date, overrides, message)


def _reset_market_failure(symbol: str) -> None:
    MARKET_FAILURES.pop(symbol, None)


def _reset_provider_failure(provider: str, symbol: str) -> None:
    PROVIDER_FAILURES.pop(f"{provider}:{symbol}", None)


def _handle_market_failure(symbol: str, details: str) -> None:
    threshold = MARKET_FAILURE_ALERT_THRESHOLD
    if threshold <= 0:
        return
    count = MARKET_FAILURES.get(symbol, 0) + 1
    if count >= threshold:
        market_notifier.notify(
            "ERROR",
            f"Market data fetch repeatedly failing for {symbol}",
            details=details,
        )
        MARKET_FAILURES[symbol] = 0
        _record_market_event(
            "market_lookup_failure",
            symbol=symbol,
            details=details,
        )
    else:
        MARKET_FAILURES[symbol] = count


def _record_provider_failure(provider: str, symbol: str, details: str) -> None:
    threshold = MARKET_FAILURE_ALERT_THRESHOLD
    if threshold <= 0:
        return
    key = f"{provider}:{symbol}"
    count = PROVIDER_FAILURES.get(key, 0) + 1
    if count >= threshold:
        market_notifier.notify(
            "WARNING",
            f"{provider.upper()} quotes repeatedly failing for {symbol}",
            details=details,
        )
        PROVIDER_FAILURES[key] = 0
        _record_market_event(
            "provider_failure",
            provider=provider,
            symbol=symbol,
            details=details,
        )
    else:
        PROVIDER_FAILURES[key] = count


bhavcopy_resolver = BhavcopyMarketResolver(
    cache_loader=_load_cached_bhavcopy_quote, cache_writer=_persist_bhavcopy_quote
)


def _get_realtime_fetcher() -> BSEAnnouncementsFetcher:
    global _realtime_fetcher
    if _realtime_fetcher is None:
        _realtime_fetcher = BSEAnnouncementsFetcher(cache_dir=str(Path("cache")))
    return _realtime_fetcher


def _get_realtime_processor() -> FinancialDataProcessor:
    global _realtime_processor
    if _realtime_processor is None:
        _realtime_processor = FinancialDataProcessor(
            download_dir=str(Path("downloads")),
            cache_dir=str(Path("cache")),
            db_manager=_get_db(),
        )
    return _realtime_processor


def _build_indian_snapshot_record(
    normalized: str, candidate: str, snapshot
) -> Tuple[Dict[str, Any], str, str, datetime]:
    """Return a filing-style record constructed from an Indian API snapshot."""

    filing_date = snapshot.end_date or datetime.utcnow().date()
    filing_dt = datetime(
        filing_date.year, filing_date.month, filing_date.day, tzinfo=timezone.utc
    )
    symbol_code = (snapshot.bse_code or candidate or normalized or "").strip().upper()
    alias = (snapshot.nse_code or candidate or normalized or "").strip().upper()
    if not symbol_code:
        symbol_code = alias or normalized
    if not alias:
        alias = normalized

    notes = "Derived from Indian API snapshot"
    record: Dict[str, Any] = {
        "symbol": symbol_code,
        "symbol_alias": alias,
        "company_name": snapshot.company_name or normalized,
        "filing_date": filing_dt,
        "category": "Realtime Snapshot",
        "headline": "Metrics sourced from Indian market API",
        "confidence": "LOW",
        "audit_status": "indianapi",
        "governance_notes": notes,
        "quality_issues": [],
        "market_cap_used": snapshot.market_cap,
        "market_data_provider": "indianapi" if snapshot.market_cap else None,
        "trailing_cap_used": None,
    }

    metric_fields = [
        "total_debt",
        "cash_equiv",
        "revenue",
        "interest_income",
        "dividend_income",
        "non_halal_income",
        "accounts_receivable",
        "liquid_assets",
    ]
    for field in metric_fields:
        value = snapshot.metrics.get(field)
        if value is not None:
            record[field] = value

    return record, symbol_code, alias, filing_dt


def _persist_indian_api_filing(
    normalized: str,
    candidate: str,
    record: Dict[str, Any],
    snapshot,
    filing_dt: datetime,
) -> Optional[Dict[str, Any]]:
    """Store an Indian API-derived record so future lookups hit the database."""

    db = _get_db()
    symbol_code = record["symbol"]
    alias = record.get("symbol_alias") or candidate or normalized

    announcement = {
        "symbol": symbol_code,
        "symbol_alias": alias,
        "company_name": record.get("company_name"),
        "filing_date": filing_dt,
        "category": record.get("category"),
        "headline": record.get("headline"),
        "confidence": record.get("confidence"),
        "raw_json": {"source": "indianapi", "payload": snapshot.raw},
        "minio_path": None,
        "pdf_stored": False,
    }
    db.insert_announcements([announcement])

    extracted = {
        "audit_status": record.get("audit_status", "indianapi"),
        "total_debt": record.get("total_debt"),
        "cash_equiv": record.get("cash_equiv"),
        "revenue": record.get("revenue"),
        "interest_income": record.get("interest_income"),
        "dividend_income": record.get("dividend_income"),
        "non_halal_income": record.get("non_halal_income"),
        "accounts_receivable": record.get("accounts_receivable"),
        "liquid_assets": record.get("liquid_assets"),
        "governance_notes": record.get("governance_notes"),
    }
    db.insert_financial_snapshots(
        [
            {
                "symbol": symbol_code,
                "filing_date": filing_dt,
                "extracted_data": extracted,
            }
        ]
    )

    db.insert_indianapi_snapshot(
        symbol=symbol_code,
        symbol_alias=alias,
        company_name=record.get("company_name"),
        snapshot_date=filing_dt.date(),
        payload=snapshot.raw,
    )

    if record.get("market_cap_used") is not None or snapshot.share_price is not None:
        db.insert_market_snapshot(
            symbol_code,
            record.get("market_cap_used"),
            snapshot.share_price,
            provider="indianapi",
        )

    for identifier in {normalized, candidate, alias, symbol_code}:
        if identifier:
            _prime_symbol_metadata(identifier, symbol_code, alias)

    persisted = db.get_latest_filing(symbol_code) or db.get_latest_filing(alias)
    return persisted


def _fetch_latest_filing_from_bse(symbol: str) -> Optional[Dict[str, Any]]:
    """Fetch announcements for a symbol directly from BSE when cache misses."""

    fetcher = _get_realtime_fetcher()
    processor = _get_realtime_processor()
    today = datetime.utcnow().date()
    db = _get_db()
    normalized = (symbol or "").strip().upper()
    script_code = _resolve_bse_script_code(symbol)
    target_codes: List[str] = []
    if script_code:
        target_codes.append(script_code)
    if normalized and normalized not in target_codes:
        target_codes.append(normalized)

    lookbacks = [
        REALTIME_LOOKBACK_DAYS,
        REALTIME_LOOKBACK_DAYS * REALTIME_LOOKBACK_MULTIPLIER,
    ]

    for window in lookbacks:
        start = (today - timedelta(days=window)).strftime("%Y%m%d")
        end = today.strftime("%Y%m%d")
        for code in target_codes:
            try:
                announcements = fetcher.get_company_announcements(code, start, end)
            except Exception as exc:  # pragma: no cover - network failures
                api_logger.warning("Realtime BSE fetch failed for %s: %s", code, exc)
                continue

            if not announcements:
                continue

            try:
                db.insert_announcements(announcements)
            except Exception as exc:  # pragma: no cover - logged upstream
                api_logger.warning(
                    "Failed to persist realtime announcements for %s: %s", code, exc
                )

            try:
                snapshots = processor.process_announcements(announcements)
            except Exception as exc:  # pragma: no cover - extraction failures
                api_logger.warning("Realtime processing failed for %s: %s", code, exc)
                snapshots = []

            if snapshots:
                try:
                    db.insert_financial_snapshots(snapshots)
                except Exception as exc:  # pragma: no cover
                    api_logger.warning("Failed to store snapshots for %s: %s", code, exc)

            for key in target_codes:
                record = db.get_latest_filing(key)
                if record:
                    if normalized and normalized != record.get("symbol"):
                        record.setdefault("symbol_alias", normalized)
                    return record

    fallback = _build_record_from_indian_api(symbol)
    if fallback:
        return fallback
    return None


def _build_record_from_indian_api(symbol: str) -> Optional[Dict[str, Any]]:
    """Create an in-memory filing record using Indian API metrics."""

    if not indian_api_enabled():
        return None

    normalized = (symbol or "").strip().upper()
    if not normalized:
        return None

    for candidate in _indian_api_candidates(normalized):
        snapshot = fetch_indian_financial_snapshot(candidate)
        if not snapshot:
            continue

        record, _, _, filing_dt = _build_indian_snapshot_record(
            normalized, candidate, snapshot
        )

        try:
            persisted = _persist_indian_api_filing(
                normalized, candidate, record, snapshot, filing_dt
            )
            if persisted:
                return persisted
        except Exception as exc:  # pragma: no cover - defensive persistence path
            api_logger.warning(
                "Failed to persist Indian API snapshot for %s: %s", normalized, exc
            )

        record["_transient"] = True
        return record

    return None


def _get_symbol_metadata_cached(identifier: str) -> Optional[Dict[str, str]]:
    key = (identifier or "").strip().upper()
    if not key:
        return None
    if key in SYMBOL_METADATA_CACHE:
        return SYMBOL_METADATA_CACHE[key]
    metadata = _get_db().get_symbol_metadata(key)
    if metadata:
        SYMBOL_METADATA_CACHE[key] = metadata
    return metadata


def _load_quality_issues(symbol: str, filing_date: datetime) -> List[str]:
    try:
        return _get_db().get_quality_issues(symbol, filing_date)
    except Exception:
        return []


def _supplement_history_from_indian_api(
    symbol: str, limit: int, existing_count: int
) -> bool:
    if existing_count >= limit or not indian_api_enabled():
        return False

    snapshots = fetch_indian_financial_history(symbol, limit=limit * 2)
    if not snapshots:
        return False

    needed = limit - existing_count
    inserted = False
    for snapshot in snapshots:
        if needed <= 0:
            break
        if _persist_indian_history_entry(snapshot):
            inserted = True
            needed -= 1
    return inserted


def _persist_indian_history_entry(snapshot: IndianAPISnapshot) -> bool:
    if not snapshot.end_date:
        return False

    filing_dt = datetime.combine(snapshot.end_date, datetime.min.time()).replace(
        tzinfo=timezone.utc
    )
    db = _get_db()
    existing = db.get_filing(snapshot.symbol, filing_dt)
    if existing:
        return False

    announcement_payload = {
        "symbol": snapshot.symbol,
        "symbol_alias": snapshot.bse_code or snapshot.symbol,
        "company_name": snapshot.company_name or snapshot.symbol,
        "filing_date": filing_dt.isoformat(),
        "category": "Result",
        "headline": f"Financials for period ending {snapshot.end_date.isoformat()} (Indian API)",
        "confidence": "MEDIUM",
        "raw_json": snapshot.raw or {},
        "minio_path": None,
        "pdf_stored": False,
    }
    db.insert_announcements([announcement_payload])

    metrics = snapshot.metrics or {}
    extracted_data = {
        "period": snapshot.end_date.strftime("%d.%m.%Y"),
        "quarter": _quarter_label(snapshot.end_date),
        "audit_status": "indianapi",
        "total_debt": metrics.get("total_debt"),
        "cash_equiv": metrics.get("cash_equiv"),
        "revenue": metrics.get("revenue"),
        "interest_income": metrics.get("interest_income"),
        "dividend_income": metrics.get("dividend_income"),
        "accounts_receivable": metrics.get("accounts_receivable"),
        "liquid_assets": metrics.get("liquid_assets"),
        "non_halal_income": metrics.get("non_halal_income"),
        "governance_notes": "Auto-ingested from Indian Stock Market API",
    }
    db.insert_financial_snapshots(
        [
            {
                "symbol": snapshot.symbol,
                "filing_date": filing_dt.isoformat(),
                "extracted_data": extracted_data,
            }
        ]
    )

    provider = "indianapi" if snapshot.market_cap else "manual"
    if snapshot.market_cap or snapshot.share_price:
        db.insert_market_snapshot(
            symbol=snapshot.symbol,
            market_cap=snapshot.market_cap,
            share_price=snapshot.share_price,
            provider=provider,
        )

    evaluation = engine.evaluate(
        FinancialSnapshotInput(
            symbol=snapshot.symbol,
            filing_date=filing_dt,
            total_debt=metrics.get("total_debt"),
            cash_equiv=metrics.get("cash_equiv"),
            revenue=metrics.get("revenue"),
            interest_income=metrics.get("interest_income"),
            dividend_income=metrics.get("dividend_income"),
            non_permissible_income=metrics.get("non_halal_income"),
            accounts_receivable=metrics.get("accounts_receivable"),
            liquid_assets=metrics.get("liquid_assets"),
            non_halal_income=metrics.get("non_halal_income"),
        ),
        MarketDataInput(
            market_cap=snapshot.market_cap,
            share_price=snapshot.share_price,
            provider=provider,
        ),
    )

    ratios_payload = {name: asdict(comp) for name, comp in evaluation.ratios.items()}
    verdict = _derive_verdict(evaluation)
    summary = _build_summary(evaluation)

    db.upsert_filing_evaluation(
        symbol=snapshot.symbol,
        filing_date=filing_dt,
        is_compliant=evaluation.is_compliant
        if verdict != "insufficient-data"
        else None,
        ratios=ratios_payload,
        summary=summary,
        verdict=verdict,
        narration_source="indianapi",
        market_cap_used=snapshot.market_cap,
        trailing_cap_used=None,
        market_data_provider=provider,
    )
    return True


def _quarter_label(period_end: Optional[date]) -> Optional[str]:
    if not period_end:
        return None
    quarter = ((period_end.month - 1) // 3) + 1
    return f"Q{quarter} FY{period_end.year % 100:02d}"


def _normalize_candidate(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    token = value.strip().upper()
    if not token:
        return None
    for suffix in (".BO", ".NS"):
        if token.endswith(suffix):
            token = token[: -len(suffix)]
    return token or None


def _indian_api_candidates(symbol: str) -> List[str]:
    normalized = (symbol or "").strip().upper()
    metadata = _get_symbol_metadata_cached(normalized)
    alias = metadata.get("symbol_alias") if metadata else None
    primary = metadata.get("symbol") if metadata else normalized
    candidates: List[str] = []
    for candidate in (normalized, alias, primary):
        cleaned = _normalize_candidate(candidate)
        if cleaned and cleaned not in candidates:
            candidates.append(cleaned)
    return candidates or ([normalized] if normalized else [])


def _prime_symbol_metadata(
    identifier: Optional[str], symbol_code: Optional[str], alias: Optional[str]
) -> None:
    key = (identifier or "").strip().upper()
    if not key or not symbol_code:
        return
    cached = SYMBOL_METADATA_CACHE.get(key, {})
    SYMBOL_METADATA_CACHE[key] = {
        "symbol": symbol_code,
        "symbol_alias": alias or cached.get("symbol_alias"),
    }


def _resolve_bse_script_code(symbol: str) -> Optional[str]:
    normalized = (symbol or "").strip().upper()
    if not normalized:
        return None

    metadata = _get_symbol_metadata_cached(normalized)
    if metadata:
        for field in ("symbol", "symbol_alias"):
            candidate = (metadata.get(field) or "").strip().upper()
            if candidate.isdigit():
                return candidate

    if normalized.isdigit():
        return normalized

    if not indian_api_enabled():
        return normalized

    for candidate in _indian_api_candidates(normalized):
        snapshot = fetch_indian_financial_snapshot(candidate)
        if not snapshot or not snapshot.bse_code:
            continue
        code = snapshot.bse_code.strip()
        if not code.isdigit():
            continue
        alias = snapshot.nse_code or candidate
        _prime_symbol_metadata(candidate, code, alias)
        if normalized != candidate:
            _prime_symbol_metadata(normalized, code, alias)
        return code

    return normalized


@app.get("/health")
async def healthcheck() -> Dict[str, str]:
    """Liveness probe endpoint."""

    return {"status": "ok"}


class NarrationResponse(BaseModel):
    """Response model for narrator endpoint."""

    symbol: str
    filing_date: datetime
    is_compliant: bool
    summary: str
    verdict: str
    bullets: List[str]
    citations: List[str]
    source: Optional[str] = None


class WatchlistEntryPayload(BaseModel):
    """Payload to register a watchlist entry."""

    model_config = ConfigDict(extra="forbid")

    user_id: str
    symbol: str
    trigger: str = "compliance_flip"


class AlertEventPayload(BaseModel):
    """Alert event returned to clients."""

    user_id: str
    symbol: str
    trigger: str
    message: str


class AlertCheckPayload(BaseModel):
    """Payload used to evaluate compliance flip alerts."""

    symbol: str
    is_compliant: bool


class FeedbackPayload(BaseModel):
    """User feedback for filings/verdicts."""

    symbol: Optional[str] = None
    filing_date: Optional[datetime] = None
    verdict: Optional[str] = None
    message: str
    contact: Optional[str] = None
    status: str = "open"
    review_notes: Optional[str] = None
    resolved_at: Optional[datetime] = None
    resolved_by: Optional[str] = None
    created_at: Optional[datetime] = None


class FeedbackUpdatePayload(BaseModel):
    status: Literal["open", "in_review", "resolved"]
    review_notes: Optional[str] = None
    reviewer: Optional[str] = None
    trigger_recompute: bool = True


class FeedbackReportResponse(BaseModel):
    id: int
    symbol: Optional[str] = None
    filing_date: Optional[datetime] = None
    verdict: Optional[str] = None
    message: str
    contact: Optional[str] = None
    source: Optional[str] = None
    status: str
    review_notes: Optional[str] = None
    resolved_at: Optional[datetime] = None
    resolved_by: Optional[str] = None
    public_token: Optional[str] = None
    status_updated_at: datetime
    reevaluated_at: Optional[datetime] = None
    reevaluation_notes: Optional[str] = None
    created_at: datetime


class FeedbackEventResponse(BaseModel):
    id: int
    feedback_id: int
    event_type: str
    status: Optional[str] = None
    reviewer: Optional[str] = None
    details: Optional[str] = None
    source: Optional[str] = None
    created_at: datetime


class FeedbackSubmissionResponse(BaseModel):
    status: str
    ticket_id: int
    tracking_token: str


class FeedbackPublicStatusResponse(BaseModel):
    ticket_id: int
    symbol: Optional[str] = None
    filing_date: Optional[datetime] = None
    verdict: Optional[str] = None
    message: str
    status: str
    review_notes: Optional[str] = None
    created_at: datetime
    status_updated_at: datetime
    resolved_at: Optional[datetime] = None
    reevaluated_at: Optional[datetime] = None
    reevaluation_notes: Optional[str] = None
    events: List[FeedbackEventResponse] = Field(default_factory=list)


class GovernanceOverridePayload(BaseModel):
    symbol: str
    filing_date: datetime
    accounts_receivable: Optional[float] = None
    liquid_assets: Optional[float] = None
    non_halal_income: Optional[float] = None
    governance_notes: Optional[str] = None
    reviewer: Optional[str] = None
    reason: Optional[str] = None
    source: Optional[str] = "manual"


class GovernanceOverrideResponse(GovernanceOverridePayload):
    created_at: datetime
    updated_at: datetime


class FilingHistoryResponse(BaseModel):
    entries: List[FilingResponse]
    next_cursor: Optional[datetime] = None


def _coerce_float(value: Any) -> Optional[float]:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, Decimal):
        return float(value)
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _snapshot_from_record(record: Dict[str, Any]) -> Optional[FinancialSnapshotInput]:
    filing_date = record.get("filing_date")
    symbol = record.get("symbol")
    if not symbol or not filing_date:
        return None

    return FinancialSnapshotInput(
        symbol=str(symbol).strip().upper(),
        filing_date=filing_date,
        total_debt=_coerce_float(record.get("total_debt")),
        cash_equiv=_coerce_float(record.get("cash_equiv")),
        revenue=_coerce_float(record.get("revenue")),
        interest_income=_coerce_float(record.get("interest_income")),
        dividend_income=_coerce_float(record.get("dividend_income")),
        non_permissible_income=_coerce_float(record.get("non_halal_income")),
        accounts_receivable=_coerce_float(record.get("accounts_receivable")),
        liquid_assets=_coerce_float(record.get("liquid_assets")),
    )


def _market_data_for_filing(
    symbol: str, as_of: datetime
) -> tuple[Optional[float], Optional[float], Optional[str]]:
    key = symbol.strip().upper()
    db_snapshot = _get_db().get_cached_market_data(key, as_of)
    if db_snapshot:
        return db_snapshot
    return _fetch_and_cache_market_data(symbol, as_of)


def _fetch_and_cache_market_data(
    symbol: str, as_of: Optional[datetime] = None
) -> tuple[Optional[float], Optional[float], Optional[str]]:
    key = symbol.strip().upper()
    now = time.time()
    cached = MARKET_CACHE.get(key)
    if cached and now - cached[0] < CACHE_TTL_SECONDS:
        return cached[1]

    attempt_details: List[str] = []

    primary_failed = True
    if indian_api_enabled():
        for candidate in _indian_api_candidates(symbol):
            indian_snapshot = fetch_indian_financial_snapshot(
                candidate, target_date=as_of
            )
            if not indian_snapshot:
                continue
            if (
                indian_snapshot.market_cap is None
                and indian_snapshot.share_price is None
            ):
                continue
            _get_db().insert_market_snapshot(
                symbol=key,
                market_cap=indian_snapshot.market_cap,
                share_price=indian_snapshot.share_price,
                provider="indianapi",
            )
            MARKET_CACHE[key] = (
                now,
                (indian_snapshot.market_cap, indian_snapshot.share_price, "indianapi"),
            )
            primary_failed = False
            _reset_provider_failure("indianapi", key)
            _reset_market_failure(key)
            return (
                indian_snapshot.market_cap,
                indian_snapshot.share_price,
                "indianapi",
            )
        attempt_details.append(
            "Indian API lookup unavailable or returned no data for configured candidates."
        )
        _record_provider_failure(
            "indianapi", key, attempt_details[-1]
        )
    else:
        attempt_details.append("Indian API integration disabled; skipping live quote.")

    if as_of and primary_failed:
        _record_market_issue(
            key,
            as_of,
            "market_data_fetch_failed",
            "Indian API quotes unavailable; attempting Bhavcopy fallback.",
        )

    fallback_cap, fallback_price = bhavcopy_resolver.resolve(symbol, as_of)
    if fallback_cap is None and fallback_price is not None:
        cached_any = _get_db().get_cached_market_data(key)
        cached_cap = cached_any[0] if cached_any else None
        if cached_cap is not None:
            market_logger.info(
                "Using cached market cap for %s due to missing NSE data", key
            )
            fallback_cap = cached_cap

    if fallback_cap is not None:
        _get_db().insert_market_snapshot(
            symbol=key,
            market_cap=fallback_cap,
            share_price=fallback_price,
            provider="bhavcopy",
        )
        MARKET_CACHE[key] = (now, (fallback_cap, fallback_price, "bhavcopy"))
        if primary_failed and as_of:
            _record_market_issue(
                key,
                as_of,
                "market_data_fetch_failed",
                "Used Bhavcopy fallback due to upstream failure.",
            )
        _reset_provider_failure("bhavcopy", key)
        _reset_market_failure(key)
        return fallback_cap, fallback_price, "bhavcopy"

    if fallback_price is not None:
        market_logger.warning(
            "Bhavcopy returned share price but no market cap for %s", key
        )
        attempt_details.append("Bhavcopy returned share price but no market cap.")
        if as_of:
            _record_market_issue(
                key,
                as_of,
                "market_cap_missing",
                "Bhavcopy share price found but market cap unavailable",
            )
        _record_provider_failure(
            "bhavcopy", key, "Bhavcopy returned share price but no market cap."
        )
    else:
        attempt_details.append("Bhavcopy returned no quote.")
        _record_provider_failure("bhavcopy", key, attempt_details[-1])

    if as_of:
        _record_market_issue(
            key,
            as_of,
            "market_data_unavailable",
            "Indian API and Bhavcopy lookups all failed",
        )
    detail_text = "\n".join(attempt_details)
    _handle_market_failure(key, detail_text or "No providers responded.")
    raise HTTPException(status_code=404, detail="Market data unavailable")


def _ratios_payload(raw: Optional[Dict[str, Any]]) -> Optional[Dict[str, RatioComputationPayload]]:
    if not raw:
        return None
    ratios: Dict[str, RatioComputationPayload] = {}
    for name, payload in raw.items():
        if isinstance(payload, RatioComputationPayload):
            ratios[name] = payload
        else:
            ratios[name] = RatioComputationPayload(**payload)
    return ratios


FRIENDLY_LABELS = {
    "debt_to_market_cap": "Debt to market cap",
    "cash_to_market_cap": "Cash to market cap",
    "non_permissible_income_ratio": "Non-permissible income ratio",
    "receivables_to_market_cap": "Receivables to market cap",
    "liquid_assets_to_market_cap": "Liquid assets to market cap",
}
STRUCTURED_FIELDS = {
    "accounts_receivable": "accounts_receivable",
    "liquid_assets": "liquid_assets",
    "non_permissible_income": "non_halal_income",
    "non_halal_income": "non_halal_income",
}


def _build_summary(evaluation):
    failing = [
        FRIENDLY_LABELS.get(name, name)
        for name, comp in evaluation.ratios.items()
        if comp.passed is False
    ]
    if evaluation.is_compliant and not failing:
        return "All computed AAOIFI ratios are within the prescribed thresholds."
    if failing:
        return f"{', '.join(failing)} exceeded AAOIFI thresholds for this filing."
    if evaluation.missing_inputs:
        missing = ", ".join(sorted(evaluation.missing_inputs.keys()))
        return f"Insufficient data to compute all ratios (missing: {missing})."
    return "Ratios could not be computed for this filing."


def _derive_verdict(evaluation):
    has_ratios = any(comp.passed is not None for comp in evaluation.ratios.values())
    if not has_ratios:
        return "insufficient-data"
    return "compliant" if evaluation.is_compliant else "non-compliant"


def _needs_structured_override(current: Optional[float], candidate: Optional[float]) -> bool:
    if current is None or candidate is None:
        return False
    try:
        cur_val = float(current)
        cand_val = float(candidate)
    except (TypeError, ValueError):
        return False
    baseline = max(abs(cur_val), 1.0)
    return abs(cand_val - cur_val) / baseline >= INDIAN_API_OVERRIDE_TOLERANCE


def _persist_structured_override(
    symbol: str,
    filing_date: datetime,
    overrides: Dict[str, float],
    note: str,
) -> None:
    db = _get_db()
    try:
        db.upsert_governance_override(
            symbol=symbol,
            filing_date=filing_date,
            accounts_receivable=overrides.get("accounts_receivable"),
            liquid_assets=overrides.get("liquid_assets"),
            non_halal_income=overrides.get("non_halal_income"),
            governance_notes=note,
            reviewer="system",
            reason="Structured metrics from Indian API",
            source="indianapi",
        )
        db.record_quality_issue(
            symbol,
            filing_date,
            "governance_override",
            f"Structured override applied for {', '.join(overrides.keys())}",
        )
    except Exception:  # pragma: no cover - defensive
        pass


def _coerce_metric_value(value: Optional[Any]) -> Optional[float]:
    if value is None:
        return None
    if isinstance(value, Decimal):
        return float(value)
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _build_governance_metric_set(
    source_data: Optional[Dict[str, Any]],
    *,
    label: str,
    source: str,
    applied: Optional[bool] = None,
    reviewer: Optional[str] = None,
    reason: Optional[str] = None,
    notes: Optional[str] = None,
    updated_at: Optional[datetime] = None,
    snapshot_date: Optional[date] = None,
    market_cap: Optional[float] = None,
) -> Optional[GovernanceMetricSet]:
    if source_data is None:
        return None
    metrics: Dict[str, Optional[float]] = {}
    for field in GOVERNANCE_METRICS:
        value = source_data.get(field)
        if value is None and field == "non_halal_income":
            value = source_data.get("non_permissible_income")
        metrics[field] = _coerce_metric_value(value)

    return GovernanceMetricSet(
        label=label,
        source=source,
        metrics=metrics,
        applied=applied,
        reviewer=reviewer,
        reason=reason,
        notes=notes,
        updated_at=updated_at,
        snapshot_date=snapshot_date,
        market_cap=_coerce_metric_value(market_cap),
    )


def _relative_delta(base: Optional[float], other: Optional[float]) -> Optional[float]:
    if base is None or other is None:
        return None
    baseline = abs(base) or abs(other)
    if not baseline:
        return None
    return (other - base) / baseline


def _compute_metric_differences(
    ingested: Dict[str, Optional[float]],
    override: Optional[Dict[str, Optional[float]]],
    indian: Optional[Dict[str, Optional[float]]],
) -> Dict[str, Dict[str, Optional[float]]]:
    differences: Dict[str, Dict[str, Optional[float]]] = {}
    for field in GOVERNANCE_METRICS:
        entry: Dict[str, Optional[float]] = {}
        if override:
            entry["override_delta"] = _relative_delta(
                ingested.get(field), override.get(field)
            )
        if indian:
            entry["indian_delta"] = _relative_delta(
                ingested.get(field), indian.get(field)
            )
        if entry:
            differences[field] = entry
    return differences


def _load_indian_snapshot_for_filing(
    symbol: str, filing_date: datetime
) -> Optional[IndianAPISnapshot]:
    normalized = (symbol or "").strip().upper()
    if not normalized:
        return None
    db = _get_db()
    snapshot: Optional[IndianAPISnapshot] = None
    target_date = filing_date.date()
    for candidate in _indian_api_candidates(normalized):
        cached = db.get_indianapi_snapshot(candidate, target_date)
        payload = (cached or {}).get("payload") if cached else None
        if payload:
            snapshot = snapshot_from_indian_payload(
                payload, symbol=candidate, target_date=filing_date
            )
            if snapshot:
                break
        if not indian_api_enabled():
            continue
        live_snapshot = fetch_indian_financial_snapshot(
            candidate, target_date=filing_date
        )
        if live_snapshot:
            snapshot = live_snapshot
            try:
                db.insert_indianapi_snapshot(
                    symbol=live_snapshot.symbol,
                    symbol_alias=live_snapshot.nse_code or candidate,
                    company_name=live_snapshot.company_name,
                    snapshot_date=live_snapshot.end_date or target_date,
                    payload=live_snapshot.raw,
                )
            except Exception:
                pass
            break
    return snapshot


def _evaluate_request(payload: HalalScoreRequest, provider: Optional[str] = None):
    snapshot_input = FinancialSnapshotInput(**payload.snapshot.model_dump())
    market_kwargs = payload.market_data.model_dump()
    if provider:
        market_kwargs["provider"] = provider
    elif market_kwargs.get("provider"):
        provider = market_kwargs["provider"]
    market_input = MarketDataInput(**market_kwargs)

    if not (market_input.market_cap or market_input.trailing_market_cap):
        raise HTTPException(
            status_code=422,
            detail="market_cap or trailing_market_cap is required to compute ratios",
        )
    return engine.evaluate(snapshot_input, market_input)


@app.post("/halal-score", response_model=HalalScoreResponse)
async def halal_score(payload: HalalScoreRequest) -> HalalScoreResponse:
    """Compute the halal verdict for provided financial metrics."""

    evaluation = _evaluate_request(payload, provider=payload.market_data.provider or "manual")

    ratios: Dict[str, RatioComputationPayload] = {}
    for name, computation in evaluation.ratios.items():
        ratios[name] = RatioComputationPayload(**asdict(computation))

    return HalalScoreResponse(
        symbol=evaluation.symbol,
        filing_date=evaluation.filing_date,
        is_compliant=evaluation.is_compliant,
        ratios=ratios,
        missing_inputs=evaluation.missing_inputs,
        market_cap_used=payload.market_data.market_cap,
        trailing_cap_used=payload.market_data.trailing_market_cap,
        market_data_provider="manual",
    )


@app.post("/narrate", response_model=NarrationResponse)
async def narrate(
    payload: HalalScoreRequest, authorization: Optional[str] = Header(None)
) -> NarrationResponse:
    """Generate a plain-English explanation alongside the halal verdict."""

    _require_paid_feature(authorization, "Explain-Why narratives")
    evaluation = _evaluate_request(payload, provider=payload.market_data.provider or "manual")
    narration = narrator.build(evaluation)

    return NarrationResponse(
        symbol=evaluation.symbol,
        filing_date=evaluation.filing_date,
        is_compliant=evaluation.is_compliant,
        summary=narration.summary,
        verdict=narration.verdict,
        bullets=narration.bullets,
        citations=narration.citations,
        source=narration.metadata.get("source"),
    )


@app.get("/auth/google/start")
async def auth_google_start():
    """Initiate Google OAuth login."""

    _ensure_google_oauth_enabled()
    state = secrets.token_urlsafe(32)
    _store_google_state(state)
    return RedirectResponse(_build_google_authorization_url(state), status_code=307)


@app.get("/auth/google/callback")
async def auth_google_callback(code: str, state: str):
    """Handle Google's OAuth redirect, issue HalalLens session, and forward to the dashboard."""

    _ensure_google_oauth_enabled()
    _consume_google_state(state)
    token_data = _exchange_google_code(code)
    access_token = token_data.get("access_token")
    if not access_token:
        raise HTTPException(status_code=400, detail="Missing Google access token")
    profile = _fetch_google_profile(access_token)
    email = _normalize_email(profile.get("email", ""))
    sub = profile.get("sub")
    if not email or not sub:
        raise HTTPException(status_code=400, detail="Google profile missing identifiers")
    if profile.get("email_verified") is False:
        raise HTTPException(status_code=403, detail="Google email not verified")

    placeholder_hash = _placeholder_password_hash()
    user_row = _get_db().upsert_google_user(
        email=email,
        google_sub=sub,
        password_hash=placeholder_hash,
        full_name=profile.get("name"),
        avatar_url=profile.get("picture"),
    )
    user_row = _apply_admin_flag(user_row)
    _get_db().touch_user_login(user_row["id"])
    api_logger.info("Google SSO user upserted id=%s email=%s", user_row["id"], email)
    token, expires_at = _issue_session(user_row["id"])
    return RedirectResponse(_build_google_redirect(token, expires_at), status_code=302)


@app.post("/auth/register", response_model=AuthTokenResponse)
async def auth_register(payload: RegisterRequest) -> AuthTokenResponse:
    """Register a new user and issue a session token."""

    email = _normalize_email(payload.email)
    if not email or "@" not in email:
        raise HTTPException(status_code=400, detail="Valid email required")
    if len(payload.password or "") < 8:
        raise HTTPException(
            status_code=400, detail="Password must be at least 8 characters"
        )
    if _get_db().get_user_by_email(email):
        raise HTTPException(status_code=409, detail="Email already registered")

    password_hash = _hash_password(payload.password)
    user_row = _get_db().create_user(
        email=email,
        password_hash=password_hash,
        is_admin=_is_admin_email(email),
    )
    token, expires_at = _issue_session(user_row["id"])
    profile = _serialize_user_profile(user_row)
    return AuthTokenResponse(token=token, expires_at=expires_at, user=profile)


@app.post("/auth/login", response_model=AuthTokenResponse)
async def auth_login(payload: LoginRequest) -> AuthTokenResponse:
    """Authenticate an existing user."""

    email = _normalize_email(payload.email)
    user_row = _get_db().get_user_by_email(email)
    if not user_row or not _verify_password(payload.password, user_row["password_hash"]):
        raise HTTPException(status_code=401, detail="Invalid email or password")
    if user_row.get("provider") == "google":
        raise HTTPException(
            status_code=400, detail="Use Google sign-in for this account"
        )

    user_row = _apply_admin_flag(user_row)
    _get_db().touch_user_login(user_row["id"])
    token, expires_at = _issue_session(user_row["id"])
    profile = _serialize_user_profile(user_row)
    return AuthTokenResponse(token=token, expires_at=expires_at, user=profile)


@app.post("/auth/logout")
async def auth_logout(authorization: Optional[str] = Header(None)) -> Dict[str, str]:
    """Revoke the active session token."""

    token, _ = _require_session(authorization)
    _get_db().delete_session(token)
    return {"status": "logged_out"}


@app.get("/auth/me", response_model=UserProfile)
async def auth_me(authorization: Optional[str] = Header(None)) -> UserProfile:
    """Return the authenticated user's profile."""

    _, session = _require_session(authorization)
    profile_row = _get_db().get_user_by_id(session["user_id"])
    profile_row = _apply_admin_flag(profile_row) or {
        "id": session["user_id"],
        "email": session["email"],
        "plan": session.get("plan", "free"),
        "subscription_status": session.get("subscription_status", "inactive"),
        "subscription_renewal": session.get("subscription_renewal"),
        "full_name": session.get("full_name"),
        "avatar_url": session.get("avatar_url"),
        "is_admin": session.get("is_admin", False),
    }
    return _serialize_user_profile(profile_row)


@app.get("/billing/plans", response_model=List[BillingPlan])
async def list_billing_plans() -> List[BillingPlan]:
    plans = _get_db().list_subscription_plans(active_only=True)
    return [
        BillingPlan(
            code=plan["code"],
            name=plan["name"],
            price_inr=int(plan["price_inr"]),
            interval_days=int(plan["interval_days"]),
            features=list(plan.get("features") or []),
            is_active=bool(plan["is_active"]),
        )
        for plan in plans
    ]


@app.post("/billing/razorpay/order", response_model=RazorpayOrderResponse)
async def create_razorpay_order(
    payload: RazorpayOrderRequest, authorization: Optional[str] = Header(None)
) -> RazorpayOrderResponse:
    _ensure_razorpay_enabled()
    _, session = _require_session(authorization)
    plan_code = payload.plan_code or SUBSCRIPTION_PLAN_CODE
    plan = _get_db().get_subscription_plan(plan_code)
    if not plan or not plan.get("is_active"):
        raise HTTPException(status_code=404, detail="Plan not available")
    order = _create_razorpay_order(
        user_id=session["user_id"],
        email=session["email"],
        plan=plan,
    )
    return RazorpayOrderResponse(
        key_id=RAZORPAY_KEY_ID,
        order_id=order["id"],
        amount=int(order["amount"]),
        currency=order.get("currency", "INR"),
        plan_code=plan_code,
        plan_name=plan["name"],
        email=session["email"],
    )


@app.post("/billing/razorpay/verify", response_model=SubscriptionStatusResponse)
async def verify_razorpay_payment(
    payload: RazorpayVerifyRequest, authorization: Optional[str] = Header(None)
) -> SubscriptionStatusResponse:
    _ensure_razorpay_enabled()
    _, session = _require_session(authorization)
    order = _get_db().get_razorpay_order(payload.order_id)
    if not order or order.get("user_id") != session.get("user_id"):
        raise HTTPException(status_code=404, detail="Order not found")
    message = f"{payload.order_id}|{payload.payment_id}"
    if not _verify_razorpay_signature(message, payload.signature):
        raise HTTPException(status_code=400, detail="Invalid payment signature")

    plan_code = order.get("payload", {}).get("notes", {}).get("plan_code") or SUBSCRIPTION_PLAN_CODE
    plan = _get_db().get_subscription_plan(plan_code)
    if not plan:
        raise HTTPException(status_code=404, detail="Plan not found")

    now = datetime.now(timezone.utc)
    renewal = now + timedelta(days=int(plan["interval_days"]))
    _get_db().upsert_user_subscription(
        user_id=session["user_id"],
        plan_code=plan_code,
        provider="razorpay",
        status="active",
        current_period_start=now,
        current_period_end=renewal,
        cancel_at_period_end=False,
    )
    _get_db().update_user_plan(
        user_id=session["user_id"],
        plan=plan_code,
        subscription_status="active",
        subscription_renewal=renewal,
        plan_started_at=now,
    )
    _get_db().record_payment_event(
        user_id=session["user_id"],
        provider="razorpay",
        event_type="payment.verified",
        event_id=payload.payment_id,
        payload={
            "order_id": payload.order_id,
            "payment_id": payload.payment_id,
        },
    )
    return SubscriptionStatusResponse(
        plan=plan_code,
        subscription_status="active",
        subscription_renewal=renewal,
    )


@app.post("/webhooks/razorpay")
async def razorpay_webhook(request: Request) -> Dict[str, str]:
    signature = request.headers.get("X-Razorpay-Signature")
    if not signature:
        raise HTTPException(status_code=400, detail="Missing signature")
    body = await request.body()
    if not _verify_razorpay_webhook(body, signature):
        raise HTTPException(status_code=400, detail="Invalid signature")

    event = await request.json()
    event_type = event.get("event", "unknown")
    payment_entity = (
        event.get("payload", {})
        .get("payment", {})
        .get("entity", {})
    )
    order_id = payment_entity.get("order_id")
    payment_id = payment_entity.get("id")
    order = _get_db().get_razorpay_order(order_id) if order_id else None
    user_id = order.get("user_id") if order else None
    _get_db().record_payment_event(
        user_id=user_id,
        provider="razorpay",
        event_type=event_type,
        event_id=payment_id,
        payload=event,
    )
    return {"status": "ok"}


@app.post("/watchlist", response_model=WatchlistEntryPayload)
async def add_watchlist(
    entry: WatchlistEntryPayload,
    authorization: Optional[str] = Header(None),
) -> WatchlistEntryPayload:
    """Register or update a watchlist entry."""

    _require_paid_feature(authorization, "Watchlist alerts")
    watch_storage.upsert(
        WatchEntry(
            user_id=entry.user_id,
            symbol=entry.symbol,
            trigger=entry.trigger,
        )
    )
    return entry


@app.get("/watchlist/{user_id}", response_model=List[WatchlistEntryPayload])
async def list_watchlist(
    user_id: str,
    authorization: Optional[str] = Header(None),
) -> List[WatchlistEntryPayload]:
    """List watchlist entries for a user."""

    _require_paid_feature(authorization, "Watchlist alerts")
    entries = watch_storage.list(user_id=user_id)
    sanitized = []
    for entry in entries:
        data = asdict(entry)
        filtered = {
            "user_id": data["user_id"],
            "symbol": data["symbol"],
            "trigger": data.get("trigger", "compliance_flip"),
        }
        sanitized.append(WatchlistEntryPayload(**filtered))
    return sanitized


@app.post("/alerts/check", response_model=List[AlertEventPayload])
async def check_alerts(payload: AlertCheckPayload) -> List[AlertEventPayload]:
    """Evaluate compliance flip alerts for a symbol."""

    events: List[AlertEvent] = alert_engine.process_verdict(
        payload.symbol, payload.is_compliant
    )
    for event in events:
        email_notifier.send(event)
    return [AlertEventPayload(**asdict(event)) for event in events]


class FilingResponse(BaseModel):
    symbol: str
    company_name: Optional[str] = ""
    filing_date: datetime
    category: Optional[str] = ""
    headline: Optional[str] = ""
    confidence: Optional[str] = ""
    total_debt: Optional[float] = None
    cash_equiv: Optional[float] = None
    revenue: Optional[float] = None
    interest_income: Optional[float] = None
    dividend_income: Optional[float] = None
    accounts_receivable: Optional[float] = None
    liquid_assets: Optional[float] = None
    non_halal_income: Optional[float] = None
    governance_notes: Optional[str] = None
    audit_status: Optional[str] = None
    is_compliant: Optional[bool] = None
    verdict: Optional[str] = None
    summary: Optional[str] = None
    narration_source: Optional[str] = None
    ratios: Optional[Dict[str, RatioComputationPayload]] = None
    market_cap_used: Optional[float] = None
    trailing_cap_used: Optional[float] = None
    market_data_provider: Optional[str] = None
    quality_issues: List[str] = Field(default_factory=list)
    governance_override_applied: bool = False
    governance_override_source: Optional[str] = None
    governance_override_reason: Optional[str] = None
    governance_override_reviewer: Optional[str] = None
    governance_override_updated_at: Optional[datetime] = None


class MarketQuoteResponse(BaseModel):
    """Market data proxy response."""

    symbol: str
    market_cap: Optional[float] = None
    share_price: Optional[float] = None
    provider: Optional[str] = None


def _detect_quality_issues(
    snapshot: FinancialSnapshotInput, evaluation
) -> List[str]:
    """Return human-readable reasons when ratios look suspicious."""

    issues: List[str] = []
    ratios = evaluation.ratios
    npi = ratios.get("non_permissible_income_ratio")
    if npi and npi.value is not None and npi.value > 1.0:
        issues.append(
            f"Non-permissible income ratio {npi.value:.2f} (>100%) suggests unit mismatch."
        )
    cash_ratio = ratios.get("cash_to_market_cap")
    if cash_ratio and cash_ratio.value is not None and cash_ratio.value > 2.0:
        issues.append(
            f"Cash to market cap ratio {cash_ratio.value:.2f} (>200%) looks unrealistic."
        )
    if snapshot.revenue and snapshot.revenue < 1e6:
        npi_value = npi.value if npi else None
        if npi_value and npi_value > 0.5:
            issues.append(
                "Revenue figure appears too small relative to non-permissible income."
            )
    return issues


def _ensure_filing_evaluation(record: Dict[str, Any]) -> Optional[Dict[str, RatioComputationPayload]]:
    _maybe_enrich_record_with_indian_api(record)
    ratios = _ratios_payload(record.get("ratios"))
    if ratios is not None:
        return ratios

    snapshot = _snapshot_from_record(record)
    if not snapshot:
        return None

    transient = bool(record.get("_transient"))
    market_cap = record.get("market_cap_used")
    trailing = record.get("trailing_cap_used")
    provider = record.get("market_data_provider")
    share_price: Optional[float] = None

    if market_cap is None and trailing is None:
        market_cap, share_price, provider = _market_data_for_filing(
            snapshot.symbol, snapshot.filing_date
        )

    if market_cap is None and trailing is None:
        raise HTTPException(status_code=503, detail="Market data unavailable")

    evaluation = engine.evaluate(
        snapshot,
        MarketDataInput(
            market_cap=market_cap,
            trailing_market_cap=trailing,
            share_price=share_price,
            provider=provider or "manual",
        ),
    )

    verdict = _derive_verdict(evaluation)
    summary = _build_summary(evaluation)
    ratios_dict = {name: asdict(comp) for name, comp in evaluation.ratios.items()}

    quality_issues = _detect_quality_issues(snapshot, evaluation)
    if quality_issues:
        verdict = "needs-review"
        summary = "Flagged for manual review due to anomalous ratios."
        record["is_compliant"] = None

    if not transient:
        db = _get_db()
        if quality_issues:
            for issue in quality_issues:
                db.record_quality_issue(
                    snapshot.symbol, snapshot.filing_date, "ratio_anomaly", issue
                )
        else:
            db.resolve_quality_issues(
                snapshot.symbol, snapshot.filing_date, issue_types=["ratio_anomaly"]
            )
            quality_issues = _load_quality_issues(snapshot.symbol, snapshot.filing_date)

        db.upsert_filing_evaluation(
            symbol=snapshot.symbol,
            filing_date=snapshot.filing_date,
            is_compliant=evaluation.is_compliant
            if verdict != "insufficient-data"
            else None,
            ratios=ratios_dict,
            summary=summary,
            verdict=verdict,
            narration_source="api",
            market_cap_used=market_cap,
            trailing_cap_used=trailing,
            market_data_provider=provider,
        )
    else:
        record["quality_issues"] = quality_issues

    record["is_compliant"] = (
        None if quality_issues else evaluation.is_compliant
    )
    record["verdict"] = verdict
    record["summary"] = summary
    record["narration_source"] = "api"
    record["market_cap_used"] = market_cap
    record["trailing_cap_used"] = trailing
    record["market_data_provider"] = provider
    record["ratios"] = ratios_dict
    record["quality_issues"] = quality_issues

    return _ratios_payload(ratios_dict)


def _trigger_feedback_reevaluation(symbol: str, filing_date: datetime) -> str:
    """Re-run evaluation for a feedback ticket and return a note."""

    try:
        record = _get_db().get_filing(symbol, filing_date)
    except Exception:
        record = None

    if not record:
        return "Re-evaluation skipped: filing not available."

    try:
        _ensure_filing_evaluation(record)
    except HTTPException as exc:
        return f"Re-evaluation failed: {exc.detail}"
    except Exception as exc:  # pragma: no cover
        return f"Re-evaluation errored: {exc}"

    verdict = record.get("verdict") or "unknown"
    summary = record.get("summary") or "Evaluation updated."
    return f"Verdict {verdict}: {summary}"


def _auto_reevaluate_feedback_reports(
    symbol: str,
    filing_date: datetime,
    reviewer: Optional[str],
    base_note: str,
) -> None:
    """Update open feedback tickets when overrides trigger re-evaluations."""

    if not base_note:
        return
    try:
        db = _get_db()
        reports = db.list_feedback_for_filing(
            symbol, filing_date, statuses=["open", "in_review"]
        )
    except Exception:
        return
    if not reports:
        return
    message_prefix = (
        f"Auto re-evaluation via governance override ({reviewer or 'override'}). "
    )
    note = f"{message_prefix}{base_note}"
    for report in reports:
        try:
            db.record_feedback_reevaluation(report["id"], note)
        except Exception:
            continue


@app.get("/filings/recent", response_model=List[FilingResponse])
async def recent_filings(limit: int = 20) -> List[FilingResponse]:
    """Return recent filings from announcements."""

    rows = _get_db().get_recent_filings(limit=limit)
    for row in rows:
        symbol = row.get("symbol")
        filing_date = row.get("filing_date")
        if symbol and filing_date:
            row["quality_issues"] = _load_quality_issues(symbol, filing_date)
    return [FilingResponse(**row) for row in rows]


def _needs_financial_refresh(record: Dict[str, Any]) -> bool:
    """Return True if the record lacks usable financial inputs."""

    for key in (
        "total_debt",
        "cash_equiv",
        "revenue",
        "interest_income",
        "dividend_income",
    ):
        if record.get(key) is not None:
            return False
    return True


@app.get("/filings/{symbol}", response_model=FilingResponse)
async def filing_detail(
    symbol: str,
    refresh: bool = False,
    authorization: Optional[str] = Header(None),
) -> FilingResponse:
    """Return the latest filing and computed ratios for a symbol."""

    normalized = symbol.strip().upper()
    record: Optional[Dict[str, Any]] = None

    if not refresh:
        record = _get_db().get_latest_filing(normalized)

    if refresh or not record or _needs_financial_refresh(record):
        _require_paid_feature(authorization, "Instant lookup")
        latest = _fetch_latest_filing_from_bse(normalized)
        if latest:
            record = latest
        elif not record:
            record = None

    if not record:
        raise HTTPException(status_code=404, detail="No filing found for symbol")

    ratio_payload = _ensure_filing_evaluation(record)
    if ratio_payload is not None:
        record["ratios"] = ratio_payload

    record.setdefault("symbol", normalized)
    if "quality_issues" not in record or record["quality_issues"] is None:
        symbol = record.get("symbol")
        filing_date = record.get("filing_date")
        if symbol and filing_date:
            record["quality_issues"] = _load_quality_issues(symbol, filing_date)
    record.setdefault("company_name", "")
    record.setdefault("category", "")
    return FilingResponse(**record)


@app.get("/filings/{symbol}/history", response_model=FilingHistoryResponse)
async def filing_history(
    symbol: str,
    limit: int = 10,
    cursor: Optional[str] = None,
    authorization: Optional[str] = Header(None),
) -> FilingHistoryResponse:
    """Return a symbol's recent filings for context/timeline views."""

    _require_paid_feature(authorization, "History view")
    normalized = symbol.strip().upper()
    db = _get_db()
    parsed_cursor = _parse_path_datetime(cursor) if cursor else None
    effective_limit = max(1, min(limit, 40))
    rows = db.get_filing_history(
        normalized, limit=effective_limit + 1, cursor_ts=parsed_cursor
    )

    if len(rows) <= effective_limit and parsed_cursor is None:
        supplemented = _supplement_history_from_indian_api(
            normalized, effective_limit, len(rows)
        )
        if supplemented:
            rows = db.get_filing_history(
                normalized, limit=effective_limit + 1, cursor_ts=parsed_cursor
            )

    if not rows and parsed_cursor is None:
        record = _fetch_latest_filing_from_bse(normalized)
        if not record:
            raise HTTPException(status_code=404, detail="No filings found for symbol")
        rows = [record]

    has_more = len(rows) > effective_limit
    entries = rows[:effective_limit]

    responses: List[FilingResponse] = []
    for row in entries:
        if not row.get("ratios"):
            try:
                ratio_payload = _ensure_filing_evaluation(row)
                if ratio_payload is not None:
                    row["ratios"] = ratio_payload
            except HTTPException:
                # Leave ratios empty; evaluation can be retried later.
                pass
        symbol_value = row.get("symbol")
        filing_date = row.get("filing_date")
        if symbol_value and filing_date:
            row["quality_issues"] = _load_quality_issues(symbol_value, filing_date)
        responses.append(FilingResponse(**row))

    next_cursor = None
    if has_more and responses:
        next_cursor = responses[-1].filing_date

    return FilingHistoryResponse(entries=responses, next_cursor=next_cursor)


@app.get("/market-data/{symbol}", response_model=MarketQuoteResponse)
async def market_data(symbol: str) -> MarketQuoteResponse:
    """Fetch market cap/share price for a symbol via the Indian market API."""

    key = symbol.strip().upper()
    now = time.time()
    cached = MARKET_CACHE.get(key)

    provider: Optional[str] = None

    if cached and now - cached[0] < CACHE_TTL_SECONDS:
        market_cap, share_price, provider = cached[1]
    else:
        db_snapshot = _get_db().get_cached_market_data(key)
        if db_snapshot:
            market_cap, share_price, provider = db_snapshot
            MARKET_CACHE[key] = (now, db_snapshot)
        else:
            market_cap, share_price, provider = _fetch_and_cache_market_data(symbol)

    return MarketQuoteResponse(
        symbol=key, market_cap=market_cap, share_price=share_price, provider=provider
    )


@app.get("/ingestion/stats")
async def ingestion_stats() -> Dict[str, Any]:
    """Fetch counts for announcements and financial snapshots."""

    stats = _get_db().get_database_stats()
    return stats


@app.get("/ops/metrics")
async def ops_metrics() -> Dict[str, Any]:
    """Expose summarized ingestion + reliability metrics for dashboards."""

    ingestion_summary = summarize_ingestion_metrics(INGESTION_METRICS_PATH)
    return {
        "ingestion": ingestion_summary,
        "market_data": {
            "recent_alerts": list(MARKET_ALERT_EVENTS),
            "active_failures": dict(MARKET_FAILURES),
            "active_provider_failures": dict(PROVIDER_FAILURES),
        },
        "llm": {
            "recent_failures": list(LLM_FAILURE_EVENTS),
            "failure_count": len(LLM_FAILURE_EVENTS),
        },
    }


@app.post("/feedback", response_model=FeedbackSubmissionResponse, status_code=201)
async def submit_feedback(payload: FeedbackPayload) -> FeedbackSubmissionResponse:
    """Store user feedback about a filing or verdict."""

    message = payload.message.strip()
    if not message:
        raise HTTPException(status_code=400, detail="Feedback message is required")

    token = secrets.token_urlsafe(TRACKING_TOKEN_LENGTH)

    try:
        row = _get_db().insert_feedback(
            symbol=(payload.symbol or "").strip().upper() or None,
            filing_date=payload.filing_date,
            verdict=payload.verdict,
            message=message,
            contact=payload.contact,
            source="ui",
            public_token=token,
        )
    except HTTPException:
        raise
    except Exception as exc:  # pragma: no cover - logged upstream
        raise HTTPException(status_code=500, detail="Unable to store feedback") from exc

    return FeedbackSubmissionResponse(
        status="received",
        ticket_id=row["id"],
        tracking_token=row["public_token"],
    )


def _serialize_feedback(row: Dict[str, Any]) -> FeedbackReportResponse:
    return FeedbackReportResponse(**row)


def _parse_path_datetime(value: str) -> datetime:
    try:
        return datetime.fromisoformat(value)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid filing_date format") from exc


@app.get("/feedback", response_model=List[FeedbackReportResponse])
async def list_feedback(
    status: Optional[str] = None, limit: int = 50
) -> List[FeedbackReportResponse]:
    """List feedback reports for reviewers."""

    normalized = status.lower() if status else None
    if normalized and normalized not in FEEDBACK_STATUSES:
        raise HTTPException(status_code=400, detail="Invalid feedback status filter")

    rows = _get_db().list_feedback_reports(
        status=normalized,
        limit=max(1, min(limit, 200)),
    )
    return [_serialize_feedback(row) for row in rows]


@app.patch("/feedback/{feedback_id}", response_model=FeedbackReportResponse)
async def update_feedback(
    feedback_id: int, payload: FeedbackUpdatePayload
) -> FeedbackReportResponse:
    """Update a feedback report (resolve/reopen, add reviewer notes)."""

    status = payload.status.lower()
    if status not in FEEDBACK_STATUSES:
        raise HTTPException(status_code=400, detail="Invalid feedback status")

    reviewer = payload.reviewer or "dashboard"
    row = _get_db().update_feedback_report(
        feedback_id,
        status=status,
        reviewer=reviewer,
        review_notes=payload.review_notes,
    )
    if not row:
        raise HTTPException(status_code=404, detail="Feedback report not found")

    if (
        status == "resolved"
        and payload.trigger_recompute
        and row.get("symbol")
        and row.get("filing_date")
    ):
        reevaluation_note = _trigger_feedback_reevaluation(
            row["symbol"], row["filing_date"]
        )
        updated = _get_db().record_feedback_reevaluation(feedback_id, reevaluation_note)
        if updated:
            row = updated

    return _serialize_feedback(row)


@app.get("/feedback/{feedback_id}/events", response_model=List[FeedbackEventResponse])
async def feedback_events(feedback_id: int) -> List[FeedbackEventResponse]:
    """Return audit history for reviewers."""

    rows = _get_db().get_feedback_events(feedback_id)
    return [FeedbackEventResponse(**row) for row in rows]


@app.get("/feedback/status/{tracking_token}", response_model=FeedbackPublicStatusResponse)
async def feedback_status(tracking_token: str) -> FeedbackPublicStatusResponse:
    """Return sanitized status for a feedback ticket."""

    token = tracking_token.strip()
    row = _get_db().get_feedback_by_token(token)
    if not row:
        raise HTTPException(status_code=404, detail="Feedback ticket not found")

    events = _get_db().get_feedback_events_by_token(token)

    return FeedbackPublicStatusResponse(
        ticket_id=row["id"],
        symbol=row.get("symbol"),
        filing_date=row.get("filing_date"),
        verdict=row.get("verdict"),
        message=row.get("message"),
        status=row.get("status"),
        review_notes=row.get("review_notes"),
        created_at=row.get("created_at"),
        status_updated_at=row.get("status_updated_at"),
        resolved_at=row.get("resolved_at"),
        reevaluated_at=row.get("reevaluated_at"),
        reevaluation_notes=row.get("reevaluation_notes"),
        events=[FeedbackEventResponse(**event) for event in events],
    )


@app.get(
    "/governance/review/{symbol}/{filing_date}",
    response_model=GovernanceReviewResponse,
)
async def governance_review(
    symbol: str,
    filing_date: str,
    authorization: Optional[str] = Header(None),
) -> GovernanceReviewResponse:
    """Provide a reviewer-friendly comparison of governance metrics."""

    _require_paid_feature(authorization, "Governance overrides")
    parsed_date = _parse_path_datetime(filing_date)
    db = _get_db()
    record = db.get_filing(symbol.strip().upper(), parsed_date)
    if not record:
        raise HTTPException(status_code=404, detail="Filing not found")

    ingested_set = _build_governance_metric_set(
        record,
        label="Ingested metrics",
        source="ingestion",
        applied=bool(record.get("governance_override_applied")),
        reviewer=record.get("governance_override_reviewer"),
        reason=record.get("governance_override_reason"),
        notes=record.get("governance_notes"),
        updated_at=record.get("governance_override_updated_at"),
        market_cap=record.get("market_cap_used"),
    )

    override_row = db.get_governance_override(symbol.strip().upper(), parsed_date)
    override_set = (
        _build_governance_metric_set(
            override_row,
            label="Override metrics",
            source=(override_row.get("source") or "override") if override_row else "override",
            applied=True,
            reviewer=override_row.get("reviewer") if override_row else None,
            reason=override_row.get("reason") if override_row else None,
            notes=override_row.get("governance_notes") if override_row else None,
            updated_at=override_row.get("updated_at") if override_row else None,
        )
        if override_row
        else None
    )

    indian_snapshot = _load_indian_snapshot_for_filing(symbol, parsed_date)
    indian_set = (
        _build_governance_metric_set(
            indian_snapshot.metrics,
            label="Indian API snapshot",
            source="indianapi",
            applied=False,
            snapshot_date=indian_snapshot.end_date,
            market_cap=indian_snapshot.market_cap,
        )
        if indian_snapshot
        else None
    )

    differences = _compute_metric_differences(
        ingested_set.metrics,
        override_set.metrics if override_set else None,
        indian_set.metrics if indian_set else None,
    )

    return GovernanceReviewResponse(
        symbol=record.get("symbol") or symbol.strip().upper(),
        filing_date=parsed_date,
        ingested=ingested_set,
        override=override_set,
        indian_api=indian_set,
        differences=differences,
    )


@app.get("/governance/overrides", response_model=List[GovernanceOverrideResponse])
async def list_governance_overrides(
    symbol: Optional[str] = None,
    limit: int = 50,
    authorization: Optional[str] = Header(None),
) -> List[GovernanceOverrideResponse]:
    """List governance overrides applied to filings."""

    _require_paid_feature(authorization, "Governance overrides")
    rows = _get_db().list_governance_overrides(symbol=symbol, limit=max(1, min(limit, 200)))
    return [GovernanceOverrideResponse(**row) for row in rows]


@app.put("/governance/overrides", response_model=GovernanceOverrideResponse)
async def upsert_governance_override(
    payload: GovernanceOverridePayload,
    authorization: Optional[str] = Header(None),
) -> GovernanceOverrideResponse:
    """Create or update a governance override entry."""

    _require_paid_feature(authorization, "Governance overrides")
    if not any(
        [
            payload.accounts_receivable is not None,
            payload.liquid_assets is not None,
            payload.non_halal_income is not None,
            payload.governance_notes is not None,
        ]
    ):
        raise HTTPException(
            status_code=400,
            detail="Provide at least one metric to override.",
        )

    row = _get_db().upsert_governance_override(
        symbol=payload.symbol,
        filing_date=payload.filing_date,
        accounts_receivable=payload.accounts_receivable,
        liquid_assets=payload.liquid_assets,
        non_halal_income=payload.non_halal_income,
        governance_notes=payload.governance_notes,
        reviewer=payload.reviewer,
        reason=payload.reason,
        source=payload.source or "manual",
    )
    reeval_note = _trigger_feedback_reevaluation(payload.symbol, payload.filing_date)
    _auto_reevaluate_feedback_reports(
        payload.symbol,
        payload.filing_date,
        payload.reviewer,
        reeval_note,
    )
    return GovernanceOverrideResponse(**row)


@app.delete("/governance/overrides/{symbol}/{filing_date}", status_code=204)
async def delete_governance_override(
    symbol: str,
    filing_date: str,
    authorization: Optional[str] = Header(None),
) -> None:
    """Remove an override (switch back to raw extracted metrics)."""

    _require_paid_feature(authorization, "Governance overrides")
    parsed_date = _parse_path_datetime(filing_date)
    deleted = _get_db().delete_governance_override(symbol, parsed_date)
    if not deleted:
        raise HTTPException(status_code=404, detail="Override not found")


__all__ = ["app"]

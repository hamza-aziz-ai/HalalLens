#!/usr/bin/env python3
"""FastAPI service exposing the Halal ratio engine."""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import asdict
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Literal, Deque
from collections import deque

import asyncio
import hashlib
import hmac
import logging
import os
import secrets
import time
import json
import re
from concurrent.futures import ThreadPoolExecutor
import requests
from urllib.parse import urlencode, urlsplit, urlunsplit
from fastapi import FastAPI, HTTPException, Header, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, ConfigDict, Field, field_validator

from alerts import AlertEngine, AlertEvent, WatchEntry, WatchlistStorage, owner_key
from config import (
    LLM_API_KEY,
    LLM_ENDPOINT,
    LLM_MAX_TOKENS,
    LLM_MODEL,
    LLM_PROVIDER,
    LLM_TEMPERATURE,
    LLM_TIMEOUT,
    NARRATOR_MODE,
    NARRATION_TIMEOUT_SECONDS,
    NARRATION_QUEUE_TIMEOUT_SECONDS,
    NARRATION_MAX_WORKERS,
    NARRATION_MAX_CONCURRENT,
    NARRATION_CACHE_TTL_SECONDS,
    HISTORY_CACHE_TTL_SECONDS,
    RECENT_CACHE_TTL_SECONDS,
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
    RATE_LIMIT_ENABLED,
    RATE_LIMIT_LOGIN_PER_MINUTE,
    RATE_LIMIT_REGISTER_PER_HOUR,
    RATE_LIMIT_PUBLIC_PER_MINUTE,
    RATE_LIMIT_METERED_PER_MINUTE,
    RATE_LIMIT_WRITE_PER_HOUR,
    TRUST_PROXY_HEADERS,
)
from api import billing
from api.razorpay_client import RazorpayClient, RazorpayError
from api.razorpay_client import payment_created_at
from api.razorpay_client import payment_matches_order as _payment_matches_order
from api.mailer import send_email
from api.security import (
    RateLimitRule,
    SlidingWindowRateLimiter,
    dummy_verify,
    generate_session_token,
    hash_password,
    hash_session_token,
    needs_rehash,
    password_policy_error,
    redact_token,
    verify_password,
)
from config.logging_config import configure_logging
from narrator import NarrationEngine, NarratorConfig, NarrationResult
from ratio_engine import (
    FinancialSnapshotInput,
    MarketDataInput,
    RatioEngine,
    build_summary,
)
from ratio_engine.amounts import coerce_amount
from database import BSEDatabaseManager
from evaluation import quality
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


def _reject_unsupported_amount(value):
    """Reject amounts that Pydantic's float coercion would turn into a verified
    number: JSON true/false (1.0/0.0) and strings such as "1e-400" that flush to
    0.0. Only the original string is visible here; a numeric JSON literal may
    already have underflowed while decoding."""

    if isinstance(value, bool):
        raise ValueError("a boolean is not a valid number")
    if isinstance(value, str) and coerce_amount(value) is None:
        raise ValueError("not a usable amount")
    return value


class FinancialSnapshotPayload(BaseModel):
    """Request payload for financial snapshot metrics."""

    model_config = ConfigDict(extra="forbid")

    no_bool = field_validator(
        "total_debt",
        "cash_equiv",
        "revenue",
        "interest_income",
        "dividend_income",
        "non_permissible_income",
        "accounts_receivable",
        "liquid_assets",
        "non_halal_income",
        mode="before",
    )(_reject_unsupported_amount)

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

    no_bool = field_validator(
        "market_cap", "trailing_market_cap", "share_price", mode="before"
    )(_reject_unsupported_amount)

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
    is_compliant: Optional[bool]
    # Engine verdict: compliant | non-compliant | insufficient-data. is_compliant
    # is None for insufficient-data, so clients must not treat it as "false".
    screen_verdict: str
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
    subscription_renewal: Optional[datetime] = None
    trial_used: bool = False
    full_name: Optional[str] = None
    avatar_url: Optional[str] = None
    is_admin: bool = False
    email_verified: bool = False
    google_linked: bool = False


class AuthTokenResponse(BaseModel):
    """Returned after registration or login."""

    token: str
    expires_at: datetime
    user: UserProfile


class RegisterRequest(BaseModel):
    """Email-first sign-up (and password-reset request): only the address.

    The password is chosen after the mailbox is proven, on the emailed link.
    """

    model_config = ConfigDict(extra="forbid")

    email: str


class LinkStartRequest(BaseModel):
    """Fresh re-authentication before linking a Google account."""

    model_config = ConfigDict(extra="forbid")

    password: str


class LinkConfirmRequest(BaseModel):
    """The one-time code the link callback put in the account page's fragment."""

    model_config = ConfigDict(extra="forbid")

    code: str = Field(..., min_length=20, max_length=200)


class TokenPasswordRequest(BaseModel):
    """An emailed proof plus the password the mailbox owner chooses."""

    model_config = ConfigDict(extra="forbid")

    token: str = Field(..., min_length=20, max_length=200)
    password: str


class LoginRequest(BaseModel):
    """Payload for user login."""

    model_config = ConfigDict(extra="forbid")

    email: str
    password: str


class ClientLogRequest(BaseModel):
    """Payload for client-side log events."""

    model_config = ConfigDict(extra="forbid")

    level: Literal["debug", "info", "warning", "error"] = "info"
    message: str
    context: Optional[Dict[str, Any]] = None
    url: Optional[str] = None
    user_agent: Optional[str] = None


class BillingPlan(BaseModel):
    code: str
    name: str
    price_inr: int
    interval_days: int
    trial_days: int
    features: List[str]
    is_active: bool
    rank: int = 0


class EntitlementSegment(BaseModel):
    plan_code: str
    source: str
    start: datetime
    end: Optional[datetime] = None  # None: Lifetime


class LifetimeQuote(BaseModel):
    plan_code: str
    #: Amounts in paise: amount = list_amount - credit_amount.
    list_amount: int
    credit_amount: int
    amount: int
    #: Payable below one rupee: no checkout, contact support.
    blocked: bool
    #: How long an order's price holds for a payment attempt.
    valid_for_seconds: int


class EntitlementResponse(BaseModel):
    plan: str
    subscription_status: str
    #: Current and queued paid periods, in the order they run.
    segments: List[EntitlementSegment]
    #: When a purchase made now would start (end of the paid chain, or now).
    next_purchase_starts: datetime
    #: Lifetime is active or scheduled: it already covers every plan.
    purchases_blocked: bool
    #: Every plan is a one-time purchase; nothing renews automatically.
    auto_renewal: bool = False
    #: What Lifetime would cost now after upgrade credit (D-030); a preview,
    #: the order fixes the binding price. None when Lifetime is held or not sold.
    lifetime_quote: Optional[LifetimeQuote] = None


class RazorpayOrderRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    plan_code: Optional[str] = None


class TrialStartRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    plan_code: str


class RazorpayOrderResponse(BaseModel):
    key_id: str
    order_id: str
    #: Charged amount in paise (list_amount - credit_amount).
    amount: int
    currency: str
    plan_code: str
    plan_name: str
    email: str
    list_amount: int
    credit_amount: int = 0
    #: Credited orders only: the price holds for payment attempts created by then.
    price_valid_until: Optional[datetime] = None


class RazorpayOrderStatusResponse(BaseModel):
    order_id: str
    #: created | attempted (not paid yet) | paid | refund_due | refunded
    status: str
    #: refund_due only: lifetime_held | price_expired | credit_changed, and what to tell the buyer
    reason: Optional[str] = None
    message: Optional[str] = None


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

_ALLOWED_ORIGIN_RE = (
    re.compile(ALLOWED_ORIGIN_REGEX)
    if ALLOWED_ORIGIN_REGEX
    else None
)


SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Cross-Origin-Opener-Policy": "same-origin",
    "Permissions-Policy": "geolocation=(), microphone=(), camera=()",
}


@app.middleware("http")
async def add_security_headers(request: Request, call_next):
    response = await call_next(request)
    for header, value in SECURITY_HEADERS.items():
        response.headers.setdefault(header, value)
    # HSTS only makes sense once TLS terminates in front of the API (Caddy in
    # the shipped compose stack); advertising it over plain HTTP is a footgun.
    if request.url.scheme == "https" or (
        TRUST_PROXY_HEADERS
        and request.headers.get("x-forwarded-proto", "").lower() == "https"
    ):
        response.headers.setdefault(
            "Strict-Transport-Security", "max-age=31536000; includeSubDomains"
        )
    return response


def _origin_allowed(origin: str) -> bool:
    """Decide whether `origin` may receive credentialed CORS headers."""

    if not origin:
        return False
    if origin in (ALLOWED_ORIGINS or DEFAULT_ALLOWED_ORIGINS):
        return True
    if _ALLOWED_ORIGIN_RE is None:
        return False
    # fullmatch, not match: `re.match` anchors only at the start, so a pattern
    # like `https://app\.example\.com` would happily accept
    # `https://app.example.com.attacker.test` and, because credentials are
    # allowed, hand that origin the caller's bearer token.
    return bool(_ALLOWED_ORIGIN_RE.fullmatch(origin))


@app.middleware("http")
async def inject_cors_headers(request: Request, call_next):
    response = await call_next(request)
    origin = request.headers.get("origin")
    if not origin or not _origin_allowed(origin):
        return response
    if "access-control-allow-origin" not in response.headers:
        response.headers["Access-Control-Allow-Origin"] = origin
    response.headers.setdefault("Access-Control-Allow-Credentials", "true")
    response.headers.setdefault(
        "Access-Control-Allow-Methods",
        "DELETE, GET, HEAD, OPTIONS, PATCH, POST, PUT",
    )
    response.headers.setdefault(
        "Access-Control-Allow-Headers",
        "Authorization, Content-Type",
    )
    response.headers.setdefault("Vary", "Origin")
    return response

LOG_HTTP_REQUESTS = os.getenv("LOG_HTTP_REQUESTS", "true").lower() in {
    "1",
    "true",
    "yes",
    "on",
}


@app.middleware("http")
async def log_http_requests(request: Request, call_next):
    if not LOG_HTTP_REQUESTS:
        return await call_next(request)

    start = time.perf_counter()
    path = request.url.path
    method = request.method
    client_ip = request.client.host if request.client else "unknown"
    try:
        response = await call_next(request)
    except Exception:
        duration = (time.perf_counter() - start) * 1000
        api_logger.exception(
            "HTTP %s %s failed from %s after %.1fms",
            method,
            path,
            client_ip,
            duration,
        )
        raise
    duration = (time.perf_counter() - start) * 1000
    api_logger.info(
        "HTTP %s %s -> %s from %s in %.1fms",
        method,
        path,
        response.status_code,
        client_ip,
        duration,
    )
    return response
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
# Watchlists live in PostgreSQL; the lambda defers to _get_db (defined below,
# 503 when the database is unavailable) at call time.
watch_storage = WatchlistStorage(lambda: _get_db())
alert_engine = AlertEngine(watch_storage)
try:
    DB_MANAGER: Optional[BSEDatabaseManager] = BSEDatabaseManager()
except Exception:  # pragma: no cover
    logging.getLogger("api").warning(
        "Database unavailable; DB-backed endpoints will return 503"
    )
    DB_MANAGER = None
SYMBOL_METADATA_CACHE: Dict[str, Dict[str, str]] = {}
market_logger = logging.getLogger("market_data")
MARKET_CACHE: Dict[
    str, tuple[float, tuple[Optional[float], Optional[float], Optional[str]]]
] = {}
CACHE_TTL_SECONDS = 300
# Stored rows, not responses: each response is masked with current open issues.
RECENT_FILINGS_CACHE: Dict[str, tuple[float, List[Dict[str, Any]]]] = {}
HISTORY_CACHE: Dict[str, tuple[float, Tuple[List[Dict[str, Any]], Optional[datetime]]]] = {}
NARRATION_CACHE: Dict[str, tuple[float, Dict[str, Any]]] = {}
NARRATION_IN_FLIGHT: Dict[str, asyncio.Future] = {}
NARRATION_IN_FLIGHT_LOCK = asyncio.Lock()
NARRATION_EXECUTOR = ThreadPoolExecutor(max_workers=NARRATION_MAX_WORKERS)
NARRATION_SEMAPHORE = asyncio.Semaphore(NARRATION_MAX_CONCURRENT)
BACKOFF_SECONDS = 30
REALTIME_LOOKBACK_DAYS = 30
REALTIME_LOOKBACK_MULTIPLIER = 4
_realtime_fetcher: Optional[BSEAnnouncementsFetcher] = None
_realtime_processor: Optional[FinancialDataProcessor] = None
api_logger = logging.getLogger("api")
client_logger = logging.getLogger("client")
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
billing_notifier = OpsNotifier(component="billing")
MARKET_ALERT_EVENTS: Deque[Dict[str, Any]] = deque(maxlen=OPS_EVENT_HISTORY)
LLM_FAILURE_EVENTS: Deque[Dict[str, Any]] = deque(maxlen=OPS_EVENT_HISTORY)

RATE_LIMITER = SlidingWindowRateLimiter()
RATE_LIMIT_RULES: Dict[str, RateLimitRule] = {
    "auth_login": RateLimitRule(RATE_LIMIT_LOGIN_PER_MINUTE, 60.0),
    "auth_register": RateLimitRule(RATE_LIMIT_REGISTER_PER_HOUR, 3600.0),
    # Account emails (sign-up / reset links): per address, a 60 s cooldown and
    # a global cap, on top of the per-IP auth_register bucket.
    # ponytail: per-process limiter (one API worker); move to Redis to scale.
    "auth_email_address": RateLimitRule(3, 3600.0),
    "auth_email_cooldown": RateLimitRule(1, 60.0),
    "auth_email_global": RateLimitRule(200, 3600.0),
    "auth_token_confirm": RateLimitRule(20, 3600.0),
    "public_compute": RateLimitRule(RATE_LIMIT_PUBLIC_PER_MINUTE, 60.0),
    "metered": RateLimitRule(RATE_LIMIT_METERED_PER_MINUTE, 60.0),
    "anon_write": RateLimitRule(RATE_LIMIT_WRITE_PER_HOUR, 3600.0),
}


def _client_identity(request: Optional[Request]) -> str:
    """Best-effort caller identity for rate limiting.

    ``X-Forwarded-For`` is trusted only when TRUST_PROXY_HEADERS is set, because
    a client can otherwise spoof it and mint a fresh rate-limit bucket per
    request.
    """

    if request is None:
        return "unknown"
    if TRUST_PROXY_HEADERS:
        forwarded = request.headers.get("x-forwarded-for", "")
        if forwarded:
            return forwarded.split(",")[0].strip() or "unknown"
    return request.client.host if request.client else "unknown"


def _enforce_rate_limit(bucket: str, identity: str) -> None:
    """Raise 429 when ``identity`` has exhausted ``bucket``'s allowance."""

    if not RATE_LIMIT_ENABLED:
        return
    rule = RATE_LIMIT_RULES.get(bucket)
    if rule is None:
        return
    allowed, retry_after = RATE_LIMITER.check(bucket, identity, rule)
    if allowed:
        return
    api_logger.warning("Rate limit hit bucket=%s identity=%s", bucket, identity)
    raise HTTPException(
        status_code=429,
        detail="Too many requests. Please retry shortly.",
        headers={"Retry-After": str(max(1, int(retry_after) + 1))},
    )


_LOG_CONTROL_RE = re.compile(r"[\r\n\x00-\x1f\x7f]")


def _sanitize_log_text(value: Any, *, limit: int = 500) -> str:
    """Strip control characters and clamp length before logging caller input.

    Without this a client can embed newlines in a log message and inject
    convincing fake log lines into the operator's audit trail.
    """

    text = value if isinstance(value, str) else str(value)
    cleaned = _LOG_CONTROL_RE.sub(" ", text).strip()
    if len(cleaned) > limit:
        cleaned = f"{cleaned[:limit]}...[truncated]"
    return cleaned


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


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
OAUTH_FLOW_TTL = timedelta(minutes=10)
#: Short-lived HttpOnly cookie that binds a Google OAuth flow to the browser
#: that started it (D-021).
OAUTH_BROWSER_COOKIE = "hl_oauth"
RAZORPAY_API_BASE = "https://api.razorpay.com/v1"


def _normalize_email(value: str) -> str:
    return (value or "").strip().lower()


def _admin_allowlist() -> List[str]:
    """ADMIN_EMAILS, normalised. An address on it becomes admin only when its
    mailbox is proven (sign-up link, password reset or Google sign-in), never
    because someone typed it; the database methods apply this."""

    return [_normalize_email(email) for email in ADMIN_EMAILS if email]


def _hash_password(password: str) -> str:
    return hash_password(password)


def _verify_password(password: str, stored_hash: Optional[str]) -> bool:
    return verify_password(password, stored_hash)


def _serialize_user_profile(row: Dict[str, Any]) -> UserProfile:
    return UserProfile(
        id=row["id"],
        email=row["email"],
        plan=row.get("plan", "free"),
        subscription_status=row.get("subscription_status", "inactive"),
        subscription_renewal=row.get("subscription_renewal"),
        trial_used=bool(row.get("trial_used")),
        full_name=row.get("full_name"),
        avatar_url=row.get("avatar_url"),
        is_admin=bool(row.get("is_admin")),
        email_verified=bool(row.get("email_verified_at")),
        google_linked=bool(row.get("google_sub")),
    )


def _issue_session(user_id: int) -> Tuple[str, datetime]:
    """Mint a bearer token and persist only its digest."""

    expires_at = datetime.now(timezone.utc) + timedelta(hours=AUTH_TOKEN_TTL_HOURS)
    token = generate_session_token()
    _get_db().create_user_session(hash_session_token(token), user_id, expires_at)
    return token, expires_at


def _extract_token(authorization: Optional[str]) -> Optional[str]:
    # Anything that is not a string (missing header, or the FastAPI Header
    # sentinel when a handler is invoked directly) counts as "no credentials".
    if not authorization or not isinstance(authorization, str):
        return None
    parts = authorization.strip().split(" ", 1)
    if len(parts) != 2:
        return None
    scheme, token = parts
    if scheme.lower() != "bearer":
        return None
    return token.strip() or None


def _redact_token(token: Optional[str]) -> str:
    return redact_token(token)


def _require_session(authorization: Optional[str]) -> Tuple[str, Dict[str, Any]]:
    """Resolve the caller's session, or raise 401.

    Returns the *stored* token digest so callers can revoke the session without
    the raw token ever reaching the database layer.
    """

    token = _extract_token(authorization)
    if not token:
        raise HTTPException(status_code=401, detail="Authorization token required")
    token_hash = hash_session_token(token)
    session = _get_db().get_session(token_hash)
    if not session:
        raise HTTPException(status_code=401, detail="Invalid session")
    expires_at = session.get("expires_at")
    if isinstance(expires_at, datetime):
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)
        if expires_at < datetime.now(timezone.utc):
            _get_db().delete_session(token_hash)
            raise HTTPException(status_code=401, detail="Session expired")
    if not session.get("email_verified_at"):
        # Fail closed: every session belongs to a proven mailbox.
        raise HTTPException(status_code=401, detail="Email not verified")
    return token_hash, session


def _require_admin(authorization: Optional[str], feature: str) -> Dict[str, Any]:
    """Gate reviewer/operator surfaces behind the admin flag.

    A paid subscription is not sufficient here: governance overrides rewrite the
    AAOIFI inputs that every user's verdict is derived from, and the feedback
    queue exposes other users' contact details.
    """

    _, session = _require_session(authorization)  # verified email required
    if session.get("is_admin"):
        return session
    raise HTTPException(status_code=403, detail=f"{feature} requires an admin account")


def _razorpay_enabled() -> bool:
    return bool(RAZORPAY_KEY_ID and RAZORPAY_KEY_SECRET)


def _ensure_razorpay_enabled() -> None:
    if not _razorpay_enabled():
        raise HTTPException(status_code=503, detail="Billing not configured")


def _utcnow() -> datetime:
    """Clock for entitlement checks (a seam the billing tests move forward)."""

    return datetime.now(timezone.utc)


def _subscription_active(session: Dict[str, Any]) -> bool:
    """Paid access for this session (admins always).

    users.plan / subscription_renewal mirror the grants (D-024, api/billing.py).
    While the mirrored period runs, no query is needed. Once it has ended the
    next queued grant may have started, so the projection is rebuilt from the
    grants under the user lock and copied into ``session``.
    """

    if session.get("is_admin"):
        return True
    plan = (session.get("plan") or "free").lower()
    status = (session.get("subscription_status") or "inactive").lower()
    if plan == "free":
        return False
    if status in {"active", "trialing"}:
        if plan == "lifetime":
            return True
        renewal = session.get("subscription_renewal")
        if isinstance(renewal, date) and not isinstance(renewal, datetime):
            renewal = datetime.combine(renewal, datetime.min.time()).replace(tzinfo=timezone.utc)
        if isinstance(renewal, datetime):
            if renewal.tzinfo is None:
                renewal = renewal.replace(tzinfo=timezone.utc)
            if renewal > _utcnow():
                return True
    user_id = session.get("user_id")
    if not user_id:
        return False
    projection = _get_db().refresh_entitlement(user_id, billing.project)
    session.update(projection)
    return projection["plan"] != "free"


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


def _normalize_redirect_base(value: str) -> str:
    parts = urlsplit(value.strip())
    return urlunsplit((parts.scheme, parts.netloc, parts.path.rstrip("/"), "", ""))


MOBILE_REDIRECT_SCHEME = "halallens"


def _sanitize_google_redirect(value: Optional[str]) -> Optional[str]:
    """Allow-list the post-login redirect target.

    The OAuth callback hands a bearer token to whatever URL this returns, so the
    check compares parsed scheme+host+port. A plain ``startswith`` on the
    frontend base would accept ``https://app.example.com.attacker.test`` and
    leak the token to that host.
    """

    if not value:
        return None
    try:
        parts = urlsplit(value.strip())
        normalized = _normalize_redirect_base(value)
    except Exception:
        return None

    if parts.scheme == MOBILE_REDIRECT_SCHEME:
        return normalized

    frontend_base = (FRONTEND_BASE_URL or "").strip().rstrip("/")
    if not frontend_base:
        return None
    allowed = urlsplit(frontend_base)
    if parts.scheme != allowed.scheme or parts.netloc.lower() != allowed.netloc.lower():
        return None
    # Same origin: keep the path so /login, /dashboard etc. still work, but the
    # query and fragment were already stripped by _normalize_redirect_base.
    return normalized


def _oauth_cookie_path(request: Optional[Request]) -> str:
    # Behind Caddy the API lives under /api (uvicorn --root-path), and the
    # browser sends the cookie only to the Google auth routes.
    root = (request.scope.get("root_path", "") if request is not None else "").rstrip("/")
    return f"{root}/auth/google"


def _oauth_cookie_secure() -> bool:
    return (FRONTEND_BASE_URL or "").lower().startswith("https://")


def _start_oauth_flow(
    response: Response,
    request: Optional[Request],
    *,
    purpose: str,
    redirect: Optional[str] = None,
    user_id: Optional[int] = None,
    session_digest: Optional[str] = None,
) -> str:
    """Create a single-use flow bound to this browser; return Google's URL.

    The state sent to Google and a second random value set as an HttpOnly,
    SameSite=Lax cookie are stored only as digests. The callback must present
    both, once, within OAUTH_FLOW_TTL, so a state cannot be replayed or
    finished in another browser (login CSRF / session swap).
    """

    state = secrets.token_urlsafe(32)
    browser = secrets.token_urlsafe(32)
    _get_db().create_oauth_flow(
        purpose=purpose,
        state_digest=hash_session_token(state),
        browser_digest=hash_session_token(browser),
        expires_at=datetime.now(timezone.utc) + OAUTH_FLOW_TTL,
        redirect=redirect,
        user_id=user_id,
        session_digest=session_digest,
    )
    response.set_cookie(
        OAUTH_BROWSER_COOKIE,
        browser,
        max_age=int(OAUTH_FLOW_TTL.total_seconds()),
        httponly=True,
        secure=_oauth_cookie_secure(),
        samesite="lax",
        path=_oauth_cookie_path(request),
    )
    return _build_google_authorization_url(state)


def _build_google_authorization_url(state: str) -> str:
    params = {
        "client_id": GOOGLE_CLIENT_ID,
        "redirect_uri": GOOGLE_REDIRECT_URI,
        "response_type": "code",
        "scope": "openid email profile",
        # Identity only: no refresh token is requested or stored.
        "prompt": "select_account",
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
        raise HTTPException(status_code=503, detail="Google token exchange failed")
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
        raise HTTPException(status_code=503, detail="Google profile fetch failed")
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
    quote: Optional[Dict[str, Any]] = None,
    priced_at: Optional[datetime] = None,
) -> Dict[str, Any]:
    """Create the Razorpay order (outside any DB transaction), then store it with its terms.

    ``quote`` (billing.upgrade_quote, priced at ``priced_at`` by the database
    clock) makes it a credited order: Razorpay is asked for the charged
    amount and the stored order carries the pricing terms (D-030).
    """

    _ensure_razorpay_enabled()
    if quote and not quote["credit_amount"]:
        # No credit: an ordinary Lifetime order, with no 15-minute price window.
        quote = None
    list_paise = int(plan["price_inr"]) * 100
    amount_paise = int(quote["amount"]) if quote else list_paise
    # Unique per call (two checkouts in one second must not share a receipt);
    # Razorpay allows 40 characters.
    receipt = f"user_{user_id}_{secrets.token_hex(8)}"
    payload = {
        "amount": amount_paise,
        "currency": "INR",
        "receipt": receipt,
        "notes": {
            "user_id": str(user_id),
            "plan_code": plan["code"],
            "email": email,
            **({"list_amount": str(list_paise), "credit_amount": str(quote["credit_amount"])} if quote else {}),
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
        # 503, not 502, for every upstream failure: Cloudflare replaces an
        # origin 502 (even this JSON) with its own HTML error page.
        raise HTTPException(
            status_code=503, detail="Checkout is unavailable right now. Please try again shortly."
        )
    order = resp.json()
    terms: Dict[str, Any] = {"list_amount": order["amount"]}
    if quote:
        # Fail closed: a credited order is stored only for exactly the quoted charge.
        if order.get("amount") != amount_paise or str(order.get("currency") or "").upper() != "INR":
            api_logger.error(
                "Razorpay order %s came back as %s %s, quoted %s INR: not stored",
                order.get("id"), order.get("amount"), order.get("currency"), amount_paise,
            )
            raise HTTPException(
                status_code=503, detail="Checkout is unavailable right now. Please try again shortly."
            )
        terms = {
            "list_amount": list_paise,
            "credit_amount": int(quote["credit_amount"]),
            "priced_at": priced_at,
            "price_valid_until": priced_at + billing.PRICE_VALIDITY,
            "credit_version": billing.CREDIT_VERSION,
            "credit_detail": {"sources": quote["sources"]},
        }
    _get_db().create_razorpay_order(
        user_id=user_id,
        order_id=order["id"],
        amount=order["amount"],
        currency=order.get("currency", "INR"),
        status=order.get("status", "created"),
        payload=order,
        plan_code=plan["code"],
        interval_days=int(plan.get("interval_days") or 0),
        **terms,
    )
    return {**order, **terms}


def _build_google_redirect(
    token: str,
    expires_at: datetime,
    redirect_base: Optional[str] = None,
) -> str:
    """Return the post-consent redirect, passing the token in the fragment only.

    Query strings land in server access logs, browser history and the Referer
    header of any subsequent outbound request; fragments do not leave the
    browser. The frontend reads ``location.hash``.
    """

    params = urlencode({"token": token, "expires": expires_at.isoformat()})
    if redirect_base:
        return f"{redirect_base.rstrip('/')}#{params}"
    base = (FRONTEND_BASE_URL or "").rstrip("/")
    if not base:
        raise HTTPException(status_code=500, detail="FRONTEND_BASE_URL is not configured")
    return f"{base}/login#{params}"


def _build_auth_error_redirect(code: str, redirect_base: Optional[str] = None) -> str:
    """Send a failed Google sign-in back to the login page with a reason code."""

    base = (redirect_base or "").rstrip("/") or f"{(FRONTEND_BASE_URL or '').rstrip('/')}/login"
    return f"{base}#{urlencode({'error': code})}"


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


def _resolve_market_issues(
    symbol: str, filing_date: Optional[datetime], disproved: Tuple[str, ...]
) -> None:
    """Close only the market-data issue types a live lookup for this filing disproved.

    Best effort: a failed resolve leaves the issue open, which can only block.
    """

    if filing_date is None:
        return
    try:
        _get_db().resolve_quality_issues(symbol, filing_date, issue_types=list(disproved))
    except Exception:
        market_logger.warning("Could not resolve market issues for %s", symbol)


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

    filing_date = snapshot.end_date or datetime.now(timezone.utc).date()
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
    today = datetime.now(timezone.utc).date()
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


def _bound_cache(cache: Dict[str, Any], limit: int) -> None:
    """Keep a plain (non-TTL) dict cache from growing without limit."""

    if len(cache) < limit:
        return
    for key in list(cache)[: max(1, limit // 4)]:
        cache.pop(key, None)


def _get_symbol_metadata_cached(identifier: str) -> Optional[Dict[str, str]]:
    key = (identifier or "").strip().upper()
    if not key:
        return None
    if key in SYMBOL_METADATA_CACHE:
        return SYMBOL_METADATA_CACHE[key]
    metadata = _get_db().get_symbol_metadata(key)
    if metadata:
        _bound_cache(SYMBOL_METADATA_CACHE, CACHE_MAX_ENTRIES)
        SYMBOL_METADATA_CACHE[key] = metadata
    return metadata


def _load_quality_issues(symbol: str, filing_date: datetime) -> List[str]:
    """Open issues for a filing; a failed read is 503, never "no issues" (D-027)."""

    try:
        return _get_db().get_quality_issues(symbol, filing_date)
    except Exception:
        api_logger.exception("Quality issue lookup failed for %s@%s", symbol, filing_date)
        raise HTTPException(status_code=503, detail="Filing data unavailable")


def _filing_response(row: Dict[str, Any]) -> "FilingResponse":
    """Response for a stored, cached or fresh row, masked by its current open issues.

    A transient record (never stored) keeps the issues it carries; any other row
    re-reads them, so a warm cache cannot serve a result a newer issue blocks.
    """

    symbol, filing_date = row.get("symbol"), row.get("filing_date")
    if symbol and filing_date and not row.get("_transient"):
        row["quality_issues"] = _load_quality_issues(symbol, filing_date)
    quality.mask_stored(row, row.get("quality_issues") or [])
    _attach_data_updated_at(row)
    return FilingResponse(**row)


def _attach_data_updated_at(record: Dict[str, Any]) -> None:
    if not record:
        return
    candidates = []
    for key in (
        "evaluation_updated_at",
        "snapshot_parsed_at",
        "governance_override_updated_at",
    ):
        value = record.get(key)
        if isinstance(value, datetime):
            candidates.append(value)
    record["data_updated_at"] = max(candidates) if candidates else None


def _cache_get(cache: Dict[str, tuple[float, Any]], key: str) -> Optional[Any]:
    entry = cache.get(key)
    if not entry:
        return None
    expires_at, value = entry
    if expires_at < time.time():
        cache.pop(key, None)
        return None
    return value


#: Ceiling for every TTL cache in this module. Keys are symbol- and
#: pagination-derived, i.e. attacker-influenced, so an unbounded dict is a slow
#: memory leak that ends as an OOM kill on the API container.
CACHE_MAX_ENTRIES = int(os.getenv("CACHE_MAX_ENTRIES", "2000"))


def _cache_set(cache: Dict[str, tuple[float, Any]], key: str, value: Any, ttl: int) -> None:
    if ttl <= 0:
        return
    if len(cache) >= CACHE_MAX_ENTRIES and key not in cache:
        _cache_evict(cache)
    cache[key] = (time.time() + ttl, value)


def _cache_evict(cache: Dict[str, tuple[float, Any]]) -> None:
    """Drop expired entries; if that frees nothing, drop the oldest quarter."""

    now = time.time()
    expired = [key for key, (expires_at, _) in cache.items() if expires_at < now]
    for key in expired:
        cache.pop(key, None)
    if expired:
        return
    # dicts preserve insertion order, so the head is the oldest.
    for key in list(cache)[: max(1, len(cache) // 4)]:
        cache.pop(key, None)


def _narration_cache_key(evaluation) -> str:
    ratios_payload = {
        key: {
            "value": computation.value,
            "threshold": computation.threshold,
            "passed": computation.passed,
            "note": computation.note,
        }
        for key, computation in evaluation.ratios.items()
    }
    payload = {
        "symbol": evaluation.symbol,
        "filing_date": evaluation.filing_date.isoformat(),
        "verdict": evaluation.verdict,
        "ratios": ratios_payload,
    }
    raw = json.dumps(payload, sort_keys=True, default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


async def _build_narration_async(evaluation) -> "NarrationResult":
    cache_key = _narration_cache_key(evaluation)
    cached = _cache_get(NARRATION_CACHE, cache_key)
    if cached:
        return NarrationResult(**cached)

    loop = asyncio.get_running_loop()
    future: Optional[asyncio.Future] = None
    is_leader = False
    async with NARRATION_IN_FLIGHT_LOCK:
        future = NARRATION_IN_FLIGHT.get(cache_key)
        if future is None or future.done():
            future = loop.create_future()
            NARRATION_IN_FLIGHT[cache_key] = future
            is_leader = True

    if not is_leader and future is not None:
        try:
            result = await asyncio.wait_for(
                asyncio.shield(future),
                timeout=NARRATION_TIMEOUT_SECONDS,
            )
            return result
        except asyncio.TimeoutError:
            result = narrator.rule_based.build(evaluation)
            result.metadata["source"] = "rule_based_wait_timeout"
            return result
        except Exception:
            result = narrator.rule_based.build(evaluation)
            result.metadata["source"] = "rule_based_wait_error"
            return result

    async def _finalize_narration(result: "NarrationResult") -> "NarrationResult":
        _cache_set(
            NARRATION_CACHE,
            cache_key,
            {
                "summary": result.summary,
                "verdict": result.verdict,
                "bullets": result.bullets,
                "citations": result.citations,
                "metadata": result.metadata,
            },
            NARRATION_CACHE_TTL_SECONDS,
        )
        try:
            if future is not None and not future.done():
                future.set_result(result)
        finally:
            async with NARRATION_IN_FLIGHT_LOCK:
                if NARRATION_IN_FLIGHT.get(cache_key) is future:
                    NARRATION_IN_FLIGHT.pop(cache_key, None)
        return result

    if narrator.llm_engine is None:
        result = narrator.rule_based.build(evaluation)
        return await _finalize_narration(result)

    try:
        await asyncio.wait_for(
            NARRATION_SEMAPHORE.acquire(),
            timeout=NARRATION_QUEUE_TIMEOUT_SECONDS,
        )
    except asyncio.TimeoutError:
        result = narrator.rule_based.build(evaluation)
        result.metadata["source"] = "rule_based_overload"
        return await _finalize_narration(result)

    try:
        result = await asyncio.wait_for(
            loop.run_in_executor(NARRATION_EXECUTOR, narrator.build, evaluation),
            timeout=NARRATION_TIMEOUT_SECONDS,
        )
    except asyncio.TimeoutError:
        result = narrator.rule_based.build(evaluation)
        result.metadata["source"] = "rule_based_timeout"
        _record_llm_failure(evaluation.symbol, "Narration timeout fallback.")
    except Exception as exc:
        result = narrator.rule_based.build(evaluation)
        result.metadata["source"] = "rule_based_error"
        _record_llm_failure(evaluation.symbol, f"Narration error fallback: {exc}")
    finally:
        NARRATION_SEMAPHORE.release()

    return await _finalize_narration(result)


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

    snapshot_input = FinancialSnapshotInput(
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
    )
    evaluation = engine.evaluate(
        snapshot_input,
        MarketDataInput(
            market_cap=snapshot.market_cap,
            share_price=snapshot.share_price,
            provider=provider,
        ),
    )
    quality.publish_evaluation(
        db,
        snapshot_input,
        evaluation,
        filing_date=filing_dt,
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
    if key not in SYMBOL_METADATA_CACHE:
        _bound_cache(SYMBOL_METADATA_CACHE, CACHE_MAX_ENTRIES)
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


#: The reconciler runs every 15 minutes; older than this means it stopped.
BILLING_HEARTBEAT_MAX_AGE = 3600


@app.get("/health/billing")
async def billing_heartbeat(response: Response) -> Dict[str, Any]:
    """Payment reconciler heartbeat, for the uptime workflow (D-025).

    Public and read-only: only a status and an age (database clock). "ok"
    means the job ran within the hour, not that no billing item is open.
    """

    response.headers["Cache-Control"] = "no-store"
    if not _razorpay_enabled():
        return {"status": "disabled"}
    try:
        beat = _get_db().read_reconcile_heartbeat()
    except Exception:  # DB down or table missing: the probe must fail
        api_logger.exception("Billing heartbeat read failed")
        raise HTTPException(status_code=503, detail="Heartbeat unavailable")
    age = beat.get("age")
    if age is None:
        return {"status": "never", "last_success_age_seconds": None}
    age = float(age)
    stale = age > BILLING_HEARTBEAT_MAX_AGE or age < -60  # a future timestamp is wrong too
    return {"status": "stale" if stale else "ok", "last_success_age_seconds": int(age)}


class NarrationResponse(BaseModel):
    """Response model for narrator endpoint."""

    symbol: str
    filing_date: datetime
    is_compliant: Optional[bool]
    screen_verdict: str
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
    """Payload used to evaluate compliance flip alerts.

    Only the symbol: the verdict comes from the stored evaluation. A legacy
    `is_compliant` field is accepted and ignored (extra fields are dropped),
    never trusted.
    """

    symbol: str


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
    return coerce_amount(value)


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
            _bound_cache(MARKET_CACHE, CACHE_MAX_ENTRIES)
            MARKET_CACHE[key] = (
                now,
                (indian_snapshot.market_cap, indian_snapshot.share_price, "indianapi"),
            )
            primary_failed = False
            _reset_provider_failure("indianapi", key)
            _reset_market_failure(key)
            if indian_snapshot.market_cap is not None:
                _resolve_market_issues(key, as_of, quality.PRIMARY_LOOKUP_DISPROVES)
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
    # Only a cap the Bhavcopy itself returned proves anything; a stored one does not.
    bhavcopy_cap_found = fallback_cap is not None
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
        _bound_cache(MARKET_CACHE, CACHE_MAX_ENTRIES)
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
        if bhavcopy_cap_found:
            _resolve_market_issues(key, as_of, quality.FALLBACK_LOOKUP_DISPROVES)
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


STRUCTURED_FIELDS = {
    "accounts_receivable": "accounts_receivable",
    "liquid_assets": "liquid_assets",
    "non_permissible_income": "non_halal_income",
    "non_halal_income": "non_halal_income",
}


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
    return coerce_amount(value)


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
async def halal_score(
    payload: HalalScoreRequest, request: Request = None
) -> HalalScoreResponse:
    """Compute the halal verdict for provided financial metrics.

    Open by design (it scores caller-supplied numbers and reads no stored data),
    but throttled so it cannot be used as free compute.
    """

    _enforce_rate_limit("public_compute", _client_identity(request))
    evaluation = _evaluate_request(payload, provider=payload.market_data.provider or "manual")

    ratios: Dict[str, RatioComputationPayload] = {}
    for name, computation in evaluation.ratios.items():
        ratios[name] = RatioComputationPayload(**asdict(computation))

    return HalalScoreResponse(
        symbol=evaluation.symbol,
        filing_date=evaluation.filing_date,
        is_compliant=evaluation.is_compliant,
        screen_verdict=evaluation.verdict,
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

    session = _require_paid_feature(authorization, "Explain-Why narratives")
    _enforce_rate_limit("metered", f"user:{session['user_id']}")
    evaluation = _evaluate_request(payload, provider=payload.market_data.provider or "manual")
    narration = await _build_narration_async(evaluation)

    return NarrationResponse(
        symbol=evaluation.symbol,
        filing_date=evaluation.filing_date,
        is_compliant=evaluation.is_compliant,
        screen_verdict=evaluation.verdict,
        summary=narration.summary,
        verdict=narration.verdict,
        bullets=narration.bullets,
        citations=narration.citations,
        source=narration.metadata.get("source"),
    )


@app.get("/auth/google/start")
async def auth_google_start(redirect: Optional[str] = None, request: Request = None):
    """Initiate Google OAuth login, bound to this browser."""

    _ensure_google_oauth_enabled()
    response = RedirectResponse("", status_code=307)
    response.headers["location"] = _start_oauth_flow(
        response, request, purpose="login", redirect=_sanitize_google_redirect(redirect)
    )
    return response


@app.post("/auth/google/link/start")
async def auth_google_link_start(
    payload: LinkStartRequest,
    request: Request,
    response: Response,
    authorization: Optional[str] = Header(None),
) -> Dict[str, str]:
    """Begin linking a Google account to the signed-in, verified account.

    Requires the account password again (fresh re-authentication). The flow
    records this user and this session; only they can confirm it later.
    """

    session_digest, session = _require_session(authorization)
    _ensure_google_oauth_enabled()
    _enforce_rate_limit("auth_login", f"user:{session['user_id']}")
    user = _get_db().get_user_by_email(session["email"])
    stored_hash = (user or {}).get("password_hash")
    if not stored_hash:
        raise HTTPException(
            status_code=400,
            detail="This account has no password. Use 'Forgot password' to set one first.",
        )
    if not _verify_password(payload.password, stored_hash):
        raise HTTPException(status_code=401, detail="Password is incorrect")
    url = _start_oauth_flow(
        response, request, purpose="link", user_id=session["user_id"], session_digest=session_digest
    )
    return {"url": url}


@app.post("/auth/google/link/confirm", response_model=UserProfile)
async def auth_google_link_confirm(
    payload: LinkConfirmRequest, authorization: Optional[str] = Header(None)
) -> UserProfile:
    """Finish a link: only the user and session that started it can."""

    session_digest, session = _require_session(authorization)
    status, user_row = _get_db().complete_google_link(
        link_code_digest=hash_session_token(payload.code),
        user_id=session["user_id"],
        session_digest=session_digest,
    )
    if status == "conflict":
        raise HTTPException(status_code=409, detail="That Google account is linked to another HalalLens account.")
    if status == "already_linked":
        raise HTTPException(status_code=409, detail="This account is already linked to a different Google account.")
    if status != "ok":
        raise HTTPException(
            status_code=400,
            detail="This link expired or was started from another session. Start again from your account page.",
        )
    api_logger.info("Google account linked to user id=%s", user_row["id"])
    return _serialize_user_profile(user_row)


@app.get("/auth/google/callback")
async def auth_google_callback(
    request: Request = None,
    code: Optional[str] = None,
    state: Optional[str] = None,
    error: Optional[str] = None,
):
    """Handle Google's redirect for a login or link flow started in this browser.

    This is a full-page navigation, not an API call: every failure redirects to
    the login page (the account page for a link flow) with a reason code in the
    fragment, and the detail goes to the log only. No raw JSON reaches the user.
    """

    flow: Optional[Dict[str, Any]] = None
    try:
        _ensure_google_oauth_enabled()
        if error or not code or not state:
            # error=access_denied: the user cancelled on Google's page.
            return _google_callback_error("google_cancelled" if error else "google_failed", None, request)
        browser = request.cookies.get(OAUTH_BROWSER_COOKIE) if request is not None else None
        flow = (
            _get_db().consume_oauth_flow(
                state_digest=hash_session_token(state), browser_digest=hash_session_token(browser)
            )
            if browser
            else None
        )
        if not flow:
            # Expired, already used, or completed in another browser (login CSRF).
            return _google_callback_error("google_expired", None, request)
        return _complete_google_callback(flow, code, request)
    except HTTPException as exc:
        api_logger.warning("Google callback failed: %s %s", exc.status_code, exc.detail)
        reason = "google_unavailable" if exc.status_code >= 500 else "google_failed"
        return _google_callback_error(reason, flow, request)


def _google_callback_error(
    reason: str, flow: Optional[Dict[str, Any]], request: Optional[Request]
) -> RedirectResponse:
    if flow and flow.get("purpose") == "link":
        # A signed-in user on /login is bounced to the dashboard, so link
        # failures go back to the account page instead.
        base = (FRONTEND_BASE_URL or "").rstrip("/")
        target = f"{base}/account/#{urlencode({'link_error': reason})}"
    else:
        target = _build_auth_error_redirect(
            reason, _sanitize_google_redirect(flow.get("redirect")) if flow else None
        )
    response = RedirectResponse(target, status_code=302)
    response.delete_cookie(OAUTH_BROWSER_COOKIE, path=_oauth_cookie_path(request))
    return response


def _complete_google_callback(
    flow: Dict[str, Any], code: str, request: Optional[Request]
) -> RedirectResponse:
    redirect_base = _sanitize_google_redirect(flow.get("redirect"))
    token_data = _exchange_google_code(code)
    access_token = token_data.get("access_token")
    if not access_token:
        raise HTTPException(status_code=400, detail="Missing Google access token")
    profile = _fetch_google_profile(access_token)
    email = _normalize_email(profile.get("email", ""))
    sub = profile.get("sub")
    if not email or not sub:
        raise HTTPException(status_code=400, detail="Google profile missing identifiers")
    if profile.get("email_verified") is not True:
        # A missing claim is not proof of the mailbox.
        return _google_callback_error("google_unverified", flow, request)

    if flow["purpose"] == "link":
        # Prove the Google identity only; the signed-in session confirms it.
        link_code = secrets.token_urlsafe(32)
        _get_db().record_link_identity(
            flow_id=flow["id"],
            google_sub=sub,
            google_email=email,
            link_code_digest=hash_session_token(link_code),
        )
        base = (FRONTEND_BASE_URL or "").rstrip("/")
        response = RedirectResponse(f"{base}/account/#{urlencode({'link': link_code})}", status_code=302)
    else:
        response = _google_login_response(email, sub, profile, redirect_base)
    response.delete_cookie(OAUTH_BROWSER_COOKIE, path=_oauth_cookie_path(request))
    return response


def _google_login_response(
    email: str, sub: str, profile: Dict[str, Any], redirect_base: Optional[str]
) -> RedirectResponse:
    status, user_row = _get_db().google_sign_in(
        email=email,
        google_sub=sub,
        full_name=profile.get("name"),
        avatar_url=profile.get("picture"),
        admin_emails=_admin_allowlist(),
    )
    if status == "email_in_use":
        # Never attach Google to an existing account by email: the account
        # owner signs in and links Google from the account page.
        return RedirectResponse(
            _build_auth_error_redirect("account_exists", redirect_base), status_code=302
        )
    if not user_row.get("email_verified_at"):
        return RedirectResponse(
            _build_auth_error_redirect("verify_email", redirect_base), status_code=302
        )
    _get_db().touch_user_login(user_row["id"])
    api_logger.info("Google SSO sign-in id=%s", user_row["id"])
    token, expires_at = _issue_session(user_row["id"])
    return RedirectResponse(_build_google_redirect(token, expires_at, redirect_base), status_code=302)


EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s.]+(\.[^@\s.]+)+$")


def _validate_email(email: str) -> str:
    if not email or not EMAIL_RE.match(email) or len(email) > 254:
        raise HTTPException(status_code=400, detail="Valid email required")
    return email


SIGNUP_TOKEN_TTL = timedelta(hours=1)
RESET_TOKEN_TTL = timedelta(minutes=30)
ACCOUNT_EMAIL_ACCEPTED = {
    "status": "check_email",
    "detail": "If the address can receive mail, a link is on its way. It expires soon; check spam too.",
}


def _frontend_link(path: str, param: str, token: str) -> str:
    """Emailed link with the proof in the URL fragment, which never reaches a
    server, proxy or Cloudflare log; the page posts it to the API."""

    base = (FRONTEND_BASE_URL or "").rstrip("/")
    if not base:
        raise HTTPException(status_code=500, detail="FRONTEND_BASE_URL is not configured")
    return f"{base}{path}#{urlencode({param: token})}"


def _send_account_email(email: str) -> None:
    """Email the right proof for ``email`` and never reveal which one it was.

    - no account: a sign-up link (the password is chosen on that page);
    - an account that can hold a password: a set-password link, which also
      proves the mailbox, revokes every session and replaces any password a
      pre-registration chose;
    - a Google-only account: a reminder to use Google (it never gains a
      password through email).

    The token is stored (as a digest) before sending; a mail failure is
    logged and the caller still answers with the same generic response.
    """

    db = _get_db()
    user = db.get_user_by_email(email)
    now = datetime.now(timezone.utc)
    if user is None:
        token = secrets.token_urlsafe(32)
        db.issue_auth_token(
            purpose="signup",
            email=email,
            user_id=None,
            token_digest=hash_session_token(token),
            expires_at=now + SIGNUP_TOKEN_TTL,
        )
        subject = "Finish creating your HalalLens account"
        body = (
            "Someone (hopefully you) asked to create a HalalLens account with this address.\n\n"
            f"Choose your password here (the link works once, for 1 hour):\n{_frontend_link('/verify/', 'signup', token)}\n\n"
            "If this was not you, ignore this email; no account is created."
        )
    elif user.get("provider") == "google":
        subject = "Sign in to HalalLens with Google"
        body = (
            "This address belongs to a HalalLens account that signs in with Google.\n\n"
            "Use \"Continue with Google\" on the sign-in page. If this was not you, ignore this email."
        )
    else:
        token = secrets.token_urlsafe(32)
        db.issue_auth_token(
            purpose="reset_password",
            email=email,
            user_id=user["id"],
            token_digest=hash_session_token(token),
            expires_at=now + RESET_TOKEN_TTL,
        )
        subject = "Set your HalalLens password"
        body = (
            "Someone (hopefully you) asked to set the password of the HalalLens account for this address.\n\n"
            f"Choose a new password here (the link works once, for 30 minutes):\n{_frontend_link('/reset/', 'reset', token)}\n\n"
            "Setting it signs out every device. If this was not you, ignore this email; nothing changes."
        )
    try:
        send_email(email, subject, body)
    except Exception:
        api_logger.exception("Account email failed (user id=%s)", user["id"] if user else None)


def _account_email_request(email_raw: str, request: Optional[Request]) -> Dict[str, str]:
    _enforce_rate_limit("auth_register", _client_identity(request))
    email = _validate_email(_normalize_email(email_raw))
    _enforce_rate_limit("auth_email_address", email)
    _enforce_rate_limit("auth_email_cooldown", email)
    _enforce_rate_limit("auth_email_global", "all")
    _send_account_email(email)
    return ACCOUNT_EMAIL_ACCEPTED


@app.post("/auth/register", status_code=202)
async def auth_register(payload: RegisterRequest, request: Request = None) -> Dict[str, str]:
    """Start an email-first sign-up: email a link; the account is created there.

    The answer is the same whether or not the address already has an account.
    """

    return _account_email_request(payload.email, request)


@app.post("/auth/password/forgot", status_code=202)
async def auth_password_forgot(payload: RegisterRequest, request: Request = None) -> Dict[str, str]:
    """Email a set-password link (or a sign-up link when there is no account)."""

    return _account_email_request(payload.email, request)


def _require_password_policy(password: str) -> None:
    policy_error = password_policy_error(password)
    if policy_error:
        raise HTTPException(status_code=400, detail=policy_error)


INVALID_LINK = "This link is invalid, already used or expired. Request a new one."


@app.post("/auth/signup/confirm", response_model=AuthTokenResponse)
async def auth_signup_confirm(
    payload: TokenPasswordRequest, request: Request = None
) -> AuthTokenResponse:
    """Create the account from a sign-up link, with the password chosen now."""

    _enforce_rate_limit("auth_token_confirm", _client_identity(request))
    _require_password_policy(payload.password)
    status, user_row = _get_db().complete_signup(
        token_digest=hash_session_token(payload.token),
        password_hash=_hash_password(payload.password),
        admin_emails=_admin_allowlist(),
    )
    if status == "invalid_token":
        raise HTTPException(status_code=400, detail=INVALID_LINK)
    if status == "email_in_use":
        raise HTTPException(
            status_code=409,
            detail="An account with this email already exists. Sign in, or use 'Forgot password'.",
        )
    api_logger.info("Registered user id=%s (email verified)", user_row["id"])
    token, expires_at = _issue_session(user_row["id"])
    return AuthTokenResponse(
        token=token, expires_at=expires_at, user=_serialize_user_profile(user_row)
    )


@app.post("/auth/password/reset")
async def auth_password_reset(
    payload: TokenPasswordRequest, request: Request = None
) -> Dict[str, str]:
    """Set a new password from a reset link; signs out every session.

    No session is issued: the user signs in with the new password.
    """

    _enforce_rate_limit("auth_token_confirm", _client_identity(request))
    _require_password_policy(payload.password)
    status, user_row = _get_db().complete_password_reset(
        token_digest=hash_session_token(payload.token),
        password_hash=_hash_password(payload.password),
        admin_emails=_admin_allowlist(),
    )
    if status != "ok":
        raise HTTPException(status_code=400, detail=INVALID_LINK)
    api_logger.info("Password reset for user id=%s; sessions revoked", user_row["id"])
    return {"status": "password_reset"}


@app.post("/auth/login", response_model=AuthTokenResponse)
async def auth_login(
    payload: LoginRequest, request: Request = None
) -> AuthTokenResponse:
    """Authenticate an existing, verified user."""

    _enforce_rate_limit("auth_login", _client_identity(request))
    email = _normalize_email(payload.email)

    def check(stored_hash: Optional[str]) -> bool:
        if not stored_hash:
            # Unknown address or Google-only account: burn equivalent CPU so
            # response time does not reveal which addresses are registered.
            dummy_verify(payload.password)
            return False
        return _verify_password(payload.password, stored_hash)

    def rehash(stored_hash: Optional[str]) -> Optional[str]:
        # Transparent upgrade from the legacy 100k-iteration scheme, inside the
        # same locked transaction as the password check.
        return _hash_password(payload.password) if needs_rehash(stored_hash) else None

    token = generate_session_token()
    expires_at = datetime.now(timezone.utc) + timedelta(hours=AUTH_TOKEN_TTL_HOURS)
    status, user_row = _get_db().login_with_password(
        email=email,
        check_password=check,
        rehash=rehash,
        session_digest=hash_session_token(token),
        expires_at=expires_at,
    )
    if status == "bad_credentials":
        raise HTTPException(status_code=401, detail="Invalid email or password")
    if status == "unverified":
        # Only after a correct password, so this does not reveal the address.
        raise HTTPException(
            status_code=403,
            detail="Email not verified. Use 'Forgot password' to confirm your email and set your password.",
        )
    api_logger.info("Login success id=%s", user_row["id"])
    return AuthTokenResponse(
        token=token, expires_at=expires_at, user=_serialize_user_profile(user_row)
    )


@app.post("/auth/logout")
async def auth_logout(authorization: Optional[str] = Header(None)) -> Dict[str, str]:
    """Revoke the active session token."""

    token, _ = _require_session(authorization)
    _get_db().delete_session(token)
    api_logger.info("Logout token revoked")
    return {"status": "logged_out"}


@app.get("/auth/me", response_model=UserProfile)
async def auth_me(authorization: Optional[str] = Header(None)) -> UserProfile:
    """Return the authenticated user's profile."""

    _, session = _require_session(authorization)
    _subscription_active(session)  # a queued period may have started
    profile_row = _get_db().get_user_by_id(session["user_id"]) or {
        "id": session["user_id"],
        "email": session["email"],
        "plan": session.get("plan", "free"),
        "subscription_status": session.get("subscription_status", "inactive"),
        "subscription_renewal": session.get("subscription_renewal"),
        "full_name": session.get("full_name"),
        "avatar_url": session.get("avatar_url"),
        "is_admin": session.get("is_admin", False),
        "email_verified_at": session.get("email_verified_at"),
    }
    return _serialize_user_profile(profile_row)


@app.post("/client-logs")
async def client_logs(
    payload: ClientLogRequest, request: Request, authorization: Optional[str] = Header(None)
) -> Dict[str, str]:
    """Collect client-side logs for debugging flows."""

    _enforce_rate_limit("anon_write", _client_identity(request))
    session = None
    token = _extract_token(authorization)
    if token:
        session = _get_db().get_session(hash_session_token(token))
    context = dict(payload.context or {})
    if payload.url:
        context["url"] = payload.url
    if payload.user_agent:
        context["user_agent"] = payload.user_agent
    context["client_ip"] = request.client.host if request.client else "unknown"
    if session:
        context["user_id"] = session.get("user_id")
        context["email"] = session.get("email")
    # Client-controlled text must not be able to forge extra log lines.
    message = _sanitize_log_text(payload.message, limit=500)
    context = {
        key: _sanitize_log_text(value, limit=200) if isinstance(value, str) else value
        for key, value in list(context.items())[:20]
    }
    level = payload.level.lower()
    context_payload = f" context={context}" if context else ""
    if level == "debug":
        client_logger.debug("%s%s", message, context_payload)
    elif level == "warning":
        client_logger.warning("%s%s", message, context_payload)
    elif level == "error":
        client_logger.error("%s%s", message, context_payload)
    else:
        client_logger.info("%s%s", message, context_payload)
    return {"status": "ok"}


@app.get("/billing/plans", response_model=List[BillingPlan])
async def list_billing_plans() -> List[BillingPlan]:
    plans = _get_db().list_subscription_plans(active_only=True)
    return [
        BillingPlan(
            code=plan["code"],
            name=plan["name"],
            price_inr=int(plan["price_inr"]),
            interval_days=int(plan["interval_days"]),
            trial_days=int(plan.get("trial_days") or 0),
            features=list(plan.get("features") or []),
            is_active=bool(plan["is_active"]),
            rank=int(plan.get("rank") or 0),
        )
        for plan in plans
    ]


@app.post("/billing/trial", response_model=SubscriptionStatusResponse)
async def start_billing_trial(
    payload: TrialStartRequest, authorization: Optional[str] = Header(None)
) -> SubscriptionStatusResponse:
    _, session = _require_session(authorization)
    plan = _get_db().get_subscription_plan(payload.plan_code)
    if not plan or not plan.get("is_active"):
        raise HTTPException(status_code=404, detail="Plan not available")
    trial_days = int(plan.get("trial_days") or 0)
    if trial_days <= 0:
        raise HTTPException(status_code=400, detail="Trial not available for this plan")
    if session.get("trial_used"):
        raise HTTPException(status_code=409, detail="Trial already used")
    current_status = (session.get("subscription_status") or "inactive").lower()
    current_plan = (session.get("plan") or "free").lower()
    if current_plan != "free" and current_status in {"active", "trialing"}:
        raise HTTPException(status_code=409, detail="Active subscription already exists")

    result, projection = _get_db().start_trial_grant(
        user_id=session["user_id"],
        plan_code=plan["code"],
        trial_days=trial_days,
        project=billing.project,
    )
    if result == "used":
        raise HTTPException(status_code=409, detail="Trial already used")
    if result == "active":
        raise HTTPException(status_code=409, detail="Active subscription already exists")
    return SubscriptionStatusResponse(
        plan=projection["plan"],
        subscription_status=projection["subscription_status"],
        subscription_renewal=projection["subscription_renewal"],
    )


def _upgrade_plan() -> Optional[Dict[str, Any]]:
    """The active never-ending (Lifetime) plan, if one is sold."""

    return next(
        (p for p in _get_db().list_subscription_plans(active_only=True) if int(p.get("interval_days") or 0) <= 0),
        None,
    )


def _lifetime_quote(grants, funding, now, plan) -> Optional[Dict[str, Any]]:
    """billing.upgrade_quote for ``plan`` at its list price, or None when Lifetime is already held."""

    if billing.lifetime_held(grants):
        return None
    return billing.upgrade_quote(grants, funding, now, int(plan["price_inr"]) * 100)


@app.get("/billing/entitlement", response_model=EntitlementResponse)
async def billing_entitlement(
    response: Response, authorization: Optional[str] = Header(None)
) -> EntitlementResponse:
    """Current and queued paid periods, when a new purchase would start, and the Lifetime price after credit."""

    response.headers["Cache-Control"] = "no-store"  # per-user money figures
    _, session = _require_session(authorization)
    _subscription_active(session)
    db = _get_db()
    grants = db.get_subscription_grants(session["user_id"])
    now = _utcnow()
    plan = _upgrade_plan()
    quote = _lifetime_quote(grants, db.get_credit_funding(session["user_id"]), now, plan) if plan else None
    return EntitlementResponse(
        lifetime_quote=None if quote is None else LifetimeQuote(
            plan_code=plan["code"],
            list_amount=quote["list_amount"],
            credit_amount=quote["credit_amount"],
            amount=quote["amount"],
            blocked=quote["blocked"],
            valid_for_seconds=int(billing.PRICE_VALIDITY.total_seconds()),
        ),
        plan=session.get("plan") or "free",
        subscription_status=session.get("subscription_status") or "inactive",
        segments=[
            EntitlementSegment(plan_code=s.plan_code, source=s.source, start=s.start, end=s.end)
            for s in billing.upcoming(billing.fold(grants), now)
        ],
        next_purchase_starts=billing.purchase_start(grants, now),
        purchases_blocked=billing.lifetime_held(grants),
    )


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
    if billing.lifetime_held(_get_db().get_subscription_grants(session["user_id"])):
        # Settlement re-checks this under the user lock (two checkouts can be open).
        raise HTTPException(status_code=409, detail="Lifetime access already covers every plan.")
    quote, priced_at = None, None
    if int(plan.get("interval_days") or 0) <= 0:
        # Lifetime is priced with upgrade credit (D-030) on one locked read;
        # the lock is released before Razorpay is called.
        quote, priced_at = _get_db().quote_upgrade(
            session["user_id"], lambda grants, funding, now: _lifetime_quote(grants, funding, now, plan)
        )
        if quote is None:
            raise HTTPException(status_code=409, detail="Lifetime access already covers every plan.")
        if quote["blocked"]:
            raise HTTPException(
                status_code=409,
                detail="Your credit covers almost all of the Lifetime price, so we can't open a checkout. "
                "Please contact support to upgrade.",
            )
    order = _create_razorpay_order(
        user_id=session["user_id"],
        email=session["email"],
        plan=plan,
        quote=quote,
        priced_at=priced_at,
    )
    api_logger.info(
        "Razorpay order created user_id=%s plan=%s order_id=%s amount=%s credit=%s",
        session["user_id"],
        plan_code,
        order.get("id"),
        order.get("amount"),
        order.get("credit_amount", 0),
    )
    return RazorpayOrderResponse(
        key_id=RAZORPAY_KEY_ID,
        order_id=order["id"],
        amount=int(order["amount"]),
        currency=order.get("currency", "INR"),
        plan_code=plan_code,
        plan_name=plan["name"],
        email=session["email"],
        list_amount=int(order["list_amount"]),
        credit_amount=int(order.get("credit_amount") or 0),
        price_valid_until=order.get("price_valid_until"),
    )


#: Webhook events that grant access. Refunds (refund.processed) revoke only the
#: grant their order created; nothing else revokes access.
RAZORPAY_GRANT_EVENTS = {"payment.captured", "order.paid"}

RAZORPAY_PAYMENT_ID_RE = re.compile(r"^pay_[A-Za-z0-9]{6,40}$")


def _fetch_razorpay_payment(payment_id: str) -> Dict[str, Any]:
    try:
        return RazorpayClient(RAZORPAY_KEY_ID, RAZORPAY_KEY_SECRET).fetch_payment(payment_id)
    except RazorpayError as exc:
        api_logger.error("Razorpay payment fetch failed: %s", exc)
        raise HTTPException(
            status_code=503,
            detail="Could not confirm the payment with Razorpay yet. If money was taken, "
            "access is added automatically within a few minutes.",
        )


def _settle_razorpay_order(
    *,
    order_id: str,
    payment_id: str,
    expected_user_id: Optional[int] = None,
    event_type: str,
    event_payload: Dict[str, Any],
    payment: Dict[str, Any],
) -> Tuple[str, Optional[Dict[str, Any]]]:
    """Turn a captured payment into a grant, exactly once (D-024).

    Browser verification and the webhook both land here (the reconciler calls
    the same database method); the database does the claim, grant, event and
    projection in one transaction under the user lock, so the loser of a race
    gets "settled" and nothing is granted twice, and a crash never leaves a
    paid order without access. ``payment`` is the payment entity: its
    ``created_at`` (when the attempt was created) decides whether a credited
    order's price still binds (D-030). When it is missing for a credited
    order, the payment is fetched here, outside any lock; still missing
    means "retry" and nothing changes.
    """

    attempt_at = payment_created_at(payment)
    if attempt_at is None:
        order = _get_db().get_razorpay_order(order_id)
        if order and order.get("credit_version") is not None:
            try:
                attempt_at = payment_created_at(
                    RazorpayClient(RAZORPAY_KEY_ID, RAZORPAY_KEY_SECRET).fetch_payment(payment_id)
                )
            except RazorpayError as exc:
                api_logger.warning("Razorpay payment fetch for %s failed: %s", payment_id, exc)
    result, info = _get_db().settle_razorpay_order(
        order_id=order_id,
        payment_id=payment_id,
        expected_user_id=expected_user_id,
        event_type=event_type,
        payload=event_payload,
        project=billing.project,
        lifetime_held=billing.lifetime_held,
        payment_created_at=attempt_at,
        credit_refusal=billing.credit_refusal,
    )
    if result == "missing":
        raise HTTPException(status_code=404, detail="Order not found")
    if result == "granted":
        api_logger.info(
            "Subscription granted order_id=%s payment_id=%s plan=%s via=%s",
            order_id, payment_id, info["granted_plan"], event_type,
        )
    elif result == "refund_due":
        # Keep the money on record; the reconciler refunds it (TEST keys) or
        # a human does (README_ops, Billing).
        api_logger.error(
            "REFUND DUE: order_id=%s payment_id=%s user_id=%s reason=%s",
            order_id, payment_id, info["user_id"], info.get("refund_due_reason"),
        )
    elif result == "retry":
        api_logger.warning(
            "Credited order %s: payment %s has no creation time yet; left for a retry", order_id, payment_id
        )
    return result, info


#: What the buyer is told when a payment is kept for a refund, by reason.
REFUND_DUE_MESSAGES = {
    "lifetime_held": "Lifetime access already covers your account, so this payment will be refunded.",
    "price_expired": "This payment started after your Lifetime price expired (a price with credit is held "
    "for 15 minutes), so the full amount will be refunded. Please start a new checkout.",
    "credit_changed": "A purchase your credit came from changed after the price was set (for example, it "
    "was refunded), so the full amount will be refunded. Please start a new checkout.",
}


def _refund_due_message(reason: Optional[str]) -> str:
    return REFUND_DUE_MESSAGES.get(reason or "lifetime_held", REFUND_DUE_MESSAGES["lifetime_held"])


def _alert_credit_conflict(refund_id: str, payment_id: Optional[str], info: Optional[Dict[str, Any]]) -> None:
    """A refunded payment had funded credit on a settled upgrade (D-030): alert only."""

    conflicts = (info or {}).get("credit_conflicts") if isinstance(info, dict) else None
    if not conflicts:
        return
    api_logger.error(
        "CREDIT CONFLICT: refund %s of payment %s; credit was used by order(s) %s", refund_id, payment_id, conflicts
    )
    billing_notifier.notify(
        "error",
        f"Billing needs attention: credit_conflict (refund {refund_id}, order {conflicts[0]})",
        "A refunded payment funded upgrade credit on a settled Lifetime order. See README_ops, Billing "
        "(credit_conflict). Tracked in billing_tracked until resolved by hand.",
    )


def _current_subscription_response(user_id: int) -> SubscriptionStatusResponse:
    row = _get_db().get_user_by_id(user_id) or {}
    return SubscriptionStatusResponse(
        plan=row.get("plan", "free"),
        subscription_status=row.get("subscription_status", "inactive"),
        subscription_renewal=row.get("subscription_renewal"),
    )


@app.get("/billing/razorpay/order/{order_id}", response_model=RazorpayOrderStatusResponse)
async def razorpay_order_status(
    order_id: str, authorization: Optional[str] = Header(None)
) -> RazorpayOrderStatusResponse:
    """Status of the caller's own order.

    The checkout can close without its success callback (the payment finished
    on the bank's page, or the window was closed afterwards) while the webhook
    still settles the order; the account page polls this before telling the
    user anything.
    """

    _, session = _require_session(authorization)
    order = _get_db().get_razorpay_order(order_id)
    if not order or order.get("user_id") != session.get("user_id"):
        raise HTTPException(status_code=404, detail="Order not found")
    # Orders that went refund_due before D-030 carry no reason: Lifetime was held.
    reason = (order.get("refund_due_reason") or "lifetime_held") if order["status"] == "refund_due" else None
    return RazorpayOrderStatusResponse(
        order_id=order_id, status=order["status"], reason=reason,
        message=_refund_due_message(reason) if reason else None,
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
    if not RAZORPAY_PAYMENT_ID_RE.match(payload.payment_id):
        raise HTTPException(status_code=400, detail="Invalid payment id")
    message = f"{payload.order_id}|{payload.payment_id}"
    if not _verify_razorpay_signature(message, payload.signature):
        api_logger.warning(
            "Razorpay signature rejected user_id=%s order_id=%s",
            session.get("user_id"),
            payload.order_id,
        )
        raise HTTPException(status_code=400, detail="Invalid payment signature")
    if order.get("status") not in ("created", "attempted"):
        # Already settled (usually the webhook landed first).
        return _current_subscription_response(session["user_id"])

    # The checkout signature proves the pairing, not that money was captured.
    payment = _fetch_razorpay_payment(payload.payment_id)
    if not _payment_matches_order(payment, order):
        api_logger.warning(
            "Razorpay payment not settled order_id=%s payment_id=%s status=%s",
            payload.order_id, payload.payment_id, payment.get("status"),
        )
        raise HTTPException(
            status_code=409,
            detail="Razorpay has not confirmed this payment yet. If money was taken, "
            "access is added automatically within a few minutes.",
        )

    result, info = _settle_razorpay_order(
        order_id=payload.order_id,
        payment_id=payload.payment_id,
        expected_user_id=session["user_id"],
        event_type="payment.verified",
        event_payload={"order_id": payload.order_id, "payment_id": payload.payment_id},
        payment=payment,
    )
    if result == "refund_due":
        raise HTTPException(status_code=409, detail=_refund_due_message(info.get("refund_due_reason")))
    if result == "retry":
        raise HTTPException(
            status_code=503,
            detail="Could not confirm the payment with Razorpay yet. If money was taken, "
            "access is added automatically within a few minutes.",
        )
    if result == "refunded_payment":
        raise HTTPException(status_code=409, detail="This payment was already refunded.")
    return _current_subscription_response(session["user_id"])


@app.post("/billing/cancel", response_model=SubscriptionStatusResponse)
async def cancel_subscription(
    authorization: Optional[str] = Header(None),
) -> SubscriptionStatusResponse:
    """Nothing to cancel: every plan is a one-time purchase that never renews.

    Paid time always runs to its end; refunds go through support. Kept so
    existing clients get the current state instead of an error.
    """

    _, session = _require_session(authorization)
    _subscription_active(session)
    return _current_subscription_response(session["user_id"])


@app.post("/webhooks/razorpay")
async def razorpay_webhook(request: Request) -> Dict[str, str]:
    """Authoritative billing callback.

    Entitlement is granted here as well as in ``/billing/razorpay/verify``: the
    browser call can be lost (tab closed, network drop) after money has moved,
    and a user who paid must still get access.
    """

    signature = request.headers.get("X-Razorpay-Signature")
    if not signature:
        raise HTTPException(status_code=400, detail="Missing signature")
    body = await request.body()
    if not _verify_razorpay_webhook(body, signature):
        api_logger.warning("Razorpay webhook signature rejected")
        raise HTTPException(status_code=400, detail="Invalid signature")

    event = await request.json()
    event_type = event.get("event", "unknown")
    entities = event.get("payload") or {}
    payment_entity = (entities.get("payment") or {}).get("entity") or {}
    order_entity = (entities.get("order") or {}).get("entity") or {}
    order_id = payment_entity.get("order_id") or order_entity.get("id")
    payment_id = payment_entity.get("id") or event.get("id")

    db = _get_db()

    if event_type == "refund.processed":
        refund_entity = (entities.get("refund") or {}).get("entity") or {}
        # Keyed by the refund id, never the payment id (the purchase is already
        # recorded under the payment id).
        refund_id = (
            refund_entity.get("id")
            or request.headers.get("X-Razorpay-Event-Id")
            or f"{event_type}:{payment_id}"
        )
        refunded_payment = refund_entity.get("payment_id") or payment_entity.get("id")
        result, info = db.refund_razorpay_payment(
            order_id=order_id,
            payment_id=refunded_payment,
            refund_id=refund_id,
            refund_amount=int(refund_entity.get("amount") or 0),
            event_type=event_type,
            payload=event,
            project=billing.project,
        )
        if refunded_payment and result != "unknown":
            # Settles an automatic refund request and the payment's refund
            # obligation, whichever path recorded the refund (D-025).
            db.sync_refund_action(refunded_payment)
        if result == "needs_review":
            api_logger.warning(
                "Refund %s for order %s: funding payment unknown, review by hand", refund_id, info["order_id"]
            )
        elif result != "duplicate":
            api_logger.info("Refund %s recorded: %s", refund_id, result)
        _alert_credit_conflict(refund_id, refunded_payment, info)
        return {"status": result}

    order = db.get_razorpay_order(order_id) if order_id else None
    user_id = order.get("user_id") if order else None

    if event_type in RAZORPAY_GRANT_EVENTS and order:
        if _payment_matches_order(payment_entity, order):
            result, _ = _settle_razorpay_order(
                order_id=order_id,
                payment_id=payment_id,
                event_type=event_type,
                event_payload=event,
                payment=payment_entity,  # the payment entity's created_at, never the envelope's
            )
            if result in ("granted", "refund_due", "refunded_payment", "retry"):
                # retry: nothing recorded; the reconciler settles it from the payment.
                return {"status": result}
            # Already settled elsewhere; fall through to record the event.
        else:
            api_logger.error(
                "Razorpay %s does not match order %s (amount, currency or status): not granted",
                event_type, order_id,
            )

    db.record_payment_event(
        user_id=user_id,
        provider="razorpay",
        event_type=event_type,
        event_id=payment_id,
        payload=event,
    )
    return {"status": "ok"}


def _watchlist_owner(session: Dict[str, Any]) -> int:
    """Watchlist owner (the session's user id), never taken from the request."""

    return int(session["user_id"])


@contextmanager
def _watchlist_storage_errors(action: str):
    """Watchlist storage failures are 503, never a silent empty result."""

    try:
        yield
    except HTTPException:
        raise
    except Exception:
        api_logger.exception("Watchlist storage failed during %s", action)
        raise HTTPException(status_code=503, detail="Watchlist storage unavailable")


@app.post("/watchlist", response_model=WatchlistEntryPayload)
async def add_watchlist(
    entry: WatchlistEntryPayload,
    authorization: Optional[str] = Header(None),
) -> WatchlistEntryPayload:
    """Register or update a watchlist entry for the authenticated user."""

    session = _require_paid_feature(authorization, "Watchlist alerts")
    owner = _watchlist_owner(session)
    with _watchlist_storage_errors("add"):
        watch_storage.add(
            WatchEntry(
                user_id=owner,
                symbol=entry.symbol.strip().upper(),
                trigger=entry.trigger,
            )
        )
    return WatchlistEntryPayload(
        user_id=owner_key(owner),
        symbol=entry.symbol.strip().upper(),
        trigger=entry.trigger,
    )


@app.get("/watchlist/{user_id}", response_model=List[WatchlistEntryPayload])
async def list_watchlist(
    user_id: str,
    authorization: Optional[str] = Header(None),
) -> List[WatchlistEntryPayload]:
    """List the authenticated user's watchlist.

    ``user_id`` is kept for URL compatibility but is ignored: the entries
    returned are always the caller's own. Honouring the path parameter let any
    subscriber enumerate every other subscriber's watchlist.
    """

    session = _require_paid_feature(authorization, "Watchlist alerts")
    owner = _watchlist_owner(session)
    with _watchlist_storage_errors("list"):
        entries = watch_storage.list(owner)
    return [
        WatchlistEntryPayload(user_id=owner_key(owner), symbol=entry.symbol, trigger=entry.trigger)
        for entry in entries
    ]


@app.post("/alerts/check", response_model=List[AlertEventPayload])
async def check_alerts(
    payload: AlertCheckPayload,
    authorization: Optional[str] = Header(None),
) -> List[AlertEventPayload]:
    """Observe the stored verdict of a symbol for the caller's own watch entry.

    Observation only (D-031): a flip becomes a pending alert email that the
    evaluation scheduler sends to the subscriber; this route never sends mail.
    The verdict comes from the stored evaluation (alerts/storage.py
    ``observe``), never from the request. Lookup failures are 503.
    """

    session = _require_paid_feature(authorization, "Watchlist alerts")
    owner = _watchlist_owner(session)
    _enforce_rate_limit("metered", owner_key(owner))
    symbol = payload.symbol.strip().upper()
    if not symbol:
        raise HTTPException(status_code=422, detail="symbol is required")

    # Only the caller's own entry is read or moved (alerts/engine.py).
    with _watchlist_storage_errors("alert check"):
        events: List[AlertEvent] = alert_engine.check(symbol, user_id=owner)
    return [AlertEventPayload(**asdict(event)) for event in events]


class AlertEmailsPayload(BaseModel):
    """Whether compliance-flip alerts are emailed to the account's own address."""

    model_config = ConfigDict(extra="forbid")

    enabled: bool


@app.get("/account/alert-emails", response_model=AlertEmailsPayload)
async def get_alert_emails(authorization: Optional[str] = Header(None)) -> AlertEmailsPayload:
    """The caller's alert-email setting. Authenticated, not paid: opting out must work after access ends."""

    _, session = _require_session(authorization)
    with _watchlist_storage_errors("alert email setting"):
        return AlertEmailsPayload(enabled=watch_storage.get_alert_emails(_watchlist_owner(session)))


@app.put("/account/alert-emails", response_model=AlertEmailsPayload)
async def put_alert_emails(
    payload: AlertEmailsPayload, authorization: Optional[str] = Header(None)
) -> AlertEmailsPayload:
    """Turn the caller's own alert emails on or off (never another account's)."""

    _, session = _require_session(authorization)
    with _watchlist_storage_errors("alert email setting"):
        enabled = watch_storage.set_alert_emails(_watchlist_owner(session), payload.enabled)
    return AlertEmailsPayload(enabled=enabled)


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
    snapshot_parsed_at: Optional[datetime] = None
    evaluation_updated_at: Optional[datetime] = None
    data_updated_at: Optional[datetime] = None
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


def _ensure_filing_evaluation(
    record: Dict[str, Any], *, allow_market_fetch: bool = True
) -> Optional[Dict[str, RatioComputationPayload]]:
    _maybe_enrich_record_with_indian_api(record)
    ratios = _ratios_payload(record.get("ratios"))
    if ratios is not None:
        # A stored result is returned as stored; _filing_response masks it with
        # the filing's current open issues before it leaves the API.
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
        if allow_market_fetch:
            market_cap, share_price, provider = _market_data_for_filing(
                snapshot.symbol, snapshot.filing_date
            )
        else:
            cached = _get_db().get_cached_market_data(
                snapshot.symbol, snapshot.filing_date
            )
            if cached:
                market_cap, share_price, provider = cached

    if market_cap is None and trailing is None:
        if allow_market_fetch:
            raise HTTPException(status_code=503, detail="Market data unavailable")
        return None

    evaluation = engine.evaluate(
        snapshot,
        MarketDataInput(
            market_cap=market_cap,
            trailing_market_cap=trailing,
            share_price=share_price,
            provider=provider or "manual",
        ),
    )

    ratios_dict = {name: asdict(comp) for name, comp in evaluation.ratios.items()}

    # One final pair, stored and returned identically: a filing with any open
    # issue is never published as compliant or non-compliant (D-027).
    if transient:
        # Nothing is stored for a transient record: newly detected anomalies and
        # the issues it already carries both block.
        detected = quality.detect_ratio_anomalies(snapshot, evaluation)
        quality_issues = list(dict.fromkeys(detected + list(record.get("quality_issues") or [])))
        verdict, final_is_compliant, summary = quality.publish(
            evaluation.verdict,
            evaluation.is_compliant,
            build_summary(evaluation),
            quality_issues,
            detected,
        )
    else:
        try:
            published = quality.publish_evaluation(
                _get_db(),
                snapshot,
                evaluation,
                filing_date=snapshot.filing_date,
                narration_source="api",
                market_cap_used=market_cap,
                trailing_cap_used=trailing,
                market_data_provider=provider,
            )
        except Exception:
            # Fail closed: without the locked issue read nothing is published.
            api_logger.exception("Publishing evaluation failed for %s", snapshot.symbol)
            raise HTTPException(status_code=503, detail="Filing data unavailable")
        verdict = published["verdict"]
        final_is_compliant = published["is_compliant"]
        summary = published["summary"]
        quality_issues = published["quality_issues"]

    record["is_compliant"] = final_is_compliant
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

    # The cache holds stored rows; every response is masked with the current
    # open issues, so a warm cache cannot outlive a newly recorded blocker.
    # ponytail: one issue read per row per request; batch them into one
    # ANY() query if /filings/recent load ever matters.
    cache_key = f"recent:{limit}"
    rows = _cache_get(RECENT_FILINGS_CACHE, cache_key)
    if not rows:
        rows = _get_db().get_recent_filings(limit=limit)
        _cache_set(RECENT_FILINGS_CACHE, cache_key, rows, RECENT_CACHE_TTL_SECONDS)
    return [_filing_response(dict(row)) for row in rows]


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
    record: Optional[Dict[str, Any]] = _get_db().get_latest_filing(normalized)

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
    record.setdefault("company_name", "")
    record.setdefault("category", "")
    return _filing_response(record)


@app.get("/filings/{symbol}/history", response_model=FilingHistoryResponse)
async def filing_history(
    symbol: str,
    limit: int = 10,
    cursor: Optional[str] = None,
    include_ratios: bool = True,
    authorization: Optional[str] = Header(None),
) -> FilingHistoryResponse:
    """Return a symbol's recent filings for context/timeline views."""

    _require_paid_feature(authorization, "History view")
    normalized = symbol.strip().upper()
    db = _get_db()
    parsed_cursor = _parse_path_datetime(cursor) if cursor else None
    effective_limit = max(1, min(limit, 40))
    cache_key = (
        f"history:{normalized}:{effective_limit}:"
        f"{parsed_cursor.isoformat() if parsed_cursor else 'none'}:"
        f"{'ratios' if include_ratios else 'lite'}"
    )
    # Cached as stored/evaluated rows, masked with current open issues on every
    # response (see recent_filings).
    cached = _cache_get(HISTORY_CACHE, cache_key)
    if cached:
        entries, next_cursor = cached
        return FilingHistoryResponse(
            entries=[_filing_response(dict(row)) for row in entries],
            next_cursor=next_cursor,
        )
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

    for row in entries:
        if include_ratios and not row.get("ratios"):
            try:
                ratio_payload = _ensure_filing_evaluation(
                    row, allow_market_fetch=False
                )
                if ratio_payload is not None:
                    row["ratios"] = ratio_payload
            except HTTPException:
                # Leave ratios empty; evaluation can be retried later.
                pass
    responses = [_filing_response(dict(row)) for row in entries]

    next_cursor = None
    if has_more and responses:
        next_cursor = responses[-1].filing_date

    _cache_set(HISTORY_CACHE, cache_key, (entries, next_cursor), HISTORY_CACHE_TTL_SECONDS)
    return FilingHistoryResponse(entries=responses, next_cursor=next_cursor)


@app.get("/market-data/{symbol}", response_model=MarketQuoteResponse)
async def market_data(
    symbol: str,
    authorization: Optional[str] = Header(None),
) -> MarketQuoteResponse:
    """Fetch market cap/share price for a symbol via the Indian market API.

    Requires a session and is metered per user: a cache miss here bills a
    request against the upstream vendor quota, so an open endpoint is a direct
    cost-of-goods leak.
    """

    _, session = _require_session(authorization)
    _enforce_rate_limit("metered", f"user:{session['user_id']}")
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
            _bound_cache(MARKET_CACHE, CACHE_MAX_ENTRIES)
            MARKET_CACHE[key] = (now, db_snapshot)
        else:
            market_cap, share_price, provider = _fetch_and_cache_market_data(symbol)

    return MarketQuoteResponse(
        symbol=key, market_cap=market_cap, share_price=share_price, provider=provider
    )


@app.get("/ingestion/stats")
async def ingestion_stats(
    authorization: Optional[str] = Header(None),
) -> Dict[str, Any]:
    """Fetch counts for announcements and financial snapshots (operators only)."""

    _require_admin(authorization, "Ingestion stats")
    stats = _get_db().get_database_stats()
    return stats


@app.get("/ops/metrics")
async def ops_metrics(
    authorization: Optional[str] = Header(None),
) -> Dict[str, Any]:
    """Expose summarized ingestion + reliability metrics for dashboards.

    Operator-only: the payload names failing symbols, upstream providers and
    LLM error strings, which is internal reliability detail.
    """

    _require_admin(authorization, "Ops metrics")
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
async def submit_feedback(
    payload: FeedbackPayload, request: Request = None
) -> FeedbackSubmissionResponse:
    """Store user feedback about a filing or verdict."""

    _enforce_rate_limit("anon_write", _client_identity(request))
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
    cleaned = value.strip()
    if cleaned.endswith("Z"):
        cleaned = f"{cleaned[:-1]}+00:00"
    try:
        parsed = datetime.fromisoformat(cleaned)
    except ValueError:
        try:
            match = re.search(r"\d{4}-\d{2}-\d{2}", cleaned)
            if not match:
                raise ValueError("No ISO date found")
            parsed_date = date.fromisoformat(match.group(0))
            parsed = datetime.combine(parsed_date, datetime.min.time(), tzinfo=timezone.utc)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="Invalid filing_date format") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


@app.get("/feedback", response_model=List[FeedbackReportResponse])
async def list_feedback(
    status: Optional[str] = None,
    limit: int = 50,
    authorization: Optional[str] = Header(None),
) -> List[FeedbackReportResponse]:
    """List feedback reports for reviewers.

    Admin-only: rows carry the reporter's free-text contact details.
    """

    _require_admin(authorization, "Feedback queue")
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
    feedback_id: int,
    payload: FeedbackUpdatePayload,
    authorization: Optional[str] = Header(None),
) -> FeedbackReportResponse:
    """Update a feedback report (resolve/reopen, add reviewer notes)."""

    session = _require_admin(authorization, "Feedback triage")
    status = payload.status.lower()
    if status not in FEEDBACK_STATUSES:
        raise HTTPException(status_code=400, detail="Invalid feedback status")

    # Attribute the action to the authenticated reviewer rather than to a
    # self-declared name in the request body.
    reviewer = session.get("email") or payload.reviewer or "dashboard"
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
async def feedback_events(
    feedback_id: int,
    authorization: Optional[str] = Header(None),
) -> List[FeedbackEventResponse]:
    """Return audit history for reviewers.

    Requesters use ``GET /feedback/status/{token}`` instead, which is scoped to
    their own ticket by an unguessable token.
    """

    _require_admin(authorization, "Feedback audit trail")
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

    _require_admin(authorization, "Governance review")
    normalized_symbol = symbol.strip().upper()
    date_only = bool(re.fullmatch(r"\d{4}-\d{2}-\d{2}", filing_date.strip()))
    parsed_date = _parse_path_datetime(filing_date)
    db = _get_db()
    record = db.get_filing(normalized_symbol, parsed_date)
    if not record and date_only:
        record = db.get_filing_by_date(normalized_symbol, parsed_date.date())
    if not record:
        raise HTTPException(status_code=404, detail="Filing not found")
    if record.get("filing_date") and record["filing_date"] != parsed_date:
        parsed_date = record["filing_date"]

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

    override_row = db.get_governance_override(normalized_symbol, parsed_date)
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

    _require_admin(authorization, "Governance overrides")
    rows = _get_db().list_governance_overrides(symbol=symbol, limit=max(1, min(limit, 200)))
    return [GovernanceOverrideResponse(**row) for row in rows]


@app.put("/governance/overrides", response_model=GovernanceOverrideResponse)
async def upsert_governance_override(
    payload: GovernanceOverridePayload,
    authorization: Optional[str] = Header(None),
) -> GovernanceOverrideResponse:
    """Create or update a governance override entry.

    Admin-only. An override rewrites the AAOIFI inputs used for *every* user's
    verdict on that filing, so it is a data-integrity operation, not a paid
    feature.
    """

    session = _require_admin(authorization, "Governance overrides")
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

    reviewer = session.get("email") or payload.reviewer
    row = _get_db().upsert_governance_override(
        symbol=payload.symbol,
        filing_date=payload.filing_date,
        accounts_receivable=payload.accounts_receivable,
        liquid_assets=payload.liquid_assets,
        non_halal_income=payload.non_halal_income,
        governance_notes=payload.governance_notes,
        reviewer=reviewer,
        reason=payload.reason,
        source=payload.source or "manual",
    )
    api_logger.info(
        "Governance override applied symbol=%s filing_date=%s reviewer=%s",
        payload.symbol,
        payload.filing_date,
        reviewer,
    )
    reeval_note = _trigger_feedback_reevaluation(payload.symbol, payload.filing_date)
    _auto_reevaluate_feedback_reports(
        payload.symbol,
        payload.filing_date,
        reviewer,
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

    _require_admin(authorization, "Governance overrides")
    parsed_date = _parse_path_datetime(filing_date)
    deleted = _get_db().delete_governance_override(symbol, parsed_date)
    if not deleted:
        raise HTTPException(status_code=404, detail="Override not found")


__all__ = ["app"]

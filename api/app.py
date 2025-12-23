#!/usr/bin/env python3
"""FastAPI service exposing the Halal ratio engine."""

from __future__ import annotations

from dataclasses import asdict
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Literal

import logging
import os
import secrets
import time
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
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
    BhavcopyMarketResolver,
    indian_api_enabled,
)
from crawler import BSEAnnouncementsFetcher
from etl import FinancialDataProcessor
from monitoring.notifier import OpsNotifier


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
narrator = NarrationEngine(config=narrator_config)
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
MARKET_FAILURE_ALERT_THRESHOLD = int(
    os.getenv("MARKET_FAILURE_ALERT_THRESHOLD", "3")
)


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
        api_logger.debug(
            "Failed to persist Bhavcopy quote for %s@%s", symbol, trade_date
        )


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
    if not missing_fields and not needs_market_cap:
        return

    snapshot = None
    for candidate in _indian_api_candidates(symbol):
        snapshot = fetch_indian_financial_snapshot(candidate, target_date=filing_date)
        if snapshot:
            break
    if not snapshot:
        return

    notes = []
    for field in missing_fields:
        value = snapshot.metrics.get(field)
        if value is not None:
            record[field] = value
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


def _reset_market_failure(symbol: str) -> None:
    MARKET_FAILURES.pop(symbol, None)


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
    else:
        MARKET_FAILURES[symbol] = count


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

        filing_date = snapshot.end_date or datetime.utcnow().date()
        filing_dt = datetime(
            filing_date.year,
            filing_date.month,
            filing_date.day,
            tzinfo=timezone.utc,
        )

        if snapshot.bse_code:
            _prime_symbol_metadata(
                normalized,
                snapshot.bse_code,
                snapshot.nse_code or candidate,
            )

        record: Dict[str, Any] = {
            "symbol": normalized,
            "symbol_alias": snapshot.nse_code or candidate,
            "company_name": snapshot.company_name or normalized,
            "filing_date": filing_dt,
            "category": "Realtime Snapshot",
            "headline": "Metrics sourced from Indian market API",
            "confidence": "LOW",
            "governance_notes": "Derived from Indian API snapshot",
            "quality_issues": [],
            "_transient": True,
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

        if snapshot.market_cap is not None:
            record["market_cap_used"] = snapshot.market_cap
            record["market_data_provider"] = "indianapi"

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
            _reset_market_failure(key)
            return (
                indian_snapshot.market_cap,
                indian_snapshot.share_price,
                "indianapi",
            )
        attempt_details.append(
            "Indian API lookup unavailable or returned no data for configured candidates."
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
    else:
        attempt_details.append("Bhavcopy returned no quote.")

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


def _evaluate_request(payload: HalalScoreRequest):
    snapshot_input = FinancialSnapshotInput(**payload.snapshot.model_dump())
    market_input = MarketDataInput(**payload.market_data.model_dump())

    if not (market_input.market_cap or market_input.trailing_market_cap):
        raise HTTPException(
            status_code=422,
            detail="market_cap or trailing_market_cap is required to compute ratios",
        )
    return engine.evaluate(snapshot_input, market_input)


@app.post("/halal-score", response_model=HalalScoreResponse)
async def halal_score(payload: HalalScoreRequest) -> HalalScoreResponse:
    """Compute the halal verdict for provided financial metrics."""

    evaluation = _evaluate_request(payload)

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
async def narrate(payload: HalalScoreRequest) -> NarrationResponse:
    """Generate a plain-English explanation alongside the halal verdict."""

    evaluation = _evaluate_request(payload)
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


@app.post("/watchlist", response_model=WatchlistEntryPayload)
async def add_watchlist(entry: WatchlistEntryPayload) -> WatchlistEntryPayload:
    """Register or update a watchlist entry."""

    watch_storage.upsert(
        WatchEntry(
            user_id=entry.user_id,
            symbol=entry.symbol,
            trigger=entry.trigger,
        )
    )
    return entry


@app.get("/watchlist/{user_id}", response_model=List[WatchlistEntryPayload])
async def list_watchlist(user_id: str) -> List[WatchlistEntryPayload]:
    """List watchlist entries for a user."""

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
async def filing_detail(symbol: str, refresh: bool = False) -> FilingResponse:
    """Return the latest filing and computed ratios for a symbol."""

    normalized = symbol.strip().upper()
    record: Optional[Dict[str, Any]] = None

    if not refresh:
        record = _get_db().get_latest_filing(normalized)

    if refresh or not record or _needs_financial_refresh(record):
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


@app.get("/filings/{symbol}/history", response_model=List[FilingResponse])
async def filing_history(symbol: str, limit: int = 10) -> List[FilingResponse]:
    """Return a symbol's recent filings for context/timeline views."""

    normalized = symbol.strip().upper()
    rows = _get_db().get_filing_history(normalized, limit=limit)
    if not rows:
        record = _fetch_latest_filing_from_bse(normalized)
        if not record:
            raise HTTPException(status_code=404, detail="No filings found for symbol")
        rows = [record]

    responses: List[FilingResponse] = []
    for row in rows:
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
    return responses


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


@app.get("/feedback/status/{tracking_token}", response_model=FeedbackPublicStatusResponse)
async def feedback_status(tracking_token: str) -> FeedbackPublicStatusResponse:
    """Return sanitized status for a feedback ticket."""

    row = _get_db().get_feedback_by_token(tracking_token.strip())
    if not row:
        raise HTTPException(status_code=404, detail="Feedback ticket not found")

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
    )


@app.get("/governance/overrides", response_model=List[GovernanceOverrideResponse])
async def list_governance_overrides(
    symbol: Optional[str] = None, limit: int = 50
) -> List[GovernanceOverrideResponse]:
    """List governance overrides applied to filings."""

    rows = _get_db().list_governance_overrides(symbol=symbol, limit=max(1, min(limit, 200)))
    return [GovernanceOverrideResponse(**row) for row in rows]


@app.put("/governance/overrides", response_model=GovernanceOverrideResponse)
async def upsert_governance_override(
    payload: GovernanceOverridePayload,
) -> GovernanceOverrideResponse:
    """Create or update a governance override entry."""

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
    return GovernanceOverrideResponse(**row)


@app.delete("/governance/overrides/{symbol}/{filing_date}", status_code=204)
async def delete_governance_override(symbol: str, filing_date: str) -> None:
    """Remove an override (switch back to raw extracted metrics)."""

    parsed_date = _parse_path_datetime(filing_date)
    deleted = _get_db().delete_governance_override(symbol, parsed_date)
    if not deleted:
        raise HTTPException(status_code=404, detail="Override not found")


__all__ = ["app"]

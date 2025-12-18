#!/usr/bin/env python3
"""FastAPI service exposing the Halal ratio engine."""

from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any, Dict, List, Optional

import logging
import os
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
from narrator import NarrationEngine, NarratorConfig
from ratio_engine import (
    FinancialSnapshotInput,
    MarketDataInput,
    RatioEngine,
)
from database import BSEDatabaseManager
from market_data import fetch_yahoo_quote, fetch_tiingo_quote, BhavcopyMarketResolver
from market_data.tickers import build_ticker_candidates, build_tiingo_tickers
from crawler import BSEAnnouncementsFetcher
from etl import FinancialDataProcessor


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


LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format="%(asctime)s %(levelname)s [api] %(message)s",
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
MARKET_CACHE: Dict[str, tuple[float, tuple[Optional[float], Optional[float]]]] = {}
CACHE_TTL_SECONDS = 300
BACKOFF_SECONDS = 30
bhavcopy_resolver = BhavcopyMarketResolver()
REALTIME_LOOKBACK_DAYS = 30
REALTIME_LOOKBACK_MULTIPLIER = 4
_realtime_fetcher: Optional[BSEAnnouncementsFetcher] = None
_realtime_processor: Optional[FinancialDataProcessor] = None
api_logger = logging.getLogger("api")


def _get_db() -> BSEDatabaseManager:
    if DB_MANAGER is None:
        raise HTTPException(status_code=503, detail="Database unavailable")
    return DB_MANAGER


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

    lookbacks = [
        REALTIME_LOOKBACK_DAYS,
        REALTIME_LOOKBACK_DAYS * REALTIME_LOOKBACK_MULTIPLIER,
    ]

    for window in lookbacks:
        start = (today - timedelta(days=window)).strftime("%Y%m%d")
        end = today.strftime("%Y%m%d")
        try:
            announcements = fetcher.get_company_announcements(symbol, start, end)
        except Exception as exc:  # pragma: no cover - network failures
            api_logger.warning("Realtime BSE fetch failed for %s: %s", symbol, exc)
            break

        if not announcements:
            continue

        try:
            db.insert_announcements(announcements)
        except Exception as exc:  # pragma: no cover - logged upstream
            api_logger.warning("Failed to persist realtime announcements for %s: %s", symbol, exc)

        try:
            snapshots = processor.process_announcements(announcements)
        except Exception as exc:  # pragma: no cover - extraction failures
            api_logger.warning("Realtime processing failed for %s: %s", symbol, exc)
            snapshots = []

        if snapshots:
            try:
                db.insert_financial_snapshots(snapshots)
            except Exception as exc:  # pragma: no cover
                api_logger.warning("Failed to store snapshots for %s: %s", symbol, exc)

        record = db.get_latest_filing(symbol)
        if record:
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


def _ticker_candidates(symbol: str) -> List[str]:
    normalized = (symbol or "").strip().upper()
    metadata = _get_symbol_metadata_cached(normalized)
    alias = metadata.get("symbol_alias") if metadata else None
    primary = metadata.get("symbol") if metadata else normalized
    additional = []
    if normalized and normalized != primary:
        additional.append(normalized)
    return build_ticker_candidates(primary, alias, additional=additional)


def _tiingo_candidates(symbol: str) -> List[str]:
    normalized = (symbol or "").strip().upper()
    metadata = _get_symbol_metadata_cached(normalized)
    alias = metadata.get("symbol_alias") if metadata else None
    primary = metadata.get("symbol") if metadata else normalized
    additional = []
    if normalized and normalized != primary:
        additional.append(normalized)
    return build_tiingo_tickers(primary, alias, additional=additional)


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
        non_permissible_income=None,
    )


def _market_data_for_filing(symbol: str, as_of: datetime) -> tuple[Optional[float], Optional[float]]:
    key = symbol.strip().upper()
    db_snapshot = _get_db().get_cached_market_data(key, as_of)
    if db_snapshot:
        return db_snapshot
    return _fetch_and_cache_market_data(symbol, as_of)


def _fetch_and_cache_market_data(
    symbol: str, as_of: Optional[datetime] = None
) -> tuple[Optional[float], Optional[float]]:
    key = symbol.strip().upper()
    now = time.time()
    cached = MARKET_CACHE.get(key)
    if cached and now - cached[0] < CACHE_TTL_SECONDS:
        return cached[1]

    tiingo_candidates = _tiingo_candidates(symbol)
    for ticker in tiingo_candidates:
        market_cap, share_price = fetch_tiingo_quote(ticker)
        if market_cap is None and share_price is None:
            continue
        _get_db().insert_market_snapshot(
            symbol=key, market_cap=market_cap, share_price=share_price, provider="tiingo"
        )
        MARKET_CACHE[key] = (now, (market_cap, share_price))
        return market_cap, share_price

    candidates = _ticker_candidates(symbol)
    for ticker in candidates:
        market_cap, share_price = fetch_yahoo_quote(
            ticker, backoff_seconds=BACKOFF_SECONDS
        )
        if market_cap is None and share_price is None:
            continue
        _get_db().insert_market_snapshot(
            symbol=key, market_cap=market_cap, share_price=share_price, provider="yahoo"
        )
        MARKET_CACHE[key] = (now, (market_cap, share_price))
        return market_cap, share_price
    fallback_cap, fallback_price = bhavcopy_resolver.resolve(symbol, as_of)
    if fallback_cap is not None or fallback_price is not None:
        _get_db().insert_market_snapshot(
            symbol=key,
            market_cap=fallback_cap,
            share_price=fallback_price,
            provider="bhavcopy",
        )
        MARKET_CACHE[key] = (now, (fallback_cap, fallback_price))
        return fallback_cap, fallback_price
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
    audit_status: Optional[str] = None
    is_compliant: Optional[bool] = None
    verdict: Optional[str] = None
    summary: Optional[str] = None
    narration_source: Optional[str] = None
    ratios: Optional[Dict[str, RatioComputationPayload]] = None
    market_cap_used: Optional[float] = None
    trailing_cap_used: Optional[float] = None
    quality_issues: List[str] = Field(default_factory=list)


class MarketQuoteResponse(BaseModel):
    """Market data proxy response."""

    symbol: str
    market_cap: Optional[float] = None
    share_price: Optional[float] = None


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
    ratios = _ratios_payload(record.get("ratios"))
    if ratios is not None:
        return ratios

    snapshot = _snapshot_from_record(record)
    if not snapshot:
        return None

    market_cap = record.get("market_cap_used")
    trailing = record.get("trailing_cap_used")
    share_price: Optional[float] = None

    if market_cap is None and trailing is None:
        market_cap, share_price = _market_data_for_filing(
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
    db = _get_db()
    if quality_issues:
        for issue in quality_issues:
            db.record_quality_issue(
                snapshot.symbol, snapshot.filing_date, "ratio_anomaly", issue
            )
        verdict = "needs-review"
        summary = "Flagged for manual review due to anomalous ratios."
        record["is_compliant"] = None
    else:
        db.resolve_quality_issues(snapshot.symbol, snapshot.filing_date)
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
    )

    record["is_compliant"] = (
        None if quality_issues else evaluation.is_compliant
    )
    record["verdict"] = verdict
    record["summary"] = summary
    record["narration_source"] = "api"
    record["market_cap_used"] = market_cap
    record["trailing_cap_used"] = trailing
    record["ratios"] = ratios_dict
    record["quality_issues"] = quality_issues

    return _ratios_payload(ratios_dict)


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


@app.get("/filings/{symbol}", response_model=FilingResponse)
async def filing_detail(symbol: str) -> FilingResponse:
    """Return the latest filing and computed ratios for a symbol."""

    normalized = symbol.strip().upper()
    record = _get_db().get_latest_filing(normalized)
    if not record:
        record = _fetch_latest_filing_from_bse(normalized)
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


@app.get("/market-data/{symbol}", response_model=MarketQuoteResponse)
async def market_data(symbol: str) -> MarketQuoteResponse:
    """Fetch market cap/share price for a symbol via Yahoo Finance."""

    key = symbol.strip().upper()
    now = time.time()
    cached = MARKET_CACHE.get(key)

    if cached and now - cached[0] < CACHE_TTL_SECONDS:
        market_cap, share_price = cached[1]
    else:
        db_snapshot = _get_db().get_cached_market_data(key)
        if db_snapshot:
            market_cap, share_price = db_snapshot
            MARKET_CACHE[key] = (now, db_snapshot)
        else:
            market_cap, share_price = _fetch_and_cache_market_data(symbol)

    return MarketQuoteResponse(symbol=key, market_cap=market_cap, share_price=share_price)


@app.get("/ingestion/stats")
async def ingestion_stats() -> Dict[str, Any]:
    """Fetch counts for announcements and financial snapshots."""

    stats = _get_db().get_database_stats()
    return stats


@app.post("/feedback", status_code=201)
async def submit_feedback(payload: FeedbackPayload) -> Dict[str, str]:
    """Store user feedback about a filing or verdict."""

    message = payload.message.strip()
    if not message:
        raise HTTPException(status_code=400, detail="Feedback message is required")

    try:
        _get_db().insert_feedback(
            symbol=(payload.symbol or "").strip().upper() or None,
            filing_date=payload.filing_date,
            verdict=payload.verdict,
            message=message,
            contact=payload.contact,
            source="ui",
        )
    except HTTPException:
        raise
    except Exception as exc:  # pragma: no cover - logged upstream
        raise HTTPException(status_code=500, detail="Unable to store feedback") from exc

    return {"status": "received"}


__all__ = ["app"]

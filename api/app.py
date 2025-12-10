#!/usr/bin/env python3
"""FastAPI service exposing the Halal ratio engine."""

from __future__ import annotations

from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import logging
import time
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, ConfigDict

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
    TICKER_MAP,
    SMTP_HOST,
    SMTP_PORT,
    SMTP_USERNAME,
    SMTP_PASSWORD,
    ALERT_EMAIL_SENDER,
    ALERT_EMAIL_RECIPIENT,
)
from narrator import NarrationEngine, NarratorConfig
from ratio_engine import (
    FinancialSnapshotInput,
    MarketDataInput,
    RatioEngine,
)
from database import BSEDatabaseManager
from market_data import fetch_yahoo_quote


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


app = FastAPI(title="Halal-Lens Ratio API", version="0.1.0")
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
db_manager = BSEDatabaseManager()
SYMBOL_CODE_MAP: Dict[str, str] = {}
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


def _normalize_ticker(symbol: str) -> str:
    sym = (symbol or "").strip().upper()
    if not sym:
        raise HTTPException(status_code=400, detail="symbol is required")
    if sym.endswith((".NS", ".BO")):
        return sym
    if sym in TICKER_MAP:
        return TICKER_MAP[sym]
    script_code = SYMBOL_CODE_MAP.get(sym)
    if not script_code:
        code = db_manager.get_symbol_code(sym)
        if code:
            SYMBOL_CODE_MAP[sym] = code
            script_code = code
    if script_code and script_code.isdigit():
        return f"{script_code}.BO"
    if sym.isdigit():
        return f"{sym}.BO"
    return f"{sym}.NS"


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


class MarketQuoteResponse(BaseModel):
    """Market data proxy response."""

    symbol: str
    market_cap: Optional[float] = None
    share_price: Optional[float] = None


@app.get("/filings/recent", response_model=List[FilingResponse])
async def recent_filings(limit: int = 20) -> List[FilingResponse]:
    """Return recent filings from announcements."""

    rows = db_manager.get_recent_filings(limit=limit)
    return [FilingResponse(**row) for row in rows]


@app.get("/market-data/{symbol}", response_model=MarketQuoteResponse)
async def market_data(symbol: str) -> MarketQuoteResponse:
    """Fetch market cap/share price for a symbol via Yahoo Finance."""

    key = symbol.strip().upper()
    now = time.time()
    cached = MARKET_CACHE.get(key)
    market_cap: Optional[float] = None
    share_price: Optional[float] = None

    if cached and now - cached[0] < CACHE_TTL_SECONDS:
        market_cap, share_price = cached[1]
    else:
        db_snapshot = db_manager.get_cached_market_data(key)
        if db_snapshot:
            market_cap, share_price = db_snapshot
            MARKET_CACHE[key] = (now, db_snapshot)
        else:
            ticker = _normalize_ticker(symbol)
            market_cap, share_price = fetch_yahoo_quote(
                ticker, backoff_seconds=BACKOFF_SECONDS
            )
            if market_cap is None and share_price is None:
                raise HTTPException(status_code=404, detail="Market data unavailable")
            db_manager.insert_market_snapshot(
                key, market_cap, share_price, provider="yahoo"
            )
            MARKET_CACHE[key] = (now, (market_cap, share_price))

    return MarketQuoteResponse(symbol=key, market_cap=market_cap, share_price=share_price)


@app.get("/ingestion/stats")
async def ingestion_stats() -> Dict[str, Any]:
    """Fetch counts for announcements and financial snapshots."""

    stats = db_manager.get_database_stats()
    return stats


__all__ = ["app"]

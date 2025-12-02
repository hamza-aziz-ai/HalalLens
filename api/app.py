#!/usr/bin/env python3
"""FastAPI service exposing the Halal ratio engine."""

from __future__ import annotations

from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, ConfigDict

from alerts import AlertEngine, AlertEvent, WatchEntry, WatchlistStorage
from narrator import NarrationEngine
from ratio_engine import (
    FinancialSnapshotInput,
    MarketDataInput,
    RatioEngine,
)


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
narrator = NarrationEngine()
watch_storage = WatchlistStorage(Path("cache/watchlists.json"))
alert_engine = AlertEngine(watch_storage)


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
    return [WatchlistEntryPayload(**asdict(entry)) for entry in entries]


@app.post("/alerts/check", response_model=List[AlertEventPayload])
async def check_alerts(payload: AlertCheckPayload) -> List[AlertEventPayload]:
    """Evaluate compliance flip alerts for a symbol."""

    events: List[AlertEvent] = alert_engine.process_verdict(
        payload.symbol, payload.is_compliant
    )
    return [AlertEventPayload(**asdict(event)) for event in events]


__all__ = ["app"]

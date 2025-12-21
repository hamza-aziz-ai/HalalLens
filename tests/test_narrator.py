#!/usr/bin/env python3
"""Tests for the narration engine."""

import json
from datetime import datetime

from narrator import NarrationEngine, NarratorConfig
from narrator.llm import LLMNarrationError
from ratio_engine import (
    FinancialSnapshotInput,
    MarketDataInput,
    RatioEngine,
)


def test_narration_contains_all_ratios():
    engine = RatioEngine()
    snapshot = FinancialSnapshotInput(
        symbol="ABC",
        filing_date=datetime(2024, 6, 30),
        total_debt=10_000_000,
        cash_equiv=2_000_000,
        revenue=100_000_000,
        non_permissible_income=500_000,
    )
    market = MarketDataInput(market_cap=200_000_000)

    evaluation = engine.evaluate(snapshot, market)

    narrator = NarrationEngine()
    result = narrator.build(evaluation)

    assert "ABC" in result.summary
    assert len(result.bullets) >= 3
    assert any("Debt to market cap" in bullet for bullet in result.bullets)
    assert result.verdict.lower().startswith("compliant")


def test_narration_handles_missing_metrics():
    engine = RatioEngine()
    snapshot = FinancialSnapshotInput(
        symbol="XYZ",
        filing_date=datetime(2024, 6, 30),
        total_debt=None,
        revenue=None,
    )
    market = MarketDataInput(market_cap=None, trailing_market_cap=100_000_000)

    evaluation = engine.evaluate(snapshot, market)

    narrator = NarrationEngine()
    result = narrator.build(evaluation)

    assert "Insufficient" in result.bullets[-1] or any(
        "cannot compute" in bullet for bullet in result.bullets
    )
    assert result.citations != []


def test_llm_narrator_consumes_client_output():
    engine = RatioEngine()
    snapshot = FinancialSnapshotInput(
        symbol="LMN",
        filing_date=datetime(2024, 6, 30),
        total_debt=10_000_000,
        cash_equiv=2_000_000,
        revenue=100_000_000,
        non_permissible_income=500_000,
    )
    market = MarketDataInput(market_cap=200_000_000)
    evaluation = engine.evaluate(snapshot, market)

    fake_response = json.dumps(
        {
            "summary": "LLM summary",
            "verdict": "LLM verdict",
            "bullets": ["Point A", "Point B"],
            "citations": ["Doc 1"],
        }
    )

    class FakeClient:
        def __init__(self):
            self.calls = 0

        def complete(self, *args, **kwargs):
            self.calls += 1
            return fake_response

    narrator = NarrationEngine(
        config=NarratorConfig(
            mode="llm", endpoint="http://fake", model="llama3", temperature=0.0
        ),
        llm_client=FakeClient(),
    )

    result = narrator.build(evaluation)
    assert result.summary == "LLM summary"
    assert result.bullets == ["Point A", "Point B"]


def test_llm_failure_fallbacks_to_rule_based():
    engine = RatioEngine()
    snapshot = FinancialSnapshotInput(
        symbol="FALL",
        filing_date=datetime(2024, 6, 30),
        total_debt=10_000_000,
        cash_equiv=2_000_000,
        revenue=100_000_000,
        non_permissible_income=500_000,
    )
    market = MarketDataInput(market_cap=200_000_000)
    evaluation = engine.evaluate(snapshot, market)

    class ErrorClient:
        def complete(self, *args, **kwargs):
            raise LLMNarrationError("boom")

    narrator = NarrationEngine(
        config=NarratorConfig(mode="llm", endpoint="x", model="y"),
        llm_client=ErrorClient(),
    )

    result = narrator.build(evaluation)
    assert result.summary.lower().startswith("fall is")

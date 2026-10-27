#!/usr/bin/env python3
"""Tests for the narration engine."""

import json
from datetime import datetime

import pytest

from narrator import NarrationEngine, NarratorConfig
from narrator.llm import LLMNarrationEngine, LLMNarrationError
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
        interest_income=0.0,
        dividend_income=0.0,
        accounts_receivable=10_000_000,
        liquid_assets=20_000_000,
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
        interest_income=0.0,
        dividend_income=0.0,
        accounts_receivable=10_000_000,
        liquid_assets=20_000_000,
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

    narrator = LLMNarrationEngine(
        FakeClient(),
        NarratorConfig(
            mode="llm", endpoint="http://fake", model="llama3", temperature=0.0
        ),
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
        interest_income=0.0,
        dividend_income=0.0,
        accounts_receivable=10_000_000,
        liquid_assets=20_000_000,
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


# --- Narration is deterministic on screening paths --------------------------


def _evaluation(**overrides):
    base = dict(
        symbol="AUTH",
        filing_date=datetime(2024, 6, 30),
        total_debt=10_000_000,
        cash_equiv=2_000_000,
        revenue=100_000_000,
        non_permissible_income=500_000,
        interest_income=0.0,
        dividend_income=0.0,
        accounts_receivable=10_000_000,
        liquid_assets=20_000_000,
    )
    base.update(overrides)
    return RatioEngine().evaluate(
        FinancialSnapshotInput(**base), MarketDataInput(market_cap=200_000_000)
    )


class _ExplodingClient:
    """Fails the test if anything asks the model for text."""

    def complete(self, *args, **kwargs):
        raise AssertionError("LLM must not be called on screening paths")


def test_insufficient_data_is_not_narrated_as_non_compliant():
    evaluation = _evaluation(interest_income=None)

    result = NarrationEngine().build(evaluation)

    assert evaluation.verdict == "insufficient-data"
    assert "NOT compliant" not in result.verdict
    assert "insufficient" in result.verdict.lower()
    assert result.metadata["screen_verdict"] == "insufficient-data"


@pytest.mark.parametrize(
    "overrides, verdict, label",
    [
        ({}, "compliant", "compliant with AAOIFI screens"),
        ({"total_debt": 60_000_001}, "non-compliant", "NOT compliant with AAOIFI screens"),
        ({"interest_income": None}, "insufficient-data", "insufficient data to screen against AAOIFI"),
    ],
)
def test_llm_mode_never_calls_the_model_and_uses_the_engine_label(
    overrides, verdict, label
):
    evaluation = _evaluation(**overrides)
    assert evaluation.verdict == verdict

    narrator = NarrationEngine(
        config=NarratorConfig(mode="llm", endpoint="http://fake", model="m"),
        llm_client=_ExplodingClient(),
    )
    result = narrator.build(evaluation)

    assert result.verdict == label
    assert result.metadata == {"source": "rule_based", "screen_verdict": verdict}


def test_llm_mode_warns_once_when_bypassed(caplog):
    narrator = NarrationEngine(
        config=NarratorConfig(mode="llm", endpoint="http://fake", model="m"),
        llm_client=_ExplodingClient(),
    )
    with caplog.at_level("WARNING", logger="narrator"):
        narrator.build(_evaluation())
        narrator.build(_evaluation())

    assert sum("LLM narration is disabled" in r.message for r in caplog.records) == 1


def test_bypass_warning_follows_the_configured_mode_not_client_construction(caplog):
    # mode=llm but no endpoint/model: no client is built, the operator still hears it.
    narrator = NarrationEngine(config=NarratorConfig(mode="llm"))
    assert narrator.llm_engine is None

    with caplog.at_level("WARNING", logger="narrator"):
        narrator.build(_evaluation())

    assert any("LLM narration is disabled" in r.message for r in caplog.records)

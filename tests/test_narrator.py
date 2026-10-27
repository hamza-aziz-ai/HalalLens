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


def test_insufficient_data_is_not_narrated_as_non_compliant():
    evaluation = _evaluation(interest_income=None)

    result = NarrationEngine().build(evaluation)

    assert evaluation.verdict == "insufficient-data"
    assert "NOT compliant" not in result.verdict
    assert "insufficient" in result.verdict.lower()
    assert result.metadata["screen_verdict"] == "insufficient-data"


class _FixedClient:
    """Returns one canned JSON answer and counts calls."""

    def __init__(self, summary, bullets=("b",), claimed="engine"):
        self.calls = 0
        self.summary = summary
        self.bullets = list(bullets)
        self.claimed = claimed

    def answer(self, verdict):
        payload = {
            "summary": self.summary,
            "verdict": "whatever the model says",
            "bullets": self.bullets,
            "citations": ["c"],
        }
        claimed = verdict if self.claimed == "engine" else self.claimed
        if claimed is not None:
            payload["screen_verdict"] = claimed
        return json.dumps(payload)


def _llm_narrator(client, verdict, failure_callback=None):
    """NarrationEngine whose model answers `client` as if the engine said `verdict`."""

    class Bound:
        def complete(self, *args, **kwargs):
            client.calls += 1
            return client.answer(verdict)

    return NarrationEngine(
        config=NarratorConfig(mode="llm", endpoint="http://fake", model="m"),
        llm_client=Bound(),
        failure_callback=failure_callback,
    )


GOOD = {
    "compliant": "Debt, cash and income ratios sit comfortably inside their caps.",
    "non-compliant": "The debt ratio is above its cap, so the screen is failed.",
}


@pytest.mark.parametrize(
    "overrides, verdict",
    [({}, "compliant"), ({"total_debt": 60_000_001}, "non-compliant")],
)
def test_consistent_llm_text_is_kept_with_the_engine_label(overrides, verdict):
    evaluation = _evaluation(**overrides)
    client = _FixedClient(GOOD[verdict])

    result = _llm_narrator(client, verdict).build(evaluation)

    assert evaluation.verdict == verdict and client.calls == 1
    assert result.metadata["source"] == "llm"
    assert result.summary == GOOD[verdict]
    assert result.verdict == NarrationEngine().rule_based.verdict_text[verdict]
    assert result.metadata["screen_verdict"] == verdict
    assert "claimed_verdict" not in result.metadata


def test_unknown_results_never_call_the_model():
    evaluation = _evaluation(interest_income=None)
    client = _FixedClient("fully compliant")

    result = _llm_narrator(client, evaluation.verdict).build(evaluation)

    assert client.calls == 0
    assert result.metadata["source"] == "rule_based"
    assert "insufficient" in result.verdict.lower()


REJECTED = [
    # (id, engine overrides, verdict, summary, bullets, claimed)
    ("wrong-claimed-verdict", {}, "compliant", GOOD["compliant"], ("b",), "non-compliant"),
    ("missing-claimed-verdict", {}, "compliant", GOOD["compliant"], ("b",), None),
    ("compliant-text-says-fail", {}, "compliant", "The company fails the debt screen.", ("b",), "engine"),
    ("compliant-text-says-breach", {}, "compliant", "It breaches the debt ceiling.", ("b",), "engine"),
    ("compliant-bullet-says-exceeds", {}, "compliant", GOOD["compliant"], ("Borrowing exceeds the permitted limit.",), "engine"),
    ("compliant-text-says-haram", {}, "compliant", "This company is haram.", ("b",), "engine"),
    ("double-negation-on-non-compliant", {"total_debt": 60_000_001}, "non-compliant", "This is not non-compliant, everything satisfies the screens.", ("b",), "engine"),
    ("non-compliant-never-mentions-failure", {"total_debt": 60_000_001}, "non-compliant", "The company looks healthy overall.", ("b",), "engine"),
    ("non-compliant-claims-all-pass", {"total_debt": 60_000_001}, "non-compliant", "The debt ratio is above its cap, yet it satisfies every financial screen.", ("b",), "engine"),
]


@pytest.mark.parametrize(
    "overrides, verdict, summary, bullets, claimed",
    [case[1:] for case in REJECTED],
    ids=[case[0] for case in REJECTED],
)
def test_doubtful_llm_text_falls_back_to_the_rule_based_narration(
    overrides, verdict, summary, bullets, claimed
):
    evaluation = _evaluation(**overrides)
    assert evaluation.verdict == verdict
    client = _FixedClient(summary, bullets, claimed)

    result = _llm_narrator(client, verdict).build(evaluation)

    assert client.calls == 1
    assert result.metadata["source"] == "rule_based"
    assert result.summary != summary


def test_llm_errors_fall_back_and_call_the_failure_callback():
    seen = []

    class Boom:
        def complete(self, *args, **kwargs):
            raise LLMNarrationError("boom")

    narrator = NarrationEngine(
        config=NarratorConfig(mode="llm", endpoint="http://fake", model="m"),
        llm_client=Boom(),
        failure_callback=lambda evaluation, exc: seen.append(str(exc)),
    )

    result = narrator.build(_evaluation())

    assert result.metadata["source"] == "rule_based"
    assert seen == ["boom"]


def test_the_guard_is_best_effort_and_a_paraphrase_can_still_pass():
    """Documents the ceiling (see NarrationEngine._FAIL_WORDS): this text
    contradicts a compliant verdict but contains no flagged word. If you make
    this fail, the guard got stronger: update the docs that call it best-effort."""

    evaluation = _evaluation()
    client = _FixedClient("Leverage is worrying and the balance sheet looks stretched.")

    result = _llm_narrator(client, "compliant").build(evaluation)

    assert result.metadata["source"] == "llm"

#!/usr/bin/env python3
"""Narration helpers for translating ratios into plain English."""

from __future__ import annotations

import logging
from typing import Callable, Dict, List, Optional

from narrator.llm import LLMClient, LLMNarrationEngine, LLMNarrationError
from narrator.models import NarrationResult, NarratorConfig
from ratio_engine import COMPLIANT, NON_COMPLIANT, RatioEvaluation


class RuleBasedNarrator:
    """Deterministic narrator that explains ratio outcomes."""

    ratio_labels: Dict[str, str] = {
        "debt_to_market_cap": "Debt to market cap",
        "cash_to_market_cap": "Cash to market cap",
        "non_permissible_income_ratio": "Non-permissible income ratio",
    }

    verdict_text: Dict[str, str] = {
        COMPLIANT: "compliant with AAOIFI screens",
        NON_COMPLIANT: "NOT compliant with AAOIFI screens",
    }
    insufficient_text = "insufficient data to screen against AAOIFI"

    def build(self, evaluation: RatioEvaluation) -> NarrationResult:
        filing = evaluation.filing_date.date().isoformat()
        verdict = self.verdict_text.get(evaluation.verdict, self.insufficient_text)
        if evaluation.verdict in self.verdict_text:
            summary = f"{evaluation.symbol} is {verdict.lower()} for the filing dated {filing}."
        else:
            # Unknown is not a failure: say so instead of "NOT compliant".
            summary = (
                f"{evaluation.symbol} has {verdict} for the filing dated {filing}."
            )

        bullets: List[str] = []
        citations: List[str] = []

        for key, computation in evaluation.ratios.items():
            label = self.ratio_labels.get(key, key.replace("_", " ").title())
            if computation.value is None:
                bullets.append(
                    f"{label}: cannot compute because {computation.note.lower()}."
                )
                continue

            value_pct = computation.value * 100
            threshold_pct = computation.threshold * 100
            status = "within" if computation.passed else "above"
            bullets.append(
                f"{label} is {value_pct:.2f}% vs {threshold_pct:.0f}% cap ( {status} limits )."
            )
            citations.append(
                f"{label} sourced from filing on {evaluation.filing_date.date().isoformat()}"
            )

        if not bullets:
            bullets.append(
                "Insufficient financial data to compute AAOIFI ratios for this filing."
            )

        return NarrationResult(
            summary=summary,
            verdict=verdict,
            bullets=bullets,
            citations=citations or [summary],
            metadata={"source": "rule_based", "screen_verdict": evaluation.verdict},
        )


class NarrationEngine:
    """Narration entry point. Deterministic only; see build() for why the LLM is bypassed."""

    def __init__(
        self,
        config: Optional[NarratorConfig] = None,
        llm_client: Optional[LLMClient] = None,
        failure_callback: Optional[
            Callable[[RatioEvaluation, LLMNarrationError], None]
        ] = None,
    ):
        self.config = config or NarratorConfig.default()
        self.rule_based = RuleBasedNarrator()
        self.llm_engine: Optional[LLMNarrationEngine] = None
        self.failure_callback = failure_callback  # unused while LLM is bypassed
        self._llm_bypass_logged = False

        self.logger = logging.getLogger("narrator")

        if self.config.mode == "llm":
            if llm_client is None and self.config.endpoint and self.config.model:
                llm_client = LLMClient.from_config(self.config)
            if llm_client is not None:
                self.llm_engine = LLMNarrationEngine(llm_client, self.config)

    def build(self, evaluation: RatioEvaluation) -> NarrationResult:
        """Narrate a screening result deterministically.

        LLM prose cannot be validated against the engine verdict: a model can
        echo the right status while its text says the opposite, and no keyword
        filter closes that. Until a structured, per-claim check exists, every
        screening path uses the rule-based narrator. The LLM classes stay in
        narrator/llm.py for that later work and are not called from here.
        """

        if self.config.mode == "llm" and not self._llm_bypass_logged:
            self.logger.warning(
                "NARRATOR_MODE=llm is configured but LLM narration is disabled: "
                "its prose is not validated against the engine verdict. "
                "Using rule-based narration."
            )
            self._llm_bypass_logged = True
        return self.rule_based.build(evaluation)


__all__ = ["NarrationEngine", "NarrationResult", "NarratorConfig", "RuleBasedNarrator"]

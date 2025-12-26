#!/usr/bin/env python3
"""Narration helpers for translating ratios into plain English."""

from __future__ import annotations

import logging
from typing import Callable, Dict, List, Optional

from narrator.llm import LLMClient, LLMNarrationEngine, LLMNarrationError
from narrator.models import NarrationResult, NarratorConfig
from ratio_engine import RatioEvaluation


class RuleBasedNarrator:
    """Deterministic narrator that explains ratio outcomes."""

    ratio_labels: Dict[str, str] = {
        "debt_to_market_cap": "Debt to market cap",
        "cash_to_market_cap": "Cash to market cap",
        "non_permissible_income_ratio": "Non-permissible income ratio",
    }

    def build(self, evaluation: RatioEvaluation) -> NarrationResult:
        verdict = (
            "compliant with AAOIFI screens"
            if evaluation.is_compliant
            else "NOT compliant with AAOIFI screens"
        )
        summary = (
            f"{evaluation.symbol} is {verdict.lower()} for the filing dated "
            f"{evaluation.filing_date.date().isoformat()}."
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
            metadata={"source": "rule_based"},
        )


class NarrationEngine:
    """Hybrid narrator that can delegate to an LLM or rule-based engine."""

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
        self.failure_callback = failure_callback

        self.logger = logging.getLogger("narrator")

        if self.config.mode == "llm":
            if llm_client is None and self.config.endpoint and self.config.model:
                llm_client = LLMClient.from_config(self.config)
            if llm_client is not None:
                self.llm_engine = LLMNarrationEngine(llm_client, self.config)

    def build(self, evaluation: RatioEvaluation) -> NarrationResult:
        """Produce a narration, preferring LLM output with safe fallback."""

        if self.llm_engine:
            try:
                return self.llm_engine.build(evaluation)
            except LLMNarrationError as exc:
                self.logger.warning(
                    "LLM narration failed for %s, falling back to rule-based",
                    evaluation.symbol,
                    exc_info=True,
                )
                if self.failure_callback:
                    try:
                        self.failure_callback(evaluation, exc)
                    except Exception:  # pragma: no cover - diagnostics only
                        self.logger.exception("LLM failure callback crashed")
        return self.rule_based.build(evaluation)


__all__ = ["NarrationEngine", "NarrationResult", "NarratorConfig", "RuleBasedNarrator"]

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
    """Narration entry point: rule-based by default, optional LLM with a best-effort guard."""

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

    # Best-effort consistency guard for LLM prose (maintainer decision, 2026-10-27).
    # It is NOT a guarantee: a model can pick a paraphrase none of these words
    # catch ("debt is too high" under a compliant label). Only the rule-based
    # narrator is guaranteed consistent. ponytail: substring lists, ceiling is
    # paraphrase; replace with a structured per-claim check if it ever matters.
    _FAIL_WORDS = (
        "non-compliant", "non compliant", "noncompliant", "not compliant",
        "haram", "impermissible", "prohibited", "exceed", "breach", "violat",
        "fail", "above the", "over the cap", "over the limit", "too high",
    )
    _PASS_ALL_WORDS = (
        "fully compliant", "satisf", "all ratios", "every screen", "every financial",
        "all screens", "no concerns", "passes all", "passed all",
    )

    def _llm_rejection(self, result: NarrationResult, evaluation: RatioEvaluation) -> Optional[str]:
        """Why this LLM text cannot be shown, or None if it passes the guard."""

        if result.metadata.get("claimed_verdict") != evaluation.verdict:
            return "claimed verdict differs from the engine's"
        text = " ".join([result.summary, result.verdict, *result.bullets]).lower()
        says_fail = any(word in text for word in self._FAIL_WORDS)
        if evaluation.verdict == COMPLIANT:
            return "text mentions a failure" if says_fail else None
        if not says_fail:
            return "text never mentions a failure"
        if any(word in text for word in self._PASS_ALL_WORDS):
            return "text claims everything passes"
        return None

    def build(self, evaluation: RatioEvaluation) -> NarrationResult:
        """Narrate a screening result.

        Unknown results (insufficient-data, needs-review) are always narrated by
        the rule-based narrator: the model is not asked about them. For
        conclusive verdicts the LLM text is used only if it passes the
        best-effort guard above; the label shown is always the engine's. Any
        doubt or LLM error falls back to the rule-based narration.
        """

        if self.llm_engine and evaluation.is_compliant is not None:
            try:
                result = self.llm_engine.build(evaluation)
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
            else:
                reason = self._llm_rejection(result, evaluation)
                if reason is None:
                    result.verdict = self.rule_based.verdict_text[evaluation.verdict]
                    result.metadata["screen_verdict"] = evaluation.verdict
                    result.metadata.pop("claimed_verdict", None)
                    return result
                self.logger.warning(
                    "LLM narration for %s rejected (%s), using rule-based",
                    evaluation.symbol,
                    reason,
                )
        return self.rule_based.build(evaluation)


__all__ = ["NarrationEngine", "NarrationResult", "NarratorConfig", "RuleBasedNarrator"]

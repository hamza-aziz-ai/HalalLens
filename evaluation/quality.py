"""Shared publication overlay: open data-quality issues mask the engine's verdict.

RatioEngine remains the sole financial verdict owner. This module never derives a
verdict from ratios: with no open issue it passes the engine's (verdict,
is_compliant, summary) through unchanged; with any open issue, of any type, it
publishes `needs-review` with `is_compliant = None`. Every writer of
filing_evaluations goes through `BSEDatabaseManager.publish_filing_evaluation`,
which applies this policy under a per-filing advisory lock (D-027).
"""

from __future__ import annotations

from dataclasses import asdict
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

REVIEW_VERDICT = "needs-review"
REVIEW_SUMMARY = "Flagged for manual review: unresolved quality issues remain."
ANOMALY_SUMMARY = "Flagged for manual review due to anomalous ratios."

# The detector owns exactly this issue type: a publication reconciles it, and a
# clean evaluation resolves it. Every other type is owned by its writer.
RATIO_ANOMALY = "ratio_anomaly"

# Market-data issue types a demonstrated lookup for the filing disproves. A cap
# from the primary provider (Indian API) disproves all four; a Bhavcopy cap does
# not disprove a primary-provider failure. A previously stored cap disproves
# nothing. Governance and anomaly issues are never cleared by a market lookup.
PRIMARY_LOOKUP_DISPROVES: Tuple[str, ...] = (
    "market-data-missing",
    "market_data_unavailable",
    "market_cap_missing",
    "market_data_fetch_failed",
)
FALLBACK_LOOKUP_DISPROVES: Tuple[str, ...] = PRIMARY_LOOKUP_DISPROVES[:3]


class StalePublication(RuntimeError):
    """A recompute preview no longer matches the filing's state at write time."""


def detect_ratio_anomalies(snapshot, evaluation) -> List[str]:
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


def combined_anomaly(anomalies: Sequence[str]) -> Optional[str]:
    """One deterministic description for the detector's row (detector order, deduplicated)."""

    return " ".join(dict.fromkeys(a for a in anomalies if a)) or None


def reconcile(
    open_issues: Sequence[Mapping[str, Any]], anomalies: Optional[Sequence[str]]
) -> List[Dict[str, Any]]:
    """Open issues after the detector's own row is reconciled.

    `anomalies is None` means the detector did not run: nothing changes.
    """

    issues = [dict(issue) for issue in open_issues]
    if anomalies is None:
        return issues
    issues = [issue for issue in issues if issue["issue_type"] != RATIO_ANOMALY]
    detail = combined_anomaly(anomalies)
    if detail:
        issues.append({"issue_type": RATIO_ANOMALY, "details": detail})
    return issues


def publish(
    verdict: Optional[str],
    is_compliant: Optional[bool],
    summary: Optional[str],
    open_issues: Sequence[Any],
    anomalies: Sequence[str] = (),
) -> Tuple[Optional[str], Optional[bool], Optional[str]]:
    """The published triple: the engine's unchanged, or needs-review when anything is open."""

    if not open_issues:
        return verdict, is_compliant, summary
    return REVIEW_VERDICT, None, ANOMALY_SUMMARY if anomalies else REVIEW_SUMMARY


def mask_stored(record: Dict[str, Any], open_issues: Sequence[Any]) -> None:
    """Mask a stored or cached result in place with the filing's current open issues.

    Only masks: a stored needs-review is never turned back into an engine
    verdict here (that takes a new evaluation through the publication path).
    """

    if open_issues and record.get("verdict") not in (None, REVIEW_VERDICT):
        record["verdict"], record["is_compliant"], record["summary"] = publish(
            record.get("verdict"), record.get("is_compliant"), record.get("summary"), open_issues
        )


def issue_texts(open_issues: Sequence[Mapping[str, Any]]) -> List[str]:
    """What the API shows for each open issue (details, else the type)."""

    texts = []
    for issue in open_issues:
        text = (issue.get("details") or issue.get("issue_type") or "").strip()
        if text:
            texts.append(text)
    return texts


def issue_types(open_issues: Sequence[Mapping[str, Any]]) -> Tuple[str, ...]:
    return tuple(sorted(issue["issue_type"] for issue in open_issues))


def publish_evaluation(
    db,
    snapshot,
    evaluation,
    *,
    filing_date,
    narration_source: str,
    market_cap_used,
    trailing_cap_used,
    market_data_provider,
    expect: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    """Run the detector and store the evaluation through the shared publication path."""

    from ratio_engine import build_summary

    return db.publish_filing_evaluation(
        symbol=snapshot.symbol,
        filing_date=filing_date,
        verdict=evaluation.verdict,
        is_compliant=evaluation.is_compliant,
        summary=build_summary(evaluation),
        ratios={name: asdict(comp) for name, comp in evaluation.ratios.items()},
        anomalies=detect_ratio_anomalies(snapshot, evaluation),
        narration_source=narration_source,
        market_cap_used=market_cap_used,
        trailing_cap_used=trailing_cap_used,
        market_data_provider=market_data_provider,
        expect=expect,
    )

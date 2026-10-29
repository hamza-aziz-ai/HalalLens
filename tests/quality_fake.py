"""In-memory stand-in for the quality-issue and publication methods of BSEDatabaseManager.

Same semantics as the PostgreSQL methods because it calls the same pure policy
(evaluation.quality): publication reconciles the detector-owned ratio_anomaly
row and masks the engine pair while any issue is open; recording an issue
downgrades a published row; resolving one never restores a verdict. The lock
and the transaction are proven against a real database in
tests/test_quality_postgres.py.
"""

from typing import Dict, List, Optional, Tuple

from evaluation import quality


class MemoryQualityDB:
    def __init__(self) -> None:
        # (symbol, filing_date) -> {issue_type: details}, open issues only
        self.issues: Dict[Tuple, Dict[str, Optional[str]]] = {}
        self.evaluations: Dict[Tuple, Dict] = {}
        self.writes: List[Dict] = []

    def seed_issue(self, symbol, filing_date, issue_type, details=None) -> None:
        self.issues.setdefault((symbol, filing_date), {})[issue_type] = details

    def get_open_quality_issues(self, symbol, filing_date) -> List[Dict]:
        open_ = self.issues.get((symbol, filing_date), {})
        return [{"issue_type": t, "details": d} for t, d in open_.items()]

    def get_quality_issues(self, symbol, filing_date) -> List[str]:
        return quality.issue_texts(self.get_open_quality_issues(symbol, filing_date))

    def record_quality_issue(self, symbol, filing_date, issue_type, details) -> None:
        self.seed_issue(symbol, filing_date, issue_type, details)
        row = self.evaluations.get((symbol, filing_date))
        if row:
            quality.mask_stored(row, [issue_type])

    def resolve_quality_issues(self, symbol, filing_date, issue_types=None) -> None:
        open_ = self.issues.get((symbol, filing_date), {})
        for issue_type in list(open_):
            if not issue_types or issue_type in issue_types:
                del open_[issue_type]

    def publish_filing_evaluation(self, *, anomalies, expect=None, **kwargs) -> Dict:
        key = (kwargs["symbol"], kwargs["filing_date"])
        issues = quality.reconcile(self.get_open_quality_issues(*key), anomalies)
        verdict, is_compliant, summary = quality.publish(
            kwargs["verdict"], kwargs["is_compliant"], kwargs["summary"], issues, anomalies or ()
        )
        if expect is not None:
            stored = self.evaluations.get(key)
            current = (
                stored.get("evaluated_at") if stored else None,
                verdict,
                is_compliant,
                quality.issue_types(issues),
            )
            wanted = (
                expect.get("evaluated_at"),
                expect.get("verdict"),
                expect.get("is_compliant"),
                tuple(expect.get("issue_types") or ()),
            )
            if current != wanted:
                raise quality.StalePublication(f"preview {wanted} is now {current}")
        self.issues[key] = {i["issue_type"]: i["details"] for i in issues}
        row = {**kwargs, "verdict": verdict, "is_compliant": is_compliant, "summary": summary}
        self.evaluations[key] = row
        self.writes.append(row)
        return {
            "verdict": verdict,
            "is_compliant": is_compliant,
            "summary": summary,
            "quality_issues": quality.issue_texts(issues),
            "issue_types": quality.issue_types(issues),
        }

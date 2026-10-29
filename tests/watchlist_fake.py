"""In-memory stand-in for alerts.storage.WatchlistStorage in offline tests.

Same semantics as the PostgreSQL storage (idempotent add that keeps the
baseline, owner-scoped list, silent seed then flip with the stale-observation
guard, the mailbox columns and their compare-and-set updates). ``filings`` maps
a symbol to its newest stored evaluation (or an Exception to raise); ``users``
holds the mail settings. Concurrency and the real SQL are proven separately
against a real database in tests/test_watchlist_postgres.py.
"""

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

from alerts.storage import COMPLIANCE_FLIP, Observation, WatchEntry, conclusive, require_user_id

Key = Tuple[int, str, str]


def _row(last=None) -> Dict[str, Any]:
    return {
        "last_is_compliant": last,
        "notified_is_compliant": last,
        "notify_attempts": 0,
        "notify_next_at": None,
        "notify_failed_at": None,
        "observed_filing_date": None,
        "observed_evaluated_at": None,
        "updated_at": 0,
    }


class MemoryWatchlistStorage:
    def __init__(self) -> None:
        self.rows: Dict[Key, Dict[str, Any]] = {}
        self.filings: Dict[str, Any] = {}
        self.users: Dict[int, Dict[str, Any]] = {}
        self.now = datetime(2026, 10, 30, tzinfo=timezone.utc)
        self._tick = 0

    def _touch(self, row):
        self._tick += 1
        row["updated_at"] = self._tick

    # --- watchlist -----------------------------------------------------------
    def add(self, entry: WatchEntry) -> None:
        key = (require_user_id(entry.user_id), entry.symbol, entry.trigger)
        if key not in self.rows:
            self.rows[key] = _row(entry.last_is_compliant)
            self._touch(self.rows[key])

    def list(self, user_id: int) -> List[WatchEntry]:
        require_user_id(user_id)
        return [
            WatchEntry(uid, symbol, trigger, row["last_is_compliant"])
            for (uid, symbol, trigger), row in sorted(self.rows.items())
            if uid == user_id
        ]

    # --- observation ---------------------------------------------------------
    def observe(self, symbol: str, user_id: Optional[int] = None, trigger: str = COMPLIANCE_FLIP) -> Observation:
        if user_id is not None:
            require_user_id(user_id)
        record = self.filings.get(symbol)
        if isinstance(record, Exception):
            raise record
        verdict = (
            conclusive(record.get("verdict"), record.get("is_compliant"), bool(record.get("open_issues")))
            if record else None
        )
        if verdict is None:
            return Observation(None)
        seen = (record["filing_date"], record["evaluated_at"])
        mine = [
            (key, row) for key, row in sorted(self.rows.items())
            if key[1] == symbol and key[2] == trigger and (user_id is None or key[0] == user_id)
        ]
        for _, row in mine:  # seed first, silently
            if row["last_is_compliant"] is None:
                row.update(last_is_compliant=verdict, notified_is_compliant=verdict,
                           observed_filing_date=seen[0], observed_evaluated_at=seen[1])
                self._touch(row)
        flipped = []
        for key, row in mine:
            stale = row["observed_filing_date"] is not None and (
                row["observed_filing_date"], row["observed_evaluated_at"]) > seen
            if row["last_is_compliant"] is not None and row["last_is_compliant"] != verdict and not stale:
                row.update(last_is_compliant=verdict, observed_filing_date=seen[0], observed_evaluated_at=seen[1],
                           notify_attempts=0, notify_next_at=None, notify_failed_at=None)
                self._touch(row)
                flipped.append(key[0])
        return Observation(verdict, seen[0], seen[1], flipped)

    # --- mailbox -------------------------------------------------------------
    @staticmethod
    def _pending(row) -> bool:
        return row["last_is_compliant"] is not row["notified_is_compliant"]

    def watched_symbols(self, trigger: str = COMPLIANCE_FLIP) -> List[str]:
        return sorted({s for (_, s, t) in self.rows if t == trigger})

    def rebaseline_all(self) -> int:
        n = 0
        for row in self.rows.values():
            if self._pending(row):
                row.update(notified_is_compliant=row["last_is_compliant"], notify_attempts=0,
                           notify_next_at=None, notify_failed_at=None)
                n += 1
        return n

    def pending(self, per_user: int, budget: int) -> List[Key]:
        due = [
            (key, row) for key, row in self.rows.items()
            if self._pending(row) and row["notify_failed_at"] is None
            and (row["notify_next_at"] is None or row["notify_next_at"] <= self.now)
        ]
        order = lambda item: (item[1]["notify_next_at"] is not None, item[1]["notify_next_at"] or self.now, item[1]["updated_at"])
        per: Dict[int, int] = {}
        picked = []
        for key, row in sorted(due, key=order):
            per[key[0]] = per.get(key[0], 0) + 1
            if per[key[0]] <= per_user:
                picked.append(key)
        return picked[:budget]

    def entry(self, key: Key) -> Optional[Dict[str, Any]]:
        row = self.rows.get(key)
        if row is None:
            return None
        user = {"email": f"user{key[0]}@example.com", "email_verified_at": self.now, "alert_emails": True,
                "is_admin": False, **self.users.get(key[0], {})}
        return {**row, **user, "now": self.now}

    def acknowledge(self, key: Key, before, submitted) -> bool:
        row = self.rows.get(key)
        if row is None or row["notified_is_compliant"] is not before:
            return False
        row.update(notified_is_compliant=submitted, notify_attempts=0, notify_next_at=None, notify_failed_at=None)
        return True

    def record_failure(self, key: Key, before, target, delay_seconds: float, terminal: bool) -> None:
        row = self.rows.get(key)
        if row is None or row["notified_is_compliant"] is not before or row["last_is_compliant"] is not target:
            return
        row["notify_attempts"] += 1
        row["notify_next_at"] = self.now + timedelta(seconds=delay_seconds)
        row["notify_failed_at"] = self.now if terminal else None

    def defer(self, key: Key, delay_seconds: float) -> None:
        if key in self.rows:
            self.rows[key]["notify_next_at"] = self.now + timedelta(seconds=delay_seconds)

    def get_alert_emails(self, user_id: int) -> bool:
        return self.users.get(require_user_id(user_id), {}).get("alert_emails", True)

    def set_alert_emails(self, user_id: int, enabled: bool) -> bool:
        self.users.setdefault(require_user_id(user_id), {})["alert_emails"] = bool(enabled)
        return bool(enabled)

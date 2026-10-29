#!/usr/bin/env python3
"""Watchlist storage in PostgreSQL (table ``watchlist_entries``).

Each row is also the subscriber's alert mailbox (D-031): ``last_is_compliant``
is the newest conclusive verdict observed, ``notified_is_compliant`` the one the
subscriber was last told about (or silently rebaselined to). A row is pending
while the two differ; alerts/delivery.py sends and acknowledges it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional, Tuple

COMPLIANCE_FLIP = "compliance_flip"

Key = Tuple[int, str, str]  # (user_id, symbol, trigger)


@dataclass
class WatchEntry:
    """Represents a watchlist entry for compliance alerts."""

    user_id: int
    symbol: str
    trigger: str = COMPLIANCE_FLIP
    last_is_compliant: Optional[bool] = None


@dataclass
class Observation:
    """What one observation of a symbol's stored evaluation found and did."""

    is_compliant: Optional[bool]  # None: no conclusive verdict, nothing moved
    filing_date: Optional[datetime] = None
    evaluated_at: Optional[datetime] = None
    flipped: List[int] = field(default_factory=list)  # user ids whose entry flipped


def owner_key(user_id: int) -> str:
    """External owner label used in API responses and alert events."""

    return f"user:{user_id}"


def require_user_id(user_id: object) -> int:
    """A positive integer user id; anything else is a programming error."""

    if isinstance(user_id, bool) or not isinstance(user_id, int) or user_id <= 0:
        raise ValueError("user_id must be a positive integer")
    return user_id


def conclusive(verdict: Optional[str], is_compliant: Optional[bool], open_issues: bool) -> Optional[bool]:
    """The stored pair as an alert verdict: True/False only when consistent and unmasked."""

    if open_issues:
        return None
    if verdict == "compliant" and is_compliant is True:
        return True
    if verdict == "non-compliant" and is_compliant is False:
        return False
    return None


# Same filing choice as database_manager.get_latest_filing (symbol or alias,
# a parsed snapshot, newest first); the canonical symbol keys the D-027 lock.
_NEWEST_FILING_SQL = """
    SELECT a.symbol, a.filing_date
      FROM announcements a
      JOIN financial_snapshots fs ON a.symbol = fs.symbol AND a.filing_date = fs.filing_date
     WHERE a.symbol = %(symbol)s OR a.symbol_alias = %(symbol)s
     ORDER BY a.filing_date DESC
     LIMIT 1
"""
_EVALUATION_SQL = """
    SELECT fe.verdict, fe.is_compliant, fe.evaluated_at,
           EXISTS (SELECT 1 FROM data_quality_issues q
                    WHERE q.symbol = fe.symbol AND q.filing_date = fe.filing_date
                      AND q.resolved_at IS NULL) AS open_issues
      FROM filing_evaluations fe
     WHERE fe.symbol = %(symbol)s AND fe.filing_date = %(filing_date)s
"""
# The NULL baseline is seeded first (silently: notified moves with it), then the
# flip runs on the rows that already had one. Flip-first could lose a concurrent
# opposite verdict: the NULL row matches no flip, another check seeds and
# commits, then this check's seed matches nothing. PostgreSQL re-checks each
# UPDATE's WHERE on the latest row version after waiting for the row lock (READ
# COMMITTED), so concurrent identical verdicts produce exactly one flip. A flip
# never applies an observation older than the one already stored, and resets
# the retry state because the pending target changed.
_WATCH_ROWS = """
     WHERE symbol = %(watch_symbol)s AND trigger = %(trigger)s
       AND (%(user_id)s::int IS NULL OR user_id = %(user_id)s::int)
"""
_SEED_SQL = (
    """
    UPDATE watchlist_entries
       SET last_is_compliant = %(verdict)s, notified_is_compliant = %(verdict)s,
           observed_filing_date = %(filing_date)s, observed_evaluated_at = %(evaluated_at)s,
           updated_at = now()
    """
    + _WATCH_ROWS
    + "   AND last_is_compliant IS NULL\n"
)
_FLIP_SQL = (
    """
    UPDATE watchlist_entries
       SET last_is_compliant = %(verdict)s,
           observed_filing_date = %(filing_date)s, observed_evaluated_at = %(evaluated_at)s,
           notify_attempts = 0, notify_next_at = NULL, notify_failed_at = NULL,
           updated_at = now()
    """
    + _WATCH_ROWS
    + """   AND last_is_compliant IS NOT NULL AND last_is_compliant <> %(verdict)s
       AND (observed_filing_date IS NULL
            OR (observed_filing_date, observed_evaluated_at) <= (%(filing_date)s, %(evaluated_at)s))
    RETURNING user_id
"""
)
_KEY = "user_id = %(user_id)s AND symbol = %(symbol)s AND trigger = %(trigger)s"
_PENDING = "last_is_compliant IS DISTINCT FROM notified_is_compliant"


class WatchlistStorage:
    """Watch entries keyed by (user_id, symbol, trigger) in PostgreSQL.

    ``get_db`` returns the database manager; its ``get_connection()`` rolls
    back on error but never commits, so every method commits explicitly. Rows
    are read by column name (the manager's pool uses RealDictCursor).
    """

    def __init__(self, get_db: Callable[[], Any]):
        self._get_db = get_db

    def _run(self, sql: str, params: Dict[str, Any], fetch: str = "") -> Any:
        with self._get_db().get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(sql, params)
                result = (
                    cursor.fetchall() if fetch == "all"
                    else cursor.fetchone() if fetch == "one"
                    else cursor.rowcount
                )
            conn.commit()
        return result

    def add(self, entry: WatchEntry) -> None:
        """Watch a symbol. Re-adding keeps the existing baseline."""

        self._run(
            """
            INSERT INTO watchlist_entries (user_id, symbol, trigger)
            VALUES (%(user_id)s, %(symbol)s, %(trigger)s)
            ON CONFLICT (user_id, symbol, trigger) DO NOTHING
            """,
            {"user_id": require_user_id(entry.user_id), "symbol": entry.symbol, "trigger": entry.trigger},
        )

    def list(self, user_id: int) -> List[WatchEntry]:
        """One user's entries; there is no "every user" listing."""

        rows = self._run(
            """
            SELECT user_id, symbol, trigger, last_is_compliant
              FROM watchlist_entries
             WHERE user_id = %(user_id)s
             ORDER BY symbol, trigger
            """,
            {"user_id": require_user_id(user_id)},
            "all",
        )
        return [WatchEntry(**row) for row in rows]

    def observe(self, symbol: str, user_id: Optional[int] = None, trigger: str = COMPLIANCE_FLIP) -> Observation:
        """Record the symbol's newest stored verdict on its watch rows (one user's, or all).

        One transaction under the filing's D-027 advisory lock (the lock that
        publication and quality-issue writes take first), so the evaluation and
        its open issues are read as one published state. Fail closed: lookup
        errors raise. None (no filing, not evaluated, inconsistent pair, open
        issue) moves nothing; a first verdict is a silent baseline; an older
        observation never overwrites a newer one. Never sends anything.
        """

        if user_id is not None:
            require_user_id(user_id)
        db = self._get_db()
        with db.get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(_NEWEST_FILING_SQL, {"symbol": symbol})
                filing = cursor.fetchone()
                evaluation = None
                if filing:
                    db._lock_filing(cursor, filing["symbol"], filing["filing_date"])
                    cursor.execute(_EVALUATION_SQL, dict(filing))
                    evaluation = cursor.fetchone()
                verdict = (
                    conclusive(evaluation["verdict"], evaluation["is_compliant"], evaluation["open_issues"])
                    if evaluation else None
                )
                if verdict is None:
                    conn.commit()
                    return Observation(None)
                params = {
                    "watch_symbol": symbol,
                    "trigger": trigger,
                    "user_id": user_id,
                    "verdict": verdict,
                    "filing_date": filing["filing_date"],
                    "evaluated_at": evaluation["evaluated_at"],
                }
                cursor.execute(_SEED_SQL, params)
                cursor.execute(_FLIP_SQL, params)
                flipped = [row["user_id"] for row in cursor.fetchall()]
            conn.commit()
        return Observation(verdict, filing["filing_date"], evaluation["evaluated_at"], flipped)

    def watched_symbols(self, trigger: str = COMPLIANCE_FLIP) -> List[str]:
        rows = self._run(
            "SELECT DISTINCT symbol FROM watchlist_entries WHERE trigger = %(trigger)s ORDER BY symbol",
            {"trigger": trigger},
            "all",
        )
        return [row["symbol"] for row in rows]

    def rebaseline_all(self) -> int:
        """Kill switch: every pending row silently takes its current verdict."""

        return self._run(
            f"""
            UPDATE watchlist_entries
               SET notified_is_compliant = last_is_compliant, notify_attempts = 0,
                   notify_next_at = NULL, notify_failed_at = NULL, updated_at = now()
             WHERE {_PENDING}
            """,
            {},
        )

    def pending(self, per_user: int, budget: int) -> List[Key]:
        """Due pending rows: never-tried first, then the longest-waiting; per-user cap, global budget."""

        rows = self._run(
            f"""
            SELECT user_id, symbol, trigger FROM (
                SELECT user_id, symbol, trigger, notify_next_at, updated_at,
                       row_number() OVER (PARTITION BY user_id
                                          ORDER BY notify_next_at NULLS FIRST, updated_at) AS n
                  FROM watchlist_entries
                 WHERE {_PENDING}
                   AND notify_failed_at IS NULL
                   AND (notify_next_at IS NULL OR notify_next_at <= now())
            ) due
             WHERE n <= %(per_user)s
             ORDER BY notify_next_at NULLS FIRST, updated_at
             LIMIT %(budget)s
            """,
            {"per_user": per_user, "budget": budget},
            "all",
        )
        return [(row["user_id"], row["symbol"], row["trigger"]) for row in rows]

    def entry(self, key: Key) -> Optional[Dict[str, Any]]:
        """The watch row with its owner's mail settings and the database clock."""

        row = self._run(
            """
            SELECT w.last_is_compliant, w.notified_is_compliant, w.notify_attempts,
                   w.observed_filing_date, w.observed_evaluated_at,
                   u.email, u.email_verified_at, u.alert_emails, u.is_admin,
                   clock_timestamp() AS now
              FROM watchlist_entries w JOIN users u ON u.id = w.user_id
             WHERE w.user_id = %(user_id)s AND w.symbol = %(symbol)s AND w.trigger = %(trigger)s
            """,
            _key_params(key),
            "one",
        )
        return dict(row) if row else None

    def acknowledge(self, key: Key, before: Optional[bool], submitted: Optional[bool]) -> bool:
        """Compare-and-set: record what was submitted unless another sender moved it first.

        Records the submitted verdict even if ``last`` moved during the send, so
        a corrective alert stays pending.
        """

        return bool(self._run(
            f"""
            UPDATE watchlist_entries
               SET notified_is_compliant = %(submitted)s, notify_attempts = 0,
                   notify_next_at = NULL, notify_failed_at = NULL, updated_at = now()
             WHERE {_KEY} AND notified_is_compliant IS NOT DISTINCT FROM %(before)s
            """,
            {**_key_params(key), "before": before, "submitted": submitted},
        ))

    def record_failure(self, key: Key, before: Optional[bool], target: Optional[bool], delay_seconds: float, terminal: bool) -> None:
        """One more failed send for this target, unless the target has changed meanwhile."""

        self._run(
            f"""
            UPDATE watchlist_entries
               SET notify_attempts = notify_attempts + 1,
                   notify_next_at = now() + make_interval(secs => %(delay)s),
                   notify_failed_at = CASE WHEN %(terminal)s THEN now() END
             WHERE {_KEY}
               AND notified_is_compliant IS NOT DISTINCT FROM %(before)s
               AND last_is_compliant IS NOT DISTINCT FROM %(target)s
            """,
            {**_key_params(key), "before": before, "target": target, "delay": delay_seconds, "terminal": terminal},
        )

    def defer(self, key: Key, delay_seconds: float) -> None:
        """Try later without counting an SMTP failure (source unknown or blocked)."""

        self._run(
            f"UPDATE watchlist_entries SET notify_next_at = now() + make_interval(secs => %(delay)s) WHERE {_KEY}",
            {**_key_params(key), "delay": delay_seconds},
        )

    def get_alert_emails(self, user_id: int) -> bool:
        row = self._run(
            "SELECT alert_emails FROM users WHERE id = %(id)s", {"id": require_user_id(user_id)}, "one"
        )
        return bool(row and row["alert_emails"])

    def set_alert_emails(self, user_id: int, enabled: bool) -> bool:
        row = self._run(
            "UPDATE users SET alert_emails = %(on)s, updated_at = now() WHERE id = %(id)s RETURNING alert_emails",
            {"id": require_user_id(user_id), "on": bool(enabled)},
            "one",
        )
        return bool(row and row["alert_emails"])


def _key_params(key: Key) -> Dict[str, Any]:
    user_id, symbol, trigger = key
    return {"user_id": require_user_id(user_id), "symbol": symbol, "trigger": trigger}


__all__ = [
    "COMPLIANCE_FLIP",
    "Observation",
    "WatchEntry",
    "WatchlistStorage",
    "conclusive",
    "owner_key",
    "require_user_id",
]

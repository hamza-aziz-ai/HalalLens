#!/usr/bin/env python3
"""Watchlist storage in PostgreSQL (table ``watchlist_entries``)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, List, Optional

COMPLIANCE_FLIP = "compliance_flip"


@dataclass
class WatchEntry:
    """Represents a watchlist entry for compliance alerts."""

    user_id: int
    symbol: str
    trigger: str = COMPLIANCE_FLIP
    last_is_compliant: Optional[bool] = None


def owner_key(user_id: int) -> str:
    """External owner label used in API responses and alert events."""

    return f"user:{user_id}"


def require_user_id(user_id: object) -> int:
    """A positive integer user id; anything else is a programming error."""

    if isinstance(user_id, bool) or not isinstance(user_id, int) or user_id <= 0:
        raise ValueError("user_id must be a positive integer")
    return user_id


# The NULL baseline is seeded first, and only if that matched nothing is a flip
# attempted. Flip-first could lose a concurrent opposite verdict: the NULL row
# matches no flip, another check seeds and commits, then this check's seed
# matches nothing. PostgreSQL re-checks each UPDATE's WHERE on the latest row
# version after waiting for the row lock (READ COMMITTED), so concurrent
# identical verdicts produce exactly one flip.
_SEED_SQL = """
    UPDATE watchlist_entries
       SET last_is_compliant = %(verdict)s, updated_at = now()
     WHERE user_id = %(user_id)s AND symbol = %(symbol)s AND trigger = %(trigger)s
       AND last_is_compliant IS NULL
"""
_FLIP_SQL = """
    UPDATE watchlist_entries
       SET last_is_compliant = %(verdict)s, updated_at = now()
     WHERE user_id = %(user_id)s AND symbol = %(symbol)s AND trigger = %(trigger)s
       AND last_is_compliant IS NOT NULL AND last_is_compliant <> %(verdict)s
"""


class WatchlistStorage:
    """Watch entries keyed by (user_id, symbol, trigger) in PostgreSQL.

    ``get_db`` returns the database manager; its ``get_connection()`` rolls
    back on error but never commits, so every method commits explicitly.
    """

    def __init__(self, get_db: Callable[[], object]):
        self._get_db = get_db

    def add(self, entry: WatchEntry) -> None:
        """Watch a symbol. Re-adding keeps the existing baseline."""

        params = {
            "user_id": require_user_id(entry.user_id),
            "symbol": entry.symbol,
            "trigger": entry.trigger,
        }
        with self._get_db().get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO watchlist_entries (user_id, symbol, trigger)
                    VALUES (%(user_id)s, %(symbol)s, %(trigger)s)
                    ON CONFLICT (user_id, symbol, trigger) DO NOTHING
                    """,
                    params,
                )
            conn.commit()

    def list(self, user_id: int) -> List[WatchEntry]:
        """One user's entries; there is no "every user" listing."""

        with self._get_db().get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT user_id, symbol, trigger, last_is_compliant
                      FROM watchlist_entries
                     WHERE user_id = %(user_id)s
                     ORDER BY symbol, trigger
                    """,
                    {"user_id": require_user_id(user_id)},
                )
                rows = cursor.fetchall()
            conn.commit()
        return [WatchEntry(*row) for row in rows]

    def transition(
        self, user_id: int, symbol: str, trigger: str, is_compliant: bool
    ) -> Optional[str]:
        """Record a conclusive verdict: 'baseline' (first one), 'flip', or None."""

        params = {
            "user_id": require_user_id(user_id),
            "symbol": symbol,
            "trigger": trigger,
            "verdict": bool(is_compliant),
        }
        with self._get_db().get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(_SEED_SQL, params)
                if cursor.rowcount:
                    outcome: Optional[str] = "baseline"
                else:
                    cursor.execute(_FLIP_SQL, params)
                    outcome = "flip" if cursor.rowcount else None
            conn.commit()
        return outcome


__all__ = ["COMPLIANCE_FLIP", "WatchEntry", "WatchlistStorage", "owner_key", "require_user_id"]

#!/usr/bin/env python3
"""Alert evaluation logic for watchlist entries."""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional

from alerts.storage import COMPLIANCE_FLIP, WatchlistStorage, owner_key, require_user_id


@dataclass
class AlertEvent:
    """Alert fired for a watch entry."""

    user_id: str
    symbol: str
    trigger: str
    message: str


class AlertEngine:
    """Detects compliance flips against watchlists."""

    def __init__(self, storage: WatchlistStorage):
        self.storage = storage

    def process_verdict(
        self, symbol: str, is_compliant: Optional[bool], *, user_id: int
    ) -> List[AlertEvent]:
        """Record one user's verdict for the symbol and return an alert on a flip.

        Only the given user's entry is read or moved; `user_id` must be a
        positive integer (the session's user id).

        None (insufficient data / under review) is not a verdict: it neither
        alerts nor moves the stored baseline, so True -> None -> False still
        flips exactly once. The storage decides baseline vs flip atomically and
        has committed before an event is returned.
        """

        require_user_id(user_id)
        if is_compliant is None:
            return []

        outcome = self.storage.transition(user_id, symbol, COMPLIANCE_FLIP, is_compliant)
        if outcome != "flip":
            return []
        return [
            AlertEvent(
                user_id=owner_key(user_id),
                symbol=symbol,
                trigger=COMPLIANCE_FLIP,
                message=f"{symbol} compliance flipped to {'Halal' if is_compliant else 'Non-Halal'}.",
            )
        ]


__all__ = ["AlertEngine", "AlertEvent"]

#!/usr/bin/env python3
"""Alert evaluation logic for watchlist entries."""

from __future__ import annotations

from dataclasses import dataclass
from typing import List

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

    def check(self, symbol: str, *, user_id: int) -> List[AlertEvent]:
        """Observe the symbol's stored verdict for one user; return an event on a flip.

        Only the given user's entry is read or moved; `user_id` must be a
        positive integer (the session's user id). Observation only: the flip
        becomes a pending alert email that the evaluation scheduler sends
        (alerts/delivery.py). None (insufficient data / under review) moves
        nothing, so True -> None -> False still flips exactly once.
        """

        require_user_id(user_id)
        observation = self.storage.observe(symbol, user_id=user_id)
        if user_id not in observation.flipped:
            return []
        label = "Halal" if observation.is_compliant else "Non-Halal"
        return [
            AlertEvent(
                user_id=owner_key(user_id),
                symbol=symbol,
                trigger=COMPLIANCE_FLIP,
                message=f"{symbol} compliance flipped to {label}.",
            )
        ]


__all__ = ["AlertEngine", "AlertEvent"]

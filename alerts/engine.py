#!/usr/bin/env python3
"""Alert evaluation logic for watchlist entries."""

from __future__ import annotations

from dataclasses import dataclass
from typing import List

from alerts.storage import WatchEntry, WatchlistStorage


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

    def process_verdict(self, symbol: str, is_compliant: bool) -> List[AlertEvent]:
        """Check every watch entry for the symbol and fire alerts on flip."""

        events: List[AlertEvent] = []
        for entry in self.storage.list():
            if entry.symbol != symbol or entry.trigger != "compliance_flip":
                continue

            if entry.last_is_compliant is None:
                entry.last_is_compliant = is_compliant
                self.storage.update_state(entry)
                continue

            if entry.last_is_compliant != is_compliant:
                message = (
                    f"{symbol} compliance flipped to {'Halal' if is_compliant else 'Non-Halal'}."
                )
                events.append(
                    AlertEvent(
                        user_id=entry.user_id,
                        symbol=symbol,
                        trigger=entry.trigger,
                        message=message,
                    )
                )
                entry.last_is_compliant = is_compliant
                self.storage.update_state(entry)

        return events


__all__ = ["AlertEngine", "AlertEvent"]

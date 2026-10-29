"""In-memory stand-in for alerts.storage.WatchlistStorage in offline tests.

Same semantics as the PostgreSQL storage (idempotent add that keeps the
baseline, owner-scoped list, seed-then-flip transition); concurrency is proven
separately against a real database in tests/test_watchlist_postgres.py.
"""

from typing import Dict, List, Optional, Tuple

from alerts.storage import WatchEntry, require_user_id


class MemoryWatchlistStorage:
    def __init__(self) -> None:
        self.rows: Dict[Tuple[int, str, str], Optional[bool]] = {}

    def add(self, entry: WatchEntry) -> None:
        key = (require_user_id(entry.user_id), entry.symbol, entry.trigger)
        self.rows.setdefault(key, entry.last_is_compliant)

    def list(self, user_id: int) -> List[WatchEntry]:
        require_user_id(user_id)
        return [
            WatchEntry(uid, symbol, trigger, value)
            for (uid, symbol, trigger), value in sorted(self.rows.items())
            if uid == user_id
        ]

    def transition(self, user_id: int, symbol: str, trigger: str, is_compliant: bool) -> Optional[str]:
        key = (require_user_id(user_id), symbol, trigger)
        if key not in self.rows:
            return None
        current = self.rows[key]
        if current is None:
            self.rows[key] = bool(is_compliant)
            return "baseline"
        if current != bool(is_compliant):
            self.rows[key] = bool(is_compliant)
            return "flip"
        return None

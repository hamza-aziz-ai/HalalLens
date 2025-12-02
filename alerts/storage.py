#!/usr/bin/env python3
"""File-based watchlist storage for quick prototyping."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Dict, List, Optional


@dataclass
class WatchEntry:
    """Represents a watchlist entry for compliance alerts."""

    user_id: str
    symbol: str
    trigger: str = "compliance_flip"
    last_is_compliant: Optional[bool] = None

    def key(self) -> str:
        return f"{self.user_id}:{self.symbol}:{self.trigger}"


class WatchlistStorage:
    """Persist watchlist entries to a JSON file."""

    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not self.path.exists():
            self._write({})

    def _read(self) -> Dict[str, Dict]:
        with self.path.open("r", encoding="utf-8") as handle:
            return json.load(handle)

    def _write(self, payload: Dict[str, Dict]) -> None:
        temp_path = self.path.with_suffix(".tmp")
        with temp_path.open("w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2)
        temp_path.replace(self.path)

    def upsert(self, entry: WatchEntry) -> WatchEntry:
        data = self._read()
        data[entry.key()] = asdict(entry)
        self._write(data)
        return entry

    def list(self, user_id: Optional[str] = None) -> List[WatchEntry]:
        data = self._read()
        items: List[WatchEntry] = []
        for value in data.values():
            if user_id and value["user_id"] != user_id:
                continue
            items.append(WatchEntry(**value))
        return items

    def update_state(self, entry: WatchEntry) -> None:
        data = self._read()
        if entry.key() not in data:
            return
        data[entry.key()] = asdict(entry)
        self._write(data)


__all__ = ["WatchEntry", "WatchlistStorage"]

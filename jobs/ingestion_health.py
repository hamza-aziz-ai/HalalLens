#!/usr/bin/env python3
"""Health probe for the ingestion scheduler."""

from __future__ import annotations

import os
import sys
from datetime import datetime, timezone
from pathlib import Path


def _read_heartbeat(path: Path) -> datetime | None:
    if not path.exists():
        return None
    raw = path.read_text().strip()
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw)
    except ValueError:
        return None


def main() -> int:
    sleep_minutes = int(os.getenv("INGESTION_INTERVAL_MINUTES", "60"))
    max_stale_seconds = max(sleep_minutes * 120, 600)
    heartbeat_path = Path(os.getenv("INGESTION_HEARTBEAT", "/tmp/ingestion_heartbeat.txt"))
    heartbeat = _read_heartbeat(heartbeat_path)
    if heartbeat is None:
        print(f"Heartbeat missing at {heartbeat_path}", file=sys.stderr)
        return 1
    delta = datetime.now(timezone.utc) - heartbeat.astimezone(timezone.utc)
    if delta.total_seconds() > max_stale_seconds:
        print(
            f"Heartbeat stale ({delta.total_seconds():.0f}s > {max_stale_seconds}s)",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())

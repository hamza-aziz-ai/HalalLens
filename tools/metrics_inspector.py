#!/usr/bin/env python3
"""Quick-and-dirty utility to inspect ingestion metrics JSONL files."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from datetime import datetime
from pathlib import Path
from statistics import mean
from typing import Any, Dict, List, Optional


def load_metrics(path: Path) -> List[Dict[str, Any]]:
    """Load JSON lines metrics into memory."""
    if not path.exists():
        raise SystemExit(f"Metrics file not found: {path}")

    rows: List[Dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    if not rows:
        raise SystemExit(f"No metrics records found in {path}")
    return rows


def summarize(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Produce aggregate stats from metrics rows."""
    status_counts = Counter(row.get("status", "unknown") for row in rows)
    durations = [row.get("duration_seconds", 0.0) for row in rows]
    timestamps = sorted(
        (
            datetime.fromisoformat(row["timestamp"])
            for row in rows
            if "timestamp" in row
        ),
        reverse=True,
    )
    latest = timestamps[0] if timestamps else None
    earliest = timestamps[-1] if timestamps else None

    return {
        "total_runs": len(rows),
        "status_counts": dict(status_counts),
        "avg_duration": round(mean(durations), 2) if durations else 0.0,
        "max_duration": round(max(durations), 2) if durations else 0.0,
        "min_duration": round(min(durations), 2) if durations else 0.0,
        "latest_run": latest.isoformat() if latest else None,
        "earliest_run": earliest.isoformat() if earliest else None,
    }


def tail(rows: List[Dict[str, Any]], count: int) -> List[Dict[str, Any]]:
    """Return the last N metrics rows."""
    return rows[-count:]


def main():
    parser = argparse.ArgumentParser(
        description="Summarize Halal-Lens ingestion metrics JSONL files.",
    )
    parser.add_argument(
        "metrics_file",
        nargs="?",
        default="logs/metrics/ingestion_metrics.jsonl",
        help="Path to the metrics JSONL file (default: %(default)s)",
    )
    parser.add_argument(
        "--tail",
        type=int,
        default=5,
        help="Show the last N runs after the summary (default: %(default)s)",
    )
    args = parser.parse_args()

    rows = load_metrics(Path(args.metrics_file))
    summary = summarize(rows)
    print("=== Ingestion metrics summary ===")
    for key, value in summary.items():
        print(f"{key:>15}: {value}")

    print(f"\n=== Last {min(args.tail, len(rows))} runs ===")
    for row in tail(rows, args.tail):
        ts = row.get("timestamp")
        status = row.get("status")
        duration = row.get("duration_seconds")
        detail = row.get("details")
        print(f"{ts} | {status:<8} | {duration:>6} s")
        if detail:
            snippet = detail.strip().splitlines()[0][:140]
            print(f"  ↳ {snippet}")


if __name__ == "__main__":
    main()

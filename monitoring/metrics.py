#!/usr/bin/env python3
"""Helpers for summarizing ops metrics JSONL logs."""

from __future__ import annotations

import json
from collections import deque
from pathlib import Path
from typing import Deque, Dict, Optional, Tuple, Any


def _load_jsonl_tail(path: Path, max_lines: int = 200) -> Deque[Dict[str, Any]]:
    entries: Deque[Dict[str, Any]] = deque(maxlen=max_lines)
    if not path.exists():
        return entries
    with path.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                payload = json.loads(line)
                entries.append(payload)
            except json.JSONDecodeError:
                continue
    return entries


def summarize_ingestion_metrics(
    path: Path, tail: int = 200
) -> Dict[str, Optional[Any]]:
    """Return a compact summary for the scheduler metrics JSONL file."""

    entries = _load_jsonl_tail(path, max_lines=tail)
    if not entries:
        if not path.exists():
            return {
                "available": False,
                "message": "metrics file missing",
                "path": str(path),
            }
        return {
            "available": False,
            "message": "metrics file empty",
            "path": str(path),
        }

    success = sum(1 for entry in entries if entry.get("status") == "success")
    failure = sum(1 for entry in entries if entry.get("status") == "failure")
    last_run = entries[-1]
    last_failure: Optional[Dict[str, Any]] = next(
        (
            entry
            for entry in reversed(entries)
            if entry.get("status") == "failure"
        ),
        None,
    )
    avg_duration = round(
        sum(entry.get("duration_seconds", 0.0) for entry in entries) / len(entries),
        3,
    )

    return {
        "available": True,
        "path": str(path),
        "total_runs_considered": len(entries),
        "success_count": success,
        "failure_count": failure,
        "last_run": last_run,
        "last_failure": last_failure,
        "avg_duration_seconds": avg_duration,
    }


__all__ = ["summarize_ingestion_metrics"]

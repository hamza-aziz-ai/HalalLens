#!/usr/bin/env python3
"""Scheduler that runs the BSE ingestion job on a fixed interval."""

from __future__ import annotations

import datetime
import json
import logging
import os
import time
import traceback
from pathlib import Path

from jobs.ingestion_cycle import run_cycle
from config.logging_config import configure_logging
from monitoring.notifier import OpsNotifier

LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
configure_logging(
    "scheduler",
    level=LOG_LEVEL,
    fmt="%(asctime)s %(levelname)s [ingestion] %(message)s",
)
logger = logging.getLogger("scheduler")

SLEEP_MINUTES = int(os.getenv("INGESTION_INTERVAL_MINUTES", "60"))
HEARTBEAT_PATH = Path(os.getenv("INGESTION_HEARTBEAT", "/tmp/ingestion_heartbeat.txt"))
METRICS_PATH = Path(
    os.getenv("INGESTION_METRICS_PATH", "logs/metrics/ingestion_metrics.jsonl"),
)
OPS_NOTIFIER = OpsNotifier(component="ingestion")


def _record_heartbeat():
    HEARTBEAT_PATH.parent.mkdir(parents=True, exist_ok=True)
    HEARTBEAT_PATH.write_text(datetime.datetime.now(datetime.timezone.utc).isoformat())


def _record_metrics(status: str, started_at: datetime.datetime, duration: float, **extra):
    METRICS_PATH.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "status": status,
        "started_at": started_at.isoformat(),
        "duration_seconds": round(duration, 3),
        "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
    }
    payload.update(extra)
    with METRICS_PATH.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(payload) + "\n")


def main():
    logger.info("Starting ingestion scheduler (runs every %s minutes)", SLEEP_MINUTES)
    _record_heartbeat()
    consecutive_failures = 0
    while True:
        started = datetime.datetime.now(datetime.timezone.utc)
        try:
            run_cycle(lookback_days=1)
            duration = (
                datetime.datetime.now(datetime.timezone.utc) - started
            ).total_seconds()
            _record_metrics("success", started, duration)
            logger.info(
                "Ingestion cycle completed successfully in %.2f seconds", duration
            )
            if consecutive_failures:
                OPS_NOTIFIER.notify(
                    "INFO",
                    "Ingestion recovered",
                    details=f"Previous consecutive failures: {consecutive_failures}",
                )
            consecutive_failures = 0
        except Exception:
            duration = (
                datetime.datetime.now(datetime.timezone.utc) - started
            ).total_seconds()
            tb = traceback.format_exc()
            _record_metrics("failure", started, duration, details=tb)
            consecutive_failures += 1
            logger.exception("Ingestion run failed")
            OPS_NOTIFIER.notify(
                "ERROR",
                f"Ingestion run failed (consecutive failures: {consecutive_failures})",
                details=tb,
            )
        finally:
            _record_heartbeat()
        due = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(minutes=SLEEP_MINUTES)
        logger.info("Next run scheduled at ~%s UTC", due.isoformat())
        time.sleep(SLEEP_MINUTES * 60)


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Scheduler that precomputes filing evaluations, then sends compliance-flip alert emails, on a fixed interval."""

from __future__ import annotations

import datetime
import json
import logging
import os
import time
import traceback
from pathlib import Path

from config.logging_config import configure_logging
from monitoring.notifier import OpsNotifier
from alerts.delivery import run_once as run_alert_emails
from jobs.precompute_evaluations import run_precompute

LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
configure_logging(
    "evaluation_scheduler",
    level=LOG_LEVEL,
    fmt="%(asctime)s %(levelname)s [evaluation] %(message)s",
)
logger = logging.getLogger("evaluation_scheduler")

SLEEP_MINUTES = int(os.getenv("EVALUATION_INTERVAL_MINUTES", "15"))
BATCH_LIMIT = int(os.getenv("EVALUATION_BATCH_LIMIT", "200"))
LOOKBACK_DAYS = int(os.getenv("EVALUATION_LOOKBACK_DAYS", "365"))
HEARTBEAT_PATH = Path(
    os.getenv("EVALUATION_HEARTBEAT", "/tmp/evaluation_heartbeat.txt")
)
METRICS_PATH = Path(
    os.getenv("EVALUATION_METRICS_PATH", "logs/metrics/evaluation_metrics.jsonl")
)
OPS_NOTIFIER = OpsNotifier(component="evaluation")


def _record_heartbeat() -> None:
    HEARTBEAT_PATH.parent.mkdir(parents=True, exist_ok=True)
    HEARTBEAT_PATH.write_text(datetime.datetime.now(datetime.timezone.utc).isoformat())


def _record_metrics(
    status: str, started_at: datetime.datetime, duration: float, **extra
) -> None:
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


def _alert_emails_step() -> None:
    """Alert emails (D-031), independent of whether the precompute succeeded.

    Ops alerts carry counts and error classes only, never addresses.
    """

    try:
        counts = run_alert_emails()
    except Exception as exc:
        logger.exception("Alert email step failed")
        OPS_NOTIFIER.notify("ERROR", "Alert email step failed", details=type(exc).__name__)
        return
    failed = counts["failed"] + counts["failed_terminal"] + counts["row_error"] + counts["observe_error"]
    if failed:
        OPS_NOTIFIER.notify(
            "WARNING",
            f"Alert email step: {failed} failure(s)",
            details=", ".join(f"{k}={v}" for k, v in sorted(counts.items())),
        )


def main() -> None:
    logger.info(
        "Starting evaluation scheduler (runs every %s minutes)", SLEEP_MINUTES
    )
    _record_heartbeat()
    consecutive_failures = 0
    while True:
        started = datetime.datetime.now(datetime.timezone.utc)
        try:
            processed = run_precompute(
                limit=BATCH_LIMIT, lookback_days=LOOKBACK_DAYS
            )
            duration = (
                datetime.datetime.now(datetime.timezone.utc) - started
            ).total_seconds()
            _record_metrics(
                "success", started, duration, processed=processed
            )
            logger.info(
                "Evaluation precompute completed: %d rows in %.2fs",
                processed,
                duration,
            )
            if consecutive_failures:
                OPS_NOTIFIER.notify(
                    "INFO",
                    "Evaluation precompute recovered",
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
            logger.exception("Evaluation precompute failed")
            OPS_NOTIFIER.notify(
                "ERROR",
                f"Evaluation precompute failed (consecutive failures: {consecutive_failures})",
                details=tb,
            )
        finally:
            _record_heartbeat()
        _alert_emails_step()
        due = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(minutes=SLEEP_MINUTES)
        logger.info("Next run scheduled at ~%s UTC", due.isoformat())
        time.sleep(SLEEP_MINUTES * 60)


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Scheduler that runs the BSE ingestion job on a fixed interval."""

from __future__ import annotations

import datetime
import logging
import os
import time
from pathlib import Path

from jobs.ingestion_cycle import run_cycle

LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format="%(asctime)s %(levelname)s [ingestion] %(message)s",
)
logger = logging.getLogger("scheduler")

SLEEP_MINUTES = int(os.getenv("INGESTION_INTERVAL_MINUTES", "60"))
HEARTBEAT_PATH = Path(os.getenv("INGESTION_HEARTBEAT", "/tmp/ingestion_heartbeat.txt"))


def _record_heartbeat():
    HEARTBEAT_PATH.parent.mkdir(parents=True, exist_ok=True)
    HEARTBEAT_PATH.write_text(datetime.datetime.now(datetime.timezone.utc).isoformat())


def main():
    logger.info("Starting ingestion scheduler (runs every %s minutes)", SLEEP_MINUTES)
    _record_heartbeat()
    while True:
        try:
            run_cycle(lookback_days=1)
            logger.info("Ingestion cycle completed successfully")
        except Exception:
            logger.exception("Ingestion run failed")
        finally:
            _record_heartbeat()
        due = datetime.datetime.utcnow() + datetime.timedelta(minutes=SLEEP_MINUTES)
        logger.info("Next run scheduled at ~%s UTC", due.isoformat())
        time.sleep(SLEEP_MINUTES * 60)


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Scheduler that runs the BSE ingestion job on a fixed interval."""

from __future__ import annotations

import datetime
import logging
import time

from jobs.ingest_bse import main as run_ingestion

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger("scheduler")

SLEEP_MINUTES = 60  # run hourly by default


def main():
    logger.info("Starting ingestion scheduler (runs every %s minutes)", SLEEP_MINUTES)
    while True:
        try:
            run_ingestion()
            logger.info("Ingestion run completed successfully")
        except Exception:
            logger.exception("Ingestion run failed")
        due = datetime.datetime.utcnow() + datetime.timedelta(minutes=SLEEP_MINUTES)
        logger.info("Next run scheduled at ~%s UTC", due.isoformat())
        time.sleep(SLEEP_MINUTES * 60)


if __name__ == "__main__":
    main()

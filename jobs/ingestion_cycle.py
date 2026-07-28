#!/usr/bin/env python3
"""Run bhavcopy ingestion followed by BSE announcement ingestion."""

from __future__ import annotations

import argparse
import logging
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Optional, Tuple

from jobs.ingest_bhavcopy import run_bhavcopy
from jobs.ingest_bse import run_ingestion
from config.logging_config import configure_logging

logger = logging.getLogger("ingestion_cycle")


def _parse_date(value: str) -> date:
    try:
        return datetime.strptime(value, "%Y%m%d").date()
    except ValueError as exc:
        raise argparse.ArgumentTypeError("Dates must be YYYYMMDD") from exc


def _determine_range(
    start: Optional[date],
    end: Optional[date],
    lookback_days: int,
) -> Tuple[date, date]:
    if start and end:
        if start > end:
            raise argparse.ArgumentTypeError("from-date cannot be after to-date")
        return start, end
    today = datetime.now(timezone.utc).date()
    lookback = max(1, lookback_days)
    computed_start = today - timedelta(days=lookback)
    return computed_start, today


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run bhavcopy ingestion followed by BSE announcement ingestion.",
    )
    parser.add_argument("--from-date", type=_parse_date, help="YYYYMMDD start date")
    parser.add_argument("--to-date", type=_parse_date, help="YYYYMMDD end date")
    parser.add_argument(
        "--lookback-days",
        type=int,
        default=1,
        help="If explicit dates are not supplied, run for today minus N days through today.",
    )
    parser.add_argument(
        "--save-cache",
        action="store_true",
        help="Persist fetched announcements to cache directory.",
    )
    parser.add_argument(
        "--cache-dir",
        type=Path,
        default=Path("./cache"),
        help="Cache directory for announcements/financial data.",
    )
    parser.add_argument(
        "--download-dir",
        type=Path,
        default=Path("./downloads"),
        help="Temporary download directory for PDFs.",
    )
    parser.add_argument(
        "--category",
        default="-1",
        help="Optional BSE category filter passed to the ingestion job.",
    )
    return parser.parse_args()


def run_cycle(
    *,
    from_date: Optional[date] = None,
    to_date: Optional[date] = None,
    lookback_days: int = 1,
    save_cache: bool = False,
    cache_dir: Path = Path("./cache"),
    download_dir: Path = Path("./downloads"),
    category: str = "-1",
) -> None:
    """Run bhavcopy + BSE ingestion sequentially."""

    start, end = _determine_range(from_date, to_date, lookback_days)
    logging.getLogger(__name__).info(
        "Running ingestion cycle for %s -> %s", start.isoformat(), end.isoformat()
    )
    run_bhavcopy(start, end)
    run_ingestion(
        start.strftime("%Y%m%d"),
        end.strftime("%Y%m%d"),
        category=category,
        cache_dir=cache_dir,
        download_dir=download_dir,
        save_cache=save_cache,
    )


def main() -> None:
    args = parse_args()
    configure_logging("ingestion_cycle")
    run_cycle(
        from_date=args.from_date,
        to_date=args.to_date,
        lookback_days=args.lookback_days,
        save_cache=args.save_cache,
        cache_dir=args.cache_dir,
        download_dir=args.download_dir,
        category=args.category,
    )


if __name__ == "__main__":
    main()

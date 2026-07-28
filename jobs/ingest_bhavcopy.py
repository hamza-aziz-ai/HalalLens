#!/usr/bin/env python3
"""Download BSE/NSE bhavcopy files and store market data snapshots."""

from __future__ import annotations

import argparse
import logging
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Iterator, Optional

from database import BSEDatabaseManager
from market_data import BhavcopyClient, BhavcopyError
from config.logging_config import configure_logging

logger = logging.getLogger("bhavcopy_ingestion")


def _parse_date(value: str) -> date:
    try:
        return datetime.strptime(value, "%Y%m%d").date()
    except ValueError as exc:
        raise argparse.ArgumentTypeError("Dates must be YYYYMMDD") from exc


def _generate_days(start: date, end: date) -> Iterator[date]:
    day = start
    while day <= end:
        yield day
        day += timedelta(days=1)


def parse_args() -> argparse.Namespace:
    today = datetime.now(timezone.utc).date()
    parser = argparse.ArgumentParser(description="Ingest official NSE/BSE bhavcopy market data.")
    parser.add_argument("--from-date", default=today.strftime("%Y%m%d"), type=_parse_date)
    parser.add_argument("--to-date", default=today.strftime("%Y%m%d"), type=_parse_date)
    parser.add_argument(
        "--bse-local-dir",
        type=Path,
        help="Optional directory containing EQ_ISINCODE_*.zip/csv files to use instead of downloading.",
    )
    parser.add_argument(
        "--nse-local-dir",
        type=Path,
        help="Optional directory containing mcap*.csv files to use instead of downloading.",
    )
    return parser.parse_args()


def run_bhavcopy(
    from_date: date,
    to_date: date,
    *,
    bse_local_dir: Optional[Path] = None,
    nse_local_dir: Optional[Path] = None,
) -> int:
    """Run bhavcopy ingestion for a date range."""

    db = BSEDatabaseManager()
    client = BhavcopyClient(
        bse_local_dir=bse_local_dir,
        nse_local_dir=nse_local_dir,
    )

    total_snapshots = 0
    try:
        for day in _generate_days(from_date, to_date):
            try:
                bse_records = client.fetch_bse_equity(day)
                nse_caps = client.fetch_nse_market_caps(day)
            except BhavcopyError as exc:
                logger.warning("Skipping %s: %s", day.isoformat(), exc)
                continue

            inserted = 0
            for code, record in bse_records.items():
                if not record.isin:
                    continue
                market_cap = nse_caps.get(record.isin)
                if market_cap is None:
                    continue
                db.insert_market_snapshot(
                    symbol=code,
                    market_cap=market_cap,
                    share_price=record.close,
                    provider="bhavcopy",
                )
                inserted += 1

            total_snapshots += inserted
            logger.info(
                "Processed %s: %d records matched ISINs (total=%d)",
                day.isoformat(),
                inserted,
                total_snapshots,
            )
    finally:
        db.close()
    return total_snapshots


def main() -> None:
    args = parse_args()
    configure_logging("bhavcopy")
    run_bhavcopy(
        args.from_date,
        args.to_date,
        bse_local_dir=args.bse_local_dir,
        nse_local_dir=args.nse_local_dir,
    )


if __name__ == "__main__":
    main()

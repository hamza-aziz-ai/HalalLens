#!/usr/bin/env python3
"""CLI entry-point to run the BSE ingestion → ETL → persistence flow."""

from __future__ import annotations

import argparse
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import List

from crawler import BSEAnnouncementsFetcher
from database import BSEDatabaseManager
from etl import FinancialDataProcessor


logger = logging.getLogger("ingestion")


def _normalize_bse_date(date_str: str) -> str:
    """Return YYYYMMDD string accepted by the BSE API."""

    cleaned = date_str.replace("-", "").strip()
    if len(cleaned) != 8 or not cleaned.isdigit():
        msg = "Date must be in YYYYMMDD or YYYY-MM-DD format"
        raise argparse.ArgumentTypeError(msg)
    return cleaned


def parse_args() -> argparse.Namespace:
    """Parse CLI arguments for the ingestion job."""

    today = datetime.utcnow().date()
    default_start = (today - timedelta(days=1)).strftime("%Y%m%d")
    default_end = today.strftime("%Y%m%d")

    parser = argparse.ArgumentParser(
        description="Fetch BSE announcements, extract financial data, and persist snapshots."
    )
    parser.add_argument(
        "--from-date",
        default=default_start,
        type=_normalize_bse_date,
        help="Start date (YYYYMMDD or YYYY-MM-DD). Defaults to yesterday.",
    )
    parser.add_argument(
        "--to-date",
        default=default_end,
        type=_normalize_bse_date,
        help="End date (YYYYMMDD or YYYY-MM-DD). Defaults to today.",
    )
    parser.add_argument(
        "--category",
        default="-1",
        help="Optional BSE category filter (default: all).",
    )
    parser.add_argument(
        "--cache-dir",
        default="./cache",
        type=Path,
        help="Directory for cached payloads and PDFs.",
    )
    parser.add_argument(
        "--download-dir",
        default="./downloads",
        type=Path,
        help="Directory for temporary downloads.",
    )
    parser.add_argument(
        "--save-cache",
        action="store_true",
        help="Persist fetched announcements as JSON in cache_dir for auditing.",
    )
    return parser.parse_args()


def _persist_announcements(
    db: BSEDatabaseManager, announcements: List[dict]
) -> int:
    """Store announcements via the database manager, guarding empty payloads."""

    if not announcements:
        return 0
    return db.insert_announcements(announcements)


def _persist_financial_snapshots(
    db: BSEDatabaseManager, processor: FinancialDataProcessor, snapshots: List[dict]
) -> int:
    """Insert extracted financial snapshots into the database."""

    if not snapshots:
        return 0
    db.insert_financial_snapshots(snapshots)
    processor.save_financial_data(snapshots)
    return len(snapshots)


def main() -> None:
    args = parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(levelname)s - %(name)s - %(message)s",
    )

    logger.info(
        "Starting BSE ingestion for %s → %s", args.from_date, args.to_date
    )

    fetcher = BSEAnnouncementsFetcher(cache_dir=str(args.cache_dir))
    processor = FinancialDataProcessor(
        download_dir=str(args.download_dir), cache_dir=str(args.cache_dir)
    )
    db_manager = BSEDatabaseManager()

    try:
        announcements = fetcher.get_announcements_paginated(
            args.from_date, args.to_date, category=args.category
        )
        logger.info("Fetched %d raw announcements", len(announcements))

        if args.save_cache and announcements:
            filename = (
                f"bse_announcements_{args.from_date}_{args.to_date}.json"
            )
            fetcher.save_to_cache(announcements, filename)

        inserted = _persist_announcements(db_manager, announcements)
        logger.info("Announcements inserted/updated: %d", inserted)

        financial_data = processor.process_announcements(announcements)
        logger.info(
            "Financial records processed: %d", len(financial_data)
        )

        snapshot_count = _persist_financial_snapshots(
            db_manager, processor, financial_data
        )
        logger.info("Financial snapshots stored: %d", snapshot_count)

        stats = processor.get_statistics()
        logger.info("Processor stats: %s", stats)

    finally:
        fetcher.close()
        processor.close()
        db_manager.close()


if __name__ == "__main__":
    main()

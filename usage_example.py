#!/usr/bin/env python3
"""
NSE/BSE Filings Crawler - Usage Example
This script demonstrates how to use all three modules together for a complete workflow.
"""

import sys
import logging
from datetime import date, timedelta, datetime
from pathlib import Path

# Import our custom modules
from crawler import NSEAnnouncementsFetcher
from crawler import BSEAnnouncementsFetcher
from etl import FinancialDataProcessor
from database import BSEDatabaseManager

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('crawler.log'),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)


class FilingsCrawler:
    """
    Integrated NSE/BSE filings crawler that coordinates all three modules.
    """

    def __init__(self, base_dir: str = "./data"):
        self.base_dir = Path(base_dir)
        self.base_dir.mkdir(exist_ok=True)

        # Initialize fetchers
        self.nse_fetcher = NSEAnnouncementsFetcher(cache_dir=str(self.base_dir / "nse_cache"))
        self.bse_fetcher = BSEAnnouncementsFetcher(cache_dir=str(self.base_dir / "bse_cache"))
        self.financial_data_processor = FinancialDataProcessor(
            download_dir=str(self.base_dir / "financial_downloads"),
            cache_dir=str(self.base_dir / "financial_data")
        )

        self.results = {
            'nse_announcements': [],
            'bse_announcements': [],
            'financial_data': [],
            'summary': {}
        }

    def fetch_nse_data(self, from_date: str, to_date: str) -> bool:
        """Fetch NSE announcements for the given date range."""
        try:
            logger.info(f"Fetching NSE data from {from_date} to {to_date}")
            announcements = self.nse_fetcher.get_corporate_announcements(from_date, to_date)

            if announcements:
                self.results['nse_announcements'] = announcements
                # Save to cache
                self.nse_fetcher.save_to_cache(
                    announcements,
                    f"nse_announcements_{from_date}_{to_date}.json"
                )
                logger.info(f"Successfully fetched {len(announcements)} NSE announcements")
                return True
            else:
                logger.warning("No NSE announcements found for the date range")
                return False

        except Exception as e:
            logger.error(f"Error fetching NSE data: {e}")
            return False

    def fetch_bse_data(self, from_date: str, to_date: str) -> bool:
        """Fetch BSE announcements for the given date range."""
        try:
            # Convert date format for BSE (YYYYMMDD)
            bse_from_date = from_date.replace('-', '')
            bse_to_date = to_date.replace('-', '')

            logger.info(f"Fetching BSE data from {bse_from_date} to {bse_to_date}")
            announcements = self.bse_fetcher.get_announcements_paginated(
                bse_from_date, bse_to_date
            )

            if announcements:
                self.results['bse_announcements'] = announcements
                # Save to cache
                self.bse_fetcher.save_to_cache(
                    announcements,
                    f"bse_announcements_{bse_from_date}_{bse_to_date}.json"
                )
                logger.info(f"Successfully fetched {len(announcements)} BSE announcements")
                return True
            else:
                logger.warning("No BSE announcements found for the date range")
                return False

        except Exception as e:
            logger.error(f"Error fetching BSE data: {e}")
            return False

    def process_financial_data(self) -> bool:
        """Process announcements to extract structured financial data."""
        try:
            # Combine announcements from both exchanges
            all_announcements = (
                    self.results['nse_announcements'] +
                    self.results['bse_announcements']
            )

            if not all_announcements:
                logger.warning("No announcements available for XBRL extraction")
                return False

            logger.info(f"Processing {len(all_announcements)} announcements for XBRL files")

            financial_data = self.financial_data_processor.process_announcements(
                all_announcements
            )

            if financial_data:
                self.results['financial_data'] = financial_data

                # Save financial data
                output_file = self.financial_data_processor.save_financial_data(financial_data)
                logger.info(f"Financial data saved to: {output_file}")

                # Show high-confidence results
                high_conf = [f for f in financial_data if f['confidence'] == 'HIGH']
                if high_conf:
                    logger.info(f"Found {len(high_conf)} high-confidence financial results")
                    for item in high_conf[:3]:  # Show first 3
                        logger.info(f"  • {item['company']} ({item['symbol']}) - {item['category']}")

                return True

            else:
                logger.info("No financial data extracted from announcements")
                return False

        except Exception as e:
            logger.error(f"Error processing financial data: {e}")
            return False

    def generate_summary(self) -> dict:
        """Generate a summary of the crawling results."""
        summary = {
            'nse_announcements_count': len(self.results['nse_announcements']),
            'bse_announcements_count': len(self.results['bse_announcements']),
            'financial_data_count': len(self.results['financial_data']),
            'total_announcements': (
                    len(self.results['nse_announcements']) +
                    len(self.results['bse_announcements'])
            ),
            'financial_statistics': self.financial_data_processor.get_statistics(),
            'timestamp': date.today().isoformat()
        }

        self.results['summary'] = summary
        return summary

    def run_daily_crawl(self, target_date: str = None) -> dict:
        """
        Run a complete daily crawl for the specified date.

        Args:
            target_date: Date in YYYY-MM-DD format (defaults to yesterday)

        Returns:
            Summary dictionary with results
        """
        if not target_date:
            # Default to yesterday's data
            yesterday = date.today() - timedelta(days=1)
            target_date = yesterday.strftime('%Y-%m-%d')

        logger.info(f"Starting daily crawl for {target_date}")

        # Fetch data from both exchanges
        nse_success = self.fetch_nse_data(target_date, target_date)
        bse_success = self.fetch_bse_data(target_date, target_date)

        # Process financial data if we have announcements
        financial_success = False
        if nse_success or bse_success:
            financial_success = self.process_financial_data()

        # Generate summary
        summary = self.generate_summary()

        logger.info("Daily crawl completed")
        logger.info(f"Summary: {summary}")

        return summary

    def run_date_range_crawl(self, from_date: str, to_date: str) -> dict:
        """
        Run a crawl for a specific date range.

        Args:
            from_date: Start date in YYYY-MM-DD format
            to_date: End date in YYYY-MM-DD format

        Returns:
            Summary dictionary with results
        """
        logger.info(f"Starting date range crawl from {from_date} to {to_date}")

        # Fetch data from both exchanges
        nse_success = self.fetch_nse_data(from_date, to_date)
        bse_success = self.fetch_bse_data(from_date, to_date)

        # Fetch data from both exchanges
        financial_success = False
        if nse_success or bse_success:
            financial_success = self.process_financial_data()

        # Generate summary
        summary = self.generate_summary()

        logger.info("Date range crawl completed")
        logger.info(f"Summary: {summary}")

        return summary

    def close(self):
        """Close all fetchers and clean up resources."""
        self.nse_fetcher.close()
        self.bse_fetcher.close()
        self.financial_data_processor.close()
        logger.info("All resources closed")


def main():
    """Main function demonstrating usage of the filings' crawler."""
    crawler = FilingsCrawler()
    db = BSEDatabaseManager()

    try:
        # Example 1: Run daily crawl for yesterday
        # print("=== Running Daily Crawl ===")
        # daily_summary = crawler.run_daily_crawl()
        # print(f"Daily crawl results: {daily_summary}")
        #
        # # Example 2: Run crawl for a specific date range
        # print("\n=== Running Date Range Crawl ===")
        # from_date = "2024-01-15"
        # to_date = "2024-01-17"
        # range_summary = crawler.run_date_range_crawl(from_date, to_date)
        # print(f"Date range crawl results: {range_summary}")

        # Example 3: Individual module usage
        print("\n=== Individual Module Examples ===")

        # NSE only
        # nse_fetcher = NSEAnnouncementsFetcher()
        # nse_data = nse_fetcher.get_corporate_announcements("2024-01-15", "2024-01-15")
        # print(f"NSE announcements: {len(nse_data) if nse_data else 0}")
        # nse_fetcher.close()

        # BSE only
        bse_fetcher = BSEAnnouncementsFetcher()
        bse_data = bse_fetcher.get_announcements_paginated("20250723", "20250723")
        if bse_data:
            # Save to cache
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            bse_fetcher.save_to_cache(bse_data, f"bse_announcements_{timestamp}.json")

            # Print summary
            print(f"Successfully fetched {len(bse_data)} announcements")
            if bse_data:
                print("\nFirst 3 announcements:")
                for i, ann in enumerate(bse_data[:3]):
                    print(f"{i + 1}. {ann.get('SCRIP_CD', 'N/A')} - {ann.get('NEWSSUB', 'N/A')}")

            # db.insert_announcements(announcements_data=bse_data)
        else:
            print("No announcements retrieved")

        print(f"BSE announcements: {len(bse_data) if bse_data else 0}")
        bse_fetcher.close()

        # Financial processor only (updated example)
        if bse_data:
            processor = FinancialDataProcessor()
            financial_data = processor.process_announcements(bse_data)
            print(f"Financial data extracted: {len(financial_data)}")

            # Show sample results
            if financial_data:
                high_conf = [f for f in financial_data if f['confidence'] == 'HIGH']
                print(f"High-confidence results: {len(high_conf)}")

                if high_conf:
                    print("Sample high-confidence financial results:")
                    for item in high_conf[:3]:
                        extracted = item.get('extracted_data', {})
                        print(f"  • {item['company']} - Q{extracted.get('quarter', 'N/A')} "
                              f"{extracted.get('audit_status', 'N/A')} results")

                db.insert_financial_snapshots(financial_data)

            processor.close()

    except Exception as e:
        logger.error(f"Error in main execution: {e}")

    finally:
        crawler.close()


if __name__ == "__main__":
    main()

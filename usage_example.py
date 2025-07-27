#!/usr/bin/env python3
"""
NSE/BSE Filings Crawler - Usage Example
This script demonstrates how to use all three modules together for a complete workflow.
"""

import logging
import sys
from datetime import datetime

# Import our custom modules
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


def main():
    """Main function demonstrating usage of the filings' crawler."""

    try:
        print("\n=== Individual Module Examples ===")

        # BSE only
        bse_fetcher = BSEAnnouncementsFetcher()
        db = BSEDatabaseManager()
        financial_processor = FinancialDataProcessor()

        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')

        bse_data = bse_fetcher.get_announcements_paginated("20250725", "20250725")
        if bse_data:
            # Save to cache
            bse_fetcher.save_to_cache(bse_data, f"bse_announcements_{timestamp}.json")

            # Print summary
            print(f"Successfully fetched {len(bse_data)} announcements")
            if bse_data:
                print("\nFirst 3 announcements:")
                for i, ann in enumerate(bse_data[:3]):
                    print(f"{i + 1}. {ann.get('SCRIP_CD', 'N/A')} - {ann.get('NEWSSUB', 'N/A')}")

            db.insert_announcements(announcements_data=bse_data)
        else:
            print("No announcements retrieved")

        print(f"BSE announcements: {len(bse_data) if bse_data else 0}")
        bse_fetcher.close()

        # Financial processor only (updated example)
        if bse_data:
            financial_data = financial_processor.process_announcements(bse_data)
            financial_processor.save_financial_data(financial_data)
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

            financial_processor.close()

    except Exception as e:
        logger.error(f"Error in main execution: {e}")


if __name__ == "__main__":
    main()

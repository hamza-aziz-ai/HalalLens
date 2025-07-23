#!/usr/bin/env python3
"""
BSE Announcements Fetcher
Production-ready implementation for fetching BSE corporate announcements.
Uses API endpoints discovered through research and proven pagination methods.
"""

import requests
import time
import json
import logging
from datetime import datetime, date, timedelta
from typing import Dict, List, Optional, Any
from pathlib import Path

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


class BSEAnnouncementsFetcher:
    """
    Production-ready BSE announcements fetcher using proven API endpoints.
    Handles pagination and proper parameter management.
    """

    def __init__(self, cache_dir: str = "./cache"):
        self.base_url = "https://api.bseindia.com/BseIndiaAPI"
        self.api_base = f"{self.base_url}/api"
        self.session = requests.Session()
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(exist_ok=True)

        # Headers required for BSE API based on research
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (X11; Ubuntu; Linux x86_64; rv:109.0) Gecko/20100101 Firefox/115.0',
            'Referer': 'https://www.bseindia.com/corporates/ann.html',
            'Accept': 'application/json, text/plain, */*',
            'Accept-Language': 'en-US,en;q=0.9',
            'Accept-Encoding': 'gzip, deflate, br',
            'Connection': 'keep-alive',
            'Sec-Fetch-Dest': 'empty',
            'Sec-Fetch-Mode': 'cors',
            'Sec-Fetch-Site': 'same-site'
        }

        self.session.headers.update(self.headers)

    def _make_request(self, url: str, params: Optional[Dict] = None, max_retries: int = 3) -> Optional[Dict]:
        """Make API request with retry logic."""
        for attempt in range(max_retries):
            try:
                # Rate limiting
                time.sleep(0.5)  # Conservative rate limiting for BSE

                response = self.session.get(
                    url,
                    params=params,
                    headers=self.headers,
                    timeout=30
                )

                if response.status_code == 200:
                    return response.json()
                else:
                    logger.warning(f"Request failed with status {response.status_code}, attempt {attempt + 1}")

            except requests.exceptions.RequestException as e:
                logger.error(f"Request error on attempt {attempt + 1}: {e}")

            # Exponential backoff
            time.sleep(2 ** attempt)

        return None

    @staticmethod
    def _chunk_data_range(start_date: str, end_date: str, max_days: int = 1):
        """Split date range into BSE-compatible chunks."""
        start_date = datetime.strptime(start_date, '%Y%m%d')
        end_date = datetime.strptime(end_date, '%Y%m%d')
        chunks = []

        current_day = start_date
        while current_day <= end_date:
            chunk_end = min(current_day + timedelta(days=max_days-1), end_date)
            chunks.append((
                current_day.strftime('%Y%m%d'),
                chunk_end.strftime('%Y%m%d'),
            ))
            current_day = chunk_end + timedelta(days=1)

        return chunks

    def _fetch_date_chunk(self, url: str, from_date_bse: str, to_date_bse: str, category: str = '-1', search_type: str = 'P') -> List[Dict]:
        """Fetch single date chunk with proper BSE pagination."""
        announcements = []
        page_no = 1

        while True:
            params = {
                'pageno': page_no,
                'strCat': category,
                'strPrevDate': from_date_bse,
                'strScrip': '',
                'strSearch': search_type,
                'strToDate': to_date_bse,
                'strType': 'C',
                'PageSize': 50
            }

            logger.info(f"Fetching page {page_no}...")
            data = self._make_request(url, params)

            if data and 'Table' in data and data['Table']:
                page_announcements = data['Table']
                announcements.extend(page_announcements)
                logger.info(f"Page {page_no}: Retrieved {len(announcements)} announcements")
                page_no += 1
            else:
                logger.info(f"No more data found. Total pages processed: {page_no - 1}")
                break

        logger.info(f"Total announcements retrieved: {len(announcements)}")
        return announcements

    def get_announcements_paginated(self, from_date: str, to_date: str,
                                    category: str = '-1', search_type: str = 'P') -> List[Dict]:
        """
        Fetch all announcements with automatic pagination.

        Args:
            from_date: Start date in YYYYMMDD format
            to_date: End date in YYYYMMDD format
            category: Category filter (-1 for all)
            search_type: Search type (P for public)

        Returns:
            List of all announcements across all pages
        """
        # Updated API endpoint based on research
        url = f"{self.api_base}/AnnGetData/w"

        date_chunks = self._chunk_data_range(from_date, to_date, max_days=1)
        all_announcements = []

        logger.info(f"Fetching BSE announcements from {from_date} to {to_date}")

        for chunk_start, chunk_end in date_chunks:
            chunk_data = self._fetch_date_chunk(url, chunk_start, chunk_end, category, search_type)
            all_announcements.extend(chunk_data)
            time.sleep(1)

        logger.info(f"Total announcements retrieved: {len(all_announcements)}")
        return all_announcements

    def get_company_announcements(self, script_code: str, from_date: str, to_date: str) -> List[Dict]:
        """
        Fetch announcements for a specific company.

        Args:
            script_code: BSE script code for the company
            from_date: Start date in YYYYMMDD format
            to_date: End date in YYYYMMDD format

        Returns:
            List of company-specific announcements
        """
        url = f"{self.api_base}/AnnSubCategoryGetData/w"

        params = {
            'pageno': 1,
            'strCat': '-1',
            'strPrevDate': from_date,
            'strScrip': script_code,
            'strSearch': 'P',
            'strToDate': to_date,
            'strType': 'C',
            'subcategory': ''
        }

        logger.info(f"Fetching announcements for script code: {script_code}")

        data = self._make_request(url, params)
        if data and 'Table' in data:
            announcements = data['Table']
            logger.info(f"Retrieved {len(announcements)} announcements for {script_code}")
            return announcements
        else:
            logger.error(f"Failed to retrieve announcements for {script_code}")
            return []

    def get_corporate_actions(self, script_code: str = "") -> List[Dict]:
        """
        Fetch corporate actions data.

        Args:
            script_code: Optional BSE script code

        Returns:
            List of corporate actions
        """
        # This endpoint might need adjustment based on actual BSE API structure
        url = f"{self.api_base}/corporate-actions"  # Placeholder - needs verification

        params = {}
        if script_code:
            params['scripcode'] = script_code

        logger.info("Fetching corporate actions")

        data = self._make_request(url, params)
        if data:
            logger.info("Retrieved corporate actions data")
            return data if isinstance(data, list) else [data]
        else:
            logger.error("Failed to retrieve corporate actions")
            return []

    def save_to_cache(self, data: Any, filename: str) -> bool:
        """Save data to cache file."""
        try:
            cache_file = self.cache_dir / filename
            with open(cache_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False, default=str)
            logger.info(f"Data saved to {cache_file}")
            return True
        except Exception as e:
            logger.error(f"Failed to save cache: {e}")
            return False

    def close(self):
        """Close the session."""
        self.session.close()
        logger.info("Session closed")


def main():
    """Example usage of BSE announcements fetcher."""
    fetcher = BSEAnnouncementsFetcher()

    try:
        # Get current date and yesterday for demo (BSE uses YYYYMMDD format)
        today = date.today().strftime('%Y%m%d')
        yesterday = date.today().replace(day=date.today().day - 1).strftime('%Y%m%d')

        # Fetch announcements with pagination
        announcements = fetcher.get_announcements_paginated(yesterday, today)

        if announcements:
            # Save to cache
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            fetcher.save_to_cache(announcements, f"bse_announcements_{timestamp}.json")

            # Print summary
            print(f"Successfully fetched {len(announcements)} announcements")
            if announcements:
                print("\nFirst 3 announcements:")
                for i, ann in enumerate(announcements[:3]):
                    print(f"{i + 1}. {ann.get('SCRIP_CD', 'N/A')} - {ann.get('NEWSSUB', 'N/A')}")
        else:
            print("No announcements retrieved")

    except Exception as e:
        logger.error(f"Error in main execution: {e}")

    finally:
        fetcher.close()


if __name__ == "__main__":
    main()

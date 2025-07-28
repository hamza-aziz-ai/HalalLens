#!/usr/bin/env python3
"""
NSE Announcements Fetcher
Production-ready implementation using session management with proper headers and rate limiting.
Based on proven approaches from NseIndiaApi library patterns.
"""

import json
import logging
import random
import time
from pathlib import Path
from typing import Dict, List, Optional, Any

import cloudscraper
import requests
import urllib3
from fake_useragent import UserAgent

urllib3.disable_warnings()

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


class NSEAnnouncementsFetcher:
    """
    Production-ready NSE announcements fetcher using session management.
    Avoids Playwright dependency by using proven session-based approach.
    """

    def __init__(self, cache_dir: str = "./cache"):
        self.scraper = cloudscraper.CloudScraper(
            browser={
                'browser': 'chrome',
                'platform': 'windows',
                'desktop': True,
            },
            debug=False
        )
        self.ua = UserAgent()
        self.base_url = "https://www.nseindia.com"
        self.api_base = f"{self.base_url}/api"
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(exist_ok=True)
        self.max_session_duration = 300
        self.session_start_time = None

        # Production-tested headers that work with NSE
        self.headers = {
            'User-Agent': self.ua.chrome,
            'Accept': 'application/json, text/plain, */*',
            'Accept-Language': 'en-US,en;q=0.9',
            'Accept-Encoding': 'gzip, deflate, br',
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1',
            'Sec-Fetch-Dest': 'empty',
            'Sec-Fetch-Mode': 'cors',
            'Sec-Fetch-Site': 'same-origin',
            'Cache-Control': 'no-cache',
            'Pragma': 'no-cache'
        }

        self.scraper.headers.update(self.headers)
        self._initialize_session()

    def _initialize_session(self) -> bool:
        """Initialize session by visiting NSE homepage to get cookies."""
        try:
            logger.info("Initializing NSE session...")
            response = self.scraper.get(self.base_url, timeout=30)
            if response.status_code == 200:
                logger.info("Session initialized successfully")
                self.session_start_time = time.time()
                # Human-like delay
                time.sleep(random.uniform(2, 4))
                return True
            else:
                logger.error(f"Failed to initialize session: {response.status_code}")
                return False
        except Exception as e:
            logger.error(f"Session initialization error: {e}")
            return False

    def _make_request(self, url: str, params: Optional[Dict] = None, max_retries: int = 3) -> Optional[Dict]:
        """Make API request with retry logic and rate limiting."""
        for attempt in range(max_retries):
            try:
                # Add referer for each request
                self.scraper.headers["Referer"] = f"{self.base_url}/companies-listing/corporate-filings-announcements"

                # CRITICAL: Visit the announcement page first
                self.scraper.get(self.scraper.headers["Referer"], timeout=30)
                # Allow session establishment
                time.sleep(random.uniform(2, 4))

                response = self.scraper.get(url, params=params, timeout=45)

                if response.status_code == 200:
                    return response.json()
                elif response.status_code in [403, 429, 503]:
                    # Anti-bot triggered, wait and reinitialize
                    logger.warning("# Anti-bot triggered, wait and reinitialize...")
                    # Exponential backoff + Human-like delay
                    wait_time = (2 ** attempt) * random.uniform(10, 20)
                    time.sleep(wait_time)
                    self._initialize_session()
                else:
                    logger.warning(f"Request failed with status {response.status_code}, attempt {attempt + 1}")

            except requests.exceptions.RequestException as e:
                logger.error(f"Request error on attempt {attempt + 1}: {e}")
                if attempt < max_retries - 1:
                    time.sleep(random.uniform(15, 30))
                    self._initialize_session()

        return None

    def _session_expired(self):
        """Check if session needs refresh"""
        if not self.session_start_time:
            return True
        return (time.time() - self.session_start_time) > self.max_session_duration

    @staticmethod
    def is_valid_response(data):
        """Validate NSE API responses"""
        if isinstance(data, dict):
            if data.get('msg') == 'no data found':
                return True, "SUCCESS: API working, no announcements for this date"
            elif data.get('data'):
                return True, f"SUCCESS: Found {len(data['data'])} announcements"
            else:
                return False, "Unexpected response structure"
        return False, "Invalid response type"

    def get_corporate_announcements(self, from_date: str, to_date: str, index: str = "equities") -> List[Dict]:
        """
        Fetch corporate announcements for date range.

        Args:
            from_date: Start date in YYYY-MM-DD format
            to_date: End date in YYYY-MM-DD format
            index: Market segment (default: "equities")

        Returns:
            List of announcement dictionaries
        """
        if not self.scraper or self._session_expired():
            if not self._initialize_session():
                return []

        url = f"{self.api_base}/corporate-announcements"
        params = {
            'index': index,
            'from_date': from_date,
            'to_date': to_date
        }

        logger.info(f"Fetching announcements from {from_date} to {to_date}")

        response = self._make_request(url, params)

        if self.is_valid_response(response):
            logger.info(f"Retrieved {len(response.get('data', []))} announcements")
            return response.get('data', [])
        elif response and isinstance(response, list):
            logger.info(f"Retrieved {len(response)} announcements")
            return response
        else:
            logger.error("Failed to retrieve announcements or invalid data format")
            return []

    def get_financial_results(self, period: str = "Quarterly", index: str = "equities") -> List[Dict]:
        """
        Fetch financial results.

        Args:
            period: Period type (Quarterly, Annual)
            index: Market segment

        Returns:
            List of financial results
        """
        url = f"{self.api_base}/corporates-financial-results"
        params = {
            'index': index,
            'period': period
        }

        logger.info(f"Fetching {period} financial results")

        data = self._make_request(url, params)
        if data:
            logger.info(f"Retrieved financial results")
            return data if isinstance(data, list) else [data]
        else:
            logger.error("Failed to retrieve financial results")
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
        self.scraper.close()
        logger.info("Session closed")

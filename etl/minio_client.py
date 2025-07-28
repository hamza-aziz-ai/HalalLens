#!/usr/bin/env python3
"""
Enhanced MinIO Client for BSE PDF Storage with Anti-Bot Measures
Handles BSE's 403 protection by mimicking browser behavior
"""

import logging
import random
import time
from datetime import datetime
from io import BytesIO
from typing import Optional, Dict

import requests
from minio import Minio
from minio.error import S3Error

from config import (
    MINIO_HOST,
    MINIO_PORT,
    MINIO_ACCESS_KEY,
    MINIO_SECRET_KEY
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class BSEPDFStorage:
    """Enhanced MinIO client with BSE anti-bot protection"""

    def __init__(self,
                 endpoint: str = "127.0.0.1:9000",
                 access_key: str = None,
                 secret_key: str = None,
                 secure: bool = False):

        # Initialize MinIO client
        self.client = Minio(
            endpoint=endpoint or f"{MINIO_HOST}:{MINIO_PORT}",
            access_key=access_key or MINIO_ACCESS_KEY,
            secret_key=secret_key or MINIO_SECRET_KEY,
            secure=secure
        )

        # Initialize HTTP session with anti-bot headers
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) '
                          'Chrome/124.0.0.0 Safari/537.36',
            'Accept': 'application/pdf,application/octet-stream,*/*;q=0.9',
            'Accept-Language': 'en-US,en;q=0.9,hi;q=0.8',
            'Accept-Encoding': 'gzip, deflate, br',
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1',
            'Sec-Fetch-Dest': 'document',
            'Sec-Fetch-Mode': 'navigate',
            'Sec-Fetch-Site': 'same-origin',
            'Cache-Control': 'max-age=0'
        })

        self.bucket_name = "bse-pdfs"
        self.bse_base_url = "https://www.bseindia.com"

        # Rate limiting parameters
        self.last_request_time = 0
        self.min_request_interval = 1.0  # 1 second between requests

        self.stats = {
            'uploaded': 0,
            'failed': 0,
            'cached': 0,
            'session_initialized': False
        }

        # Verify MinIO connection
        try:
            self.client.bucket_exists(self.bucket_name)
            logger.info(f"Connected to MinIO - bucket '{self.bucket_name}' ready")
        except Exception as e:
            logger.error(f"MinIO connection failed: {e}")
            raise

    def _initialize_bse_session(self):
        """Initialize session by visiting BSE homepage to get cookies"""
        if self.stats['session_initialized']:
            return True

        try:
            logger.info("Initializing BSE session...")

            # Visit BSE homepage to establish session
            homepage_response = self.session.get(
                f"{self.bse_base_url}/",
                timeout=30
            )

            if homepage_response.status_code == 200:
                # Visit announcements page to get additional cookies
                self.session.get(
                    f"{self.bse_base_url}/corporates/ann.html",
                    timeout=30
                )

                self.stats['session_initialized'] = True
                logger.info("BSE session initialized successfully")
                time.sleep(2)  # Human-like delay
                return True
            else:
                logger.error(f"Failed to initialize BSE session: {homepage_response.status_code}")
                return False

        except Exception as e:
            logger.error(f"BSE session initialization error: {e}")
            return False

    def _rate_limit(self):
        """Enforce rate limiting to avoid triggering anti-bot measures"""
        current_time = time.time()
        time_since_last = current_time - self.last_request_time

        if time_since_last < self.min_request_interval:
            sleep_time = self.min_request_interval - time_since_last
            time.sleep(sleep_time)

        self.last_request_time = time.time()

    @staticmethod
    def generate_pdf_path(symbol: str, filing_date: str, confidence: str) -> str:
        """Generate organized path for PDF storage"""
        try:
            date_obj = datetime.fromisoformat(filing_date.replace('Z', '+00:00'))
        except Exception as e:
            # Fallback for different date formats
            logger.warning(f"Falling back to different time format: {e}")
            date_obj = datetime.now()

        year = date_obj.strftime('%Y')
        month = date_obj.strftime('%m')

        # Organize by confidence level
        if confidence == 'HIGH':
            folder = f"financial-results/{year}/{month}"
        elif confidence == 'MEDIUM':
            folder = f"board-meetings/{year}/{month}"
        else:
            folder = f"raw-downloads/{year}/{month}"

        # Create filename with timestamp to prevent duplicates
        filename = f"{symbol}_{date_obj.strftime('%Y%m%d_%H%M%S')}.pdf"

        return f"{folder}/{filename}"

    def download_and_store_pdf(self, pdf_url: str, symbol: str,
                               filing_date: str, confidence: str = 'HIGH',
                               max_retries: int = 3) -> Optional[str]:
        """Download PDF from BSE with anti-bot protection and store in MinIO"""

        # Initialize BSE session if needed
        if not self._initialize_bse_session():
            logger.error("Failed to initialize BSE session")
            self.stats['failed'] += 1
            return None

        # Generate storage path
        minio_path = self.generate_pdf_path(symbol, filing_date, confidence)

        # Check if already exists
        if self._pdf_exists(minio_path):
            logger.info(f"PDF already exists in MinIO: {minio_path}")
            self.stats['cached'] += 1
            return minio_path

        # Attempt download with retries
        for attempt in range(max_retries):
            try:
                # Rate limiting
                self._rate_limit()

                # Set referer to BSE announcements page
                self.session.headers['Referer'] = f"{self.bse_base_url}/corporates/ann.html"

                # Download PDF with proper headers
                logger.info(f"Downloading PDF (attempt {attempt + 1}/{max_retries}): {symbol}")
                response = self.session.get(pdf_url, timeout=45, stream=True)

                # Check response status
                if response.status_code == 200:
                    # Verify content type
                    content_type = response.headers.get('content-type', '').lower()
                    if 'pdf' not in content_type and 'application/octet-stream' not in content_type:
                        logger.warning(f"Unexpected content type: {content_type} for {pdf_url}")
                        # Continue anyway as BSE sometimes returns generic content-type

                    # Read content
                    pdf_content = response.content

                    # Basic PDF validation (check PDF header)
                    if not pdf_content.startswith(b'%PDF'):
                        logger.warning(f"Downloaded content doesn't appear to be a PDF: {symbol}")
                        if attempt < max_retries - 1:
                            time.sleep(random.uniform(2, 5))
                            continue

                    # Upload to MinIO
                    pdf_data = BytesIO(pdf_content)

                    self.client.put_object(
                        bucket_name=self.bucket_name,
                        object_name=minio_path,
                        data=pdf_data,
                        length=len(pdf_content),
                        content_type='application/pdf'
                    )

                    self.stats['uploaded'] += 1
                    logger.info(f"PDF uploaded successfully: {minio_path} ({len(pdf_content)} bytes)")
                    return minio_path

                elif response.status_code == 403:
                    logger.warning(f"403 Forbidden (attempt {attempt + 1}): {pdf_url}")
                    if attempt < max_retries - 1:
                        # Reinitialize session and wait longer
                        self.stats['session_initialized'] = False
                        wait_time = random.uniform(5, 15) * (attempt + 1)
                        logger.info(f"Waiting {wait_time:.1f} seconds before retry...")
                        time.sleep(wait_time)
                        continue

                elif response.status_code == 404:
                    logger.error(f"PDF not found (404): {pdf_url}")
                    return "PDF Moved"  # No point retrying 404s

                else:
                    logger.warning(f"HTTP {response.status_code} (attempt {attempt + 1}): {pdf_url}")
                    if attempt < max_retries - 1:
                        time.sleep(random.uniform(2, 5))
                        continue

            except requests.exceptions.Timeout:
                logger.warning(f"Timeout (attempt {attempt + 1}): {pdf_url}")
                if attempt < max_retries - 1:
                    time.sleep(random.uniform(3, 8))
                    continue

            except Exception as e:
                logger.error(f"Download error (attempt {attempt + 1}) for {pdf_url}: {e}")
                if attempt < max_retries - 1:
                    time.sleep(random.uniform(2, 5))
                    continue

        # All attempts failed
        self.stats['failed'] += 1
        logger.error(f"Failed to download PDF after {max_retries} attempts: {symbol}")
        return None

    def _pdf_exists(self, minio_path: str) -> bool:
        """Check if PDF already exists in MinIO"""
        try:
            self.client.stat_object(self.bucket_name, minio_path)
            return True
        except S3Error:
            return False

    def get_pdf_url(self, minio_path: str, expires_hours: int = 24) -> Optional[str]:
        """Generate presigned URL for PDF access"""
        try:
            from datetime import timedelta
            url = self.client.presigned_get_object(
                self.bucket_name,
                minio_path,
                expires=timedelta(hours=expires_hours)
            )
            return url
        except Exception as e:
            logger.error(f"Failed to generate presigned URL: {e}")
            return None

    def get_statistics(self) -> Dict:
        """Get comprehensive statistics"""
        total_attempts = self.stats['uploaded'] + self.stats['failed']
        success_rate = (self.stats['uploaded'] / total_attempts * 100) if total_attempts > 0 else 0

        return {
            **self.stats,
            'total_attempts': total_attempts,
            'success_rate': f"{success_rate:.1f}%"
        }

    def close(self):
        """Clean up resources"""
        if hasattr(self, 'session'):
            self.session.close()
        logger.info("BSE PDF storage session closed")

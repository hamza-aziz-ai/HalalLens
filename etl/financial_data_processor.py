#!/usr/bin/env python3
"""
Financial Data Processor - PDF and XBRL Handler
Focuses on extracting structured data from BSE announcements
"""

import json
import logging
import re
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

import requests

from etl.minio_client import BSEPDFStorage
from database.database_manager import BSEDatabaseManager

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

db_client = BSEDatabaseManager()


# noinspection PyTypeChecker
class FinancialDataProcessor:
    """Realistic processor for BSE financial announcements"""

    def __init__(self, download_dir: str = "./downloads", cache_dir: str = "./cache"):
        self.download_dir = Path(download_dir)
        self.cache_dir = Path(cache_dir)
        self.download_dir.mkdir(exist_ok=True)
        self.cache_dir.mkdir(exist_ok=True)

        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Accept': 'application/pdf, application/xml, */*'
        })

        self.bse_attachment_dir = "https://www.bseindia.com/xml-data/corpfiling"
        self.bse_attachment_live = f"{self.bse_attachment_dir}/AttachLive"
        self.bse_attachment_moved = f"{self.bse_attachment_dir}/AttachHis"

        # Financial keywords for detection
        self.financial_keywords = {
            'high_confidence': ['result', 'financial results', 'quarterly results', 'annual results'],
            'medium_confidence': ['unaudited', 'audited', 'standalone', 'consolidated'],
            'board_keywords': ['approve', 'consideration', 'quarter ended', 'year ended']
        }

        self.stats = {
            'processed': 0,
            'financial_announcements': 0,
            'pdfs_downloaded': 0,
            'xbrl_found': 0,
            'extraction_successful': 0,
            'extraction_failed': 0
        }

        # Add MinIO storage
        self.pdf_storage = BSEPDFStorage()
        logger.info("MinIO PDF storage initialized")

    def process_announcements(self, anns: List[Dict]) -> List[Dict]:
        """
        Process BSE announcements to extract financial data

        Args:
            anns: List of BSE announcement dictionaries

        Returns:
            List of processed financial data
        """
        logger.info(f"Processing {len(anns)} BSE announcements for financial data")

        finance_data = []

        for announcement in anns:
            self.stats['processed'] += 1

            # Extract announcement details with null handling
            category = str(announcement.get('CATEGORYNAME', '')).strip()
            subject = str(announcement.get('NEWSSUB', '')).lower()
            company = announcement.get('SLONGNAME', '')
            symbol = str(announcement.get('SCRIP_CD', ''))
            date = announcement.get('NEWS_DT', '')
            attachment = announcement.get('ATTACHMENTNAME', '')
            year, month = date[:4], date[5:7]

            # Focus on financial announcements
            if self._is_financial_announcement(category, subject):
                self.stats['financial_announcements'] += 1

                processed_data = {
                    'symbol': symbol,
                    'company': company,
                    'category': category,
                    'subject': announcement.get('NEWSSUB', ''),
                    'date': db_client.parse_iso_datetime(date),
                    'attachment_name': attachment,
                    'confidence': self._determine_confidence(category, subject),
                    'extracted_data': None,
                    'pdf_url': None,
                    'processing_status': 'pending'
                }

                # Try to extract financial data
                if attachment:
                    pdf_url = f"{self.bse_attachment_live}/{attachment}"
                    processed_data['pdf_url'] = pdf_url

                    # Download and store PDF in MinIO
                    minio_path = self.pdf_storage.download_and_store_pdf(pdf_url, symbol, date)
                    if minio_path.lower() == "pdf moved":
                        pdf_url = f"{self.bse_attachment_moved}/{year}/{month}/{attachment}"
                        minio_path = self.pdf_storage.download_and_store_pdf(pdf_url, symbol, date)

                    if minio_path:
                        processed_data['pdf_stored'] = True
                        logger.info(f"PDF stored in MinIO: {company} ({symbol})")
                    else:
                        processed_data['pdf_stored'] = False
                        logger.warning(f"Failed to store PDF: {company} ({symbol})")

                    processed_data['minio_path'] = minio_path
                    self.updated_pdf_status(
                        symbol, processed_data['date'], processed_data['minio_path'], processed_data['pdf_stored']
                    )

                    # Extract basic financial information from announcement text
                    extracted_info = self._extract_financial_info_from_text(announcement)
                    if extracted_info:
                        processed_data['extracted_data'] = extracted_info
                        processed_data['processing_status'] = 'success'
                        self.stats['extraction_successful'] += 1
                        logger.info(f"Extracted financial data: {company} ({symbol})")
                    else:
                        processed_data['processing_status'] = 'no_data_found'
                        self.stats['extraction_failed'] += 1

                finance_data.append(processed_data)

        logger.info(f"Financial processing complete:")
        logger.info(f"  Financial announcements: {self.stats['financial_announcements']}")
        logger.info(f"  Successful extractions: {self.stats['extraction_successful']}")
        logger.info(f"  Failed extractions: {self.stats['extraction_failed']}")

        return finance_data

    @staticmethod
    def updated_pdf_status(symbol, filing_date, minio_path: str, pdf_stored: bool):
        """
        Update minio_path and pdf_stored status in BSE Announcements table

        Args:
            symbol: Financial announcements symbol
            filing_date: Financial announcements filing date
            minio_path: Path for PDF to minio bucket
            pdf_stored: Boolean flag to indicate whether the PDF stored successfully
        """
        with db_client.get_connection() as conn:
            with conn.cursor() as cursor:
                try:
                    # Use ON CONFLICT to handle duplicates
                    update_query = """
                    UPDATE announcements
                        SET minio_path = %s, pdf_stored = %s
                        WHERE symbol = %s AND filing_date = %s;
                    """

                    cursor.execute(update_query, (minio_path, pdf_stored, symbol, filing_date))

                    conn.commit()
                    logger.info(f"Successfully updated minio_path in announcements")

                except Exception as e:
                    conn.rollback()
                    logger.error(f"Failed to update minio_path: {e}")
                    raise

    def _is_financial_announcement(self, category: str, subject: str) -> bool:
        """Determine if announcement is financial-related"""

        # High confidence categories
        if category in ['Result', 'Results']:
            return True

        # Board meetings with financial keywords
        if category == 'Board Meeting':
            return any(keyword in subject for keyword in self.financial_keywords['board_keywords'])

        # Subject-based detection
        return any(keyword in subject for keyword in self.financial_keywords['high_confidence'])

    def _determine_confidence(self, category: str, subject: str) -> str:
        """Determine confidence level for financial data"""
        if category == 'Result':
            return 'HIGH'
        elif category == 'Board Meeting' and any(kw in subject for kw in self.financial_keywords['board_keywords']):
            return 'MEDIUM'
        else:
            return 'LOW'

    def _extract_financial_info_from_text(self, announcement: Dict) -> Optional[Dict]:
        """Extract financial information from announcement text"""
        try:
            subject = announcement.get('NEWSSUB', '')
            more_text = announcement.get('MORE', '')
            full_text = f"{subject} {more_text}".lower()

            extracted_info = {
                'period': self._extract_period(full_text),
                'type': self._extract_result_type(full_text),
                'financial_year': self._extract_financial_year(full_text),
                'quarter': self._extract_quarter(full_text),
                'audit_status': self._extract_audit_status(full_text)
            }

            # Only return if we found meaningful data
            if any(extracted_info.values()):
                return extracted_info

            return None

        except Exception as e:
            logger.error(f"Text extraction error: {e}")
            return None

    @staticmethod
    def _extract_period(text: str) -> Optional[str]:
        """Extract reporting period from text"""
        period_patterns = [
            r'quarter ended (\d{2}\.\d{2}\.\d{4})',
            r'year ended (\d{2}\.\d{2}\.\d{4})',
            r'period ended (\d{2}\.\d{2}\.\d{4})',
            r'q[1-4].*?(\d{4})',
            r'fy.*?(\d{4})'
        ]

        for pattern in period_patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                return match.group(1)

        return None

    @staticmethod
    def _extract_result_type(text: str) -> Optional[str]:
        """Extract result type (standalone/consolidated)"""
        if 'consolidated' in text:
            return 'consolidated'
        elif 'standalone' in text:
            return 'standalone'
        return None

    @staticmethod
    def _extract_financial_year(text: str) -> Optional[str]:
        """Extract financial year"""
        fy_pattern = r'fy.*?(\d{4})'
        match = re.search(fy_pattern, text, re.IGNORECASE)
        return match.group(1) if match else None

    @staticmethod
    def _extract_quarter(text: str) -> Optional[str]:
        """Extract quarter information"""
        quarter_patterns = [
            r'q([1-4])',
            r'quarter.*?([1-4])',
            r'first quarter',
            r'second quarter',
            r'third quarter',
            r'fourth quarter'
        ]

        for pattern in quarter_patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                if pattern in ['first quarter']:
                    return 'Q1'
                elif pattern in ['second quarter']:
                    return 'Q2'
                elif pattern in ['third quarter']:
                    return 'Q3'
                elif pattern in ['fourth quarter']:
                    return 'Q4'
                else:
                    return f"Q{match.group(1)}"

        return None

    @staticmethod
    def _extract_audit_status(text: str) -> Optional[str]:
        """Extract audit status"""
        if 'unaudited' in text:
            return 'unaudited'
        elif 'audited' in text:
            return 'audited'
        return None

    def save_financial_data(self, finance_data: List[Dict]) -> Path:
        """Save extracted financial data to JSON file"""
        if not finance_data:
            logger.warning("No financial data to save")
            return None

        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        output_file_path = self.cache_dir / f"financial_data_{timestamp}.json"

        with open(output_file_path, 'w') as file:
            json.dump(finance_data, file, indent=2, default=str)

        logger.info(f"Financial data saved to: {output_file_path}")
        return output_file_path

    def get_statistics(self) -> Dict:
        """Get processing statistics"""
        return dict(self.stats)

    def close(self):
        """Clean up resources"""
        self.session.close()
        logger.info("Financial processor session closed")

#!/usr/bin/env python3
"""
Financial Data Processor - PDF and XBRL Handler
Focuses on extracting structured data from BSE announcements
"""

import json
import logging
import os
import re
import tempfile
from datetime import datetime
from pathlib import Path
from io import BytesIO
from typing import Dict, List, Optional

import camelot
import warnings
import requests

from etl.minio_client import BSEPDFStorage
from database.database_manager import BSEDatabaseManager

warnings.filterwarnings("ignore", message="Cannot set non-stroke color.*")

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)
logging.getLogger("pdfminer").setLevel(logging.ERROR)
logging.getLogger("pdfminer.image").setLevel(logging.ERROR)

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
            'high_confidence': [
                'financial result',
                'quarterly result',
                'annual result',
                'half year results',
                'standalone financial',
                'consolidated financial',
                'unaudited financial',
                'audited financial'
            ],
            'medium_confidence': ['unaudited', 'audited', 'standalone', 'consolidated'],
            'board_keywords': [
                'board meeting',
                'consider and approve',
                'approval of financial',
                'results for the quarter',
                'results for the year'
            ],
            'document_markers': [
                'quarter ended',
                'year ended',
                'financial year',
                'fy ',
                'q1',
                'q2',
                'q3',
                'q4'
            ],
            'noise_terms': [
                'resignation',
                'esop',
                'allotment',
                'press release',
                'investor presentation',
                'agm',
                'egm',
                'scheme',
                'sast',
                'insider trading'
            ]
        }

        self.result_categories = {'Result', 'Results', 'Financial Result'}
        self.board_categories = {'Board Meeting'}
        self.support_categories = {'Company Update', 'Corp. Action', 'AGM/EGM'}

        self.stats = {
            'processed': 0,
            'financial_announcements': 0,
            'pdfs_downloaded': 0,
            'xbrl_found': 0,
            'extraction_successful': 0,
            'extraction_failed': 0
        }

        self.numeric_pattern = re.compile(r'-?\d[\d,]*(?:\.\d+)?')

        self.metric_patterns = {
            'revenue': [
                'total revenue',
                'total income',
                'net sales',
                'gross income'
            ],
            'total_debt': [
                'total debt',
                'total borrowings',
                'borrowings',
                'loan funds'
            ],
            'cash_equiv': [
                'cash and cash equivalents',
                'cash equivalents',
                'cash & bank balances',
                'cash and bank balances'
            ],
            'interest_income': [
                'interest income'
            ],
            'dividend_income': [
                'dividend income'
            ]
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
            subject_text = str(announcement.get('NEWSSUB', ''))
            subject = subject_text.lower()
            company = announcement.get('SLONGNAME', '')
            symbol = str(announcement.get('SCRIP_CD', ''))
            date = announcement.get('NEWS_DT') or announcement.get('DT_TM', '')
            attachment = announcement.get('ATTACHMENTNAME', '')
            year = date[:4] if len(date) >= 4 else ''
            month = date[5:7] if len(date) >= 7 else ''

            # Focus on financial announcements
            if self._is_financial_announcement(category, subject):
                self.stats['financial_announcements'] += 1

                processed_data = {
                    'symbol': symbol,
                    'company': company,
                    'category': category,
                    'subject': subject_text,
                    'date': db_client.parse_iso_datetime(date) if date else None,
                    'attachment_name': attachment,
                    'confidence': self._determine_confidence(category, subject),
                    'extracted_data': None,
                    'pdf_url': None,
                    'processing_status': 'pending'
                }

                # Try to extract financial data
                if attachment and processed_data['date']:
                    attachment_str = str(attachment)
                    is_absolute = attachment_str.lower().startswith('http')
                    pdf_url = attachment_str if is_absolute else f"{self.bse_attachment_live}/{attachment_str}"
                    processed_data['pdf_url'] = pdf_url

                    # Download and store PDF in MinIO
                    minio_path = self.pdf_storage.download_and_store_pdf(pdf_url, symbol, date)
                    if (not is_absolute and isinstance(minio_path, str) and
                            minio_path.lower() == "pdf moved"):
                        pdf_url = f"{self.bse_attachment_moved}/{attachment_str}"
                        minio_path = self.pdf_storage.download_and_store_pdf(pdf_url, symbol, date)

                    if minio_path:
                        processed_data['pdf_stored'] = True
                        logger.info(f"PDF stored in MinIO: {company} ({symbol})")
                    else:
                        processed_data['pdf_stored'] = False
                        logger.warning(f"Failed to store PDF: {company} ({symbol})")

                    processed_data['minio_path'] = minio_path
                    if processed_data['date']:
                        self.updated_pdf_status(
                            symbol, processed_data['date'], processed_data['minio_path'], processed_data['pdf_stored']
                        )

                    # Extract basic financial information from announcement text/PDF
                    extracted_info = self._extract_financial_info_from_text(announcement) or {}
                    numeric_metrics = self._get_or_extract_pdf_metrics(processed_data.get('minio_path'))
                    combined_data = {**extracted_info, **numeric_metrics} if numeric_metrics else extracted_info

                    if combined_data:
                        processed_data['extracted_data'] = combined_data
                        processed_data['processing_status'] = 'success'
                        self.stats['extraction_successful'] += 1
                        logger.info(f"Extracted financial data: {company} ({symbol})")
                    else:
                        processed_data['processing_status'] = 'no_data_found'
                        self.stats['extraction_failed'] += 1

                else:
                    processed_data['processing_status'] = 'no_attachment'

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
        if not subject:
            return False

        if category in self.result_categories:
            return True

        if category in self.board_categories:
            return (
                self._contains_keywords(subject, self.financial_keywords['board_keywords']) and
                self._contains_keywords(subject, self.financial_keywords['document_markers'])
            )

        if category in self.support_categories:
            return (
                self._contains_keywords(subject, self.financial_keywords['high_confidence']) and
                not self._contains_keywords(subject, self.financial_keywords['noise_terms'])
            )

        return (
            self._contains_keywords(subject, self.financial_keywords['high_confidence']) and
            not self._contains_keywords(subject, self.financial_keywords['noise_terms'])
        )

    def _contains_keywords(self, text: str, keywords: List[str]) -> bool:
        """Utility to check if any keyword is present in text"""
        return any(keyword in text for keyword in keywords)

    def _determine_confidence(self, category: str, subject: str) -> str:
        """Determine confidence level for financial data"""
        if category in self.result_categories:
            return 'HIGH'
        elif category in self.board_categories and self._contains_keywords(
                subject, self.financial_keywords['board_keywords']):
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
            r'quarter ended (\d{1,2}\s+\w+\s+\d{4})',
            r'half year ended (\d{1,2}\s+\w+\s+\d{4})',
            r'year ended (\d{1,2}\s+\w+\s+\d{4})',
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
        patterns = [
            r'fy\s*([0-9]{4}\s*-\s*[0-9]{2,4})',
            r'financial year\s*(\d{4}\s*-\s*\d{2,4})',
            r'fy\s*(\d{4})',
            r'financial year\s*(\d{4})'
        ]

        for pattern in patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                return match.group(1).replace(' ', '')

        return None

    @staticmethod
    def _extract_quarter(text: str) -> Optional[str]:
        """Extract quarter information"""
        quarter_match = re.search(r'\bq([1-4])\b', text, re.IGNORECASE)
        if quarter_match:
            return f"Q{quarter_match.group(1)}"

        number_match = re.search(r'quarter\s*(?:ended)?\s*(?:for)?\s*the\s*(first|second|third|fourth)', text,
                                 re.IGNORECASE)
        if number_match:
            mapping = {
                'first': 'Q1',
                'second': 'Q2',
                'third': 'Q3',
                'fourth': 'Q4'
            }
            return mapping.get(number_match.group(1).lower())

        half_match = re.search(r'half\s*year', text, re.IGNORECASE)
        if half_match:
            return 'H1'

        return None

    @staticmethod
    def _extract_audit_status(text: str) -> Optional[str]:
        """Extract audit status"""
        if 'unaudited' in text:
            return 'unaudited'
        elif 'audited' in text:
            return 'audited'
        return None

    def _get_or_extract_pdf_metrics(self, minio_path: Optional[str]) -> Dict[str, float]:
        """Download PDF from MinIO and extract numeric metrics using Camelot"""
        if not minio_path:
            return {}

        cache_key = f"metrics/{minio_path}.json"

        cached_metrics = self._fetch_cached_metrics(cache_key)
        if cached_metrics is not None:
            return cached_metrics

        temp_path = None
        try:
            with tempfile.NamedTemporaryFile(delete=False, suffix='.pdf') as tmp:
                temp_path = tmp.name

            self.pdf_storage.client.fget_object(
                self.pdf_storage.bucket_name,
                minio_path,
                temp_path
            )

            tables = self._read_pdf_tables(temp_path)
            if not tables:
                logger.info(f"No readable tables detected in {minio_path}")
                return {}

            metrics = {}

            for table in tables:
                table_df = getattr(table, 'df', None)
                if table_df is None:
                    continue

                try:
                    table_metrics = self._parse_table_for_metrics(table_df, metrics)
                    metrics.update(table_metrics)
                except Exception as table_err:
                    logger.debug(f"Table parsing skipped for {minio_path}: {table_err}")
                    continue

                if len(metrics) == len(self.metric_patterns):
                    break

            self._store_cached_metrics(cache_key, metrics)
            return metrics

        except Exception as e:
            logger.warning(f"PDF metric extraction failed for {minio_path}: {e}")
            return {}
        finally:
            if temp_path and os.path.exists(temp_path):
                os.remove(temp_path)

    def _parse_table_for_metrics(self, dataframe, existing_metrics: Dict[str, float]) -> Dict[str, float]:
        """Parse Camelot dataframe to capture financial metrics"""
        metrics = {}
        if dataframe.empty:
            return metrics

        header_rows = min(2, len(dataframe))
        header_text = ' '.join(
            ' '.join(str(cell) for cell in dataframe.iloc[i].tolist())
            for i in range(header_rows)
        ).lower()

        table_scale = self._detect_scale(header_text)

        for _, row in dataframe.iterrows():
            cells = [str(cell).strip() for cell in row.tolist() if str(cell).strip()]
            if not cells:
                continue

            row_text = ' '.join(cells).lower()
            value = self._extract_numeric_value(cells)
            if value is None:
                continue

            scale = table_scale if table_scale != 1.0 else self._detect_scale(row_text)
            scaled_value = value * scale

            for metric, keywords in self.metric_patterns.items():
                if metric in existing_metrics or metric in metrics:
                    continue
                if any(keyword in row_text for keyword in keywords):
                    metrics[metric] = scaled_value
                    break

            if len(metrics) + len(existing_metrics) == len(self.metric_patterns):
                break

        return metrics

    def _extract_numeric_value(self, cells: List[str]) -> Optional[float]:
        """Extract numeric value from table row cells"""
        for cell in reversed(cells):
            normalized = (
                cell.replace(',', '')
                    .replace('₹', '')
                    .replace('rs.', '')
                    .replace('Rs.', '')
                    .replace('−', '-')
            )
            match = self.numeric_pattern.search(normalized)
            if match:
                try:
                    return float(match.group(0))
                except ValueError:
                    continue
        return None

    @staticmethod
    def _detect_scale(text: str) -> float:
        """Detect numeric scale based on textual hints"""
        if not text:
            return 1.0

        text = text.lower()
        if 'crore' in text or 'cr' in text:
            return 10_000_000
        if 'billion' in text or 'bn' in text:
            return 1_000_000_000
        if 'million' in text or 'mn' in text:
            return 1_000_000
        if 'lakh' in text or 'lac' in text:
            return 100_000
        return 1.0

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
    def _read_pdf_tables(self, temp_path: str):
        """Attempt to read tables using Camelot with multiple strategies"""
        tables = []
        for flavor in ('stream', 'lattice'):
            try:
                with warnings.catch_warnings():
                    warnings.simplefilter("ignore", UserWarning)
                    result = camelot.read_pdf(
                        temp_path,
                        pages='all',
                        flavor=flavor,
                        suppress_stdout=True
                    )
                if result and result.n > 0:
                    tables.extend(result)
                    break
            except Exception as e:
                logger.debug(f"Camelot {flavor} parsing failed for {temp_path}: {e}")
                continue
        return tables

    def _fetch_cached_metrics(self, cache_key: str) -> Optional[Dict[str, float]]:
        """Fetch previously computed metrics from MinIO cache"""
        try:
            self.pdf_storage.client.stat_object(self.pdf_storage.bucket_name, cache_key)
            data = self.pdf_storage.client.get_object(self.pdf_storage.bucket_name, cache_key)
            try:
                content = data.read().decode('utf-8')
                return json.loads(content)
            finally:
                data.close()
                data.release_conn()
        except Exception:
            return None

    def _store_cached_metrics(self, cache_key: str, metrics: Dict[str, float]):
        """Store metrics in MinIO cache for reuse"""
        if not metrics:
            return

        payload = json.dumps(metrics).encode('utf-8')
        try:
            self.pdf_storage.client.put_object(
                bucket_name=self.pdf_storage.bucket_name,
                object_name=cache_key,
                data=BytesIO(payload),
                length=len(payload),
                content_type='application/json'
            )
        except Exception:
            logger.debug(f"Unable to cache metrics for {cache_key}")

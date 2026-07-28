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
from typing import Any, Dict, List, Optional

import warnings
import camelot
import requests
from pdfminer.high_level import extract_text
from lxml import etree

from etl.minio_client import BSEPDFStorage
from database.database_manager import BSEDatabaseManager

warnings.filterwarnings("ignore", message="Cannot set non-stroke color.*")

# `cryptography` is only a transitive dependency of the PDF stack and is used
# here purely to silence a deprecation warning. Importing it at module scope
# made it a hard requirement of the whole API, so a slim install without it
# could not even start.
try:
    from cryptography.utils import CryptographyDeprecationWarning
except ImportError:  # pragma: no cover - optional dependency
    pass
else:
    warnings.filterwarnings(
        "ignore",
        message="ARC4 has been moved to cryptography.hazmat.decrepit.ciphers.algorithms.ARC4",
        category=CryptographyDeprecationWarning,
    )

logger = logging.getLogger(__name__)
logging.getLogger("pdfminer").setLevel(logging.ERROR)
logging.getLogger("pdfminer.image").setLevel(logging.ERROR)


# noinspection PyTypeChecker
class FinancialDataProcessor:
    """Realistic processor for BSE financial announcements"""

    STRUCTURED_EXTENSIONS = {".xbrl", ".xml", ".json"}
    STRUCTURED_ALIASES = {
        'revenue': [
            'revenuefromoperations',
            'totalrevenue',
            'totalincome',
            'grossincome',
        ],
        'total_debt': [
            'borrowings',
            'totalloans',
            'securedloans',
            'unsecuredloans',
            'financialliabilities',
        ],
        'cash_equiv': [
            'cashandcashequivalents',
            'cashandbankbalances',
            'bankbalances',
        ],
        'interest_income': [
            'interestincome',
            'financeincome',
        ],
        'dividend_income': [
            'dividendincome',
        ],
        'accounts_receivable': [
            'tradereceivables',
            'receivablescurrent',
            'accountsreceivable',
            'sundrydebtors',
        ],
        'liquid_assets': [
            'currentassets',
            'netcurrentassets',
        ],
        'non_halal_income': [
            'nonpermissibleincome',
            'impermissibleincome',
            'haramincome',
        ],
    }

    def __init__(
        self,
        download_dir: str = "./downloads",
        cache_dir: str = "./cache",
        db_manager: Optional[BSEDatabaseManager] = None,
    ):
        self.download_dir = Path(download_dir)
        self.cache_dir = Path(cache_dir)
        self.download_dir.mkdir(exist_ok=True)
        self.cache_dir.mkdir(exist_ok=True)
        self.db = db_manager or BSEDatabaseManager()
        self.metric_cache_version = "v4"

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
                'gross income',
                'revenue from operations',
                'income from operations'
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
            ],
            'accounts_receivable': [
                'trade receivables',
                'accounts receivable',
                'sundry debtors',
                'bills receivable'
            ],
            'liquid_assets': [
                'liquid assets',
                'current assets',
                'net current assets',
                'cash and bank balances'
            ],
            'non_halal_income': [
                'non permissible income',
                'non-permissible income',
                'impermissible income',
                'haram income'
            ],
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
            more_text = str(announcement.get('MORE', ''))
            company = announcement.get('SLONGNAME', '')
            symbol = str(announcement.get('SCRIP_CD', ''))
            date = announcement.get('NEWS_DT') or announcement.get('DT_TM', '')
            attachment = announcement.get('ATTACHMENTNAME', '')
            year = date[:4] if len(date) >= 4 else ''
            month = date[5:7] if len(date) >= 7 else ''

            # Focus on financial announcements
            if self._is_financial_announcement(category, subject):
                self.stats['financial_announcements'] += 1

                scale_hint = self._detect_scale(f"{subject_text} {more_text}")

                processed_data = {
                    'symbol': symbol,
                    'company': company,
                    'category': category,
                    'subject': subject_text,
                    'date': self.db.parse_iso_datetime(date) if date else None,
                    'attachment_name': attachment,
                    'confidence': self._determine_confidence(category, subject),
                    'extracted_data': None,
                    'pdf_url': None,
                    'processing_status': 'pending',
                    'pdf_stored': False,
                    'minio_path': None,
                }

                # Try to extract financial data
                if attachment and processed_data['date']:
                    attachment_str = str(attachment)
                    is_absolute = attachment_str.lower().startswith('http')
                    pdf_url = attachment_str if is_absolute else f"{self.bse_attachment_live}/{attachment_str}"
                    processed_data['pdf_url'] = pdf_url
                    attachment_ext = Path(attachment_str.lower()).suffix
                    structured_metrics = {}
                    if attachment_ext in self.STRUCTURED_EXTENSIONS:
                        structured_metrics = self._extract_structured_data(pdf_url, scale_hint=scale_hint)
                        if structured_metrics:
                            self.stats['xbrl_found'] += 1
                            logger.info("Structured data extracted for %s (%s)", company, symbol)

                    numeric_metrics = {}
                    if attachment_ext not in self.STRUCTURED_EXTENSIONS:
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
                    if attachment_ext not in self.STRUCTURED_EXTENSIONS:
                        numeric_metrics = self._get_or_extract_pdf_metrics(
                            processed_data, scale_hint=scale_hint
                        )
                    combined_data: Dict[str, float] = {}
                    if extracted_info:
                        combined_data.update(extracted_info)
                    if numeric_metrics:
                        combined_data.update(numeric_metrics)
                    if structured_metrics:
                        combined_data.update(structured_metrics)

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
        logger.info(f"  Structured (XBRL/JSON) hits: {self.stats['xbrl_found']}")

        return finance_data

    def updated_pdf_status(self, symbol, filing_date, minio_path: str, pdf_stored: bool):
        """
        Update minio_path and pdf_stored status in BSE Announcements table

        Args:
            symbol: Financial announcements symbol
            filing_date: Financial announcements filing date
            minio_path: Path for PDF to minio bucket
            pdf_stored: Boolean flag to indicate whether the PDF stored successfully
        """
        with self.db.get_connection() as conn:
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

    def _get_or_extract_pdf_metrics(
        self, record: Dict, scale_hint: float = 1.0
    ) -> Dict[str, float]:
        """Download PDF from MinIO and extract numeric metrics using Camelot"""
        minio_path = record.get("minio_path")
        if not minio_path:
            return {}

        pdf_url = record.get("pdf_url")
        attachment_name = record.get("attachment_name")
        symbol = record.get("symbol")
        filing_date = record.get("date")
        confidence = record.get("confidence", "HIGH")

        cache_key = f"metrics/{self.metric_cache_version}/{minio_path}.json"

        cached_metrics = self._fetch_cached_metrics(cache_key)
        if cached_metrics is not None:
            return cached_metrics

        temp_path = None
        try:
            for refresh in range(2):
                with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
                    temp_path = tmp.name

                self.pdf_storage.client.fget_object(
                    self.pdf_storage.bucket_name,
                    minio_path,
                    temp_path
                )

                if not self._is_valid_pdf(temp_path):
                    os.remove(temp_path)
                    temp_path = None
                    refreshed = self._refresh_pdf(
                        minio_path,
                        pdf_url,
                        attachment_name,
                        symbol,
                        filing_date,
                        confidence,
                    )
                    if refreshed:
                        record["minio_path"] = refreshed
                        minio_path = refreshed
                        cache_key = (
                            f"metrics/{self.metric_cache_version}/{minio_path}.json"
                        )
                        continue
                    return {}
                break
            else:
                return {}

            try:
                text = extract_text(temp_path) or ""
            except Exception:
                text = ""
            text_scale = self._detect_scale(text)
            effective_hint = max(scale_hint, text_scale)
            governance_note = self._extract_governance_notes(text)
            non_halal_from_text = self._extract_non_halal_from_text(text)

            tables = self._read_pdf_tables(temp_path)
            if not tables:
                logger.info(f"No readable tables detected in {minio_path}")
                metrics = {}
                if governance_note:
                    metrics["governance_notes"] = governance_note
                if non_halal_from_text is not None:
                    metrics["non_halal_income"] = non_halal_from_text
                return metrics

            metrics = {}

            for table in tables:
                table_df = getattr(table, 'df', None)
                if table_df is None:
                    continue

                try:
                    table_metrics = self._parse_table_for_metrics(
                        table_df, metrics, scale_hint=effective_hint
                    )
                    metrics.update(table_metrics)
                except Exception as table_err:
                    logger.debug(f"Table parsing skipped for {minio_path}: {table_err}")
                    continue

                if len(metrics) == len(self.metric_patterns):
                    break

            if governance_note:
                metrics.setdefault("governance_notes", governance_note)
            if (
                non_halal_from_text is not None
                and not metrics.get("non_halal_income")
            ):
                metrics["non_halal_income"] = non_halal_from_text

            self._store_cached_metrics(cache_key, metrics)
            return metrics

        except Exception as e:
            logger.warning(f"PDF metric extraction failed for {minio_path}: {e}")
            return {}
        finally:
            if temp_path and os.path.exists(temp_path):
                os.remove(temp_path)

    def _extract_structured_data(
        self, attachment_url: str, scale_hint: float = 1.0
    ) -> Dict[str, float]:
        """Fetch and parse structured (XBRL/JSON) attachments."""

        if not attachment_url:
            return {}

        normalized_url = attachment_url.lower()
        if not any(normalized_url.endswith(ext) for ext in self.STRUCTURED_EXTENSIONS):
            return {}

        try:
            response = self.session.get(attachment_url, timeout=30)
            response.raise_for_status()
        except Exception as exc:
            logger.warning("Structured attachment download failed (%s): %s", attachment_url, exc)
            return {}

        try:
            if normalized_url.endswith(".json"):
                payload = response.json()
                return self._parse_structured_json(payload, scale_hint)
            return self._parse_xbrl(response.content, scale_hint)
        except Exception as exc:
            logger.warning("Structured attachment parse failed (%s): %s", attachment_url, exc)
            return {}

    def _parse_table_for_metrics(
        self, dataframe, existing_metrics: Dict[str, float], scale_hint: float = 1.0
    ) -> Dict[str, float]:
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
            value, value_scale = self._extract_numeric_value(cells)
            if value is None:
                continue

            row_scale = self._detect_scale(row_text)
            effective_scale = max(scale_hint, table_scale, row_scale, value_scale)
            scale = effective_scale if effective_scale > 1.0 else 1.0
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

    def _extract_numeric_value(self, cells: List[str]) -> tuple[Optional[float], float]:
        """Extract numeric value and scale hints from table row cells"""
        detected_scale = 1.0
        for cell in reversed(cells):
            normalized = (
                cell.replace(',', "")
                .replace("₹", "")
                .replace("rs.", "")
                .replace("Rs.", "")
                .replace("−", "-")
            )
            cell_scale = self._detect_scale(cell)
            if cell_scale > 1.0:
                detected_scale = max(detected_scale, cell_scale)
            match = self.numeric_pattern.search(normalized)
            if match:
                try:
                    return float(match.group(0)), detected_scale
                except ValueError:
                    continue
        return None, detected_scale

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
        if 'thousand' in text or 'k ' in text:
            return 1_000
        return 1.0

    @staticmethod
    def _scale_from_unit(unit: str) -> float:
        key = (unit or "").strip().lower()
        mapping = {
            "crore": 10_000_000,
            "cr": 10_000_000,
            "million": 1_000_000,
            "mn": 1_000_000,
            "billion": 1_000_000_000,
            "bn": 1_000_000_000,
            "lakh": 100_000,
            "lac": 100_000,
            "thousand": 1_000,
            "k": 1_000,
        }
        return mapping.get(key, 1.0)

    @classmethod
    def _extract_non_halal_from_text(cls, text: str) -> Optional[float]:
        if not text:
            return None
        pattern = re.compile(
            r"(non[\s-]?permissible income|impermissible income|haram income|prohibited income|interest income)"
            r"(?:(?:fy\s*\d{2,4})|(?:q\d+\s*fy\s*\d{2,4})|[^\d])*?"
            r"(?:inr|rs\.?|₹)?\s*([\d,]+(?:\.\d+)?)\s*(crore|cr|million|mn|billion|bn|lakh|lac|thousand|k)?",
            re.IGNORECASE,
        )
        matches = list(pattern.finditer(text))
        if not matches:
            return None
        selected = None
        for match in matches:
            snippet = match.group(0).lower()
            if "inr" in snippet or "rs" in snippet or "₹" in snippet:
                selected = match
                break
        if selected is None:
            selected = matches[-1]
        raw_value = selected.group(2).replace(",", "")
        try:
            value = float(raw_value)
        except ValueError:
            return None
        unit = selected.group(3) or ""
        scale = cls._scale_from_unit(unit)
        if scale > 1:
            return value * scale
        surrounding = selected.group(0)
        inferred_scale = cls._detect_scale(surrounding)
        return value * max(1.0, inferred_scale)

    @staticmethod
    def _extract_governance_notes(text: str) -> Optional[str]:
        if not text:
            return None
        keywords = [
            "non permissible",
            "non-permissible",
            "impermissible",
            "haram",
            "shariah",
            "cleansing",
            "charity",
            "donate",
            "prohibited income",
        ]
        sentences = re.split(r"(?<=[\.\?\!])\s+", text)
        priority = {"non permissible", "non-permissible", "impermissible", "haram"}
        for sentence in sentences:
            normalized = sentence.lower()
            if any(word in normalized for word in priority):
                snippet = " ".join(sentence.split())
                return snippet[:320]
        for sentence in sentences:
            normalized = sentence.lower()
            if any(keyword in normalized for keyword in keywords):
                snippet = " ".join(sentence.split())
                return snippet[:320]
        return None

    @classmethod
    def _parse_xbrl(cls, payload: bytes, scale_hint: float = 1.0) -> Dict[str, float]:
        metrics: Dict[str, float] = {}
        if not payload:
            return metrics
        try:
            root = etree.fromstring(payload)
        except Exception as exc:
            logger.warning("Invalid XBRL payload: %s", exc)
            return metrics

        for element in root.iter():
            try:
                tag = etree.QName(element).localname
            except Exception:
                tag = element.tag
            normalized = cls._normalize_tag(tag)
            metric = cls._match_structured_metric(normalized)
            if not metric or metric in metrics:
                continue
            numeric = cls._coerce_numeric(element.text)
            if numeric is None:
                continue
            metrics[metric] = cls._apply_structured_scale(numeric, scale_hint)
        return metrics

    @classmethod
    def _parse_structured_json(cls, payload, scale_hint: float = 1.0) -> Dict[str, float]:
        metrics: Dict[str, float] = {}

        def walk(node, prefix: str = ""):
            if isinstance(node, dict):
                for key, value in node.items():
                    combined = f"{prefix}_{key}" if prefix else str(key)
                    if isinstance(value, (dict, list)):
                        walk(value, combined)
                    else:
                        normalized = cls._normalize_tag(combined)
                        metric = cls._match_structured_metric(normalized)
                        if not metric or metric in metrics:
                            continue
                        numeric = cls._coerce_numeric(value)
                        if numeric is None:
                            continue
                        metrics[metric] = cls._apply_structured_scale(numeric, scale_hint)
            elif isinstance(node, list):
                for item in node:
                    walk(item, prefix)

        walk(payload)
        return metrics

    @staticmethod
    def _normalize_tag(name: str) -> str:
        return re.sub(r"[^a-z0-9]", "", (name or "").lower())

    @classmethod
    def _match_structured_metric(cls, normalized_tag: str) -> Optional[str]:
        if not normalized_tag:
            return None
        for metric, aliases in cls.STRUCTURED_ALIASES.items():
            if any(alias in normalized_tag for alias in aliases):
                return metric
        return None

    @staticmethod
    def _coerce_numeric(value: Any) -> Optional[float]:
        if value is None:
            return None
        if isinstance(value, (int, float)):
            return float(value)
        text = str(value).strip()
        if not text:
            return None
        normalized = text.replace(",", "")
        try:
            return float(normalized)
        except ValueError:
            return None

    @staticmethod
    def _apply_structured_scale(value: float, scale_hint: float) -> float:
        if scale_hint and scale_hint > 1.0:
            return value * scale_hint
        return value

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

    @staticmethod
    def _is_valid_pdf(path: str) -> bool:
        try:
            with open(path, "rb") as handle:
                return handle.read(4).startswith(b"%PDF")
        except Exception:
            return False

    def _refresh_pdf(
        self,
        minio_path: str,
        pdf_url: Optional[str],
        attachment_name: Optional[str],
        symbol: Optional[str],
        filing_date: Optional[datetime],
        confidence: str,
    ) -> Optional[str]:
        """Force refresh the PDF from BSE when cached copy is invalid."""

        if not pdf_url or not symbol or not filing_date:
            return None

        if isinstance(filing_date, datetime):
            filing_iso = filing_date.isoformat()
        else:
            filing_iso = str(filing_date)

        refreshed = self.pdf_storage.download_and_store_pdf(
            pdf_url,
            symbol,
            filing_iso,
            confidence=confidence,
            force=True,
        )

        if isinstance(refreshed, str) and refreshed.lower() == "pdf moved":
            if attachment_name:
                moved_url = (
                    attachment_name
                    if attachment_name.lower().startswith("http")
                    else f"{self.bse_attachment_moved}/{attachment_name}"
                )
                refreshed = self.pdf_storage.download_and_store_pdf(
                    moved_url,
                    symbol,
                    filing_iso,
                    confidence=confidence,
                    force=True,
                )

        if not refreshed or (
            isinstance(refreshed, str) and refreshed.lower() == "pdf moved"
        ):
            return None

        logger.info("Refreshed PDF for %s (%s)", symbol, minio_path)
        return refreshed

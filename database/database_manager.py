#!/usr/bin/env python3
"""
PostgreSQL Database Integration for BSE Financial Data Crawler
=============================================================

Handles all database operations for announcements and financial snapshots
with proper connection pooling, error handling, and transaction management.
"""

import logging
import re
from contextlib import contextmanager
from datetime import datetime, timezone, date
from typing import Dict, List, Optional

import pandas as pd
import psycopg2
from psycopg2 import pool
from psycopg2.extras import RealDictCursor, Json

from config import (
    POSTGRES_HOST,
    POSTGRES_PORT,
    POSTGRES_DB,
    POSTGRES_USER,
    POSTGRES_PASSWORD
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class BSEDatabaseManager:
    """Production-ready PostgreSQL integration for BSE financial data"""

    def __init__(self,
                 host: str = "localhost",
                 port: int = 5432,
                 database: str = "Halal-Lens",
                 user: str = None,
                 password: str = None,
                 min_connections: int = 2,
                 max_connections: int = 20):

        self.connection_params = {
            'host': host or POSTGRES_HOST,
            'port': port or POSTGRES_PORT,
            'database': database or POSTGRES_DB,
            'user': user or POSTGRES_USER,
            'password': password or POSTGRES_PASSWORD,
            'cursor_factory': RealDictCursor
        }

        # Initialize connection pool
        try:
            self.connection_pool = psycopg2.pool.ThreadedConnectionPool(
                min_connections,
                max_connections,
                **self.connection_params
            )
            logger.info(f"Database connection pool initialized ({min_connections}-{max_connections} connections)")

            # Test connection
            with self.get_connection() as conn:
                with conn.cursor() as cursor:
                    cursor.execute("SELECT version();")
                    version = cursor.fetchone()
                    logger.info(f"Connected to PostgreSQL: {version['version'][:50]}...")

        except Exception as e:
            logger.error(f"Database connection failed: {e}")
            raise

        self.stats = {
            'announcements_inserted': 0,
            'announcements_updated': 0,
            'snapshots_inserted': 0,
            'snapshots_updated': 0,
            'errors': 0
        }

    @contextmanager
    def get_connection(self):
        """Get database connection from pool with automatic cleanup"""
        conn = None
        try:
            conn = self.connection_pool.getconn()
            yield conn
        except Exception as e:
            if conn:
                conn.rollback()
            logger.error(f"Database operation failed: {e}")
            raise
        finally:
            if conn:
                self.connection_pool.putconn(conn)

    def insert_announcements(self, announcements_data: List[Dict]) -> int:
        """
        Insert or update announcements data in bulk

        Args:
            announcements_data: List of announcement dictionaries

        Returns:
            Number of records processed
        """
        if not announcements_data:
            logger.warning("No announcements data to insert")
            return 0

        processed_count = 0

        with self.get_connection() as conn:
            with conn.cursor() as cursor:
                try:
                    for announcement in announcements_data:
                        # Prepare data for insertion
                        insert_data = self._prepare_announcement_data(announcement)

                        # Use ON CONFLICT to handle duplicates
                        insert_query = """
                        INSERT INTO announcements (
                            symbol, company_name, filing_date, category, headline,
                            confidence, raw_json, minio_path, pdf_stored
                        ) VALUES (
                            %(symbol)s, %(company_name)s, %(filing_date)s, %(category)s, %(headline)s,
                            %(confidence)s, %(raw_json)s, %(minio_path)s, %(pdf_stored)s
                        ) ON CONFLICT (symbol, filing_date) 
                        DO UPDATE SET
                            company_name = EXCLUDED.company_name,
                            category = EXCLUDED.category,
                            headline = EXCLUDED.headline,
                            confidence = EXCLUDED.confidence,
                            raw_json = EXCLUDED.raw_json,
                            minio_path = EXCLUDED.minio_path,
                            pdf_stored = EXCLUDED.pdf_stored
                        """

                        cursor.execute(insert_query, insert_data)

                        if cursor.rowcount == 1:
                            self.stats['announcements_inserted'] += 1
                        else:
                            self.stats['announcements_updated'] += 1

                        processed_count += 1

                    conn.commit()
                    logger.info(f"Successfully processed {processed_count} announcements")

                except Exception as e:
                    conn.rollback()
                    self.stats['errors'] += 1
                    logger.error(f"Failed to insert announcements: {e}")
                    raise

        return processed_count

    def insert_financial_snapshots(self, snapshots_data: List[Dict]) -> int:
        """
        Insert or update financial snapshots data

        Args:
            snapshots_data: List of financial snapshot dictionaries

        Returns:
            Number of records processed
        """
        if not snapshots_data:
            logger.warning("No financial snapshots to insert")
            return 0

        processed_count = 0

        with self.get_connection() as conn:
            with conn.cursor() as cursor:
                try:
                    for snapshot in snapshots_data:
                        # Prepare data for insertion
                        insert_data = self._prepare_snapshot_data(snapshot)

                        # Only insert if corresponding announcement exists
                        check_query = """
                                      SELECT 1 as alias
                                      FROM announcements
                                      WHERE symbol = %(symbol)s
                                        AND filing_date = %(filing_date)s \
                                      """
                        cursor.execute(check_query, {
                            'symbol': insert_data['symbol'],
                            'filing_date': insert_data['filing_date']
                        })

                        if not cursor.fetchone():
                            logger.warning(
                                f"No announcement found for snapshot: {insert_data['symbol']} "
                                f"on {insert_data['filing_date']}"
                            )
                            continue

                        # Insert or update snapshot
                        insert_query = """
                        INSERT INTO financial_snapshots (
                            symbol, filing_date, fy_end, quarter, audit_status,
                            total_debt, cash_equiv, revenue, interest_income, dividend_income
                        ) VALUES (
                            %(symbol)s, %(filing_date)s, %(fy_end)s, %(quarter)s, %(audit_status)s,
                            %(total_debt)s, %(cash_equiv)s, %(revenue)s, %(interest_income)s, %(dividend_income)s
                        ) ON CONFLICT (symbol, filing_date)
                        DO UPDATE SET
                            fy_end = EXCLUDED.fy_end,
                            quarter = EXCLUDED.quarter,
                            audit_status = EXCLUDED.audit_status,
                            total_debt = EXCLUDED.total_debt,
                            cash_equiv = EXCLUDED.cash_equiv,
                            revenue = EXCLUDED.revenue,
                            interest_income = EXCLUDED.interest_income,
                            dividend_income = EXCLUDED.dividend_income,
                            parsed_at = now()
                        """

                        cursor.execute(insert_query, insert_data)

                        if cursor.rowcount == 1:
                            self.stats['snapshots_inserted'] += 1
                        else:
                            self.stats['snapshots_updated'] += 1

                        processed_count += 1

                    conn.commit()
                    logger.info(f"Successfully processed {processed_count} financial snapshots")

                except Exception as e:
                    conn.rollback()
                    self.stats['errors'] += 1
                    logger.error(f"Failed to insert financial snapshots: {e}")
                    raise

        return processed_count

    @staticmethod
    def parse_iso_datetime(dt_str: str) -> datetime:
        """
        Parse an ISO datetime string.
        """
        # Normalize fractional seconds to 6 digits for microseconds if present
        # Match fractional seconds and pad/truncate as needed
        m = re.match(r'(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})(\.\d+)?', dt_str)
        if not m:
            # fallback parse
            return datetime.strptime(dt_str, '%Y-%m-%dT%H:%M:%S').replace(tzinfo=timezone.utc)

        base = m.group(1)
        frac = m.group(2) or ''
        if frac:
            # Remove the dot and pad/truncate to 6 digits
            frac_digits = frac[1:]  # strip the dot
            frac_digits_padded = (frac_digits + '000000')[:6]
            normalized = f"{base}.{frac_digits_padded}"
        else:
            normalized = base

        return datetime.fromisoformat(normalized).replace(tzinfo=timezone.utc)

    def _prepare_announcement_data(self, announcement: Dict) -> Optional[Dict]:
        """Prepare announcement data for database insertion"""
        try:
            # Handle filing_date conversion
            symbol = str(announcement.get("SCRIP_CD") or '').strip()
            filing_date = announcement.get('NEWS_DT') or announcement.get('DT_TM')

            # ── SKIP rows that break the NOT-NULL PK ─────────────────────
            if not symbol or not filing_date:
                logger.warning("Skipping: missing symbol/filing_date NEWSID=%s",
                               announcement.get("NEWSID"))
                return None
            # ─────────────────────────────────────────────────────────────

            if isinstance(filing_date, str):
                # Parse ISO format with timezone
                try:
                    filing_date = self.parse_iso_datetime(filing_date)
                except Exception as e:
                    logger.error(f"Failed parsing filing_date '{filing_date}': {e}")
                    raise

            if announcement.get("CATEGORYNAME") == "Result":
                confidence = "HIGH"
            elif announcement.get("CATEGORYNAME") == "Board Meeting":
                confidence = "MEDIUM"
            else:
                confidence = "LOW"

            return {
                'symbol': symbol,
                'company_name': (announcement.get("SLONGNAME") or "").strip(),
                'filing_date': filing_date,
                'category': (announcement.get("CATEGORYNAME") or "").strip(),
                'headline': announcement.get("NEWSSUB", "")[:600],
                'confidence': confidence,
                'raw_json': Json(announcement),  # Store complete original data
                'minio_path': announcement.get('minio_path', None),
                'pdf_stored': announcement.get('pdf_stored', False)
            }
        except Exception as e:
            logger.error(f"Error preparing announcement data: {e}")
            logger.error(f"Problematic data: {announcement}")
            raise

    def _prepare_snapshot_data(self, snapshot: Dict) -> Dict:
        """Prepare financial snapshot data for database insertion"""
        try:
            # Handle filing_date conversion
            filing_date = snapshot.get('date') or snapshot.get('filing_date')
            if isinstance(filing_date, str):
                # Parse ISO format with timezone
                try:
                    filing_date = self.parse_iso_datetime(filing_date)
                except Exception as e:
                    logger.error(f"Failed parsing filing_date '{filing_date}': {e}")
                    raise

            # Extract financial data from extracted_data field if present
            extracted_data = snapshot.get('extracted_data', {}) or {}

            return {
                'symbol': str(snapshot.get('symbol', '')),
                'filing_date': filing_date,
                'fy_end': self._parse_fy_end(extracted_data.get('period')),
                'quarter': extracted_data.get('quarter'),
                'audit_status': extracted_data.get('audit_status'),
                'total_debt': extracted_data.get('total_debt'),
                'cash_equiv': extracted_data.get('cash_equiv'),
                'revenue': extracted_data.get('revenue'),
                'interest_income': extracted_data.get('interest_income'),
                'dividend_income': extracted_data.get('dividend_income')
            }
        except Exception as e:
            logger.error(f"Error preparing snapshot data: {e}")
            logger.error(f"Problematic data: {snapshot}")
            raise

    @staticmethod
    def _parse_fy_end(period_str: Optional[str]) -> Optional[date]:
        """Parse fiscal year-end date from period string"""
        if not period_str:
            return None

        try:
            # Handle common formats like "31.03.2025"
            if '.' in period_str:
                return datetime.strptime(period_str, '%d.%m.%Y').date()
            # Handle other formats as needed
            return None
        except Exception as e:
            logger.error(f"Error parsing fiscal year-end date: {e}")
            return None

    def get_latest_announcements(self, limit: int = 100, confidence: str = None) -> List[Dict]:
        """Retrieve recent announcements from database"""
        with self.get_connection() as conn:
            with conn.cursor() as cursor:
                query = """
                SELECT symbol, company_name, filing_date, category, headline,
                       confidence, minio_path, pdf_stored
                FROM announcements
                """
                params = {}

                if confidence:
                    query += " WHERE confidence = %(confidence)s"
                    params['confidence'] = confidence

                query += " ORDER BY filing_date DESC LIMIT %(limit)s"
                params['limit'] = limit

                cursor.execute(query, params)
                return [dict(row) for row in cursor.fetchall()]

    def get_financial_data(self, symbol: str = None, limit: int = 50) -> List[Dict]:
        """Retrieve financial snapshots with announcement data"""
        with self.get_connection() as conn:
            with conn.cursor() as cursor:
                query = """
                SELECT a.symbol, a.company_name, a.filing_date, a.category,
                       f.quarter, f.audit_status, f.fy_end,
                       f.total_debt, f.cash_equiv, f.revenue,
                       f.interest_income, f.dividend_income
                FROM announcements a
                JOIN financial_snapshots f ON a.symbol = f.symbol AND a.filing_date = f.filing_date
                """
                params = {}

                if symbol:
                    query += " WHERE a.symbol = %(symbol)s"
                    params['symbol'] = symbol

                query += " ORDER BY a.filing_date DESC LIMIT %(limit)s"
                params['limit'] = limit

                cursor.execute(query, params)
                return [dict(row) for row in cursor.fetchall()]

    def get_database_stats(self) -> Dict:
        """Get comprehensive database statistics"""
        with self.get_connection() as conn:
            with conn.cursor() as cursor:
                statistics = {}

                # Announcements statistics
                cursor.execute("""
                SELECT 
                    COUNT(*) as total_announcements,
                    COUNT(*) FILTER (WHERE confidence = 'HIGH') as high_confidence,
                    COUNT(*) FILTER (WHERE pdf_stored = true) as pdfs_stored,
                    MAX(filing_date) as latest_filing,
                    COUNT(DISTINCT symbol) as unique_companies
                FROM announcements
                """)
                statistics.update(dict(cursor.fetchone()))

                # Financial snapshots statistics
                cursor.execute("""
                SELECT 
                    COUNT(*) as financial_snapshots,
                    COUNT(*) FILTER (WHERE total_debt IS NOT NULL) as with_debt_data,
                    COUNT(*) FILTER (WHERE revenue IS NOT NULL) as with_revenue_data,
                    COUNT(DISTINCT quarter) as quarters_covered
                FROM financial_snapshots
                """)
                statistics.update(dict(cursor.fetchone()))

                return statistics

    def export_to_dataframe(self, table: str = 'announcements', limit: int = None) -> pd.DataFrame:
        """Export table data to pandas DataFrame for analysis"""
        with self.get_connection() as conn:
            query = f"SELECT * FROM {table}"
            if limit:
                query += f" LIMIT {limit}"

            return pd.read_sql_query(query, conn)

    def get_statistics(self) -> Dict:
        """Get processing statistics"""
        return dict(self.stats)

    def close(self):
        """Close all database connections"""
        if hasattr(self, 'connection_pool'):
            self.connection_pool.closeall()
        logger.info("Database connections closed")


# Test the database manager
if __name__ == "__main__":
    # Initialize database manager
    db_manager = BSEDatabaseManager()

    try:
        # Test basic operations
        print("✅ Database connection established")

        # Get database statistics
        stats = db_manager.get_database_stats()
        print(f"📊 Database Statistics: {stats}")

        # Get recent announcements
        recent = db_manager.get_latest_announcements(limit=5)
        print(f"📈 Recent announcements: {len(recent)}")

        # Processing statistics
        process_stats = db_manager.get_statistics()
        print(f"⚙️ Processing Statistics: {process_stats}")

    finally:
        db_manager.close()

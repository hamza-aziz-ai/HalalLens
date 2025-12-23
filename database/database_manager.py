#!/usr/bin/env python3
"""
PostgreSQL Database Integration for BSE Financial Data Crawler
=============================================================

Handles all database operations for announcements and financial snapshots
with proper connection pooling, error handling, and transaction management.
"""

import logging
import json
from contextlib import contextmanager
from datetime import datetime, date, timezone
from typing import Dict, List, Optional, Tuple

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
from utils.datetime_parser import parse_bse_datetime

logger = logging.getLogger(__name__)


class BSEDatabaseManager:
    """Production-ready PostgreSQL integration for BSE financial data"""

    def __init__(self,
                 host: Optional[str] = None,
                 port: Optional[int] = None,
                 database: Optional[str] = None,
                 user: Optional[str] = None,
                 password: Optional[str] = None,
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
                    insert_query = """
                    INSERT INTO announcements (
                        symbol, symbol_alias, company_name, filing_date, category, headline,
                        confidence, raw_json, minio_path, pdf_stored
                    ) VALUES (
                        %(symbol)s, %(symbol_alias)s, %(company_name)s, %(filing_date)s, %(category)s, %(headline)s,
                        %(confidence)s, %(raw_json)s, %(minio_path)s, %(pdf_stored)s
                    ) ON CONFLICT (symbol, filing_date) 
                    DO UPDATE SET
                        symbol_alias = EXCLUDED.symbol_alias,
                        company_name = EXCLUDED.company_name,
                        category = EXCLUDED.category,
                        headline = EXCLUDED.headline,
                        confidence = EXCLUDED.confidence,
                        raw_json = EXCLUDED.raw_json,
                        minio_path = EXCLUDED.minio_path,
                        pdf_stored = EXCLUDED.pdf_stored
                    """
                    for announcement in announcements_data:
                        insert_data = self._prepare_announcement_data(announcement)
                        if not insert_data:
                            continue
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
                            total_debt, cash_equiv, revenue, interest_income, dividend_income,
                            accounts_receivable, liquid_assets, non_halal_income, governance_notes
                        ) VALUES (
                            %(symbol)s, %(filing_date)s, %(fy_end)s, %(quarter)s, %(audit_status)s,
                            %(total_debt)s, %(cash_equiv)s, %(revenue)s, %(interest_income)s, %(dividend_income)s,
                            %(accounts_receivable)s, %(liquid_assets)s, %(non_halal_income)s, %(governance_notes)s
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
                            accounts_receivable = EXCLUDED.accounts_receivable,
                            liquid_assets = EXCLUDED.liquid_assets,
                            non_halal_income = EXCLUDED.non_halal_income,
                            governance_notes = EXCLUDED.governance_notes,
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

    def insert_market_snapshot(
        self,
        symbol: str,
        market_cap: Optional[float],
        share_price: Optional[float],
        provider: str = "yahoo",
    ) -> None:
        """Store a point-in-time market data snapshot."""

        if market_cap is None and share_price is None:
            return

        with self.get_connection() as conn:
            with conn.cursor() as cursor:
                try:
                    cursor.execute(
                        """
                        INSERT INTO market_data_snapshots (symbol, market_cap, share_price, provider)
                        VALUES (%(symbol)s, %(market_cap)s, %(share_price)s, %(provider)s)
                        """,
                        {
                            "symbol": symbol,
                            "market_cap": market_cap,
                            "share_price": share_price,
                            "provider": provider,
                        },
                    )
                    conn.commit()
                except Exception as exc:
                    conn.rollback()
                    logger.warning(
                        "Failed to insert market snapshot for %s: %s", symbol, exc
                    )

    def insert_indianapi_snapshot(
        self,
        *,
        symbol: str,
        symbol_alias: Optional[str],
        company_name: Optional[str],
        snapshot_date: Optional[date],
        payload: Dict,
    ) -> None:
        """Archive raw Indian API responses for historical analysis."""

        if not payload:
            return

        with self.get_connection() as conn:
            with conn.cursor() as cursor:
                try:
                    cursor.execute(
                        """
                        INSERT INTO indianapi_snapshots (
                            symbol, symbol_alias, company_name, snapshot_date, payload
                        )
                        VALUES (%(symbol)s, %(symbol_alias)s, %(company_name)s, %(snapshot_date)s, %(payload)s)
                        ON CONFLICT (symbol, snapshot_date)
                        DO UPDATE SET
                            symbol_alias = EXCLUDED.symbol_alias,
                            company_name = EXCLUDED.company_name,
                            payload = EXCLUDED.payload,
                            fetched_at = NOW()
                        """,
                        {
                            "symbol": symbol,
                            "symbol_alias": symbol_alias,
                            "company_name": company_name,
                            "snapshot_date": snapshot_date,
                            "payload": Json(payload),
                        },
                    )
                    conn.commit()
                except Exception as exc:  # pragma: no cover - logging path
                    conn.rollback()
                    logger.warning(
                        "Failed to insert Indian API snapshot for %s: %s", symbol, exc
                    )

    def get_cached_market_data(
        self, symbol: str, as_of: Optional[datetime] = None
    ) -> Optional[Tuple[Optional[float], Optional[float]]]:
        """Return the most recent market snapshot for a symbol."""

        with self.get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT market_cap, share_price, provider
                    FROM market_data_snapshots
                    WHERE symbol = %(symbol)s
                      AND (%(as_of)s IS NULL OR captured_at <= %(as_of)s)
                    ORDER BY captured_at DESC
                    LIMIT 1
                    """,
                    {"symbol": symbol, "as_of": as_of},
                )
                row = cursor.fetchone()
                if not row:
                    return None
                return row["market_cap"], row["share_price"], row.get("provider")

    def upsert_bhavcopy_quote(
        self,
        *,
        symbol: str,
        trade_date: date,
        share_price: Optional[float],
        market_cap: Optional[float],
        provider: str = "bhavcopy",
    ) -> None:
        """Persist Bhavcopy-derived quote data for reuse."""

        if share_price is None and market_cap is None:
            return

        with self.get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO bhavcopy_quotes (
                        symbol, trade_date, share_price, market_cap, provider
                    )
                    VALUES (%(symbol)s, %(trade_date)s, %(share_price)s, %(market_cap)s, %(provider)s)
                    ON CONFLICT (symbol, trade_date)
                    DO UPDATE SET
                        share_price = COALESCE(EXCLUDED.share_price, bhavcopy_quotes.share_price),
                        market_cap = COALESCE(EXCLUDED.market_cap, bhavcopy_quotes.market_cap),
                        provider = EXCLUDED.provider,
                        created_at = NOW()
                    """,
                    {
                        "symbol": symbol,
                        "trade_date": trade_date,
                        "share_price": share_price,
                        "market_cap": market_cap,
                        "provider": provider,
                    },
                )
                conn.commit()

    def get_bhavcopy_quote(
        self, symbol: str, trade_date: date
    ) -> Optional[Tuple[Optional[float], Optional[float], Optional[str]]]:
        """Return a cached Bhavcopy quote for a specific trade date."""

        with self.get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT share_price, market_cap, provider
                      FROM bhavcopy_quotes
                     WHERE symbol = %(symbol)s
                       AND trade_date = %(trade_date)s
                    """,
                    {"symbol": symbol, "trade_date": trade_date},
                )
                row = cursor.fetchone()
                if not row:
                    return None
                return row["market_cap"], row["share_price"], row.get("provider")

    def upsert_filing_evaluation(
        self,
        *,
        symbol: str,
        filing_date: datetime,
        is_compliant: Optional[bool],
        ratios: Dict,
        summary: str,
        verdict: str,
        narration_source: str,
        market_cap_used: Optional[float],
        trailing_cap_used: Optional[float],
        market_data_provider: Optional[str] = None,
    ) -> None:
        """Persist computed ratio evaluations for a filing."""

        with self.get_connection() as conn:
            with conn.cursor() as cursor:
                try:
                    cursor.execute(
                        """
                        INSERT INTO filing_evaluations (
                            symbol,
                            filing_date,
                            is_compliant,
                            ratios,
                            summary,
                            verdict,
                            narration_source,
                            market_cap_used,
                            trailing_cap_used,
                            market_data_provider
                        )
                        VALUES (
                            %(symbol)s,
                            %(filing_date)s,
                            %(is_compliant)s,
                            %(ratios)s,
                            %(summary)s,
                            %(verdict)s,
                            %(narration_source)s,
                            %(market_cap_used)s,
                            %(trailing_cap_used)s,
                            %(market_data_provider)s
                        )
                        ON CONFLICT (symbol, filing_date)
                        DO UPDATE SET
                            is_compliant = EXCLUDED.is_compliant,
                            ratios = EXCLUDED.ratios,
                            summary = EXCLUDED.summary,
                            verdict = EXCLUDED.verdict,
                            narration_source = EXCLUDED.narration_source,
                            market_cap_used = EXCLUDED.market_cap_used,
                            trailing_cap_used = EXCLUDED.trailing_cap_used,
                            market_data_provider = EXCLUDED.market_data_provider,
                            evaluated_at = NOW()
                        """,
                        {
                            "symbol": symbol,
                            "filing_date": filing_date,
                            "is_compliant": is_compliant,
                            "ratios": Json(ratios),
                            "summary": summary,
                            "verdict": verdict,
                            "narration_source": narration_source,
                            "market_cap_used": market_cap_used,
                            "trailing_cap_used": trailing_cap_used,
                            "market_data_provider": market_data_provider,
                        },
                    )
                    conn.commit()
                except Exception as exc:
                    conn.rollback()
                    logger.error(
                        "Failed to upsert filing evaluation for %s@%s: %s",
                        symbol,
                        filing_date,
                        exc,
                    )
                    raise

    def record_quality_issue(
        self, symbol: str, filing_date: datetime, issue_type: str, details: str
    ) -> None:
        """Persist or update a data-quality issue for a filing."""

        with self.get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO data_quality_issues (
                        symbol, filing_date, issue_type, details
                    ) VALUES (%(symbol)s, %(filing_date)s, %(issue_type)s, %(details)s)
                    ON CONFLICT (symbol, filing_date, issue_type)
                    DO UPDATE SET
                        details = EXCLUDED.details,
                        resolved_at = NULL,
                        created_at = NOW()
                    """,
                    {
                        "symbol": symbol,
                        "filing_date": filing_date,
                        "issue_type": issue_type,
                        "details": details,
                    },
                )
                conn.commit()

    def resolve_quality_issues(
        self,
        symbol: str,
        filing_date: datetime,
        issue_types: Optional[List[str]] = None,
    ) -> None:
        """Mark open data-quality issues as resolved."""

        with self.get_connection() as conn:
            with conn.cursor() as cursor:
                params = {"symbol": symbol, "filing_date": filing_date}
                if issue_types:
                    params["issue_types"] = issue_types
                    cursor.execute(
                        """
                        UPDATE data_quality_issues
                           SET resolved_at = NOW()
                         WHERE symbol = %(symbol)s
                           AND filing_date = %(filing_date)s
                           AND resolved_at IS NULL
                           AND issue_type = ANY(%(issue_types)s)
                        """,
                        params,
                    )
                else:
                    cursor.execute(
                        """
                        UPDATE data_quality_issues
                           SET resolved_at = NOW()
                         WHERE symbol = %(symbol)s
                           AND filing_date = %(filing_date)s
                           AND resolved_at IS NULL
                        """,
                        params,
                    )
                conn.commit()

    def get_quality_issues(self, symbol: str, filing_date: datetime) -> List[str]:
        """Return unresolved quality issues for a filing."""

        with self.get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT issue_type, details
                      FROM data_quality_issues
                     WHERE symbol = %(symbol)s
                       AND filing_date = %(filing_date)s
                       AND resolved_at IS NULL
                     ORDER BY created_at ASC
                    """,
                    {"symbol": symbol, "filing_date": filing_date},
                )
                rows = cursor.fetchall()
        return [
            (row["details"] or row["issue_type"]).strip()
            for row in rows
            if (row.get("details") or row.get("issue_type"))
        ]

    def insert_feedback(
        self,
        *,
        symbol: Optional[str],
        filing_date: Optional[datetime],
        verdict: Optional[str],
        message: str,
        contact: Optional[str] = None,
        source: str = "ui",
        status: str = "open",
        public_token: str,
    ) -> Dict:
        """Persist a feedback report and return the stored row."""

        with self.get_connection() as conn:
            with conn.cursor() as cursor:
                try:
                    cursor.execute(
                        """
                        INSERT INTO feedback_reports (
                            symbol,
                            filing_date,
                            verdict,
                            message,
                            contact,
                            source,
                            status,
                            public_token
                        ) VALUES (
                            %(symbol)s,
                            %(filing_date)s,
                            %(verdict)s,
                            %(message)s,
                            %(contact)s,
                            %(source)s,
                            %(status)s,
                            %(public_token)s
                        )
                        RETURNING
                            id,
                            symbol,
                            filing_date,
                            verdict,
                            message,
                            contact,
                            source,
                            status,
                            review_notes,
                            resolved_at,
                            resolved_by,
                            public_token,
                            status_updated_at,
                            reevaluated_at,
                            reevaluation_notes,
                            created_at
                        """,
                        {
                            "symbol": symbol,
                            "filing_date": filing_date,
                            "verdict": verdict,
                            "message": message,
                            "contact": contact,
                            "source": source,
                            "status": status,
                            "public_token": public_token,
                        },
                    )
                    row = cursor.fetchone()
                    conn.commit()
                    return dict(row)
                except Exception as exc:
                    conn.rollback()
                    logger.error("Failed to store feedback for %s: %s", symbol, exc)
                    raise

    def list_feedback_reports(
        self,
        status: Optional[str] = None,
        limit: int = 50,
    ) -> List[Dict]:
        """Return recent feedback reports filtered by status."""

        with self.get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT
                        id,
                        symbol,
                        filing_date,
                        verdict,
                        message,
                        contact,
                        source,
                        status,
                        review_notes,
                        resolved_at,
                        resolved_by,
                        public_token,
                        status_updated_at,
                        reevaluated_at,
                        reevaluation_notes,
                        created_at
                    FROM feedback_reports
                    WHERE (%(status)s IS NULL OR status = %(status)s)
                    ORDER BY created_at DESC
                    LIMIT %(limit)s
                    """,
                    {"status": status, "limit": limit},
                )
                rows = cursor.fetchall()
                return [dict(row) for row in rows]

    def update_feedback_report(
        self,
        feedback_id: int,
        status: str,
        reviewer: Optional[str] = None,
        review_notes: Optional[str] = None,
    ) -> Optional[Dict]:
        """Update the status/notes for a feedback report."""

        resolved_at = datetime.now(timezone.utc) if status == "resolved" else None

        with self.get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    UPDATE feedback_reports
                       SET status = %(status)s,
                           review_notes = COALESCE(%(review_notes)s, review_notes),
                           resolved_at = CASE
                               WHEN %(status)s = 'resolved' THEN %(resolved_at)s
                               ELSE NULL
                           END,
                           resolved_by = CASE
                               WHEN %(status)s = 'resolved' THEN COALESCE(%(resolved_by)s, resolved_by)
                               ELSE NULL
                           END,
                           status_updated_at = NOW()
                     WHERE id = %(feedback_id)s
                 RETURNING
                        id,
                        symbol,
                        filing_date,
                        verdict,
                        message,
                        contact,
                        source,
                        status,
                        review_notes,
                        resolved_at,
                        resolved_by,
                        public_token,
                        status_updated_at,
                        reevaluated_at,
                        reevaluation_notes,
                        created_at
                    """,
                    {
                        "feedback_id": feedback_id,
                        "status": status,
                        "review_notes": review_notes,
                        "resolved_at": resolved_at,
                        "resolved_by": reviewer,
                    },
                )
                row = cursor.fetchone()
                if not row:
                    conn.rollback()
                    return None
                conn.commit()
                return dict(row)

    def record_feedback_reevaluation(
        self, feedback_id: int, notes: Optional[str]
    ) -> Optional[Dict]:
        """Store re-evaluation metadata for a feedback report."""

        with self.get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    UPDATE feedback_reports
                       SET reevaluated_at = NOW(),
                           reevaluation_notes = %(notes)s
                     WHERE id = %(feedback_id)s
                 RETURNING
                        id,
                        symbol,
                        filing_date,
                        verdict,
                        message,
                        contact,
                        source,
                        status,
                        review_notes,
                        resolved_at,
                        resolved_by,
                        public_token,
                        status_updated_at,
                        reevaluated_at,
                        reevaluation_notes,
                        created_at
                    """,
                    {"feedback_id": feedback_id, "notes": notes},
                )
                row = cursor.fetchone()
                if not row:
                    conn.rollback()
                    return None
                conn.commit()
                return dict(row)

    def get_feedback_report(self, feedback_id: int) -> Optional[Dict]:
        """Return a single feedback report."""

        with self.get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT
                        id,
                        symbol,
                        filing_date,
                        verdict,
                        message,
                        contact,
                        source,
                        status,
                        review_notes,
                        resolved_at,
                        resolved_by,
                        public_token,
                        status_updated_at,
                        reevaluated_at,
                        reevaluation_notes,
                        created_at
                    FROM feedback_reports
                    WHERE id = %(feedback_id)s
                    """,
                    {"feedback_id": feedback_id},
                )
                row = cursor.fetchone()
                return dict(row) if row else None

    def get_feedback_by_token(self, token: str) -> Optional[Dict]:
        """Return a feedback report via public token."""

        if not token:
            return None

        with self.get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT
                        id,
                        symbol,
                        filing_date,
                        verdict,
                        message,
                        status,
                        review_notes,
                        resolved_at,
                        status_updated_at,
                        reevaluated_at,
                        reevaluation_notes,
                        created_at
                    FROM feedback_reports
                    WHERE public_token = %(token)s
                    """,
                    {"token": token},
                )
                row = cursor.fetchone()
                return dict(row) if row else None

    def upsert_governance_override(
        self,
        *,
        symbol: str,
        filing_date: datetime,
        accounts_receivable: Optional[float] = None,
        liquid_assets: Optional[float] = None,
        non_halal_income: Optional[float] = None,
        governance_notes: Optional[str] = None,
        reviewer: Optional[str] = None,
        reason: Optional[str] = None,
        source: str = "manual",
    ) -> Dict:
        """Insert or update a governance override record."""

        with self.get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO governance_overrides (
                        symbol,
                        filing_date,
                        accounts_receivable,
                        liquid_assets,
                        non_halal_income,
                        governance_notes,
                        reviewer,
                        reason,
                        source
                    ) VALUES (
                        %(symbol)s,
                        %(filing_date)s,
                        %(accounts_receivable)s,
                        %(liquid_assets)s,
                        %(non_halal_income)s,
                        %(governance_notes)s,
                        %(reviewer)s,
                        %(reason)s,
                        %(source)s
                    )
                    ON CONFLICT (symbol, filing_date)
                    DO UPDATE SET
                        accounts_receivable = EXCLUDED.accounts_receivable,
                        liquid_assets = EXCLUDED.liquid_assets,
                        non_halal_income = EXCLUDED.non_halal_income,
                        governance_notes = EXCLUDED.governance_notes,
                        reviewer = EXCLUDED.reviewer,
                        reason = EXCLUDED.reason,
                        source = EXCLUDED.source
                    RETURNING *
                    """,
                    {
                        "symbol": symbol.strip().upper(),
                        "filing_date": filing_date,
                        "accounts_receivable": accounts_receivable,
                        "liquid_assets": liquid_assets,
                        "non_halal_income": non_halal_income,
                        "governance_notes": governance_notes,
                        "reviewer": reviewer,
                        "reason": reason,
                        "source": source,
                    },
                )
                row = cursor.fetchone()
                conn.commit()
                return dict(row)

    def delete_governance_override(self, symbol: str, filing_date: datetime) -> bool:
        """Delete an override; returns True if a row was removed."""

        with self.get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    DELETE FROM governance_overrides
                    WHERE symbol = %(symbol)s AND filing_date = %(filing_date)s
                    """,
                    {"symbol": symbol.strip().upper(), "filing_date": filing_date},
                )
                deleted = cursor.rowcount > 0
                conn.commit()
                return deleted

    def list_governance_overrides(
        self, symbol: Optional[str] = None, limit: int = 50
    ) -> List[Dict]:
        """Return latest governance overrides."""

        with self.get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT
                        symbol,
                        filing_date,
                        accounts_receivable,
                        liquid_assets,
                        non_halal_income,
                        governance_notes,
                        reviewer,
                        reason,
                        source,
                        created_at,
                        updated_at
                    FROM governance_overrides
                    WHERE (%(symbol)s IS NULL OR symbol = %(symbol)s)
                    ORDER BY updated_at DESC
                    LIMIT %(limit)s
                    """,
                    {"symbol": symbol.strip().upper() if symbol else None, "limit": limit},
                )
                rows = cursor.fetchall()
                return [dict(row) for row in rows]

    @staticmethod
    def parse_iso_datetime(dt_str: str) -> datetime:
        """
        Parse an ISO datetime string with BSE-specific normalization.
        """
        return parse_bse_datetime(dt_str)

    def _prepare_announcement_data(self, announcement: Dict) -> Optional[Dict]:
        """Prepare announcement data for database insertion"""
        try:
            # Handle filing_date conversion
            symbol = self._normalize_symbol_value(
                announcement.get("SCRIP_CD")
                or announcement.get("symbol")
                or announcement.get("symbol_code")
            )
            symbol_alias = self._extract_symbol_alias(announcement)
            if not symbol and symbol_alias:
                symbol = symbol_alias
            filing_date = (
                announcement.get('NEWS_DT')
                or announcement.get('DT_TM')
                or announcement.get('filing_date')
            )

            # ?"??"? SKIP rows that break the NOT-NULL PK ?"??"??"??"??"??"??"??"??"??"??"??"??"??"??"??"??"??"??"??"?
            if not symbol or not filing_date:
                logger.warning("Skipping: missing symbol/filing_date NEWSID=%s",
                               announcement.get("NEWSID"))
                return None
            # ?"??"??"??"??"??"??"??"??"??"??"??"??"??"??"??"??"??"??"??"??"??"??"??"??"??"??"??"??"??"??"??"??"??"??"??"??"??"??"??"??"??"??"??"??"??"??"??"??"??"??"??"??"??"??"?

            if isinstance(filing_date, str):
                # Parse ISO format with timezone
                try:
                    filing_date = self.parse_iso_datetime(filing_date)
                except Exception as e:
                    logger.error(f"Failed parsing filing_date '{filing_date}': {e}")
                    raise

            confidence = announcement.get("confidence")
            if not confidence:
                if announcement.get("CATEGORYNAME") == "Result":
                    confidence = "HIGH"
                elif announcement.get("CATEGORYNAME") == "Board Meeting":
                    confidence = "MEDIUM"
                else:
                    confidence = "LOW"

            raw_payload = announcement.get("raw_json") or announcement
            raw_json = Json(
                raw_payload,
                dumps=lambda obj: json.dumps(obj, default=self._json_default),
            )

            return {
                'symbol': symbol,
                'symbol_alias': symbol_alias,
                'company_name': (announcement.get("SLONGNAME") or announcement.get("company_name") or "").strip(),
                'filing_date': filing_date,
                'category': (announcement.get("CATEGORYNAME") or announcement.get("category") or "").strip(),
                'headline': (announcement.get("NEWSSUB") or announcement.get("headline") or "")[:600],
                'confidence': confidence,
                'raw_json': raw_json,  # Store complete original data
                'minio_path': announcement.get('minio_path', None),
                'pdf_stored': announcement.get('pdf_stored', False)
            }
        except Exception as e:
            logger.error(f"Error preparing announcement data: {e}")
            logger.error(f"Problematic data: {announcement}")
            raise

    @staticmethod
    def _extract_symbol_alias(announcement: Dict) -> str:
        direct_alias = announcement.get("symbol_alias")
        if direct_alias:
            cleaned = str(direct_alias).strip()
            if cleaned:
                return cleaned.replace(" ", "").upper()

        alias_sources = [
            announcement.get("symbol"),
            announcement.get("SYMBOL"),
            announcement.get("SYMBOL_TICKER"),
            announcement.get("SecurityId"),
            announcement.get("SYMBOL_NAME"),
        ]
        for candidate in alias_sources:
            if candidate:
                cleaned = str(candidate).strip()
                if cleaned:
                    return cleaned.replace(" ", "").upper()

        ns_url = announcement.get("NSURL") or ""
        if ns_url:
            parts = [part for part in ns_url.split("/") if part]
            if len(parts) >= 2:
                maybe_code = parts[-1]
                maybe_alias = parts[-2]
                if maybe_code.isdigit():
                    alias = maybe_alias
                else:
                    alias = maybe_code
                alias = alias.replace(" ", "").upper()
                if alias and not alias.isdigit():
                    return alias
        return ""

    @staticmethod
    def _normalize_symbol_value(value: Optional[str]) -> str:
        if not value:
            return ""
        token = str(value).strip()
        return token.upper()

    @staticmethod
    def _json_default(value):
        if isinstance(value, datetime):
            return value.isoformat()
        if isinstance(value, date):
            return value.isoformat()
        return str(value)

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
                'dividend_income': extracted_data.get('dividend_income'),
                'accounts_receivable': extracted_data.get('accounts_receivable'),
                'liquid_assets': extracted_data.get('liquid_assets'),
                'non_halal_income': extracted_data.get(
                    'non_halal_income', extracted_data.get('non_permissible_income')
                ),
                'governance_notes': extracted_data.get('governance_notes'),
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
                       f.interest_income, f.dividend_income,
                       f.accounts_receivable, f.liquid_assets, f.non_halal_income,
                       f.governance_notes
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

    def get_recent_filings(self, limit: int = 20) -> List[Dict]:
        """Return recent announcements with optional financial data."""

        with self.get_connection() as conn:
            with conn.cursor() as cursor:
                query = """
                SELECT
                    a.symbol,
                    a.company_name,
                    a.filing_date,
                    a.category,
                    a.headline,
                    a.confidence,
                    fs.total_debt,
                    fs.cash_equiv,
                    fs.revenue,
                    fs.interest_income,
                    fs.dividend_income,
                    COALESCE(go.accounts_receivable, fs.accounts_receivable) AS accounts_receivable,
                    COALESCE(go.liquid_assets, fs.liquid_assets) AS liquid_assets,
                    COALESCE(go.non_halal_income, fs.non_halal_income) AS non_halal_income,
                    COALESCE(go.governance_notes, fs.governance_notes) AS governance_notes,
                    fs.audit_status,
                    fe.is_compliant,
                    fe.verdict,
                    fe.summary,
                    fe.narration_source,
                    fe.ratios,
                    fe.market_cap_used,
                    fe.trailing_cap_used,
                    fe.market_data_provider,
                    (go.symbol IS NOT NULL) AS governance_override_applied,
                    go.source AS governance_override_source,
                    go.reviewer AS governance_override_reviewer,
                    go.reason AS governance_override_reason,
                    go.updated_at AS governance_override_updated_at
                FROM announcements a
                JOIN financial_snapshots fs
                  ON a.symbol = fs.symbol
                 AND a.filing_date = fs.filing_date
                 AND (
                    fs.total_debt IS NOT NULL
                    OR fs.cash_equiv IS NOT NULL
                    OR fs.revenue IS NOT NULL
                 )
                LEFT JOIN filing_evaluations fe
                  ON a.symbol = fe.symbol
                 AND a.filing_date = fe.filing_date
                LEFT JOIN governance_overrides go
                  ON a.symbol = go.symbol
                 AND a.filing_date = go.filing_date
                ORDER BY (fe.ratios IS NOT NULL)::int DESC, a.filing_date DESC
                LIMIT %(limit)s
                """
                cursor.execute(query, {"limit": limit})
                return [dict(row) for row in cursor.fetchall()]

    def get_latest_filing(self, symbol: str) -> Optional[Dict]:
        """Return the most recent filing + financial snapshot for a symbol."""

        if not symbol:
            return None

        with self.get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT
                        a.symbol,
                        a.company_name,
                        a.filing_date,
                    a.category,
                    a.headline,
                    a.confidence,
                    fs.total_debt,
                    fs.cash_equiv,
                    fs.revenue,
                    fs.interest_income,
                    fs.dividend_income,
                    COALESCE(go.accounts_receivable, fs.accounts_receivable) AS accounts_receivable,
                    COALESCE(go.liquid_assets, fs.liquid_assets) AS liquid_assets,
                    COALESCE(go.non_halal_income, fs.non_halal_income) AS non_halal_income,
                    COALESCE(go.governance_notes, fs.governance_notes) AS governance_notes,
                    fs.audit_status,
                    fe.is_compliant,
                    fe.verdict,
                    fe.summary,
                    fe.narration_source,
                    fe.ratios,
                    fe.market_cap_used,
                    fe.trailing_cap_used,
                    fe.market_data_provider,
                    (go.symbol IS NOT NULL) AS governance_override_applied,
                    go.source AS governance_override_source,
                    go.reviewer AS governance_override_reviewer,
                    go.reason AS governance_override_reason,
                    go.updated_at AS governance_override_updated_at
                FROM announcements a
                JOIN financial_snapshots fs
                  ON a.symbol = fs.symbol
                 AND a.filing_date = fs.filing_date
                LEFT JOIN filing_evaluations fe
                  ON a.symbol = fe.symbol
                 AND a.filing_date = fe.filing_date
                LEFT JOIN governance_overrides go
                  ON a.symbol = go.symbol
                 AND a.filing_date = go.filing_date
                WHERE a.symbol = %(symbol)s
                   OR a.symbol_alias = %(symbol)s
                ORDER BY a.filing_date DESC
                LIMIT 1
                    """,
                    {"symbol": symbol.strip().upper()},
                )
                row = cursor.fetchone()
                if not row:
                    return None
                return dict(row)

    def get_filing(self, symbol: str, filing_date: datetime) -> Optional[Dict]:
        """Return a specific filing joined with financial/evaluation data."""

        if not symbol or not filing_date:
            return None

        with self.get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT
                        a.symbol,
                        a.company_name,
                        a.filing_date,
                        a.category,
                        a.headline,
                        a.confidence,
                        fs.total_debt,
                        fs.cash_equiv,
                        fs.revenue,
                        fs.interest_income,
                        fs.dividend_income,
                        COALESCE(go.accounts_receivable, fs.accounts_receivable) AS accounts_receivable,
                        COALESCE(go.liquid_assets, fs.liquid_assets) AS liquid_assets,
                        COALESCE(go.non_halal_income, fs.non_halal_income) AS non_halal_income,
                        COALESCE(go.governance_notes, fs.governance_notes) AS governance_notes,
                        fs.audit_status,
                        fe.is_compliant,
                        fe.verdict,
                        fe.summary,
                        fe.narration_source,
                        fe.ratios,
                        fe.market_cap_used,
                        fe.trailing_cap_used,
                        fe.market_data_provider,
                        (go.symbol IS NOT NULL) AS governance_override_applied,
                        go.source AS governance_override_source,
                        go.reviewer AS governance_override_reviewer,
                        go.reason AS governance_override_reason,
                        go.updated_at AS governance_override_updated_at
                    FROM announcements a
                    JOIN financial_snapshots fs
                      ON a.symbol = fs.symbol
                     AND a.filing_date = fs.filing_date
                    LEFT JOIN filing_evaluations fe
                      ON a.symbol = fe.symbol
                     AND a.filing_date = fe.filing_date
                    LEFT JOIN governance_overrides go
                      ON a.symbol = go.symbol
                     AND a.filing_date = go.filing_date
                    WHERE a.symbol = %(symbol)s
                      AND a.filing_date = %(filing_date)s
                    LIMIT 1
                    """,
                    {
                        "symbol": symbol.strip().upper(),
                        "filing_date": filing_date,
                    },
                )
                row = cursor.fetchone()
                return dict(row) if row else None

    def get_filing_history(self, symbol: str, limit: int = 10) -> List[Dict]:
        """Return recent filings for a single symbol ordered by filing date."""

        if not symbol:
            return []

        with self.get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT
                        a.symbol,
                        a.company_name,
                        a.filing_date,
                        a.category,
                    a.headline,
                    a.confidence,
                    fs.total_debt,
                    fs.cash_equiv,
                    fs.revenue,
                    fs.interest_income,
                    fs.dividend_income,
                    fs.audit_status,
                    fe.is_compliant,
                    fe.verdict,
                    fe.summary,
                    fe.narration_source,
                    fe.ratios,
                    fe.market_cap_used,
                    fe.trailing_cap_used,
                    fe.market_data_provider,
                    COALESCE(go.accounts_receivable, fs.accounts_receivable) AS accounts_receivable,
                    COALESCE(go.liquid_assets, fs.liquid_assets) AS liquid_assets,
                    COALESCE(go.non_halal_income, fs.non_halal_income) AS non_halal_income,
                    COALESCE(go.governance_notes, fs.governance_notes) AS governance_notes,
                    (go.symbol IS NOT NULL) AS governance_override_applied,
                    go.source AS governance_override_source,
                    go.reviewer AS governance_override_reviewer,
                    go.reason AS governance_override_reason,
                    go.updated_at AS governance_override_updated_at
                FROM announcements a
                JOIN financial_snapshots fs
                  ON a.symbol = fs.symbol
                 AND a.filing_date = fs.filing_date
                LEFT JOIN filing_evaluations fe
                  ON a.symbol = fe.symbol
                 AND a.filing_date = fe.filing_date
                LEFT JOIN governance_overrides go
                  ON a.symbol = go.symbol
                 AND a.filing_date = go.filing_date
                WHERE a.symbol = %(symbol)s
                   OR a.symbol_alias = %(symbol)s
                ORDER BY a.filing_date DESC
                LIMIT %(limit)s
                    """,
                    {"symbol": symbol.strip().upper(), "limit": limit},
                )
                rows = cursor.fetchall()
                return [dict(row) for row in rows]

    def get_symbol_metadata(self, identifier: str) -> Optional[Dict[str, str]]:
        """Return numeric symbol and alias for an identifier (symbol or alias)."""

        normalized = (identifier or "").strip().upper()
        if not normalized:
            return None

        with self.get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT symbol, symbol_alias
                    FROM announcements
                    WHERE symbol = %(identifier)s
                       OR symbol_alias = %(identifier)s
                    ORDER BY filing_date DESC
                    LIMIT 1
                    """,
                    {"identifier": normalized},
                )
                row = cursor.fetchone()
                if not row:
                    return None
                return dict(row)

    def get_symbol_alias(self, symbol: str) -> Optional[str]:
        metadata = self.get_symbol_metadata(symbol)
        if not metadata:
            return None
        alias = (metadata.get("symbol_alias") or "").strip().upper()
        return alias or None

    def get_symbol_code(self, identifier: str) -> Optional[str]:
        metadata = self.get_symbol_metadata(identifier)
        if not metadata:
            return None
        return metadata.get("symbol")

    def get_database_stats(self) -> Dict:
        """Get comprehensive database statistics"""
        with self.get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT 
                        COUNT(*) as total_announcements,
                        COUNT(*) FILTER (WHERE confidence = 'HIGH') as high_confidence,
                        COUNT(*) FILTER (WHERE pdf_stored = true) as pdfs_stored,
                        MAX(filing_date) as latest_filing,
                        COUNT(DISTINCT symbol) as unique_companies
                    FROM announcements
                    """
                )
                announcements_stats = dict(cursor.fetchone())

                cursor.execute(
                    """
                    SELECT 
                        COUNT(*) as financial_snapshots,
                        COUNT(*) FILTER (WHERE total_debt IS NOT NULL) as with_debt_data,
                        COUNT(*) FILTER (WHERE revenue IS NOT NULL) as with_revenue_data,
                        COUNT(DISTINCT quarter) as quarters_covered
                    FROM financial_snapshots
                    """
                )
                snapshots_stats = dict(cursor.fetchone())

                stats = {**announcements_stats, **snapshots_stats}
                latest = stats.get("latest_filing")
                if isinstance(latest, datetime):
                    stats["latest_filing"] = latest.isoformat()
                return stats

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

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
from datetime import datetime, date, timedelta, timezone
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

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
from evaluation import quality
from utils.datetime_parser import parse_bse_datetime

logger = logging.getLogger(__name__)

# First key of the two-key advisory lock that serialises one filing's
# publication and quality-issue writes (pg_advisory_xact_lock(int4, int4)).
FILING_LOCK_NAMESPACE = 20261029


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

        self._ensure_auth_infrastructure()

    def _ensure_auth_infrastructure(self) -> None:
        """
        Make sure auth-related columns exist (especially for Google SSO).

        Some environments skip manual migrations, so we defensively add the
        new metadata columns here to avoid runtime failures when OAuth is used.
        """
        ddl = """
        ALTER TABLE IF EXISTS users
            ADD COLUMN IF NOT EXISTS provider TEXT NOT NULL DEFAULT 'password',
            ADD COLUMN IF NOT EXISTS google_sub TEXT UNIQUE,
            ADD COLUMN IF NOT EXISTS full_name TEXT,
            ADD COLUMN IF NOT EXISTS avatar_url TEXT;
        CREATE INDEX IF NOT EXISTS idx_users_google_sub ON users(google_sub);
        """

        with self.get_connection() as conn:
            with conn.cursor() as cursor:
                try:
                    cursor.execute(ddl)
                    conn.commit()
                except Exception as exc:
                    conn.rollback()
                    logger.warning("Unable to ensure auth columns (continuing): %s", exc)

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
            with conn.cursor(cursor_factory=RealDictCursor) as cursor:
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

    def get_indianapi_snapshot(
        self, symbol: str, target_date: Optional[date] = None
    ) -> Optional[Dict]:
        """Return the cached Indian API payload closest to the target date."""

        normalized = (symbol or "").strip().upper()
        if not normalized:
            return None

        with self.get_connection() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cursor:
                if target_date:
                    cursor.execute(
                        """
                        SELECT payload
                        FROM indianapi_snapshots
                        WHERE symbol = %(symbol)s
                          AND snapshot_date IS NOT NULL
                        ORDER BY ABS(snapshot_date - %(target)s)
                        LIMIT 1
                        """,
                        {"symbol": normalized, "target": target_date},
                    )
                else:
                    cursor.execute(
                        """
                        SELECT payload
                          FROM indianapi_snapshots
                         WHERE symbol = %(symbol)s
                         ORDER BY fetched_at DESC
                         LIMIT 1
                        """,
                        {"symbol": normalized},
                    )
                row = cursor.fetchone()
                return dict(row) if row else None

    def get_cached_market_data(
        self, symbol: str, as_of: Optional[datetime] = None
    ) -> Optional[Tuple[Optional[float], Optional[float], Optional[str]]]:
        """Return the most recent market snapshot for a symbol."""

        with self.get_connection() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cursor:
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
            with conn.cursor(cursor_factory=RealDictCursor) as cursor:
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
            with conn.cursor(cursor_factory=RealDictCursor) as cursor:
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

    def _lock_filing(self, cursor, symbol: str, filing_date: datetime) -> None:
        """Serialise publication and issue writes for one filing until commit.

        Transaction-scoped, keyed on the canonical (symbol, filing instant), in
        its own two-key namespace so it cannot meet the single-key job locks.
        """

        cursor.execute(
            """
            SELECT pg_advisory_xact_lock(
                %(namespace)s,
                hashtext(%(symbol)s || '|' || extract(epoch FROM %(filing_date)s::timestamptz)::text)
            )
            """,
            {
                "namespace": FILING_LOCK_NAMESPACE,
                "symbol": str(symbol).strip().upper(),
                "filing_date": filing_date,
            },
        )

    @staticmethod
    def _open_issue_rows(cursor, symbol: str, filing_date: datetime) -> List[Dict]:
        cursor.execute(
            """
            SELECT issue_type, details
              FROM data_quality_issues
             WHERE symbol = %(symbol)s
               AND filing_date = %(filing_date)s
               AND resolved_at IS NULL
             ORDER BY created_at ASC, id ASC
            """,
            {"symbol": symbol, "filing_date": filing_date},
        )
        return [dict(row) for row in cursor.fetchall()]

    def publish_filing_evaluation(
        self,
        *,
        symbol: str,
        filing_date: datetime,
        verdict: str,
        is_compliant: Optional[bool],
        summary: str,
        ratios: Dict,
        anomalies: Optional[Sequence[str]],
        narration_source: str,
        market_cap_used: Optional[float],
        trailing_cap_used: Optional[float],
        market_data_provider: Optional[str] = None,
        expect: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Store an engine result through the shared publication overlay (D-027).

        One transaction under the filing's advisory lock: reconcile the
        detector-owned `ratio_anomaly` row with `anomalies` (None: the detector
        did not run), read every open issue, apply evaluation.quality.publish
        and upsert filing_evaluations. Any open issue publishes needs-review.
        `expect` (recompute --write) rejects the write with StalePublication
        when the stored evaluation, the open issue types or the published pair
        differ from the preview. Returns the published verdict, is_compliant,
        summary, quality_issues (display text) and issue_types.
        """

        key = {"symbol": symbol, "filing_date": filing_date}
        with self.get_connection() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cursor:
                self._lock_filing(cursor, symbol, filing_date)
                open_issues = self._open_issue_rows(cursor, symbol, filing_date)
                issues = quality.reconcile(open_issues, anomalies)
                final_verdict, final_is_compliant, final_summary = quality.publish(
                    verdict, is_compliant, summary, issues, anomalies or ()
                )

                if expect is not None:
                    cursor.execute(
                        """
                        SELECT evaluated_at FROM filing_evaluations
                         WHERE symbol = %(symbol)s AND filing_date = %(filing_date)s
                        """,
                        key,
                    )
                    row = cursor.fetchone()
                    current = (
                        row["evaluated_at"] if row else None,
                        final_verdict,
                        final_is_compliant,
                        quality.issue_types(issues),
                    )
                    wanted = (
                        expect.get("evaluated_at"),
                        expect.get("verdict"),
                        expect.get("is_compliant"),
                        tuple(expect.get("issue_types") or ()),
                    )
                    if current != wanted:
                        raise quality.StalePublication(
                            f"{symbol}@{filing_date}: preview {wanted} is now {current}"
                        )

                if anomalies is not None:
                    detail = quality.combined_anomaly(anomalies)
                    existing = next(
                        (i for i in open_issues if i["issue_type"] == quality.RATIO_ANOMALY),
                        None,
                    )
                    # Identical and still open: no write, so no timestamp churn.
                    if detail and (existing is None or existing["details"] != detail):
                        cursor.execute(
                            """
                            INSERT INTO data_quality_issues (symbol, filing_date, issue_type, details)
                            VALUES (%(symbol)s, %(filing_date)s, %(issue_type)s, %(details)s)
                            ON CONFLICT (symbol, filing_date, issue_type)
                            DO UPDATE SET details = EXCLUDED.details,
                                          resolved_at = NULL,
                                          created_at = NOW()
                            """,
                            {**key, "issue_type": quality.RATIO_ANOMALY, "details": detail},
                        )
                    elif not detail and existing is not None:
                        cursor.execute(
                            """
                            UPDATE data_quality_issues
                               SET resolved_at = NOW()
                             WHERE symbol = %(symbol)s
                               AND filing_date = %(filing_date)s
                               AND issue_type = %(issue_type)s
                               AND resolved_at IS NULL
                            """,
                            {**key, "issue_type": quality.RATIO_ANOMALY},
                        )

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
                        **key,
                        "is_compliant": final_is_compliant,
                        "ratios": Json(ratios),
                        "summary": final_summary,
                        "verdict": final_verdict,
                        "narration_source": narration_source,
                        "market_cap_used": market_cap_used,
                        "trailing_cap_used": trailing_cap_used,
                        "market_data_provider": market_data_provider,
                    },
                )
                conn.commit()
        return {
            "verdict": final_verdict,
            "is_compliant": final_is_compliant,
            "summary": final_summary,
            "quality_issues": quality.issue_texts(issues),
            "issue_types": quality.issue_types(issues),
        }

    def record_quality_issue(
        self, symbol: str, filing_date: datetime, issue_type: str, details: str
    ) -> None:
        """Open (or update) a data-quality issue and mask the filing's published result.

        Same lock and transaction as publication, so a blocker recorded while an
        evaluation is being published can never leave a conclusive row behind.
        """

        key = {"symbol": symbol, "filing_date": filing_date}
        review_verdict, _, review_summary = quality.publish(None, None, None, [issue_type])
        with self.get_connection() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cursor:
                self._lock_filing(cursor, symbol, filing_date)
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
                    {**key, "issue_type": issue_type, "details": details},
                )
                # evaluated_at is kept: this masks, it does not re-evaluate, and
                # a newer snapshot or override must still make the filing due.
                cursor.execute(
                    """
                    UPDATE filing_evaluations
                       SET verdict = %(verdict)s,
                           is_compliant = NULL,
                           summary = %(summary)s
                     WHERE symbol = %(symbol)s
                       AND filing_date = %(filing_date)s
                       AND verdict IS DISTINCT FROM %(verdict)s
                    """,
                    {**key, "verdict": review_verdict, "summary": review_summary},
                )
                conn.commit()

    def resolve_quality_issues(
        self,
        symbol: str,
        filing_date: datetime,
        issue_types: Optional[List[str]] = None,
    ) -> None:
        """Mark open data-quality issues as resolved.

        Resolution alone never restores a verdict: a stored needs-review stays
        until a new evaluation goes through publish_filing_evaluation.
        """

        with self.get_connection() as conn:
            with conn.cursor() as cursor:
                self._lock_filing(cursor, symbol, filing_date)
                params = {"symbol": symbol, "filing_date": filing_date}
                if issue_types:
                    params["issue_types"] = list(issue_types)
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

    def get_open_quality_issues(self, symbol: str, filing_date: datetime) -> List[Dict]:
        """Unresolved issues for a filing as {issue_type, details}, oldest first."""

        with self.get_connection() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cursor:
                return self._open_issue_rows(cursor, symbol, filing_date)

    def get_quality_issues(self, symbol: str, filing_date: datetime) -> List[str]:
        """Return unresolved quality issues for a filing (display text)."""

        return quality.issue_texts(self.get_open_quality_issues(symbol, filing_date))

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
                    try:
                        self.log_feedback_event(
                            row["id"],
                            "submitted",
                            status=row.get("status"),
                            details="Feedback submitted via {}".format(source or "ui"),
                            source=source or "ui",
                        )
                    except Exception:
                        pass
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
                try:
                    self.log_feedback_event(
                        feedback_id,
                        "status_change",
                        status=status,
                        reviewer=reviewer,
                        details=review_notes,
                    )
                except Exception:
                    pass
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
                try:
                    self.log_feedback_event(
                        feedback_id,
                        "reevaluated",
                        status=row.get("status"),
                        reviewer=row.get("resolved_by"),
                        details=notes,
                    )
                except Exception:
                    pass
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

    def log_feedback_event(
        self,
        feedback_id: int,
        event_type: str,
        *,
        status: Optional[str] = None,
        reviewer: Optional[str] = None,
        details: Optional[str] = None,
        source: str = "api",
    ) -> None:
        if not feedback_id:
            return
        with self.get_connection() as conn:
            with conn.cursor() as cursor:
                try:
                    cursor.execute(
                        """
                        INSERT INTO feedback_events (
                            feedback_id,
                            event_type,
                            status,
                            reviewer,
                            details,
                            source
                        ) VALUES (
                            %(feedback_id)s,
                            %(event_type)s,
                            %(status)s,
                            %(reviewer)s,
                            %(details)s,
                            %(source)s
                        )
                        """,
                        {
                            "feedback_id": feedback_id,
                            "event_type": event_type,
                            "status": status,
                            "reviewer": reviewer,
                            "details": details,
                            "source": source,
                        },
                    )
                    conn.commit()
                except Exception as exc:
                    conn.rollback()
                    logger.debug(
                        "Failed to log feedback event %s (%s): %s",
                        feedback_id,
                        event_type,
                        exc,
                    )

    def get_feedback_events(self, feedback_id: int) -> List[Dict]:
        if not feedback_id:
            return []
        with self.get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT id,
                           feedback_id,
                           event_type,
                           status,
                           reviewer,
                           details,
                           source,
                           created_at
                    FROM feedback_events
                    WHERE feedback_id = %(feedback_id)s
                    ORDER BY created_at
                    """,
                    {"feedback_id": feedback_id},
                )
                rows = cursor.fetchall()
                return [dict(row) for row in rows]

    def get_feedback_events_by_token(self, token: str) -> List[Dict]:
        if not token:
            return []
        with self.get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT fe.id,
                           fe.feedback_id,
                           fe.event_type,
                           fe.status,
                           fe.reviewer,
                           fe.details,
                           fe.source,
                           fe.created_at
                    FROM feedback_events fe
                             JOIN feedback_reports fr
                                  ON fr.id = fe.feedback_id
                    WHERE fr.public_token = %(token)s
                    ORDER BY fe.created_at
                    """,
                    {"token": token},
                )
                rows = cursor.fetchall()
                return [dict(row) for row in rows]

    def list_feedback_for_filing(
        self,
        symbol: str,
        filing_date: datetime,
        statuses: Optional[List[str]] = None,
    ) -> List[Dict]:
        """Return feedback reports matching a specific filing."""

        normalized = (symbol or "").strip().upper()
        if not normalized or not filing_date:
            return []

        query = """
            SELECT id, status
              FROM feedback_reports
             WHERE symbol = %(symbol)s
               AND filing_date = %(filing_date)s
        """
        params: Dict[str, Any] = {
            "symbol": normalized,
            "filing_date": filing_date,
        }
        if statuses:
            query += " AND status = ANY(%(statuses)s)"
            params["statuses"] = statuses

        with self.get_connection() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cursor:
                cursor.execute(query, params)
                rows = cursor.fetchall()
                return [dict(row) for row in rows]

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

    def get_governance_override(
        self, symbol: str, filing_date: datetime
    ) -> Optional[Dict]:
        """Return governance override for a specific filing."""

        with self.get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT *
                      FROM governance_overrides
                     WHERE symbol = %(symbol)s
                       AND filing_date = %(filing_date)s
                    """,
                    {"symbol": symbol.strip().upper(), "filing_date": filing_date},
                )
                row = cursor.fetchone()
                return dict(row) if row else None

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
                    fe.evaluated_at AS evaluation_updated_at,
                    fe.market_cap_used,
                    fe.trailing_cap_used,
                    fe.market_data_provider,
                    -- The jobs need "has a non-empty evaluation" without pulling the
                    -- ratios JSON into the /filings/recent response (FilingResponse.ratios).
                    (fe.ratios IS NOT NULL AND fe.ratios <> '{}'::jsonb) AS has_ratios,
                    fs.parsed_at AS snapshot_parsed_at,
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
                ORDER BY (fe.ratios IS NOT NULL)::int DESC, a.filing_date DESC, a.symbol
                LIMIT %(limit)s
                """
                cursor.execute(query, {"limit": limit})
                return [dict(row) for row in cursor.fetchall()]

    def get_filings_needing_evaluation(
        self, *, limit: int = 200, lookback_days: int = 365
    ) -> List[Dict]:
        """Return filings missing or stale evaluations within a lookback window."""

        lookback_days = max(1, int(lookback_days))
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
                    fe.evaluated_at AS evaluation_updated_at,
                    fe.market_cap_used,
                    fe.trailing_cap_used,
                    fe.market_data_provider,
                    fs.parsed_at AS snapshot_parsed_at,
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
                WHERE a.filing_date >= (NOW() - (%(lookback_days)s * INTERVAL '1 day'))
                  AND (
                    fe.ratios IS NULL
                    OR fe.evaluated_at IS NULL
                    OR (go.updated_at IS NOT NULL AND (fe.evaluated_at IS NULL OR go.updated_at > fe.evaluated_at))
                    OR (fs.parsed_at IS NOT NULL AND (fe.evaluated_at IS NULL OR fs.parsed_at > fe.evaluated_at))
                  )
                ORDER BY a.filing_date DESC
                LIMIT %(limit)s
                """
                cursor.execute(
                    query,
                    {"limit": int(limit), "lookback_days": lookback_days},
                )
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
                    fe.evaluated_at AS evaluation_updated_at,
                    fe.market_cap_used,
                    fe.trailing_cap_used,
                    fe.market_data_provider,
                    fs.parsed_at AS snapshot_parsed_at,
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
                        fe.evaluated_at AS evaluation_updated_at,
                        fe.market_cap_used,
                        fe.trailing_cap_used,
                        fe.market_data_provider,
                        fs.parsed_at AS snapshot_parsed_at,
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

    def get_filing_by_date(self, symbol: str, filing_date: date) -> Optional[Dict]:
        """Return the most recent filing for a symbol on a given date."""

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
                        fe.evaluated_at AS evaluation_updated_at,
                        fe.market_cap_used,
                        fe.trailing_cap_used,
                        fe.market_data_provider,
                        fs.parsed_at AS snapshot_parsed_at,
                        (go.symbol IS NOT NULL) AS governance_override_applied,
                        go.source AS governance_override_source,
                        go.reviewer AS governance_override_reviewer,
                        go.reason AS governance_override_reason,
                        go.updated_at AS governance_override_updated_at
                    FROM announcements a
                    LEFT JOIN financial_snapshots fs
                      ON a.symbol = fs.symbol
                     AND a.filing_date = fs.filing_date
                    LEFT JOIN filing_evaluations fe
                      ON a.symbol = fe.symbol
                     AND a.filing_date = fe.filing_date
                    LEFT JOIN governance_overrides go
                      ON a.symbol = go.symbol
                     AND a.filing_date = go.filing_date
                    WHERE a.symbol = %(symbol)s
                      AND a.filing_date::date = %(filing_date)s
                    ORDER BY a.filing_date DESC
                    LIMIT 1
                    """,
                    {
                        "symbol": symbol.strip().upper(),
                        "filing_date": filing_date,
                    },
                )
                row = cursor.fetchone()
                return dict(row) if row else None

    def get_filing_history(
        self, symbol: str, limit: int = 10, cursor_ts: Optional[datetime] = None
    ) -> List[Dict]:
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
                    fe.evaluated_at AS evaluation_updated_at,
                    fe.market_cap_used,
                    fe.trailing_cap_used,
                    fe.market_data_provider,
                    fs.parsed_at AS snapshot_parsed_at,
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
                WHERE (a.symbol = %(symbol)s OR a.symbol_alias = %(symbol)s)
                  AND (%(cursor_ts)s IS NULL OR a.filing_date < %(cursor_ts)s)
                ORDER BY a.filing_date DESC
                LIMIT %(limit)s
                    """,
                    {
                        "symbol": symbol.strip().upper(),
                        "limit": limit,
                        "cursor_ts": cursor_ts,
                    },
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

    # ----------------------------
    # User & session management
    # ----------------------------

    def create_user(
        self,
        *,
        email: str,
        password_hash: str,
        plan: str = "free",
        subscription_status: str = "inactive",
        provider: str = "password",
        google_sub: Optional[str] = None,
        full_name: Optional[str] = None,
        avatar_url: Optional[str] = None,
        is_admin: bool = False,
    ) -> Dict:
        with self.get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO users (
                        email,
                        password_hash,
                        provider,
                        google_sub,
                        full_name,
                        avatar_url,
                        is_admin,
                        plan,
                        subscription_status,
                        plan_started_at
                    ) VALUES (
                        %(email)s,
                        %(password_hash)s,
                        %(provider)s,
                        %(google_sub)s,
                        %(full_name)s,
                        %(avatar_url)s,
                        %(is_admin)s,
                        %(plan)s,
                        %(subscription_status)s,
                        NOW()
                    )
                    RETURNING id, email, plan, subscription_status,
                              subscription_renewal, plan_started_at,
                              created_at, updated_at, provider, google_sub,
                              full_name, avatar_url, is_admin
                    """,
                    {
                        "email": email,
                        "password_hash": password_hash,
                        "provider": provider,
                        "google_sub": google_sub,
                        "full_name": full_name,
                        "avatar_url": avatar_url,
                        "is_admin": is_admin,
                        "plan": plan,
                        "subscription_status": subscription_status,
                    },
                )
                row = cursor.fetchone()
                conn.commit()
                return dict(row)

    def get_user_by_email(self, email: str) -> Optional[Dict]:
        with self.get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT id, email, password_hash, plan,
                           subscription_status, subscription_renewal,
                           provider, google_sub, full_name, avatar_url,
                           plan_started_at, last_login, created_at, updated_at,
                           is_admin, trial_used, email_verified_at
                    FROM users
                    WHERE email = %(email)s
                    """,
                    {"email": email},
                )
                row = cursor.fetchone()
                if not row:
                    return None
                return dict(row)

    def get_user_by_id(self, user_id: int) -> Optional[Dict]:
        with self.get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT id, email, plan, subscription_status,
                           subscription_renewal, plan_started_at,
                           last_login, created_at, updated_at,
                           provider, google_sub, full_name, avatar_url,
                           is_admin, trial_used, email_verified_at
                    FROM users
                    WHERE id = %(user_id)s
                    """,
                    {"user_id": user_id},
                )
                row = cursor.fetchone()
                if not row:
                    return None
                return dict(row)

    def update_user_password_hash(self, user_id: int, password_hash: str) -> None:
        """Persist a re-derived password hash (transparent upgrade on login)."""

        with self.get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    UPDATE users
                    SET password_hash = %(password_hash)s, updated_at = NOW()
                    WHERE id = %(user_id)s
                    """,
                    {"user_id": user_id, "password_hash": password_hash},
                )
                conn.commit()

    def delete_sessions_for_user(self, user_id: int) -> int:
        """Revoke every session for a user; returns the number removed."""

        with self.get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    "DELETE FROM user_sessions WHERE user_id = %(user_id)s",
                    {"user_id": user_id},
                )
                deleted = cursor.rowcount or 0
                conn.commit()
                return deleted

    def get_user_by_google_sub(self, google_sub: str) -> Optional[Dict]:
        with self.get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT id, email, plan, subscription_status,
                           subscription_renewal, plan_started_at,
                           last_login, created_at, updated_at,
                           provider, google_sub, full_name, avatar_url,
                           is_admin, trial_used
                    FROM users
                    WHERE google_sub = %(google_sub)s
                    """,
                    {"google_sub": google_sub},
                )
                row = cursor.fetchone()
                if not row:
                    return None
                return dict(row)

    _USER_COLUMNS = """id, email, plan, subscription_status, subscription_renewal,
                       plan_started_at, last_login, created_at, updated_at,
                       provider, google_sub, full_name, avatar_url, is_admin,
                       trial_used, email_verified_at"""

    def google_sign_in(
        self,
        *,
        email: str,
        google_sub: str,
        full_name: Optional[str],
        avatar_url: Optional[str],
        admin_emails: List[str],
    ) -> Tuple[str, Optional[Dict]]:
        """Resolve a Google sign-in whose email Google has verified.

        Returns ("ok", user) or ("email_in_use", None). An account is matched
        only by its Google subject; an existing account with the same email is
        never linked implicitly (that let a pre-registered password account
        absorb the real owner's Google sign-in). A match whose primary email is
        this Google email is marked verified, and admin is granted only then.
        """

        with self.get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    f"SELECT {self._USER_COLUMNS} FROM users "
                    "WHERE google_sub = %(sub)s FOR UPDATE",
                    {"sub": google_sub},
                )
                row = cursor.fetchone()
                if row:
                    if row["email"] == email:
                        cursor.execute(
                            f"""
                            UPDATE users
                               SET email_verified_at = COALESCE(email_verified_at, NOW()),
                                   is_admin = is_admin OR email = ANY(%(admins)s),
                                   updated_at = NOW()
                             WHERE id = %(id)s
                            RETURNING {self._USER_COLUMNS}
                            """,
                            {"id": row["id"], "admins": list(admin_emails)},
                        )
                        row = cursor.fetchone()
                    conn.commit()
                    return "ok", dict(row)

                cursor.execute(
                    "SELECT 1 FROM users WHERE email = %(email)s", {"email": email}
                )
                if cursor.fetchone():
                    conn.commit()
                    return "email_in_use", None

                cursor.execute(
                    f"""
                    INSERT INTO users (
                        email, password_hash, provider, google_sub, full_name,
                        avatar_url, plan, subscription_status, plan_started_at,
                        email_verified_at, is_admin
                    ) VALUES (
                        %(email)s, NULL, 'google', %(sub)s, %(full_name)s,
                        %(avatar_url)s, 'free', 'active', NOW(), NOW(),
                        %(email)s = ANY(%(admins)s)
                    )
                    ON CONFLICT DO NOTHING
                    RETURNING {self._USER_COLUMNS}
                    """,
                    {
                        "email": email,
                        "sub": google_sub,
                        "full_name": full_name,
                        "avatar_url": avatar_url,
                        "admins": list(admin_emails),
                    },
                )
                created = cursor.fetchone()
                conn.commit()
                if not created:  # a concurrent sign-up took the email or subject
                    return "email_in_use", None
                return "ok", dict(created)

    def login_with_password(
        self,
        *,
        email: str,
        check_password: Callable[[Optional[str]], bool],
        rehash: Callable[[Optional[str]], Optional[str]],
        session_digest: str,
        expires_at: datetime,
    ) -> Tuple[str, Optional[Dict]]:
        """Check a password and create a session in one transaction.

        The user row stays locked (FOR UPDATE) from the password check through
        the session insert, and a password reset takes the same lock, so a
        login that verified the old password cannot leave a session behind
        after the reset. Returns ("ok" | "bad_credentials" | "unverified", row).
        """

        with self.get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    f"SELECT {self._USER_COLUMNS}, password_hash FROM users "
                    "WHERE email = %(email)s FOR UPDATE",
                    {"email": email},
                )
                row = cursor.fetchone()
                if not row or not check_password(row["password_hash"]):
                    conn.rollback()
                    return "bad_credentials", None
                if not row["email_verified_at"]:
                    conn.rollback()
                    return "unverified", dict(row)
                upgraded = rehash(row["password_hash"])
                if upgraded:
                    cursor.execute(
                        "UPDATE users SET password_hash = %(h)s WHERE id = %(id)s",
                        {"h": upgraded, "id": row["id"]},
                    )
                cursor.execute(
                    "INSERT INTO user_sessions (token, user_id, expires_at) "
                    "VALUES (%(token)s, %(id)s, %(expires_at)s)",
                    {"token": session_digest, "id": row["id"], "expires_at": expires_at},
                )
                cursor.execute(
                    "UPDATE users SET last_login = NOW(), updated_at = NOW() WHERE id = %(id)s",
                    {"id": row["id"]},
                )
                conn.commit()
                return "ok", dict(row)

    def issue_auth_token(
        self,
        *,
        purpose: str,
        email: str,
        user_id: Optional[int],
        token_digest: str,
        expires_at: datetime,
    ) -> None:
        """Store a new emailed proof; older unused ones for the same email and
        purpose stop working, so only the latest link is valid."""

        with self.get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    "UPDATE auth_tokens SET consumed_at = NOW() "
                    "WHERE email = %(email)s AND purpose = %(purpose)s AND consumed_at IS NULL",
                    {"email": email, "purpose": purpose},
                )
                cursor.execute(
                    "INSERT INTO auth_tokens (purpose, email, user_id, token_digest, expires_at) "
                    "VALUES (%(purpose)s, %(email)s, %(user_id)s, %(digest)s, %(expires_at)s)",
                    {
                        "purpose": purpose,
                        "email": email,
                        "user_id": user_id,
                        "digest": token_digest,
                        "expires_at": expires_at,
                    },
                )
                conn.commit()

    _CONSUME_TOKEN_SQL = """
        UPDATE auth_tokens SET consumed_at = NOW()
         WHERE token_digest = %(digest)s AND purpose = %(purpose)s
           AND consumed_at IS NULL AND expires_at > NOW()
        RETURNING email, user_id
    """

    def complete_signup(
        self,
        *,
        token_digest: str,
        password_hash: str,
        admin_emails: List[str],
    ) -> Tuple[str, Optional[Dict]]:
        """Consume a signup proof and create the verified account.

        Returns ("ok", user), ("invalid_token", None) or ("email_in_use", None).
        The password is chosen here, after the mailbox is proven, so nobody
        can pre-register someone else's address with a password they know.
        """

        with self.get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    self._CONSUME_TOKEN_SQL, {"digest": token_digest, "purpose": "signup"}
                )
                token = cursor.fetchone()
                if not token:
                    conn.rollback()
                    return "invalid_token", None
                cursor.execute(
                    f"""
                    INSERT INTO users (
                        email, password_hash, provider, plan, subscription_status,
                        plan_started_at, email_verified_at, is_admin
                    ) VALUES (
                        %(email)s, %(hash)s, 'password', 'free', 'inactive',
                        NOW(), NOW(), %(email)s = ANY(%(admins)s)
                    )
                    ON CONFLICT (email) DO NOTHING
                    RETURNING {self._USER_COLUMNS}
                    """,
                    {"email": token["email"], "hash": password_hash, "admins": list(admin_emails)},
                )
                created = cursor.fetchone()
                conn.commit()  # the proof is spent either way
                if not created:
                    return "email_in_use", None
                return "ok", dict(created)

    def complete_password_reset(
        self,
        *,
        token_digest: str,
        password_hash: str,
        admin_emails: List[str],
    ) -> Tuple[str, Optional[Dict]]:
        """Consume a reset proof and replace the password, in one transaction.

        Locks the user row (as login does), sets the password, marks the
        email verified (the mailbox was just proven), grants admin from the
        allowlist, revokes every session and every other unused proof.
        Returns ("ok", user) or ("invalid_token", None).
        """

        with self.get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    self._CONSUME_TOKEN_SQL,
                    {"digest": token_digest, "purpose": "reset_password"},
                )
                token = cursor.fetchone()
                if not token or not token["user_id"]:
                    conn.rollback()
                    return "invalid_token", None
                cursor.execute(
                    "SELECT id, email FROM users WHERE id = %(id)s FOR UPDATE",
                    {"id": token["user_id"]},
                )
                user = cursor.fetchone()
                if not user or user["email"] != token["email"]:
                    conn.rollback()
                    return "invalid_token", None
                cursor.execute(
                    f"""
                    UPDATE users
                       SET password_hash = %(hash)s,
                           email_verified_at = COALESCE(email_verified_at, NOW()),
                           is_admin = is_admin OR email = ANY(%(admins)s),
                           updated_at = NOW()
                     WHERE id = %(id)s
                    RETURNING {self._USER_COLUMNS}
                    """,
                    {"id": user["id"], "hash": password_hash, "admins": list(admin_emails)},
                )
                updated = cursor.fetchone()
                cursor.execute(
                    "DELETE FROM user_sessions WHERE user_id = %(id)s", {"id": user["id"]}
                )
                cursor.execute(
                    "UPDATE auth_tokens SET consumed_at = NOW() "
                    "WHERE user_id = %(id)s AND consumed_at IS NULL",
                    {"id": user["id"]},
                )
                conn.commit()
                return "ok", dict(updated)

    def create_oauth_flow(
        self,
        *,
        purpose: str,
        state_digest: str,
        browser_digest: str,
        expires_at: datetime,
        redirect: Optional[str] = None,
        user_id: Optional[int] = None,
        session_digest: Optional[str] = None,
    ) -> None:
        """Record a Google OAuth flow started by one browser (D-021)."""

        with self.get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    "DELETE FROM oauth_flows WHERE expires_at < NOW() - INTERVAL '1 day'"
                )
                cursor.execute(
                    """
                    INSERT INTO oauth_flows (purpose, state_digest, browser_digest, redirect,
                                             user_id, session_digest, expires_at)
                    VALUES (%(purpose)s, %(state)s, %(browser)s, %(redirect)s,
                            %(user_id)s, %(session)s, %(expires_at)s)
                    """,
                    {
                        "purpose": purpose,
                        "state": state_digest,
                        "browser": browser_digest,
                        "redirect": redirect,
                        "user_id": user_id,
                        "session": session_digest,
                        "expires_at": expires_at,
                    },
                )
                conn.commit()

    def consume_oauth_flow(self, *, state_digest: str, browser_digest: str) -> Optional[Dict]:
        """Spend a flow at the callback: right state, same browser, once, in time."""

        with self.get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    UPDATE oauth_flows SET callback_at = NOW()
                     WHERE state_digest = %(state)s AND browser_digest = %(browser)s
                       AND callback_at IS NULL AND expires_at > NOW()
                    RETURNING id, purpose, redirect, user_id
                    """,
                    {"state": state_digest, "browser": browser_digest},
                )
                row = cursor.fetchone()
                conn.commit()
                return dict(row) if row else None

    def record_link_identity(
        self, *, flow_id: int, google_sub: str, google_email: str, link_code_digest: str
    ) -> None:
        """Store the Google identity a link flow proved; nothing is linked yet."""

        with self.get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    UPDATE oauth_flows
                       SET google_sub = %(sub)s, google_email = %(email)s,
                           link_code_digest = %(code)s
                     WHERE id = %(id)s AND purpose = 'link'
                    """,
                    {"sub": google_sub, "email": google_email, "code": link_code_digest, "id": flow_id},
                )
                conn.commit()

    def complete_google_link(
        self, *, link_code_digest: str, user_id: int, session_digest: str
    ) -> Tuple[str, Optional[Dict]]:
        """Link the proven Google identity to the account that started the flow.

        Only the same user and the same, still valid session that started the
        flow can finish it, so a victim who completes an attacker's link flow
        in their own browser cannot attach their Google account to the
        attacker's account. Returns ("ok", user) or ("invalid" | "conflict" |
        "already_linked", None). Never merges accounts, never changes the
        primary email or admin rights.
        """

        with self.get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT id, user_id, session_digest, google_sub FROM oauth_flows
                     WHERE link_code_digest = %(code)s AND purpose = 'link'
                       AND callback_at IS NOT NULL AND completed_at IS NULL
                       AND expires_at > NOW()
                     FOR UPDATE
                    """,
                    {"code": link_code_digest},
                )
                flow = cursor.fetchone()
                if (
                    not flow
                    or flow["user_id"] != user_id
                    or flow["session_digest"] != session_digest
                    or not flow["google_sub"]
                ):
                    conn.rollback()
                    return "invalid", None
                cursor.execute(
                    "SELECT 1 FROM user_sessions WHERE token = %(s)s AND user_id = %(u)s "
                    "AND expires_at > NOW()",
                    {"s": session_digest, "u": user_id},
                )
                if not cursor.fetchone():
                    conn.rollback()
                    return "invalid", None
                cursor.execute(
                    "SELECT id FROM users WHERE google_sub = %(sub)s", {"sub": flow["google_sub"]}
                )
                owner = cursor.fetchone()
                if owner and owner["id"] != user_id:
                    conn.rollback()
                    return "conflict", None
                cursor.execute(
                    "SELECT google_sub FROM users WHERE id = %(id)s FOR UPDATE", {"id": user_id}
                )
                current = cursor.fetchone()
                if current["google_sub"] and current["google_sub"] != flow["google_sub"]:
                    conn.rollback()
                    return "already_linked", None
                cursor.execute(
                    f"""
                    UPDATE users SET google_sub = %(sub)s, updated_at = NOW()
                     WHERE id = %(id)s
                    RETURNING {self._USER_COLUMNS}
                    """,
                    {"sub": flow["google_sub"], "id": user_id},
                )
                user = cursor.fetchone()
                cursor.execute(
                    "UPDATE oauth_flows SET completed_at = NOW() WHERE id = %(id)s",
                    {"id": flow["id"]},
                )
                conn.commit()
                return "ok", dict(user)

    def touch_user_login(self, user_id: int) -> None:
        with self.get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    UPDATE users
                    SET last_login = NOW(), updated_at = NOW()
                    WHERE id = %(user_id)s
                    """,
                    {"user_id": user_id},
                )
                conn.commit()

    def create_user_session(self, token: str, user_id: int, expires_at: datetime) -> None:
        with self.get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO user_sessions (token, user_id, expires_at)
                    VALUES (%(token)s, %(user_id)s, %(expires_at)s)
                    ON CONFLICT (token) DO UPDATE
                    SET user_id = EXCLUDED.user_id,
                        expires_at = EXCLUDED.expires_at,
                        created_at = NOW()
                    """,
                    {
                        "token": token,
                        "user_id": user_id,
                        "expires_at": expires_at,
                    },
                )
                conn.commit()

    def get_session(self, token: str) -> Optional[Dict]:
        with self.get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT 
                        s.token,
                        s.user_id,
                        s.expires_at,
                        u.email,
                        u.plan,
                        u.subscription_status,
                        u.subscription_renewal,
                        u.trial_used,
                        u.full_name,
                        u.avatar_url,
                        u.is_admin,
                        u.email_verified_at
                    FROM user_sessions s
                    JOIN users u ON u.id = s.user_id
                    WHERE s.token = %(token)s
                    """,
                    {"token": token},
                )
                row = cursor.fetchone()
                if not row:
                    return None
                return dict(row)

    def set_user_admin(self, user_id: int, is_admin: bool = True) -> None:
        with self.get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    UPDATE users
                    SET is_admin = %(is_admin)s, updated_at = NOW()
                    WHERE id = %(user_id)s
                    """,
                    {"user_id": user_id, "is_admin": is_admin},
                )
                conn.commit()

    def delete_session(self, token: str) -> None:
        with self.get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    "DELETE FROM user_sessions WHERE token = %(token)s",
                    {"token": token},
                )
                conn.commit()

    def purge_expired_sessions(self) -> None:
        with self.get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    "DELETE FROM user_sessions WHERE expires_at < NOW()"
                )
                conn.commit()

    # ----------------------------
    # Billing & subscriptions
    # ----------------------------

    def list_subscription_plans(self, active_only: bool = True) -> list[Dict]:
        with self.get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT code, name, price_inr, interval_days, trial_days, features, is_active, rank
                    FROM subscription_plans
                    WHERE (%(active_only)s = false OR is_active = true)
                    ORDER BY rank, price_inr
                    """,
                    {"active_only": active_only},
                )
                return [dict(row) for row in cursor.fetchall()]

    def get_subscription_plan(self, code: str) -> Optional[Dict]:
        with self.get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT code, name, price_inr, interval_days, trial_days, features, is_active, rank
                    FROM subscription_plans
                    WHERE code = %(code)s
                    """,
                    {"code": code},
                )
                row = cursor.fetchone()
                return dict(row) if row else None

    def create_razorpay_order(
        self,
        *,
        user_id: int,
        order_id: str,
        amount: int,
        currency: str,
        status: str,
        payload: Dict[str, Any],
        plan_code: Optional[str] = None,
        interval_days: Optional[int] = None,
        list_amount: Optional[int] = None,
        credit_amount: int = 0,
        priced_at: Optional[datetime] = None,
        price_valid_until: Optional[datetime] = None,
        credit_version: Optional[int] = None,
        credit_detail: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Store an order with its fixed terms; pricing terms (D-030) only on insert."""

        with self.get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO razorpay_orders (
                        order_id, user_id, amount, currency, status, payload, plan_code, interval_days,
                        list_amount, credit_amount, priced_at, price_valid_until, credit_version, credit_detail
                    ) VALUES (
                        %(order_id)s, %(user_id)s, %(amount)s, %(currency)s, %(status)s, %(payload)s,
                        %(plan_code)s, %(interval_days)s, %(list_amount)s, %(credit_amount)s, %(priced_at)s,
                        %(price_valid_until)s, %(credit_version)s, %(credit_detail)s
                    )
                    ON CONFLICT (order_id) DO UPDATE
                    SET status = EXCLUDED.status,
                        payload = EXCLUDED.payload,
                        updated_at = NOW()
                    """,
                    {
                        "order_id": order_id,
                        "user_id": user_id,
                        "amount": amount,
                        "currency": currency,
                        "status": status,
                        "payload": Json(payload),
                        "plan_code": plan_code,
                        "interval_days": interval_days,
                        "list_amount": list_amount,
                        "credit_amount": int(credit_amount),
                        "priced_at": priced_at,
                        "price_valid_until": price_valid_until,
                        "credit_version": credit_version,
                        "credit_detail": None if credit_detail is None else Json(credit_detail),
                    },
                )
                conn.commit()

    _ORDER_COLUMNS = (
        "order_id, user_id, amount, currency, status, payload, plan_code, interval_days, payment_id, "
        "list_amount, credit_amount, priced_at, price_valid_until, credit_version, credit_detail, refund_due_reason"
    )

    def get_razorpay_order(self, order_id: str) -> Optional[Dict]:
        with self.get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    f"""
                    SELECT {self._ORDER_COLUMNS}
                    FROM razorpay_orders
                    WHERE order_id = %(order_id)s
                    """,
                    {"order_id": order_id},
                )
                row = cursor.fetchone()
                return dict(row) if row else None

    def record_payment_event(
        self,
        *,
        user_id: Optional[int],
        provider: str,
        event_type: str,
        event_id: Optional[str],
        payload: Dict[str, Any],
    ) -> bool:
        """Store a payment event.

        Returns False when an event with the same ``(provider, event_id)`` was
        already recorded, so callers can skip re-applying its side effects.
        """

        with self.get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO payment_events (
                        user_id, provider, event_type, event_id, payload
                    ) VALUES (
                        %(user_id)s, %(provider)s, %(event_type)s, %(event_id)s, %(payload)s
                    )
                    ON CONFLICT (provider, event_id) DO NOTHING
                    """,
                    {
                        "user_id": user_id,
                        "provider": provider,
                        "event_type": event_type,
                        "event_id": event_id,
                        "payload": Json(payload),
                    },
                )
                inserted = (cursor.rowcount or 0) > 0
                conn.commit()
                return inserted

    # ------------------------------------------------------------------
    # Subscription grants (D-024). Every write below runs in ONE transaction
    # that first locks the user row, so settlements, refunds, trials and
    # projection refreshes for a user are serialised. Times come from the
    # database clock taken after the lock, so allocation order is the order
    # in which grants were actually allocated. ``project`` is
    # api.billing.project, passed in to keep this layer free of API imports.
    # ------------------------------------------------------------------

    _GRANT_COLUMNS = (
        "id, user_id, plan_code, source, order_id, duration, allocated_at, refunded_amount, revoked_at"
    )
    _CLAIMABLE_ORDER_STATES = ("created", "attempted")

    def get_subscription_grants(self, user_id: int) -> List[Dict]:
        with self.get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    f"SELECT {self._GRANT_COLUMNS} FROM subscription_grants "
                    "WHERE user_id = %(user_id)s ORDER BY allocated_at, id",
                    {"user_id": user_id},
                )
                return [dict(row) for row in cursor.fetchall()]

    def _lock_user_grants(self, cursor, user_id: int) -> Tuple[Optional[Dict], List[Dict], datetime]:
        cursor.execute(
            "SELECT id, trial_used FROM users WHERE id = %(id)s FOR UPDATE", {"id": user_id}
        )
        user = cursor.fetchone()
        cursor.execute(
            f"SELECT {self._GRANT_COLUMNS} FROM subscription_grants "
            "WHERE user_id = %(user_id)s ORDER BY allocated_at, id",
            {"user_id": user_id},
        )
        grants = [dict(row) for row in cursor.fetchall()]
        cursor.execute("SELECT clock_timestamp() AS now")
        now = cursor.fetchone()["now"]
        return (dict(user) if user else None), grants, now

    @staticmethod
    def _credit_funding(cursor, user_id: int) -> Dict[str, Dict]:
        """Funding facts of the user's paid orders, for upgrade credit (D-030).

        refunded: processed refunds of the funding payment (payment_refunds is
        the record; grant.refunded_amount is a copy). refund_pending: an open
        billing item names the order or the payment, or a refund request for
        the payment is not settled (best effort from what this app recorded).
        """

        cursor.execute(
            """
            SELECT o.order_id, o.amount, o.currency, o.status, o.payment_id,
                   COALESCE((SELECT SUM(r.amount) FROM payment_refunds r WHERE r.payment_id = o.payment_id), 0)
                       AS refunded,
                   (EXISTS (SELECT 1 FROM billing_tracked t WHERE t.resolved_at IS NULL
                                AND (t.order_id = o.order_id OR t.provider_id = o.payment_id))
                    OR EXISTS (SELECT 1 FROM refund_actions a WHERE a.payment_id = o.payment_id
                                AND a.obligation_settled_at IS NULL)) AS refund_pending
            FROM razorpay_orders o
            WHERE o.user_id = %(u)s AND o.payment_id IS NOT NULL
            """,
            {"u": user_id},
        )
        return {row["order_id"]: {**dict(row), "refunded": int(row["refunded"])} for row in cursor.fetchall()}

    def get_credit_funding(self, user_id: int) -> Dict[str, Dict]:
        with self.get_connection() as conn:
            with conn.cursor() as cursor:
                return self._credit_funding(cursor, user_id)

    def quote_upgrade(
        self, user_id: int, quote: Callable[[List[Dict], Dict[str, Dict], datetime], Optional[Dict]]
    ) -> Tuple[Optional[Dict], datetime]:
        """Run ``quote(grants, funding, now)`` on one consistent, locked read; writes nothing.

        The lock is released before the caller talks to the payment provider.
        """

        with self.get_connection() as conn:
            with conn.cursor() as cursor:
                _, grants, now = self._lock_user_grants(cursor, user_id)
                result = quote(grants, self._credit_funding(cursor, user_id), now)
                conn.rollback()
                return result, now

    @staticmethod
    def _write_projection(cursor, user_id: int, projection: Dict, *, trial_used: Optional[bool] = None) -> None:
        cursor.execute(
            """
            UPDATE users
            SET plan = %(plan)s,
                subscription_status = %(subscription_status)s,
                subscription_renewal = %(subscription_renewal)s,
                plan_started_at = %(plan_started_at)s,
                trial_used = COALESCE(%(trial_used)s, trial_used),
                updated_at = NOW()
            WHERE id = %(user_id)s
            """,
            {**projection, "trial_used": trial_used, "user_id": user_id},
        )

    @staticmethod
    def _insert_payment_event(cursor, *, user_id, event_type, event_id, payload) -> bool:
        cursor.execute(
            """
            INSERT INTO payment_events (user_id, provider, event_type, event_id, payload)
            VALUES (%(user_id)s, 'razorpay', %(event_type)s, %(event_id)s, %(payload)s)
            ON CONFLICT (provider, event_id) DO NOTHING
            """,
            {"user_id": user_id, "event_type": event_type, "event_id": event_id, "payload": Json(payload)},
        )
        return (cursor.rowcount or 0) > 0

    def settle_razorpay_order(
        self,
        *,
        order_id: str,
        payment_id: str,
        expected_user_id: Optional[int],
        event_type: str,
        payload: Dict[str, Any],
        project: Callable[[List[Dict], datetime], Dict],
        lifetime_held: Callable[[List[Dict]], bool],
        payment_created_at: Optional[int] = None,
        credit_refusal: Optional[Callable[[Dict, List[Dict], Dict[str, Dict], int], Optional[str]]] = None,
    ) -> Tuple[str, Optional[Dict]]:
        """Turn a captured payment into a grant, exactly once.

        Claim, grant, event and projection commit together, so a crash leaves
        the order claimable instead of "paid without access". Returns one of
        ("granted", projection), ("settled", order) when already settled,
        ("missing", None) for an unknown or foreign order,
        ("refund_due", order) when Lifetime already covers the user or a
        credited order's terms no longer hold (the payment is kept on record
        for a refund of the charged amount, no time is granted;
        order["refund_due_reason"] says why), ("retry", order) when a
        credited order's payment attempt time is unknown (nothing changes; the
        caller or the reconciler tries again with the payment entity), and
        ("refunded_payment", order) when this payment was already fully
        refunded before settlement.

        Credited orders (credit_version set, D-030) also need
        ``payment_created_at`` (the attempt's provider creation time, epoch
        seconds) and ``credit_refusal`` (api.billing.credit_refusal); orders
        without credit_version settle exactly as before.
        """

        with self.get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    f"SELECT {self._ORDER_COLUMNS} FROM razorpay_orders WHERE order_id = %(order_id)s FOR UPDATE",
                    {"order_id": order_id},
                )
                order = cursor.fetchone()
                if not order or (expected_user_id is not None and order["user_id"] != expected_user_id):
                    conn.rollback()
                    return "missing", None
                order = dict(order)
                if order["status"] not in self._CLAIMABLE_ORDER_STATES:
                    conn.rollback()
                    return "settled", order
                user_id = order["user_id"]
                _, grants, now = self._lock_user_grants(cursor, user_id)
                event = {"user_id": user_id, "event_type": event_type, "event_id": payment_id, "payload": payload}
                cursor.execute(
                    "SELECT COALESCE(SUM(amount), 0) AS total FROM payment_refunds WHERE payment_id = %(p)s",
                    {"p": payment_id},
                )
                if int(cursor.fetchone()["total"]) >= int(order["amount"]):
                    # Refunded before we settled it: this payment can never fund
                    # the order; another attempt still can (D-025).
                    self._insert_payment_event(cursor, **event)
                    conn.commit()
                    return "refunded_payment", order
                reason = "lifetime_held" if lifetime_held(grants) else None
                if reason is None and order["credit_version"] is not None:
                    if payment_created_at is None or credit_refusal is None:
                        conn.rollback()  # never price by processing time
                        return "retry", order
                    reason = credit_refusal(order, grants, self._credit_funding(cursor, user_id), payment_created_at)
                if reason is not None:
                    cursor.execute(
                        "UPDATE razorpay_orders SET status = 'refund_due', payment_id = %(p)s, "
                        "refund_due_reason = %(r)s, updated_at = NOW() WHERE order_id = %(o)s",
                        {"p": payment_id, "r": reason, "o": order_id},
                    )
                    self._insert_payment_event(cursor, **event)
                    conn.commit()
                    return "refund_due", {**order, "status": "refund_due", "refund_due_reason": reason}
                interval_days = int(order["interval_days"] or 0)
                cursor.execute(
                    f"""
                    INSERT INTO subscription_grants (user_id, plan_code, source, order_id, duration, allocated_at)
                    VALUES (%(user_id)s, %(plan_code)s, 'razorpay', %(order_id)s, %(duration)s, %(now)s)
                    RETURNING {self._GRANT_COLUMNS}
                    """,
                    {
                        "user_id": user_id,
                        "plan_code": order["plan_code"],
                        "order_id": order_id,
                        "duration": timedelta(days=interval_days) if interval_days > 0 else None,
                        "now": now,
                    },
                )
                grants.append(dict(cursor.fetchone()))
                cursor.execute(
                    "UPDATE razorpay_orders SET status = 'paid', payment_id = %(p)s, updated_at = NOW() "
                    "WHERE order_id = %(o)s",
                    {"p": payment_id, "o": order_id},
                )
                self._insert_payment_event(cursor, **event)
                projection = project(grants, now)
                # Any purchase consumes the free trial.
                self._write_projection(cursor, user_id, projection, trial_used=True)
                conn.commit()
                return "granted", {**projection, "granted_plan": order["plan_code"]}

    def refund_razorpay_payment(
        self,
        *,
        order_id: Optional[str],
        payment_id: Optional[str],
        refund_id: str,
        refund_amount: int,
        event_type: str,
        payload: Dict[str, Any],
        project: Callable[[List[Dict], datetime], Dict],
    ) -> Tuple[str, Optional[Dict]]:
        """Record one processed refund and apply it to the payment it refunds (D-025).

        Each refund is stored once, by refund id, against its own payment;
        totals are the sum of those rows, never a mix of per-refund deltas and
        Razorpay's cumulative snapshot (which double-counted). Access changes
        only when the refunded payment is the one that funded the order's
        grant (razorpay_orders.payment_id) and its processed refunds reach the
        order amount: a refund of another attempt on the same order, or a
        partial refund, never revokes the plan the funding payment bought.

        Returns ("revoked" | "partial", projection), ("duplicate", None),
        ("other_payment", order) for a refund of a payment that did not fund
        the order, ("unsettled", order) when the order has no funding payment
        yet (the refunded payment can then never fund it: see
        settle_razorpay_order), ("refund_due_closed", order) when a refund_due
        payment is fully refunded, ("needs_review", order) for a pre-ledger
        grant whose funding payment is unknown, or ("unknown", None).

        When the refunded payment funded part of a settled credited order's
        credit (D-030), a 'credit_conflict' billing item is opened in the same
        transaction and the projection carries "credit_conflicts" (those
        orders' ids) so the caller alerts; access changes only as above.
        """

        with self.get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    "SELECT order_id, user_id, amount, status, payment_id FROM razorpay_orders "
                    "WHERE order_id = %(o)s OR (%(p)s::text IS NOT NULL AND payment_id = %(p)s) "
                    "ORDER BY (order_id = %(o)s) DESC LIMIT 1 FOR UPDATE",
                    {"o": order_id, "p": payment_id},
                )
                order = cursor.fetchone()
                if not order:
                    conn.rollback()
                    return "unknown", None
                order = dict(order)
                user_id = order["user_id"]
                _, grants, now = self._lock_user_grants(cursor, user_id)
                cursor.execute(
                    """
                    INSERT INTO payment_refunds (refund_id, payment_id, order_id, amount)
                    VALUES (%(r)s, %(p)s, %(o)s, %(a)s)
                    ON CONFLICT (refund_id) DO NOTHING
                    """,
                    {"r": refund_id, "p": payment_id, "o": order["order_id"], "a": int(refund_amount)},
                )
                if not (cursor.rowcount or 0):
                    conn.rollback()
                    return "duplicate", None
                self._insert_payment_event(
                    cursor, user_id=user_id, event_type=event_type, event_id=refund_id, payload=payload
                )
                funding = order["payment_id"]
                if funding is None:
                    grant = next((g for g in grants if g["order_id"] == order["order_id"]), None)
                    conn.commit()
                    # No funding payment recorded: either nothing was granted yet
                    # (this payment can no longer fund the order), or a pre-ledger
                    # grant whose funding payment is unknown (review by hand).
                    return ("needs_review" if grant else "unsettled"), order
                if payment_id and payment_id != funding:
                    conn.commit()
                    return "other_payment", order
                cursor.execute(
                    "SELECT COALESCE(SUM(amount), 0) AS total FROM payment_refunds WHERE payment_id = %(p)s",
                    {"p": funding},
                )
                total = int(cursor.fetchone()["total"])
                full = total >= int(order["amount"])
                if order["status"] == "refund_due":
                    if full:
                        cursor.execute(
                            "UPDATE razorpay_orders SET status = 'refunded', updated_at = NOW() WHERE order_id = %(o)s",
                            {"o": order["order_id"]},
                        )
                    conn.commit()
                    return ("refund_due_closed" if full else "partial"), order
                grant = next((g for g in grants if g["order_id"] == order["order_id"]), None)
                if grant is None:
                    conn.commit()
                    return "needs_review", order
                revoke = full and grant["revoked_at"] is None
                cursor.execute(
                    "UPDATE subscription_grants SET refunded_amount = %(t)s, "
                    "revoked_at = CASE WHEN %(r)s THEN %(now)s ELSE revoked_at END WHERE id = %(id)s",
                    {"t": total, "r": revoke, "now": now, "id": grant["id"]},
                )
                grant["refunded_amount"] = total
                if revoke:
                    grant["revoked_at"] = now
                    cursor.execute(
                        "UPDATE razorpay_orders SET status = 'refunded', updated_at = NOW() WHERE order_id = %(o)s",
                        {"o": order["order_id"]},
                    )
                projection = project(grants, now)
                self._write_projection(cursor, user_id, projection)
                # The credit a settled upgrade took from this payment is not
                # clawed back (maintainer decision, D-030): open an item for a human.
                cursor.execute(
                    "SELECT order_id FROM razorpay_orders WHERE user_id = %(u)s AND credit_version IS NOT NULL "
                    "AND status = 'paid' AND credit_detail -> 'sources' @> %(src)s ORDER BY order_id",
                    {"u": user_id, "src": Json([{"payment_id": funding}])},
                )
                conflicts = [row["order_id"] for row in cursor.fetchall()]
                if conflicts:
                    cursor.execute(
                        """
                        INSERT INTO billing_tracked (kind, provider_id, order_id, reason, last_status, last_notified_at)
                        VALUES ('credit_conflict', %(r)s, %(o)s, 'credit_conflict', %(s)s, NOW())
                        ON CONFLICT (kind, provider_id) DO NOTHING
                        """,
                        {"r": refund_id, "o": conflicts[0], "s": f"refund of {funding} ({total} paise in total)"},
                    )
                    projection = {**projection, "credit_conflicts": conflicts}
                conn.commit()
                return ("revoked" if revoke else "partial"), projection

    def start_trial_grant(
        self,
        *,
        user_id: int,
        plan_code: str,
        trial_days: int,
        project: Callable[[List[Dict], datetime], Dict],
    ) -> Tuple[str, Optional[Dict]]:
        """Grant the one free trial. Returns ("started", projection), ("used", None) or ("active", None)."""

        with self.get_connection() as conn:
            with conn.cursor() as cursor:
                user, grants, now = self._lock_user_grants(cursor, user_id)
                if not user or user["trial_used"]:
                    conn.rollback()
                    return "used", None
                if project(grants, now)["plan"] != "free":
                    conn.rollback()
                    return "active", None
                cursor.execute(
                    f"""
                    INSERT INTO subscription_grants (user_id, plan_code, source, duration, allocated_at)
                    VALUES (%(user_id)s, %(plan_code)s, 'trial', %(duration)s, %(now)s)
                    RETURNING {self._GRANT_COLUMNS}
                    """,
                    {"user_id": user_id, "plan_code": plan_code, "duration": timedelta(days=trial_days), "now": now},
                )
                grants.append(dict(cursor.fetchone()))
                projection = project(grants, now)
                self._write_projection(cursor, user_id, projection, trial_used=True)
                conn.commit()
                return "started", projection

    def refresh_entitlement(
        self, user_id: int, project: Callable[[List[Dict], datetime], Dict]
    ) -> Dict:
        """Rewrite the projection from the grants (after a period ends)."""

        with self.get_connection() as conn:
            with conn.cursor() as cursor:
                _, grants, now = self._lock_user_grants(cursor, user_id)
                projection = project(grants, now)
                self._write_projection(cursor, user_id, projection)
                conn.commit()
                return projection

    def bind_legacy_payment(
        self, *, order_id: str, payment_id: str, project: Callable[[List[Dict], datetime], Dict]
    ) -> Tuple[str, Optional[Dict]]:
        """Record the funding payment of a pre-ledger purchase, then apply its refunds.

        The caller has verified at Razorpay that this payment is the only
        attempt of the order that ever succeeded, for the order's terms. In one
        transaction (order row, then user, as everywhere else) the order gets
        its payment_id, and refunds already recorded for that payment are
        applied to the legacy grant (they were held for review until now).
        Returns ("bound", projection), ("already_bound", order) or
        ("no_legacy_grant", order).
        """

        with self.get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    "SELECT order_id, user_id, amount, status, payment_id FROM razorpay_orders "
                    "WHERE order_id = %(o)s FOR UPDATE",
                    {"o": order_id},
                )
                order = cursor.fetchone()
                if not order:
                    conn.rollback()
                    return "no_legacy_grant", None
                order = dict(order)
                if order["payment_id"] is not None:
                    conn.rollback()
                    return "already_bound", order
                _, grants, now = self._lock_user_grants(cursor, order["user_id"])
                grant = next(
                    (g for g in grants if g["order_id"] == order_id and g["source"] == "legacy"), None
                )
                if grant is None:
                    conn.rollback()
                    return "no_legacy_grant", order
                cursor.execute(
                    "UPDATE razorpay_orders SET payment_id = %(p)s, updated_at = NOW() WHERE order_id = %(o)s",
                    {"p": payment_id, "o": order_id},
                )
                cursor.execute(
                    "SELECT COALESCE(SUM(amount), 0) AS total FROM payment_refunds WHERE payment_id = %(p)s",
                    {"p": payment_id},
                )
                total = int(cursor.fetchone()["total"])
                revoke = total >= int(order["amount"]) and grant["revoked_at"] is None
                cursor.execute(
                    "UPDATE subscription_grants SET refunded_amount = %(t)s, "
                    "revoked_at = CASE WHEN %(r)s THEN %(now)s ELSE revoked_at END WHERE id = %(id)s",
                    {"t": total, "r": revoke, "now": now, "id": grant["id"]},
                )
                grant["refunded_amount"] = total
                if revoke:
                    grant["revoked_at"] = now
                    cursor.execute(
                        "UPDATE razorpay_orders SET status = 'refunded', updated_at = NOW() WHERE order_id = %(o)s",
                        {"o": order_id},
                    )
                projection = project(grants, now)
                self._write_projection(cursor, order["user_id"], projection)
                conn.commit()
                return "bound", projection

    # --- payment reconciler state (jobs/reconcile_payments.py, D-025) --------

    def first_order_created_at(self) -> Optional[datetime]:
        with self.get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute("SELECT MIN(created_at) AS first FROM razorpay_orders")
                return cursor.fetchone()["first"]

    def get_reconcile_state(self) -> Dict:
        with self.get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute("INSERT INTO billing_reconcile_state (id) VALUES (1) ON CONFLICT (id) DO NOTHING")
                cursor.execute("SELECT * FROM billing_reconcile_state WHERE id = 1")
                row = dict(cursor.fetchone())
                conn.commit()
                return row

    def save_reconcile_progress(
        self,
        *,
        checkpoints: Optional[Dict[str, datetime]] = None,
        audit_before: Optional[datetime] = None,
        error: Optional[str] = None,
        success: bool = False,
    ) -> None:
        """Checkpoints only move forward (GREATEST); success clears last_error."""

        checkpoints = checkpoints or {}
        with self.get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    UPDATE billing_reconcile_state SET
                        payments_checkpoint = GREATEST(payments_checkpoint, %(payments)s),
                        refunds_checkpoint = GREATEST(refunds_checkpoint, %(refunds)s),
                        audit_before = COALESCE(%(audit)s, audit_before),
                        last_success_at = CASE WHEN %(ok)s THEN NOW() ELSE last_success_at END,
                        last_error = CASE WHEN %(ok)s THEN NULL ELSE COALESCE(%(error)s, last_error) END,
                        updated_at = NOW()
                    WHERE id = 1
                    """,
                    {
                        "payments": checkpoints.get("payments"),
                        "refunds": checkpoints.get("refunds"),
                        "audit": audit_before,
                        "ok": success,
                        "error": error,
                    },
                )
                conn.commit()

    def track_billing_item(
        self,
        *,
        kind: str,
        provider_id: str,
        order_id: Optional[str],
        reason: str,
        last_status: Optional[str],
        recheck_after_seconds: int,
    ) -> Dict:
        """Open (or reopen and reclassify) a tracked item; returns the row."""

        with self.get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO billing_tracked (kind, provider_id, order_id, reason, last_status, next_check_at)
                    VALUES (%(k)s, %(p)s, %(o)s, %(r)s, %(s)s, NOW() + make_interval(secs => %(after)s))
                    ON CONFLICT (kind, provider_id) DO UPDATE SET
                        order_id = COALESCE(EXCLUDED.order_id, billing_tracked.order_id),
                        reason = EXCLUDED.reason,
                        last_status = EXCLUDED.last_status,
                        attempts = billing_tracked.attempts + 1,
                        last_checked = NOW(),
                        -- Never retired by age: after a week, looked at daily (D-025).
                        next_check_at = CASE WHEN billing_tracked.first_seen < NOW() - INTERVAL '7 days'
                            THEN NOW() + make_interval(secs => GREATEST(%(after)s, 86400))
                            ELSE EXCLUDED.next_check_at END,
                        resolved_at = NULL
                    RETURNING *
                    """,
                    {"k": kind, "p": provider_id, "o": order_id, "r": reason, "s": last_status,
                     "after": recheck_after_seconds},
                )
                row = dict(cursor.fetchone())
                conn.commit()
                return row

    def resolve_billing_item(self, kind: str, provider_id: str) -> None:
        with self.get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    "UPDATE billing_tracked SET resolved_at = NOW(), last_checked = NOW() "
                    "WHERE kind = %(k)s AND provider_id = %(p)s AND resolved_at IS NULL",
                    {"k": kind, "p": provider_id},
                )
                conn.commit()

    def mark_billing_notified(self, kind: str, provider_id: str) -> None:
        with self.get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    "UPDATE billing_tracked SET last_notified_at = NOW() WHERE kind = %(k)s AND provider_id = %(p)s",
                    {"k": kind, "p": provider_id},
                )
                conn.commit()

    def due_billing_items(self, limit: int) -> List[Dict]:
        with self.get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    # credit_conflict items wait for a human; nothing to re-check at Razorpay.
                    "SELECT * FROM billing_tracked WHERE resolved_at IS NULL AND next_check_at <= NOW() "
                    "AND kind <> 'credit_conflict' ORDER BY next_check_at LIMIT %(n)s",
                    {"n": limit},
                )
                return [dict(row) for row in cursor.fetchall()]

    # --- automatic refunds (D-025, PR C) -------------------------------------

    _ACTION_COLUMNS = (
        "id, payment_id, order_id, reason, amount, currency, idempotency_key, request_body, state, "
        "provider_refund_id, attempts, next_attempt_at, last_error, obligation_settled_at"
    )
    # Monotonic: a state may only move to a later one; failed / blocked only
    # from requested or created; processed is final.
    _ACTION_RANK = {"requested": 0, "created": 1, "failed": 2, "blocked": 2, "processed": 3}

    def create_refund_intent(
        self, *, payment_id: str, order_id: str, reason: str, amount: int, currency: str,
        idempotency_key: str, request_body: Dict[str, Any],
    ) -> Tuple[str, Optional[Dict]]:
        """Re-check eligibility under the order lock and persist the refund intent.

        duplicate: the order was settled by a different, known payment.
        refund_due: the order is refund_due and this payment funds it.
        Both: amount and currency equal the order's. Returns ("created" |
        "existing", action) or ("ineligible", None); the existing row is
        returned unchanged (its key and body never change).
        """

        with self.get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    "SELECT order_id, amount, currency, status, payment_id FROM razorpay_orders "
                    "WHERE order_id = %(o)s FOR UPDATE",
                    {"o": order_id},
                )
                order = cursor.fetchone()
                cursor.execute(
                    f"SELECT {self._ACTION_COLUMNS} FROM refund_actions WHERE payment_id = %(p)s",
                    {"p": payment_id},
                )
                existing = cursor.fetchone()
                if existing:
                    conn.rollback()
                    return "existing", dict(existing)
                terms = (
                    order is not None
                    and int(order["amount"]) == int(amount)
                    and str(order["currency"] or "INR").upper() == str(currency).upper()
                )
                funding = order["payment_id"] if order else None
                eligible = terms and (
                    (reason == "duplicate" and order["status"] in ("paid", "refunded", "refund_due")
                     and funding is not None and funding != payment_id)
                    or (reason == "refund_due" and order["status"] == "refund_due" and funding == payment_id)
                )
                if not eligible:
                    conn.rollback()
                    return "ineligible", None
                cursor.execute(
                    f"""
                    INSERT INTO refund_actions
                        (payment_id, order_id, reason, amount, currency, idempotency_key, request_body)
                    VALUES (%(p)s, %(o)s, %(r)s, %(a)s, %(c)s, %(k)s, %(b)s)
                    RETURNING {self._ACTION_COLUMNS}
                    """,
                    {"p": payment_id, "o": order_id, "r": reason, "a": int(amount), "c": currency.upper(),
                     "k": idempotency_key, "b": Json(request_body)},
                )
                action = dict(cursor.fetchone())
                conn.commit()
                return "created", action

    def update_refund_action(
        self, action_id: int, *, state: Optional[str] = None, provider_refund_id: Optional[str] = None,
        error: Optional[str] = None, retry_after_seconds: Optional[int] = None,
    ) -> Dict:
        """Record an attempt's outcome; the state never moves backwards (see _ACTION_RANK)."""

        with self.get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    f"SELECT {self._ACTION_COLUMNS} FROM refund_actions WHERE id = %(id)s FOR UPDATE",
                    {"id": action_id},
                )
                action = dict(cursor.fetchone())
                current = action["state"]
                new_state = current
                if state and self._ACTION_RANK[state] > self._ACTION_RANK[current] and current not in (
                    "failed", "blocked", "processed"
                ):
                    new_state = state
                cursor.execute(
                    f"""
                    UPDATE refund_actions SET
                        state = %(s)s,
                        provider_refund_id = COALESCE(provider_refund_id, %(pr)s),
                        attempts = attempts + 1,
                        last_error = %(e)s,
                        next_attempt_at = NOW() + make_interval(secs => %(after)s),
                        updated_at = NOW()
                    WHERE id = %(id)s
                    RETURNING {self._ACTION_COLUMNS}
                    """,
                    {"s": new_state, "pr": provider_refund_id, "e": error,
                     "after": retry_after_seconds if retry_after_seconds is not None else 900, "id": action_id},
                )
                row = dict(cursor.fetchone())
                conn.commit()
                return row

    def get_refund_action(self, payment_id: str) -> Optional[Dict]:
        with self.get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    f"SELECT {self._ACTION_COLUMNS} FROM refund_actions WHERE payment_id = %(p)s",
                    {"p": payment_id},
                )
                row = cursor.fetchone()
                return dict(row) if row else None

    def refund_actions_due(self, limit: int) -> List[Dict]:
        with self.get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    f"SELECT {self._ACTION_COLUMNS} FROM refund_actions "
                    "WHERE state IN ('requested', 'created') AND obligation_settled_at IS NULL "
                    "AND next_attempt_at <= NOW() ORDER BY next_attempt_at LIMIT %(n)s",
                    {"n": limit},
                )
                return [dict(row) for row in cursor.fetchall()]

    def open_refund_obligations(self, limit: int) -> List[Dict]:
        """Open duplicate / refund_due payments that have no automatic refund yet."""

        with self.get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    "SELECT t.provider_id AS payment_id, t.order_id, t.reason FROM billing_tracked t "
                    "LEFT JOIN refund_actions a ON a.payment_id = t.provider_id "
                    "WHERE t.kind = 'payment' AND t.resolved_at IS NULL "
                    "AND t.reason IN ('duplicate', 'refund_due') AND a.id IS NULL "
                    "ORDER BY t.first_seen LIMIT %(n)s",
                    {"n": limit},
                )
                return [dict(row) for row in cursor.fetchall()]

    def sync_refund_action(self, payment_id: str) -> Dict[str, Any]:
        """Bring a payment's refund action and refund obligation up to date.

        Two separate facts, both from recorded processed refunds
        (payment_refunds), whatever path recorded them and whatever the refund
        methods returned: the automatic request is processed once its own
        provider refund is recorded; the obligation (a billing_tracked
        duplicate / refund_due item) is settled once this payment's distinct
        processed refunds reach its full amount, manual refunds included.
        """

        with self.get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    "SELECT COALESCE(SUM(amount), 0) AS total FROM payment_refunds WHERE payment_id = %(p)s",
                    {"p": payment_id},
                )
                total = int(cursor.fetchone()["total"])
                cursor.execute(
                    f"SELECT {self._ACTION_COLUMNS} FROM refund_actions WHERE payment_id = %(p)s FOR UPDATE",
                    {"p": payment_id},
                )
                action = cursor.fetchone()
                cursor.execute(
                    "SELECT t.order_id, o.amount FROM billing_tracked t "
                    "JOIN razorpay_orders o ON o.order_id = t.order_id "
                    "WHERE t.kind = 'payment' AND t.provider_id = %(p)s AND t.resolved_at IS NULL "
                    "AND t.reason IN ('duplicate', 'refund_due')",
                    {"p": payment_id},
                )
                tracked = cursor.fetchone()
                owed = int(action["amount"]) if action else (int(tracked["amount"]) if tracked else None)
                settled = owed is not None and total >= owed
                result = {"total_refunded": total, "obligation_settled": settled, "action_state": None}
                if action:
                    own = False
                    if action["provider_refund_id"]:
                        cursor.execute(
                            "SELECT 1 FROM payment_refunds WHERE refund_id = %(r)s",
                            {"r": action["provider_refund_id"]},
                        )
                        own = cursor.fetchone() is not None
                    cursor.execute(
                        f"""
                        UPDATE refund_actions SET
                            state = CASE WHEN %(own)s AND state IN ('requested', 'created') THEN 'processed' ELSE state END,
                            obligation_settled_at = CASE WHEN %(settled)s THEN COALESCE(obligation_settled_at, NOW())
                                                    ELSE obligation_settled_at END,
                            updated_at = NOW()
                        WHERE id = %(id)s
                        RETURNING state
                        """,
                        {"own": own, "settled": settled, "id": action["id"]},
                    )
                    result["action_state"] = cursor.fetchone()["state"]
                if settled:
                    cursor.execute(
                        "UPDATE billing_tracked SET resolved_at = NOW(), last_checked = NOW() "
                        "WHERE kind = 'payment' AND provider_id = %(p)s AND resolved_at IS NULL "
                        "AND reason IN ('duplicate', 'refund_due')",
                        {"p": payment_id},
                    )
                conn.commit()
                return result

    def read_reconcile_heartbeat(self) -> Dict[str, Any]:
        """Read-only: the reconciler's last success and its age by the database clock."""

        with self.get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    "SELECT last_success_at, EXTRACT(EPOCH FROM (NOW() - last_success_at)) AS age "
                    "FROM billing_reconcile_state WHERE id = 1"
                )
                row = cursor.fetchone()
                conn.rollback()
                return dict(row) if row else {"last_success_at": None, "age": None}

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

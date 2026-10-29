#!/usr/bin/env python3
"""Compliance-flip emails to the subscriber who watches the symbol (D-031).

One step of the evaluation scheduler (jobs/schedule_evaluations.py), run under
one session-level advisory lock so only one sender works at a time:

1. Observe every watched symbol (alerts/storage.py ``observe``).
2. Kill switch off (``ALERT_EMAILS_ENABLED=false``): every pending row is
   silently rebaselined, so nothing accumulates or replays on enable.
3. Otherwise, for each due pending row (fair order, per-user cap, global
   budget): re-check the source, then mail the user's own verified address
   only while they have paid access and have not opted out (else rebaseline
   silently), and acknowledge with a compare-and-set.

Delivery is at least once, never exactly once: a crash between the SMTP
hand-off and the acknowledgement resends the same Message-ID next run. Logs and
ops alerts carry counts and error classes only, never addresses.
"""

from __future__ import annotations

import hashlib
import logging
from collections import Counter
from contextlib import contextmanager
from typing import Any, Callable, Dict, Iterator, Optional

from alerts.storage import Key, WatchlistStorage
from api.billing import project

logger = logging.getLogger("alerts.delivery")

PER_USER_LIMIT = 5  # pending rows per user per run
SEND_BUDGET = 50  # rows per run, all users
MAX_ATTEMPTS = 5  # SMTP failures before the row stops (notify_failed_at)
RETRY_BASE_SECONDS = 15 * 60  # 15 min, 30 min, 1 h, 2 h between failures
DEFER_SECONDS = 60 * 60  # source unknown or blocked: look again in an hour
LOCK_KEY = (20261030, 1)  # pg_try_advisory_lock(int4, int4); own namespace

Send = Callable[..., None]  # send(to, subject, body, message_id=...)


def label(is_compliant: Optional[bool]) -> str:
    return "compliant" if is_compliant else "non-compliant"


def has_paid_access(entry: Dict[str, Any], grants) -> bool:
    """Paid access now, as the API grants it: admins, or any current grant (incl. a Lifetime overlay)."""

    return bool(entry.get("is_admin")) or project(grants, entry["now"])["plan"] != "free"


def message_id(key: Key, entry: Dict[str, Any], sender: str) -> str:
    """Stable per (watch row, observed evaluation): a resend is the same message."""

    seed = f"{key}|{entry['observed_evaluated_at'].isoformat() if entry['observed_evaluated_at'] else ''}"
    domain = sender.rsplit("@", 1)[-1] or "localhost"
    return f"<alert-{hashlib.sha256(seed.encode()).hexdigest()[:32]}@{domain}>"


def compose(symbol: str, before: Optional[bool], after: Optional[bool], entry: Dict[str, Any], base_url: str):
    filed = entry["observed_filing_date"]
    base = base_url.rstrip("/")
    subject = f"HalalLens: {symbol} is now {label(after)}"
    body = "\n".join([
        f"{symbol} changed from {label(before)} to {label(after)} on HalalLens.",
        "",
        f"Filing date: {filed.date().isoformat() if filed else 'unknown'}",
        f"Filing: {base}/analysis?symbol={symbol}",
        "",
        "This is an automated screen of the company's filed financials against",
        "AAOIFI-inspired ratios. It is not a fatwa and not investment advice.",
        "",
        f"Manage alerts: {base}/account",
    ])
    return subject, body


def run(storage: WatchlistStorage, get_grants: Callable[[int], Any], *, enabled: bool,
        send: Send, sender: str, base_url: str) -> Counter:
    """One sweep (caller holds the sender lock). Returns counts by outcome."""

    counts: Counter = Counter()
    for symbol in storage.watched_symbols():
        try:
            counts["flipped"] += len(storage.observe(symbol).flipped)
        except Exception as exc:  # fail closed: this symbol moves nothing this run
            counts["observe_error"] += 1
            counts[f"error:{type(exc).__name__}"] += 1
    if not enabled:
        counts["rebaselined"] += storage.rebaseline_all()
        return counts
    for key in storage.pending(PER_USER_LIMIT, SEND_BUDGET):
        try:
            counts[deliver(storage, get_grants, key, send=send, sender=sender, base_url=base_url, counts=counts)] += 1
        except Exception as exc:  # database trouble on one row must not stop the others
            counts["row_error"] += 1
            counts[f"error:{type(exc).__name__}"] += 1
    return counts


def deliver(storage: WatchlistStorage, get_grants: Callable[[int], Any], key: Key, *,
            send: Send, sender: str, base_url: str, counts: Counter) -> str:
    """Send one pending row, or say why not. Returns the outcome name."""

    user_id, symbol, _ = key
    try:
        source = storage.observe(symbol, user_id=user_id).is_compliant
    except Exception as exc:
        counts[f"error:{type(exc).__name__}"] += 1
        source = None
    entry = storage.entry(key)
    if entry is None:
        return "gone"  # unwatched or account deleted
    before, after = entry["notified_is_compliant"], entry["last_is_compliant"]
    if before is after:
        return "superseded"  # the verdict went back before we sent it
    if not (entry["email_verified_at"] and entry["alert_emails"] and has_paid_access(entry, get_grants(user_id))):
        storage.acknowledge(key, before, after)
        return "silenced"
    if source is None:
        # Unknown / under review / lookup failed: not an SMTP failure, but the
        # row moves to the back so it cannot starve the others.
        storage.defer(key, DEFER_SECONDS)
        return "deferred"
    subject, body = compose(symbol, before, after, entry, base_url)
    try:
        send(entry["email"], subject, body, message_id=message_id(key, entry, sender))
    except Exception as exc:
        attempts = entry["notify_attempts"] + 1
        storage.record_failure(key, before, after, RETRY_BASE_SECONDS * 2 ** (attempts - 1), attempts >= MAX_ATTEMPTS)
        counts[f"error:{type(exc).__name__}"] += 1
        return "failed" if attempts < MAX_ATTEMPTS else "failed_terminal"
    storage.acknowledge(key, before, after)
    return "sent"


@contextmanager
def sender_lock(db) -> Iterator[bool]:
    """Session-level advisory lock on its own connection (a pooled one could carry it to the next borrower)."""

    import psycopg2

    params = {k: v for k, v in db.connection_params.items() if k != "cursor_factory"}
    conn = psycopg2.connect(**params)
    conn.autocommit = True
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT pg_try_advisory_lock(%s, %s)", LOCK_KEY)
            acquired = cur.fetchone()[0]
            try:
                yield acquired
            finally:
                if acquired:
                    cur.execute("SELECT pg_advisory_unlock(%s, %s)", LOCK_KEY)
    finally:
        conn.close()


def run_locked(db, *, enabled: bool, send: Send, sender: str, base_url: str) -> Counter:
    """Run one sweep unless another sender holds the lock."""

    with sender_lock(db) as acquired:
        if not acquired:
            logger.info("Another alert sender holds the lock; skipping")
            return Counter(skipped_locked=1)
        storage = WatchlistStorage(lambda: db)
        return run(storage, db.get_subscription_grants, enabled=enabled, send=send, sender=sender, base_url=base_url)


def run_once() -> Counter:
    """The scheduler's entry point: production settings, its own small pool."""

    from api.mailer import send_email
    from config import ALERT_EMAIL_SENDER, ALERT_EMAILS_ENABLED, FRONTEND_BASE_URL
    from database.database_manager import BSEDatabaseManager

    db = BSEDatabaseManager(min_connections=1, max_connections=2)
    try:
        counts = run_locked(
            db, enabled=ALERT_EMAILS_ENABLED, send=send_email,
            sender=ALERT_EMAIL_SENDER or "", base_url=FRONTEND_BASE_URL,
        )
    finally:
        db.close()
    logger.info("Alert emails: %s", dict(counts) or "nothing to do")
    return counts


__all__ = ["run", "run_locked", "run_once", "deliver", "sender_lock"]

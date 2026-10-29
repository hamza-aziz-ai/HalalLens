#!/usr/bin/env python3
"""Reconcile Razorpay payments and refunds with the billing ledger (D-025).

Payments complete at Razorpay even while this server is down, and Razorpay
stops retrying a failing webhook after 24 hours. This job finds what the
webhook and the browser missed and applies it through the same locked
database methods. It only reads from Razorpay: refunds it decides are owed
(duplicate captures, Lifetime conflicts) are tracked for the automatic-refund
step (PR C) or a human.

Each run (one at a time, guarded by a Postgres advisory lock):
  1. refunds, then payments, created in [checkpoint - 30 min, now - 10 min]
     (bootstrap: the first local order; at most 7 days per run, so a long
     backlog catches up over several runs); a stream's checkpoint advances
     only after its whole window was applied or durably tracked;
  2. one older day re-swept as a historical audit;
  3. tracked items due for another look, fetched by id.
Discovery is best effort over Razorpay's list APIs (filtered by creation
time); completeness beyond the overlap and the audit is not guaranteed.

    python -m jobs.reconcile_payments          # one run
    python -m jobs.reconcile_payments --loop   # every RECONCILE_INTERVAL_MINUTES (15)
"""

from __future__ import annotations

import argparse
import logging
import os
import time
import traceback
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Dict, List, Optional

from api import billing
from api.razorpay_client import RazorpayClient, RazorpayError, payment_terms_match

logger = logging.getLogger("billing-reconcile")

LOCK_KEY = 4_221_250_025  # pg advisory lock id for this job
OVERLAP = timedelta(minutes=30)
LAG = timedelta(minutes=10)
MAX_WINDOW = timedelta(days=7)
AUDIT_DAY = timedelta(days=1)
FOLLOW_UP_BATCH = 50
FAST_RECHECK = 15 * 60      # pending items younger than a week
SLOW_RECHECK = 24 * 3600    # older pending items, and items waiting for a refund or a human
REALERT_AFTER = timedelta(days=1)
CLAIMABLE = ("created", "attempted")

# Reasons that need someone (PR C's automatic refunds, or the maintainer).
ALERT_REASONS = {"mismatch", "duplicate", "refund_due", "legacy_review", "failed_refund", "lookup_error"}


class Reconciler:
    """One reconciliation pass. ``db`` is BSEDatabaseManager (or the test fake)."""

    def __init__(self, db, client, notify: Callable[[str, str, Optional[str]], None]):
        self.db = db
        self.client = client
        self.notify = notify
        self.summary: Dict[str, int] = {}

    def _count(self, key: str) -> None:
        self.summary[key] = self.summary.get(key, 0) + 1

    # --- tracking ---------------------------------------------------------------

    def _track(self, kind, provider_id, order_id, reason, status, now) -> None:
        recheck = FAST_RECHECK if reason == "pending" else SLOW_RECHECK
        # Pending items are never retired by age; after a week the database
        # schedules them daily instead (track_billing_item).
        row = self.db.track_billing_item(
            kind=kind, provider_id=provider_id, order_id=order_id, reason=reason,
            last_status=status, recheck_after_seconds=recheck,
        )
        self._count(f"tracked_{reason}")
        notified = row.get("last_notified_at")
        if reason in ALERT_REASONS and (notified is None or now - notified >= REALERT_AFTER):
            self.notify(
                "error",
                f"Billing needs attention: {reason} ({kind} {provider_id}, order {order_id})",
                "See README_ops, Billing. Tracked in billing_tracked until resolved.",
            )
            self.db.mark_billing_notified(kind, provider_id)

    def _resolve(self, kind, provider_id) -> None:
        self.db.resolve_billing_item(kind, provider_id)

    def _webhook_missed(self, what: str) -> None:
        self._count("webhook_missed")
        self.notify(
            "warning",
            f"Reconciler applied {what}: a Razorpay webhook was missed",
            "Check the webhook's status in the Razorpay dashboard (it is disabled after 24 h of failures).",
        )

    # --- refunds ------------------------------------------------------------------

    def handle_refund(self, refund: Dict[str, Any], now: datetime) -> None:
        refund_id, payment_id, status = refund["id"], refund.get("payment_id"), refund.get("status")
        if status == "pending":
            self._track("refund", refund_id, None, "pending", status, now)
            return
        if status == "failed":
            self._track("refund", refund_id, None, "failed_refund", status, now)
            return
        if status != "processed" or not payment_id:
            self._track("refund", refund_id, None, "lookup_error", status, now)
            return
        payment = self.client.fetch_payment(payment_id)  # for its (immutable) order_id
        order = self.db.get_razorpay_order(payment.get("order_id")) if payment.get("order_id") else None
        if not order:
            self._resolve("refund", refund_id)  # not one of this app's orders
            return
        result, _ = self.db.refund_razorpay_payment(
            order_id=order["order_id"], payment_id=payment_id, refund_id=refund_id,
            refund_amount=int(refund.get("amount") or 0), event_type="reconcile.refund.processed",
            payload=refund, project=billing.project,
        )
        if result == "needs_review":
            result = self._bind_legacy(order, now) or result
        if result == "needs_review":
            self._track("refund", refund_id, order["order_id"], "legacy_review", status, now)
            return
        if result in ("revoked", "partial", "refund_due_closed"):
            self._webhook_missed(f"refund {refund_id} ({result})")
        if result == "refund_due_closed":
            self._resolve("payment", payment_id)
        self._resolve("refund", refund_id)

    def _sync_payment_refunds(self, payment: Dict[str, Any], order: Dict[str, Any], now) -> None:
        for refund in self.client.list_payment_refunds(payment["id"]):
            if refund.get("status") == "processed":
                self.db.refund_razorpay_payment(
                    order_id=order["order_id"], payment_id=payment["id"], refund_id=refund["id"],
                    refund_amount=int(refund.get("amount") or 0),
                    event_type="reconcile.refund.processed", payload=refund, project=billing.project,
                )
            elif refund.get("status") == "pending":
                self._track("refund", refund["id"], order["order_id"], "pending", "pending", now)

    # --- legacy binding -------------------------------------------------------------

    def _bind_legacy(self, order: Dict[str, Any], now) -> Optional[str]:
        """Bind a pre-ledger order to its funding payment when Razorpay proves which one it was."""

        attempts = self.client.list_order_payments(order["order_id"])
        succeeded = [p for p in attempts if p.get("status") in ("captured", "refunded")]
        if len(succeeded) != 1 or not payment_terms_match(succeeded[0], order):
            self._track("order", order["order_id"], order["order_id"], "legacy_review",
                        f"{len(succeeded)} successful attempts", now)
            return None
        payment = succeeded[0]
        self._sync_payment_refunds(payment, order, now)  # record its refunds first
        result, _ = self.db.bind_legacy_payment(
            order_id=order["order_id"], payment_id=payment["id"], project=billing.project
        )
        if result in ("bound", "already_bound"):
            self._count("legacy_bound")
            self._resolve("order", order["order_id"])
            return "bound"
        return None

    # --- payments ---------------------------------------------------------------------

    def handle_payment(self, payment: Dict[str, Any], now: datetime) -> None:
        payment_id, status = payment["id"], payment.get("status")
        order = self.db.get_razorpay_order(payment.get("order_id")) if payment.get("order_id") else None
        if not order:
            return  # not one of this app's orders (e.g. a razorpay.me link)
        order_id = order["order_id"]
        if status in ("created", "authorized"):
            self._track("payment", payment_id, order_id, "pending", status, now)
            return
        if status not in ("captured", "refunded"):  # failed: no money moved
            self._resolve("payment", payment_id)
            return
        if status == "refunded" or int(payment.get("amount_refunded") or 0) > 0:
            self._sync_payment_refunds(payment, order, now)  # refund evidence before any settle decision
            order = self.db.get_razorpay_order(order_id)
        if order["payment_id"] is None and order["status"] not in CLAIMABLE:
            if not self._bind_legacy(order, now):
                return
            order = self.db.get_razorpay_order(order_id)
        if status == "refunded":
            self._resolve("payment", payment_id)  # the money went back; nothing to grant or refund
            return
        if not payment_terms_match(payment, order):
            self._track("payment", payment_id, order_id, "mismatch", status, now)
            return
        if order["status"] in CLAIMABLE:
            result, info = self.db.settle_razorpay_order(
                order_id=order_id, payment_id=payment_id, expected_user_id=None,
                event_type="reconcile.payment.captured", payload=payment,
                project=billing.project, lifetime_held=billing.lifetime_held,
            )
            if result == "granted":
                self._webhook_missed(f"payment {payment_id} (granted)")
                self._resolve("payment", payment_id)
                return
            if result == "refunded_payment":
                self._resolve("payment", payment_id)
                return
            if result == "refund_due":
                self._track("payment", payment_id, order_id, "refund_due", status, now)
                return
            if result == "missing":
                return
            order = info  # "settled": classify the state the lock saw, not our earlier read
        self._classify_settled(payment_id, order, status, now)

    def _classify_settled(self, payment_id, order, status, now) -> None:
        funding = order.get("payment_id")
        if funding == payment_id:
            if order["status"] == "refund_due":
                self._track("payment", payment_id, order["order_id"], "refund_due", status, now)
            else:
                self._resolve("payment", payment_id)  # paid by this payment, or already refunded
        elif funding is None:
            self._track("payment", payment_id, order["order_id"], "legacy_review", status, now)
        else:
            self._track("payment", payment_id, order["order_id"], "duplicate", status, now)

    # --- the run -----------------------------------------------------------------------------

    def _sweep(self, kind: str, start: datetime, end: datetime, now: datetime) -> None:
        """Apply or track every object created in the window; raises RazorpayError on listing failures."""

        handler = self.handle_refund if kind == "refunds" else self.handle_payment
        for item in self.client.list_window(kind, int(start.timestamp()), int(end.timestamp())):
            try:
                handler(item, now)
            except RazorpayError as exc:
                if exc.auth_failure:
                    raise
                # Durably recorded, so the window may still advance.
                self._track(kind[:-1], item.get("id", "?"), item.get("order_id"), "lookup_error", str(exc)[:200], now)

    def run(self, now: datetime) -> Dict[str, int]:
        state = self.db.get_reconcile_state()
        first = self.db.first_order_created_at()
        if first is None:
            self.db.save_reconcile_progress(success=True)
            return {"skipped_no_orders": 1}
        bootstrap = first - timedelta(days=1)
        horizon = now - LAG
        error: Optional[str] = None
        try:
            for kind in ("refunds", "payments"):  # refund evidence before settlement
                checkpoint = state.get(f"{kind}_checkpoint")
                start = max(bootstrap, checkpoint - OVERLAP) if checkpoint else bootstrap
                end = min(horizon, start + MAX_WINDOW)
                if end > start:
                    self._sweep(kind, start, end, now)
                    self.db.save_reconcile_progress(checkpoints={kind: end})
            audit_end = state.get("audit_before") or horizon
            if audit_end - AUDIT_DAY < bootstrap:
                audit_end = horizon  # walked back to the first order: start over
            audit_start = max(bootstrap, audit_end - AUDIT_DAY)
            for kind in ("refunds", "payments"):
                self._sweep(kind, audit_start, audit_end, now)
            self.db.save_reconcile_progress(audit_before=audit_start)
            for item in self.db.due_billing_items(FOLLOW_UP_BATCH):
                self._follow_up(item, now)
        except RazorpayError as exc:
            error = str(exc)[:500]
            self.db.save_reconcile_progress(error=error)
            self.notify("error" if exc.auth_failure else "warning",
                        "Billing reconciliation stopped: Razorpay request failed", error)
            if exc.auth_failure:
                raise
            return {**self.summary, "stopped": 1}
        self.db.save_reconcile_progress(success=True)
        return self.summary

    def _follow_up(self, item: Dict[str, Any], now: datetime) -> None:
        kind, provider_id = item["kind"], item["provider_id"]
        try:
            if kind == "payment":
                self.handle_payment(self.client.fetch_payment(provider_id), now)
            elif kind == "refund":
                self.handle_refund(self.client.fetch_refund(provider_id), now)
            else:
                order = self.db.get_razorpay_order(provider_id)
                if order and order["payment_id"] is None:
                    self._bind_legacy(order, now)
                else:
                    self._resolve("order", provider_id)
        except RazorpayError as exc:
            if exc.auth_failure:
                raise
            self._track(kind, provider_id, item.get("order_id"), item["reason"], f"lookup failed: {exc}"[:200], now)


def run_once() -> Optional[Dict[str, int]]:
    """One locked run against the real database and Razorpay."""

    import psycopg2

    from config import RAZORPAY_KEY_ID, RAZORPAY_KEY_SECRET
    from database.database_manager import BSEDatabaseManager
    from monitoring.notifier import OpsNotifier

    if not (RAZORPAY_KEY_ID and RAZORPAY_KEY_SECRET):
        logger.info("Razorpay is not configured; nothing to reconcile")
        return None
    db = BSEDatabaseManager(min_connections=1, max_connections=2)
    params = {k: v for k, v in db.connection_params.items() if k != "cursor_factory"}
    # The advisory lock lives on its own connection for the whole run: a
    # pooled connection could carry the lock to its next borrower.
    lock_conn = psycopg2.connect(**params)
    lock_conn.autocommit = True
    try:
        with lock_conn.cursor() as cur:
            cur.execute("SELECT pg_try_advisory_lock(%s)", (LOCK_KEY,))
            if not cur.fetchone()[0]:
                logger.info("Another reconciliation run holds the lock; skipping")
                return None
            try:
                cur.execute("SELECT NOW()")
                now = cur.fetchone()[0]
                notifier = OpsNotifier(component="billing-reconcile")
                summary = Reconciler(
                    db, RazorpayClient(RAZORPAY_KEY_ID, RAZORPAY_KEY_SECRET), notifier.notify
                ).run(now)
                logger.info("Reconciliation finished: %s", summary or "nothing to do")
                return summary
            finally:
                cur.execute("SELECT pg_advisory_unlock(%s)", (LOCK_KEY,))
    finally:
        lock_conn.close()
        db.close()


def main() -> None:
    from config.logging_config import configure_logging

    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--loop", action="store_true", help="run every RECONCILE_INTERVAL_MINUTES")
    args = parser.parse_args()
    configure_logging("billing-reconcile", level=os.getenv("LOG_LEVEL", "INFO").upper(),
                      fmt="%(asctime)s %(levelname)s [billing-reconcile] %(message)s")
    interval = float(os.getenv("RECONCILE_INTERVAL_MINUTES", "15")) * 60
    while True:
        try:
            run_once()
        except Exception:  # keep the loop alive; the failure is logged and alerted
            logger.error("Reconciliation run failed:\n%s", traceback.format_exc())
            try:
                from monitoring.notifier import OpsNotifier

                OpsNotifier(component="billing-reconcile").notify("error", "Billing reconciliation run failed", traceback.format_exc()[-1500:])
            except Exception:
                pass
        if not args.loop:
            return
        time.sleep(interval)


if __name__ == "__main__":
    main()

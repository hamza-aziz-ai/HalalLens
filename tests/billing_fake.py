"""In-memory stand-in for the billing side of BSEDatabaseManager (D-024).

Mirrors the contract of settle_razorpay_order / refund_razorpay_payment /
start_trial_grant / refresh_entitlement: the same return codes and the same
order, grant, event and projection effects, with ``now`` taken from a clock
the test controls. The real SQL and its locking are covered by
tests/test_billing_postgres.py (opt-in, real Postgres).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

T0 = datetime(2026, 1, 1, tzinfo=timezone.utc)

PLANS = {
    "starter": {"code": "starter", "name": "Starter", "price_inr": 50, "interval_days": 30, "trial_days": 30, "rank": 1},
    "annual": {"code": "annual", "name": "Annual", "price_inr": 500, "interval_days": 365, "trial_days": 30, "rank": 2},
    "lifetime": {"code": "lifetime", "name": "Lifetime", "price_inr": 2000, "interval_days": 0, "trial_days": 0, "rank": 3},
}
CLAIMABLE = ("created", "attempted")


class BillingFake:
    def __init__(self):
        self.now = T0
        self.plans = {code: {**plan, "features": [], "is_active": True} for code, plan in PLANS.items()}
        self.users: Dict[int, Dict[str, Any]] = {
            42: {
                "id": 42,
                "email": "buyer@example.com",
                "plan": "free",
                "subscription_status": "inactive",
                "subscription_renewal": None,
                "plan_started_at": None,
                "trial_used": False,
            }
        }
        self.orders: Dict[str, Dict[str, Any]] = {}
        self.grants: List[Dict[str, Any]] = []
        self.events: List[Dict[str, Any]] = []
        self.refunds: Dict[str, Dict[str, Any]] = {}  # payment_refunds, by refund id

    # --- helpers for tests -------------------------------------------------
    def advance(self, days: float) -> None:
        self.now += timedelta(days=days)

    def add_order(self, order_id: str, plan_code: str, user_id: int = 42) -> Dict[str, Any]:
        plan = self.plans[plan_code]
        self.orders[order_id] = {
            "order_id": order_id,
            "user_id": user_id,
            "amount": plan["price_inr"] * 100,
            "currency": "INR",
            "status": "created",
            "payload": {},
            "plan_code": plan_code,
            "interval_days": plan["interval_days"],
            "payment_id": None,
        }
        return self.orders[order_id]

    # --- reads ---------------------------------------------------------------
    def get_subscription_plan(self, code):
        plan = self.plans.get(code)
        return dict(plan) if plan else None

    def list_subscription_plans(self, active_only=True):
        return [dict(p) for p in sorted(self.plans.values(), key=lambda p: p["rank"])]

    def get_user_by_id(self, user_id):
        row = self.users.get(user_id)
        return dict(row) if row else None

    def get_razorpay_order(self, order_id):
        order = self.orders.get(order_id)
        return dict(order) if order else None

    def get_subscription_grants(self, user_id):
        return [dict(g) for g in self.grants if g["user_id"] == user_id]

    # --- writes ---------------------------------------------------------------
    def create_razorpay_order(self, *, user_id, order_id, amount, currency, status, payload,
                              plan_code=None, interval_days=None):
        self.orders[order_id] = {
            "order_id": order_id, "user_id": user_id, "amount": amount, "currency": currency,
            "status": status, "payload": payload, "plan_code": plan_code,
            "interval_days": interval_days, "payment_id": None,
        }

    def record_payment_event(self, *, user_id, provider, event_type, event_id, payload):
        return self._event(user_id, event_type, event_id)

    def _event(self, user_id, event_type, event_id) -> bool:
        if event_id and any(e["event_id"] == event_id for e in self.events):
            return False
        self.events.append({"user_id": user_id, "event_type": event_type, "event_id": event_id})
        return True

    def _write_projection(self, user_id, projection, trial_used=None):
        self.users[user_id].update(projection)
        if trial_used is not None:
            self.users[user_id]["trial_used"] = trial_used

    def _grants_of(self, user_id):
        return [g for g in self.grants if g["user_id"] == user_id]

    def settle_razorpay_order(self, *, order_id, payment_id, expected_user_id, event_type, payload,
                              project, lifetime_held):
        order = self.orders.get(order_id)
        if not order or (expected_user_id is not None and order["user_id"] != expected_user_id):
            return "missing", None
        if order["status"] not in CLAIMABLE:
            return "settled", dict(order)
        user_id = order["user_id"]
        if self._refunded_total(payment_id) >= order["amount"]:
            self._event(user_id, event_type, payment_id)
            return "refunded_payment", dict(order)
        if lifetime_held(self._grants_of(user_id)):
            order.update(status="refund_due", payment_id=payment_id)
            self._event(user_id, event_type, payment_id)
            return "refund_due", dict(order)
        days = int(order["interval_days"] or 0)
        self.grants.append({
            "id": len(self.grants) + 1, "user_id": user_id, "plan_code": order["plan_code"],
            "source": "razorpay", "order_id": order_id,
            "duration": timedelta(days=days) if days > 0 else None,
            "allocated_at": self.now, "refunded_amount": 0, "revoked_at": None,
        })
        order.update(status="paid", payment_id=payment_id)
        self._event(user_id, event_type, payment_id)
        projection = project(self._grants_of(user_id), self.now)
        self._write_projection(user_id, projection, trial_used=True)
        return "granted", {**projection, "granted_plan": order["plan_code"]}

    def _refunded_total(self, payment_id):
        return sum(r["amount"] for r in self.refunds.values() if r["payment_id"] == payment_id)

    def refund_razorpay_payment(self, *, order_id, payment_id, refund_id, refund_amount,
                                event_type, payload, project):
        order = self.orders.get(order_id) if order_id else None
        if order is None and payment_id:
            order = next((o for o in self.orders.values() if o["payment_id"] == payment_id), None)
        if order is None:
            return "unknown", None
        user_id = order["user_id"]
        if refund_id in self.refunds:
            return "duplicate", None
        self.refunds[refund_id] = {"payment_id": payment_id, "order_id": order["order_id"], "amount": int(refund_amount)}
        self._event(user_id, event_type, refund_id)
        funding = order["payment_id"]
        grant = next((g for g in self.grants if g["order_id"] == order["order_id"]), None)
        if funding is None:
            return ("needs_review" if grant else "unsettled"), dict(order)
        if payment_id and payment_id != funding:
            return "other_payment", dict(order)
        total = self._refunded_total(funding)
        full = total >= order["amount"]
        if order["status"] == "refund_due":
            if full:
                order["status"] = "refunded"
            return ("refund_due_closed" if full else "partial"), dict(order)
        if grant is None:
            return "needs_review", dict(order)
        revoke = full and grant["revoked_at"] is None
        grant["refunded_amount"] = total
        if revoke:
            grant["revoked_at"] = self.now
            order["status"] = "refunded"
        projection = project(self._grants_of(user_id), self.now)
        self._write_projection(user_id, projection)
        return ("revoked" if revoke else "partial"), projection

    def sync_refund_action(self, payment_id):
        return {"total_refunded": self._refunded_total(payment_id), "obligation_settled": False, "action_state": None}

    def start_trial_grant(self, *, user_id, plan_code, trial_days, project):
        user = self.users[user_id]
        if user["trial_used"]:
            return "used", None
        grants = self._grants_of(user_id)
        if project(grants, self.now)["plan"] != "free":
            return "active", None
        self.grants.append({
            "id": len(self.grants) + 1, "user_id": user_id, "plan_code": plan_code, "source": "trial",
            "order_id": None, "duration": timedelta(days=trial_days), "allocated_at": self.now,
            "refunded_amount": 0, "revoked_at": None,
        })
        projection = project(self._grants_of(user_id), self.now)
        self._write_projection(user_id, projection, trial_used=True)
        return "started", projection

    def refresh_entitlement(self, user_id, project):
        projection = project(self._grants_of(user_id), self.now)
        self._write_projection(user_id, projection)
        return projection


class ReconcileFake(BillingFake):
    """BillingFake plus the reconciler's state, tracking and legacy-binding methods."""

    def __init__(self):
        super().__init__()
        self.state = {"payments_checkpoint": None, "refunds_checkpoint": None, "audit_before": None,
                      "last_success_at": None, "last_error": None}
        self.tracked: Dict[tuple, Dict[str, Any]] = {}
        self.actions: Dict[str, Dict[str, Any]] = {}  # refund_actions, by payment id

    def add_order(self, order_id, plan_code, user_id=42):
        order = super().add_order(order_id, plan_code, user_id)
        order["created_at"] = self.now
        return order

    def first_order_created_at(self):
        times = [o.get("created_at") for o in self.orders.values() if o.get("created_at")]
        return min(times) if times else None

    def get_reconcile_state(self):
        return dict(self.state)

    def save_reconcile_progress(self, *, checkpoints=None, audit_before=None, error=None, success=False):
        for kind, value in (checkpoints or {}).items():
            key = f"{kind}_checkpoint"
            self.state[key] = value if self.state[key] is None else max(self.state[key], value)
        if audit_before is not None:
            self.state["audit_before"] = audit_before
        if success:
            self.state["last_success_at"], self.state["last_error"] = self.now, None
        elif error:
            self.state["last_error"] = error

    def track_billing_item(self, *, kind, provider_id, order_id, reason, last_status, recheck_after_seconds):
        row = self.tracked.get((kind, provider_id))
        if row is None:
            row = {"kind": kind, "provider_id": provider_id, "first_seen": self.now, "attempts": 0,
                   "last_notified_at": None}
            self.tracked[(kind, provider_id)] = row
        after = recheck_after_seconds
        if self.now - row["first_seen"] > timedelta(days=7):
            after = max(after, 86400)
        row.update(order_id=order_id or row.get("order_id"), reason=reason, last_status=last_status,
                   attempts=row["attempts"] + 1, next_check_at=self.now + timedelta(seconds=after),
                   resolved_at=None)
        return dict(row)

    def resolve_billing_item(self, kind, provider_id):
        row = self.tracked.get((kind, provider_id))
        if row and row["resolved_at"] is None:
            row["resolved_at"] = self.now

    def mark_billing_notified(self, kind, provider_id):
        self.tracked[(kind, provider_id)]["last_notified_at"] = self.now

    def due_billing_items(self, limit):
        due = [dict(r) for r in self.tracked.values() if r["resolved_at"] is None and r["next_check_at"] <= self.now]
        return sorted(due, key=lambda r: r["next_check_at"])[:limit]

    def open_items(self):
        return {k: r["reason"] for k, r in self.tracked.items() if r["resolved_at"] is None}

    def bind_legacy_payment(self, *, order_id, payment_id, project):
        order = self.orders.get(order_id)
        if not order:
            return "no_legacy_grant", None
        if order["payment_id"] is not None:
            return "already_bound", dict(order)
        grant = next((g for g in self.grants if g["order_id"] == order_id and g["source"] == "legacy"), None)
        if grant is None:
            return "no_legacy_grant", dict(order)
        order["payment_id"] = payment_id
        total = self._refunded_total(payment_id)
        if total >= order["amount"] and grant["revoked_at"] is None:
            grant["revoked_at"] = self.now
            order["status"] = "refunded"
        grant["refunded_amount"] = total
        projection = project(self._grants_of(order["user_id"]), self.now)
        self._write_projection(order["user_id"], projection)
        return "bound", projection


    # --- refund_actions (mirrors database_manager, D-025 PR C) ---------------------
    RANK = {"requested": 0, "created": 1, "failed": 2, "blocked": 2, "processed": 3}

    def create_refund_intent(self, *, payment_id, order_id, reason, amount, currency, idempotency_key, request_body):
        if payment_id in self.actions:
            return "existing", dict(self.actions[payment_id])
        order = self.orders.get(order_id)
        funding = order["payment_id"] if order else None
        terms = order is not None and order["amount"] == int(amount) and currency.upper() == "INR"
        eligible = terms and (
            (reason == "duplicate" and order["status"] in ("paid", "refunded", "refund_due")
             and funding is not None and funding != payment_id)
            or (reason == "refund_due" and order["status"] == "refund_due" and funding == payment_id)
        )
        if not eligible:
            return "ineligible", None
        action = {"id": len(self.actions) + 1, "payment_id": payment_id, "order_id": order_id, "reason": reason,
                  "amount": int(amount), "currency": currency.upper(), "idempotency_key": idempotency_key,
                  "request_body": request_body, "state": "requested", "provider_refund_id": None, "attempts": 0,
                  "next_attempt_at": self.now, "last_error": None, "obligation_settled_at": None}
        self.actions[payment_id] = action
        return "created", dict(action)

    def update_refund_action(self, action_id, *, state=None, provider_refund_id=None, error=None,
                             retry_after_seconds=None):
        action = next(a for a in self.actions.values() if a["id"] == action_id)
        if state and self.RANK[state] > self.RANK[action["state"]] and action["state"] not in ("failed", "blocked", "processed"):
            action["state"] = state
        action["provider_refund_id"] = action["provider_refund_id"] or provider_refund_id
        action["attempts"] += 1
        action["last_error"] = error
        action["next_attempt_at"] = self.now + timedelta(seconds=retry_after_seconds if retry_after_seconds is not None else 900)
        return dict(action)

    def get_refund_action(self, payment_id):
        action = self.actions.get(payment_id)
        return dict(action) if action else None

    def refund_actions_due(self, limit):
        due = [dict(a) for a in self.actions.values() if a["state"] in ("requested", "created")
               and a["obligation_settled_at"] is None and a["next_attempt_at"] <= self.now]
        return sorted(due, key=lambda a: a["next_attempt_at"])[:limit]

    def open_refund_obligations(self, limit):
        rows = [{"payment_id": pid, "order_id": r["order_id"], "reason": r["reason"]}
                for (kind, pid), r in self.tracked.items()
                if kind == "payment" and r["resolved_at"] is None and r["reason"] in ("duplicate", "refund_due")
                and pid not in self.actions]
        return rows[:limit]

    def sync_refund_action(self, payment_id):
        total = self._refunded_total(payment_id)
        action = self.actions.get(payment_id)
        row = self.tracked.get(("payment", payment_id))
        open_obligation = row if row and row["resolved_at"] is None and row["reason"] in ("duplicate", "refund_due") else None
        owed = action["amount"] if action else (self.orders[open_obligation["order_id"]]["amount"] if open_obligation else None)
        settled = owed is not None and total >= owed
        if action:
            if action["provider_refund_id"] in self.refunds and action["state"] in ("requested", "created"):
                action["state"] = "processed"
            if settled and action["obligation_settled_at"] is None:
                action["obligation_settled_at"] = self.now
        if settled and open_obligation:
            open_obligation["resolved_at"] = self.now
        return {"total_refunded": total, "obligation_settled": settled,
                "action_state": action["state"] if action else None}

    def read_reconcile_heartbeat(self):
        last = self.state["last_success_at"]
        return {"last_success_at": last, "age": None if last is None else (self.now - last).total_seconds()}


class FakeRazorpay:
    """In-memory Razorpay for the reconciler: payments and refunds with created_at times."""

    def __init__(self, clock):
        self.clock = clock  # the ReconcileFake whose .now is "now"
        self.payments: Dict[str, Dict[str, Any]] = {}
        self.refunds: Dict[str, Dict[str, Any]] = {}
        self.fail_with = None  # an exception to raise from list_window
        self.list_calls = 0
        self.refund_posts = []          # (payment_id, body, key) per create_refund call
        self.post_outcomes = []         # queued: "ok", "pending", "lost" (refund made, response lost) or a RazorpayError

    def pay(self, payment_id, order, status="captured", **extra):
        payment = {"id": payment_id, "order_id": order["order_id"], "amount": order["amount"],
                   "currency": "INR", "status": status, "amount_refunded": 0,
                   "created_at": int(self.clock.now.timestamp())}
        payment.update(extra)
        self.payments[payment_id] = payment
        return payment

    def refund(self, refund_id, payment_id, amount=None, status="processed", notes=None):
        payment = self.payments[payment_id]
        amount = payment["amount"] if amount is None else amount
        self.refunds[refund_id] = {"id": refund_id, "payment_id": payment_id, "amount": amount,
                                   "currency": "INR", "status": status, "notes": notes or {},
                                   "created_at": int(self.clock.now.timestamp())}
        if status == "processed":
            payment["amount_refunded"] += amount
            if payment["amount_refunded"] >= payment["amount"]:
                payment["status"] = "refunded"
        return self.refunds[refund_id]

    def list_window(self, kind, start, end):
        self.list_calls += 1
        if self.fail_with:
            raise self.fail_with
        source = self.payments if kind == "payments" else self.refunds
        return [dict(o) for o in source.values() if start <= o["created_at"] <= end]

    def fetch_payment(self, payment_id):
        return dict(self.payments[payment_id])

    def fetch_refund(self, refund_id):
        return dict(self.refunds[refund_id])

    def list_order_payments(self, order_id):
        return [dict(p) for p in self.payments.values() if p["order_id"] == order_id]

    def list_payment_refunds(self, payment_id):
        return [dict(r) for r in self.refunds.values() if r["payment_id"] == payment_id]

    def create_refund(self, payment_id, body, idempotency_key):
        self.refund_posts.append((payment_id, body, idempotency_key))
        outcome = self.post_outcomes.pop(0) if self.post_outcomes else "ok"
        if isinstance(outcome, Exception):
            raise outcome
        # Idempotency: the same key returns the refund it already created.
        for refund in self.refunds.values():
            if refund["notes"].get("halallens_refund_key") == idempotency_key:
                return dict(refund)
        refund = self.refund(f"rfnd_auto{len(self.refunds) + 1}", payment_id, body["amount"],
                             status="pending" if outcome == "pending" else "processed", notes=body["notes"])
        if outcome == "lost":
            from api.razorpay_client import RazorpayError
            raise RazorpayError("POST timed out")
        return dict(refund)

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

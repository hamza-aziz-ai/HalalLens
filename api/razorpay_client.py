"""Razorpay REST access shared by the API and the payment reconciler (D-025).

Read-only (GET) except order creation, which stays in api/app.py. Raises
RazorpayError instead of HTTPException so jobs can use it; the API maps
errors to HTTP itself.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

import requests

API_BASE = "https://api.razorpay.com/v1"
PAGE_SIZE = 100  # Razorpay's maximum `count` for list endpoints


class RazorpayError(Exception):
    """A failed or malformed Razorpay response. ``status`` is None for network errors."""

    def __init__(self, message: str, status: Optional[int] = None):
        super().__init__(message)
        self.status = status

    @property
    def auth_failure(self) -> bool:
        return self.status in (401, 403)


class RazorpayClient:
    def __init__(self, key_id: str, key_secret: str, *, base: str = API_BASE, timeout: float = 15):
        self.auth = (key_id, key_secret)
        self.base = base
        self.timeout = timeout

    def _get(self, path: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        try:
            resp = requests.get(f"{self.base}{path}", params=params, auth=self.auth, timeout=self.timeout)
        except requests.RequestException as exc:
            raise RazorpayError(f"GET {path}: {exc}") from exc
        if resp.status_code != 200:
            raise RazorpayError(f"GET {path}: HTTP {resp.status_code}", resp.status_code)
        try:
            body = resp.json()
        except ValueError as exc:
            raise RazorpayError(f"GET {path}: response is not JSON", resp.status_code) from exc
        if not isinstance(body, dict):
            raise RazorpayError(f"GET {path}: unexpected response shape", resp.status_code)
        return body

    def _items(self, path: str, params: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        items = self._get(path, params).get("items")
        if not isinstance(items, list):
            raise RazorpayError(f"GET {path}: response has no item list")
        return items

    def fetch_payment(self, payment_id: str) -> Dict[str, Any]:
        return self._get(f"/payments/{payment_id}")

    def fetch_refund(self, refund_id: str) -> Dict[str, Any]:
        return self._get(f"/refunds/{refund_id}")

    def list_order_payments(self, order_id: str) -> List[Dict[str, Any]]:
        """Every payment attempt on an order, failed ones included."""

        return self._items(f"/orders/{order_id}/payments")

    def list_payment_refunds(self, payment_id: str) -> List[Dict[str, Any]]:
        return self._items(f"/payments/{payment_id}/refunds", {"count": PAGE_SIZE})

    def list_window(self, kind: str, start: int, end: int) -> List[Dict[str, Any]]:
        """All payments or refunds CREATED in [start, end] (unix seconds), every page."""

        if kind not in ("payments", "refunds"):
            raise ValueError(kind)
        found: List[Dict[str, Any]] = []
        skip = 0
        while True:
            page = self._items(f"/{kind}", {"from": start, "to": end, "count": PAGE_SIZE, "skip": skip})
            found.extend(page)
            if len(page) < PAGE_SIZE:
                return found
            skip += PAGE_SIZE


def payment_terms_match(payment: Dict[str, Any], order: Dict[str, Any]) -> bool:
    """The payment belongs to this order, for exactly its amount and currency."""

    try:
        amount = int(payment.get("amount"))
    except (TypeError, ValueError):
        return False
    return (
        payment.get("order_id") == order["order_id"]
        and amount == int(order["amount"])
        and str(payment.get("currency") or "").upper() == str(order.get("currency") or "INR").upper()
    )


def payment_matches_order(payment: Dict[str, Any], order: Dict[str, Any]) -> bool:
    """A captured payment for exactly this order's amount and currency."""

    return payment.get("status") == "captured" and payment_terms_match(payment, order)

"""Razorpay REST access shared by the API and the payment reconciler (D-025).

GET calls plus create_refund (used only by the reconciler's automatic
refunds, TEST keys only). Order creation stays in api/app.py. Raises
RazorpayError instead of HTTPException so jobs can use it; the API maps
errors to HTTP itself.
"""

from __future__ import annotations

import time
from typing import Any, Dict, List, Optional

import requests

API_BASE = "https://api.razorpay.com/v1"
PAGE_SIZE = 100  # Razorpay's maximum `count` for list endpoints
GET_ATTEMPTS = 3
RETRY_STATUSES = (429, 502, 503, 504)
MAX_RETRY_DELAY = 10.0  # seconds


def _retry_delay(resp, attempt: int) -> float:
    """Seconds to wait before the next GET: Retry-After when numeric, else 1 s then 2 s."""

    try:
        delay = float(resp.headers.get("Retry-After", ""))
    except (TypeError, ValueError):
        delay = 2.0**attempt
    return min(max(delay, 0.0), MAX_RETRY_DELAY)


class RazorpayError(Exception):
    """A failed or malformed Razorpay response. ``status`` is None for network errors."""

    def __init__(self, message: str, status: Optional[int] = None, body: str = ""):
        super().__init__(message)
        self.status = status
        self.body = body  # Razorpay's error text, e.g. to tell the two 409s apart

    @property
    def auth_failure(self) -> bool:
        return self.status in (401, 403)


class RazorpayClient:
    def __init__(self, key_id: str, key_secret: str, *, base: str = API_BASE, timeout: float = 15):
        self.auth = (key_id, key_secret)
        self.base = base
        self.timeout = timeout

    def _get(self, path: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        # GETs are safe to repeat: a rate limit (429) or a brief upstream error
        # gets two more tries before the caller sees it, waiting as Retry-After asks.
        for attempt in range(GET_ATTEMPTS):
            try:
                resp = requests.get(f"{self.base}{path}", params=params, auth=self.auth, timeout=self.timeout)
            except requests.RequestException as exc:
                raise RazorpayError(f"GET {path}: {exc}") from exc
            if resp.status_code not in RETRY_STATUSES or attempt == GET_ATTEMPTS - 1:
                break
            time.sleep(_retry_delay(resp, attempt))
        return self._parse(f"GET {path}", resp)

    @staticmethod
    def _parse(what: str, resp) -> Dict[str, Any]:
        if resp.status_code != 200:
            raise RazorpayError(f"{what}: HTTP {resp.status_code}", resp.status_code, resp.text[:500])
        try:
            body = resp.json()
        except ValueError as exc:
            raise RazorpayError(f"{what}: response is not JSON", resp.status_code) from exc
        if not isinstance(body, dict):
            raise RazorpayError(f"{what}: unexpected response shape", resp.status_code)
        return body

    def create_refund(self, payment_id: str, body: Dict[str, Any], idempotency_key: str) -> Dict[str, Any]:
        """POST a refund. Retries must send the same key AND body (X-Refund-Idempotency)."""

        path = f"/payments/{payment_id}/refund"
        try:
            resp = requests.post(
                f"{self.base}{path}", json=body, auth=self.auth, timeout=self.timeout,
                headers={"X-Refund-Idempotency": idempotency_key},
            )
        except requests.RequestException as exc:
            raise RazorpayError(f"POST {path}: {exc}") from exc
        return self._parse(f"POST {path}", resp)

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


def payment_created_at(payment: Dict[str, Any]) -> Optional[int]:
    """When the payment attempt was created: the payment entity's ``created_at``
    (epoch seconds), never a webhook envelope's. None when missing or malformed."""

    value = (payment or {}).get("created_at")
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        return None
    return value


def payment_matches_order(payment: Dict[str, Any], order: Dict[str, Any]) -> bool:
    """A captured payment for exactly this order's amount and currency."""

    return payment.get("status") == "captured" and payment_terms_match(payment, order)

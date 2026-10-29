"""Paid access derived from subscription grants (D-024).

Every paid order, trial and pre-ledger period is one row in
``subscription_grants``. Access is never stored as the truth: it is derived
here from the grants, so nothing paid for is ever discarded.

Timed grants (Annual, Starter, trial, legacy) are folded in allocation order,
so a timed purchase made while another period runs starts when that period
ends:

    start      = max(allocated_at, end of the previous timed grant)
    end        = start + duration
    if revoked:  end = max(start, min(end, revoked_at))

A refunded timed grant keeps the time it actually served: a queued grant
refunded before it starts takes no time (later grants move up), a current one
ends at the refund (the next starts then, with its full length), and an
expired one changes nothing.

Lifetime (``duration`` NULL) never queues (D-024 amendment, 2026-10-30): it is
an overlay that starts at its settlement time and is the current plan while
it covers, whatever timed grant runs underneath:

    start      = allocated_at
    end        = None                         (never ends)
    if revoked:  end = max(start, revoked_at)

Timed grants keep their exact dates underneath on wall-clock time (no pause,
no extension), so refunding a Lifetime reveals whatever timed access remains,
or free when none does. ``users.plan`` / ``subscription_status`` /
``subscription_renewal`` are a projection of this, written only inside the
per-user locked transactions in ``database_manager``.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Dict, Iterable, List, Optional


@dataclass(frozen=True)
class Segment:
    grant_id: int
    plan_code: str
    source: str  # razorpay | trial | legacy
    start: datetime
    end: Optional[datetime]  # None: unrevoked Lifetime
    lifetime: bool  # from the grant (duration NULL); a refunded Lifetime has a finite end


def fold(grants: Iterable[Dict[str, Any]]) -> List[Segment]:
    """Timed grants end to end plus Lifetime overlays, by (start, grant id) (see module docstring)."""

    segments: List[Segment] = []
    previous_end: Optional[datetime] = None
    for grant in sorted(grants, key=lambda g: (g["allocated_at"], g["id"])):
        duration: Optional[timedelta] = grant.get("duration")
        revoked_at = grant.get("revoked_at")
        start = grant["allocated_at"]
        if duration is None:  # Lifetime: overlays the timed chain from settlement.
            end = None if revoked_at is None else max(start, revoked_at)
            segments.append(Segment(grant["id"], grant["plan_code"], grant["source"], start, end, True))
            continue
        if previous_end is not None:
            start = max(start, previous_end)
        end = start + duration
        if revoked_at is not None:
            end = max(start, min(end, revoked_at))
        segments.append(Segment(grant["id"], grant["plan_code"], grant["source"], start, end, False))
        previous_end = end
    return sorted(segments, key=lambda s: (s.start, s.grant_id))


def _covers(segment: Segment, now: datetime) -> bool:
    return segment.start <= now and (segment.end is None or now < segment.end)


def current_segment(segments: List[Segment], now: datetime) -> Optional[Segment]:
    """The segment running at ``now``; an active Lifetime wins over the timed one under it."""

    covering = [s for s in segments if _covers(s, now)]
    return next((s for s in covering if s.lifetime), covering[0] if covering else None)


def upcoming(segments: List[Segment], now: datetime) -> List[Segment]:
    """Current and future segments, zero-length ones (refunded before start) left out.

    While a Lifetime covers ``now`` it is the only one shown: the timed time
    underneath runs out unseen and only matters if the Lifetime is refunded.
    """

    current = current_segment(segments, now)
    if current is not None and current.lifetime:
        return [current]
    return [s for s in segments if (s.end is None or s.end > now) and s.end != s.start]


def project(grants: Iterable[Dict[str, Any]], now: datetime) -> Dict[str, Any]:
    """The ``users`` columns that mirror the grants at ``now``."""

    segment = current_segment(fold(grants), now)
    if segment is None:
        return {
            "plan": "free",
            "subscription_status": "inactive",
            "subscription_renewal": None,
            "plan_started_at": None,
        }
    return {
        "plan": segment.plan_code,
        "subscription_status": "trialing" if segment.source == "trial" else "active",
        "subscription_renewal": segment.end,
        "plan_started_at": segment.start,
    }


def lifetime_held(grants: Iterable[Dict[str, Any]]) -> bool:
    """A Lifetime grant that is not refunded covers every plan."""

    return any(g.get("duration") is None and g.get("revoked_at") is None for g in grants)


def purchase_start(grants: Iterable[Dict[str, Any]], now: datetime) -> datetime:
    """When a timed purchase made now would start: the end of the timed chain, or now."""

    ends = [s.end for s in fold(grants) if not s.lifetime]
    return max([now, *ends])


# --- Upgrade credit at checkout (D-030) ---------------------------------------
#
# An upgrade to a never-ending plan is discounted by the unused part of what
# the buyer paid for timed grants (a discount, never a refund). Pure: grants,
# the funding facts of their orders and ``now`` come in; prices are
# arguments. Money is integer minor units (paise), times are aware UTC and
# durations whole microseconds.
#
#   eligible   unrevoked timed grant, source 'razorpay', its order paid by a
#              known payment in the quote's currency, no refund pending
#   net_paid   order amount (what was charged) - processed refunds, >= 0
#   credit     net_paid                                    queued (not started)
#              floor(net_paid * remaining_us / total_us)   running (total = the grant's duration)
#              0                                           expired
#
# Trial and legacy (pre-ledger) grants give nothing. Credit is floored per
# source, then summed, and never exceeds the list price.

CREDIT_VERSION = 1
#: A quoted price binds payment attempts created within this of pricing.
PRICE_VALIDITY = timedelta(minutes=15)
#: Below this (one rupee) no checkout is opened; the upgrade is reviewed by hand.
MIN_PAYABLE = 100
_US = timedelta(microseconds=1)


def _iso(value: Optional[datetime]) -> Optional[str]:
    return None if value is None else value.isoformat()


def _net_paid(order: Dict[str, Any]) -> int:
    return max(0, int(order["amount"]) - int(order.get("refunded") or 0))


def credit_sources(
    grants: Iterable[Dict[str, Any]], funding: Dict[str, Dict[str, Any]], now: datetime, currency: str = "INR"
) -> List[Dict[str, Any]]:
    """Per-source credit evidence for the eligible grants at ``now``.

    ``funding`` maps order id to {amount, currency, status, payment_id,
    refunded (processed refunds of that payment), refund_pending}.
    """

    if now.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    grants = list(grants)
    segments = {s.grant_id: s for s in fold(grants)}
    sources: List[Dict[str, Any]] = []
    for grant in grants:
        order = funding.get(grant.get("order_id") or "")
        if (
            grant.get("source") != "razorpay"
            or grant.get("duration") is None
            or grant.get("revoked_at") is not None
            or order is None
            or not order.get("payment_id")
            or order.get("status") != "paid"
            or order.get("refund_pending")
            or str(order.get("currency") or "").upper() != currency.upper()
        ):
            continue
        net_paid = _net_paid(order)
        segment = segments[grant["id"]]
        if segment.start > now:
            state, credit = "queued", net_paid
        elif segment.end is not None and segment.end > now:
            total = grant["duration"] // _US
            state, credit = "running", min(net_paid, net_paid * ((segment.end - now) // _US) // total)
        else:
            state, credit = "expired", 0
        sources.append({
            "grant_id": grant["id"],
            "order_id": grant["order_id"],
            "payment_id": order["payment_id"],
            "plan_code": grant["plan_code"],
            "net_paid": net_paid,
            "state": state,
            "start": _iso(segment.start),
            "end": _iso(segment.end),
            "credit": credit,
        })
    return sources


def upgrade_quote(
    grants: Iterable[Dict[str, Any]],
    funding: Dict[str, Dict[str, Any]],
    now: datetime,
    list_amount: int,
    currency: str = "INR",
) -> Dict[str, Any]:
    """The price of an upgrade at ``now``: list - credit, with the evidence behind the credit."""

    sources = credit_sources(grants, funding, now, currency)
    credit = min(int(list_amount), sum(s["credit"] for s in sources))
    amount = int(list_amount) - credit
    return {
        "list_amount": int(list_amount),
        "credit_amount": credit,
        "amount": amount,
        "blocked": amount < MIN_PAYABLE,
        "sources": sources,
    }


def credit_refusal(
    order: Dict[str, Any],
    grants: Iterable[Dict[str, Any]],
    funding: Dict[str, Dict[str, Any]],
    attempt_created_at: int,
) -> Optional[str]:
    """Why a credited order may not settle, or None when it may.

    The quoted price binds a payment attempt created (provider time, epoch
    seconds) no later than ``price_valid_until`` (inclusive, second
    resolution), even when that attempt is authorised or captured later.
    Every source that took credit must still be exactly as priced: grant
    unrevoked, same funding payment, same net paid, no refund pending.
    """

    if int(attempt_created_at) > int(order["price_valid_until"].timestamp()):
        return "price_expired"
    by_id = {g["id"]: g for g in grants}
    for source in (order.get("credit_detail") or {}).get("sources") or []:
        if not source.get("credit"):
            continue  # took nothing off the price
        grant = by_id.get(source["grant_id"])
        now_order = funding.get(source["order_id"])
        if (
            grant is None
            or grant.get("revoked_at") is not None
            or now_order is None
            or now_order.get("payment_id") != source["payment_id"]
            or now_order.get("status") != "paid"
            or now_order.get("refund_pending")
            or _net_paid(now_order) != int(source["net_paid"])
        ):
            return "credit_changed"
    return None

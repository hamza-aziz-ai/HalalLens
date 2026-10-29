"""Paid access derived from subscription grants (D-024).

Every paid order, trial and pre-ledger period is one row in
``subscription_grants``. Access is never stored as the truth: it is derived
here by folding the grants in allocation order, so a purchase made while
another period runs starts when that period ends, and nothing paid for is
ever discarded.

    start      = max(allocated_at, end of the previous grant)
    end        = start + duration                (None = Lifetime, never ends)
    if revoked:  end = max(start, min(end, revoked_at))

A refunded grant keeps the time it actually served: a queued grant refunded
before it starts takes no time (later grants move up), a current one ends at
the refund (the next starts then, with its full length), and an expired one
changes nothing. ``users.plan`` / ``subscription_status`` /
``subscription_renewal`` are a projection of this fold, written only inside
the per-user locked transactions in ``database_manager``.
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
    end: Optional[datetime]  # None: Lifetime


def fold(grants: Iterable[Dict[str, Any]]) -> List[Segment]:
    """Lay grants end to end in allocation order (see module docstring)."""

    segments: List[Segment] = []
    previous_end: Optional[datetime] = None
    for grant in sorted(grants, key=lambda g: (g["allocated_at"], g["id"])):
        if segments and segments[-1].end is None:
            break  # Lifetime never ends; nothing can follow it.
        start = grant["allocated_at"] if previous_end is None else max(grant["allocated_at"], previous_end)
        duration: Optional[timedelta] = grant.get("duration")
        end = None if duration is None else start + duration
        revoked_at = grant.get("revoked_at")
        if revoked_at is not None:
            end = max(start, revoked_at if end is None else min(end, revoked_at))
        segments.append(Segment(grant["id"], grant["plan_code"], grant["source"], start, end))
        previous_end = end
    return segments


def current_segment(segments: List[Segment], now: datetime) -> Optional[Segment]:
    for segment in segments:
        if segment.start <= now and (segment.end is None or now < segment.end):
            return segment
    return None


def upcoming(segments: List[Segment], now: datetime) -> List[Segment]:
    """Current and future segments, zero-length ones (refunded before start) left out."""

    return [s for s in segments if (s.end is None or s.end > now) and s.end != s.start]


def project(grants: Iterable[Dict[str, Any]], now: datetime) -> Dict[str, Any]:
    """The ``users`` columns that mirror the fold at ``now``."""

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
    """A Lifetime grant that is active or scheduled (not refunded) covers every plan."""

    return any(g.get("duration") is None and g.get("revoked_at") is None for g in grants)


def purchase_start(grants: Iterable[Dict[str, Any]], now: datetime) -> datetime:
    """When a purchase made now would start: the end of the paid chain, or now."""

    ends = [s.end for s in fold(grants) if s.end is not None]
    return max([now, *ends])

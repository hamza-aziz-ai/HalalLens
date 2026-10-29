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

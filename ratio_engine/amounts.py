#!/usr/bin/env python3
"""One place that turns an untrusted value into a plain amount.

The converters in the API, the jobs, the ETL, the vendor mapper and the cache
runner delegate here, so a boolean or an underflowing string cannot become a
known zero on those paths. Outside this guarantee: numeric JSON literals that
were already decoded to 0.0, and separate parsers such as
market_data/bhavcopy.py. The engine keeps its own exact path
(RatioEngine._number) for the values it receives; this helper returns a float,
so integer precision is not preserved end to end.
"""

from __future__ import annotations

import math
from decimal import Decimal, InvalidOperation
from typing import Any, Optional


def coerce_amount(value: Any) -> Optional[float]:
    """A finite float for a usable amount, else None (unknown).

    - None and booleans are unknown (float(False) would be a verified 0.0).
    - Strings drop thousands separators and surrounding whitespace.
    - NaN / inf / overflow / signalling NaN are unknown.
    - A source that is numerically zero ("0", "0e-400", 0.0) is a known 0.0, but
      a non-zero amount that float() flushes to 0.0 ("1e-400") is unknown.
    """

    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float, Decimal)):
        source: Any = value
    else:
        source = str(value).replace(",", "").strip()
        if not source:
            return None
    try:
        number = float(source)
    except (TypeError, ValueError, OverflowError):
        return None
    if not math.isfinite(number):
        return None
    if number == 0:
        try:
            return 0.0 if Decimal(str(source)) == 0 else None
        except InvalidOperation:
            return None
    return number

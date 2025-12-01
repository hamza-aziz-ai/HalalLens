#!/usr/bin/env python3
"""
Shared datetime parsing helpers for BSE/NSE timestamps
"""

import re
from datetime import datetime, timezone
from typing import Optional

def parse_bse_datetime(dt_str: Optional[str]) -> datetime:
    """
    Normalize BSE timestamps that may use variable fractional-second precision
    or omit timezone indicators.
    """
    if not dt_str:
        return datetime.now(timezone.utc)

    ts = dt_str.strip().replace(' ', 'T')
    if ts.endswith('Z'):
        ts = ts[:-1]

    match = re.match(r'(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})(\.\d+)?', ts)
    if match:
        base = match.group(1)
        frac = match.group(2) or ''
        if frac:
            digits = frac[1:]
            frac_padded = (digits + '000000')[:6]
            ts = f"{base}.{frac_padded}"
        else:
            ts = base

    formats = [
        '%Y-%m-%dT%H:%M:%S.%f',
        '%Y-%m-%dT%H:%M:%S'
    ]

    for fmt in formats:
        try:
            parsed = datetime.strptime(ts, fmt)
            return parsed.replace(tzinfo=timezone.utc)
        except ValueError:
            continue

    return datetime.now(timezone.utc)
